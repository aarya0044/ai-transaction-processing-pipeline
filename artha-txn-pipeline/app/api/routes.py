import hashlib
import os
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models import Job, JobStatus, Transaction
from app.api.schemas import JobOut, JobStatusOut, JobResultsOut, TransactionOut
from app.workers.tasks import process_job

router = APIRouter()


@router.post("/jobs/upload", response_model=JobOut, status_code=201)
async def upload_job(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, detail="Only .csv files are accepted")

    os.makedirs(settings.upload_dir, exist_ok=True)
    contents = await file.read()
    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, detail=f"File exceeds {settings.max_upload_mb}MB limit")
    if len(contents) == 0:
        raise HTTPException(400, detail="Empty file")

    checksum = hashlib.sha256(contents).hexdigest()
    job_id = str(uuid.uuid4())
    file_path = os.path.join(settings.upload_dir, f"{job_id}.csv")
    with open(file_path, "wb") as f:
        f.write(contents)

    job = Job(id=job_id, filename=file.filename, file_checksum=checksum, status=JobStatus.pending)
    db.add(job)
    db.commit()
    db.refresh(job)

    process_job.delay(job_id, file_path)

    return job


@router.get("/jobs/{job_id}/status", response_model=JobStatusOut)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    summary = None
    if job.status == JobStatus.completed and job.summary:
        summary = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "anomaly_count": job.summary.anomaly_count,
            "risk_level": job.summary.risk_level,
            "top_merchants": job.summary.top_merchants,
        }
    return JobStatusOut(
        id=job.id,
        filename=job.filename,
        status=job.status.value,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        duplicate_count=job.duplicate_count,
        progress_pct=job.progress_pct,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary,
    )


@router.get("/jobs/{job_id}/results", response_model=JobResultsOut)
def get_job_results(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.status != JobStatus.completed:
        raise HTTPException(409, detail=f"Job is {job.status.value}, results not ready yet")

    txns = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    anomalies = [t for t in txns if t.is_anomaly]

    summary_dict = None
    if job.summary:
        summary_dict = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "top_merchants": job.summary.top_merchants,
            "anomaly_count": job.summary.anomaly_count,
            "narrative": job.summary.narrative,
            "risk_level": job.summary.risk_level,
            "llm_calls_made": job.summary.llm_calls_made,
            "llm_calls_saved_by_cache": job.summary.llm_calls_saved_by_cache,
        }

    return JobResultsOut(
        job=JobOut.model_validate(job),
        transactions=[TransactionOut.model_validate(t) for t in txns],
        anomalies=[TransactionOut.model_validate(t) for t in anomalies],
        category_breakdown=job.summary.category_breakdown if job.summary else {},
        summary=summary_dict,
    )


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(status: str | None = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(Job)
    if status:
        try:
            status_enum = JobStatus(status)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status '{status}'")
        q = q.filter(Job.status == status_enum)
    return q.order_by(Job.created_at.desc()).all()
