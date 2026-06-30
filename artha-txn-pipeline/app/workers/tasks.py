import logging
from datetime import datetime

import pandas as pd

from app.core.db import SessionLocal
from app.models import Job, JobStatus, Transaction, JobSummary, MerchantCategoryCache
from app.services.cleaning import clean_dataframe
from app.services.anomaly import detect_anomalies
from app.services.llm import classify_merchants_batch, generate_narrative_summary, LLMError
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 25  # cap per LLM call so prompts stay small and predictable


@celery_app.task(name="app.workers.tasks.process_job", bind=True, max_retries=0)
def process_job(self, job_id: str, file_path: str):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = JobStatus.processing
        job.progress_pct = 5
        db.commit()

        # --- a) Data cleaning ---
        df_raw = pd.read_csv(file_path, dtype=str)
        job.row_count_raw = len(df_raw)
        df_clean, duplicate_count = clean_dataframe(df_raw)
        job.row_count_clean = len(df_clean)
        job.duplicate_count = duplicate_count
        job.progress_pct = 25
        db.commit()

        # --- b) Anomaly detection ---
        df_clean = detect_anomalies(df_clean)
        job.progress_pct = 40
        db.commit()

        # --- c) LLM classification (only for missing/"Uncategorised") ---
        needs_category_mask = df_clean["category"] == "Uncategorised"
        merchants_needing = sorted(set(
            m for m in df_clean.loc[needs_category_mask, "merchant"].dropna().tolist() if m
        ))

        llm_calls_made = 0
        llm_calls_saved_by_cache = 0
        merchant_category_map = {}

        # check persistent cross-job cache first (the differentiator)
        uncached_merchants = []
        for m in merchants_needing:
            norm = m.strip().lower()
            cached = db.get(MerchantCategoryCache, norm)
            if cached:
                merchant_category_map[m] = {"category": cached.category, "confidence": cached.confidence, "from_cache": True}
                cached.hit_count += 1
                llm_calls_saved_by_cache += 1
            else:
                uncached_merchants.append(m)
        db.commit()

        # batch-call the LLM only for genuinely unseen merchants
        for i in range(0, len(uncached_merchants), BATCH_SIZE):
            batch = uncached_merchants[i:i + BATCH_SIZE]
            try:
                result = classify_merchants_batch(batch)
                llm_calls_made += 1
                for m in batch:
                    info = result.get(m) or result.get(m.strip()) or {"category": "Other", "confidence": 0.3}
                    merchant_category_map[m] = {
                        "category": info.get("category", "Other"),
                        "confidence": float(info.get("confidence", 0.5)),
                        "from_cache": False,
                    }
                    norm = m.strip().lower()
                    existing = db.get(MerchantCategoryCache, norm)
                    if not existing:
                        db.add(MerchantCategoryCache(
                            merchant_normalized=norm,
                            category=info.get("category", "Other"),
                            confidence=float(info.get("confidence", 0.5)),
                            hit_count=1,
                        ))
                db.commit()
            except LLMError as e:
                logger.warning("LLM batch failed after retries for job %s: %s", job_id, e)
                for m in batch:
                    merchant_category_map[m] = {"category": None, "confidence": None, "from_cache": False, "failed": True}

        job.progress_pct = 65
        db.commit()

        # --- write transactions ---
        for _, row in df_clean.iterrows():
            info = merchant_category_map.get(row["merchant"], {})
            final_category = row["category"]
            llm_failed = False
            llm_category = None
            llm_from_cache = False
            if row["category"] == "Uncategorised" and info:
                if info.get("failed"):
                    llm_failed = True
                else:
                    llm_category = info.get("category")
                    final_category = llm_category or "Uncategorised"
                    llm_from_cache = info.get("from_cache", False)

            txn = Transaction(
                job_id=job_id,
                row_hash=row["row_hash"],
                txn_id=row.get("txn_id"),
                date=row.get("date"),
                merchant=row.get("merchant"),
                amount=row.get("amount"),
                currency=row.get("currency"),
                status=row.get("status"),
                category=final_category,
                account_id=row.get("account_id"),
                notes=row.get("notes"),
                is_anomaly=bool(row.get("is_anomaly")),
                anomaly_reason=row.get("anomaly_reason"),
                llm_category=llm_category,
                llm_confidence=info.get("confidence") if info else None,
                llm_failed=llm_failed,
                llm_from_cache=llm_from_cache,
            )
            db.add(txn)
        db.commit()
        job.progress_pct = 80
        db.commit()

        # --- d) narrative summary ---
        total_inr = float(df_clean.loc[df_clean["currency"] == "INR", "amount"].sum())
        total_usd = float(df_clean.loc[df_clean["currency"] == "USD", "amount"].sum())
        top_merchants = (
            df_clean.groupby("merchant")["amount"].sum().sort_values(ascending=False).head(3)
        )
        category_breakdown = df_clean.groupby("category")["amount"].sum().to_dict()
        anomaly_count = int(df_clean["is_anomaly"].sum())

        stats_for_llm = {
            "total_spend_inr": round(total_inr, 2),
            "total_spend_usd": round(total_usd, 2),
            "top_merchants": list(top_merchants.index),
            "category_breakdown": {k: round(v, 2) for k, v in category_breakdown.items()},
            "anomaly_count": anomaly_count,
            "row_count": len(df_clean),
        }

        narrative_data = {
            "total_spend_inr": round(total_inr, 2),
            "total_spend_usd": round(total_usd, 2),
            "top_merchants": list(top_merchants.index),
            "anomaly_count": anomaly_count,
            "narrative": None,
            "risk_level": "medium",
        }
        try:
            llm_narrative = generate_narrative_summary(stats_for_llm)
            llm_calls_made += 1
            narrative_data.update({
                "narrative": llm_narrative.get("narrative"),
                "risk_level": llm_narrative.get("risk_level", "medium"),
            })
        except LLMError as e:
            logger.warning("Narrative LLM call failed for job %s: %s", job_id, e)
            narrative_data["narrative"] = (
                f"Narrative generation failed after retries; {anomaly_count} anomalies detected "
                f"across {len(df_clean)} transactions. Review flagged rows manually."
            )
            narrative_data["risk_level"] = "high" if anomaly_count > 0 else "low"

        summary = JobSummary(
            job_id=job_id,
            total_spend_inr=round(total_inr, 2),
            total_spend_usd=round(total_usd, 2),
            top_merchants=list(top_merchants.index),
            category_breakdown={k: round(v, 2) for k, v in category_breakdown.items()},
            anomaly_count=anomaly_count,
            narrative=narrative_data["narrative"],
            risk_level=narrative_data["risk_level"],
            llm_calls_made=llm_calls_made,
            llm_calls_saved_by_cache=llm_calls_saved_by_cache,
        )
        db.add(summary)

        job.status = JobStatus.completed
        job.progress_pct = 100
        job.completed_at = datetime.utcnow()
        db.commit()

    except Exception as e:  # noqa: BLE001
        logger.exception("Job %s failed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job:
            job.status = JobStatus.failed
            job.error_message = str(e)[:2000]
            db.commit()
    finally:
        db.close()
