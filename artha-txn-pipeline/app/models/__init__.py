import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey,
    Text, Enum, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


def gen_uuid():
    return str(uuid.uuid4())


class JobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    filename = Column(String, nullable=False)
    file_checksum = Column(String, index=True, nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.pending, nullable=False, index=True)
    row_count_raw = Column(Integer, default=0)
    row_count_clean = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    progress_pct = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    transactions = relationship("Transaction", back_populates="job", cascade="all, delete-orphan")
    summary = relationship("JobSummary", back_populates="job", uselist=False, cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("job_id", "row_hash", name="uq_job_row_hash"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id"), nullable=False, index=True)
    row_hash = Column(String, nullable=False, index=True)

    txn_id = Column(String, nullable=True)
    date = Column(String, nullable=True)  # ISO 8601 string after cleaning
    merchant = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    status = Column(String, nullable=True)
    category = Column(String, nullable=True)
    account_id = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    is_anomaly = Column(Boolean, default=False)
    anomaly_reason = Column(Text, nullable=True)

    llm_category = Column(String, nullable=True)
    llm_confidence = Column(Float, nullable=True)
    llm_raw_response = Column(Text, nullable=True)
    llm_failed = Column(Boolean, default=False)
    llm_from_cache = Column(Boolean, default=False)

    job = relationship("Job", back_populates="transactions")


class JobSummary(Base):
    __tablename__ = "job_summaries"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id"), nullable=False, unique=True)

    total_spend_inr = Column(Float, default=0)
    total_spend_usd = Column(Float, default=0)
    top_merchants = Column(JSON, default=list)
    category_breakdown = Column(JSON, default=dict)
    anomaly_count = Column(Integer, default=0)
    narrative = Column(Text, nullable=True)
    risk_level = Column(String, nullable=True)
    llm_calls_made = Column(Integer, default=0)
    llm_calls_saved_by_cache = Column(Integer, default=0)

    job = relationship("Job", back_populates="summary")


class MerchantCategoryCache(Base):
    """
    Differentiator: a persistent merchant -> category cache, shared ACROSS jobs.
    Most submissions will batch LLM calls per-job but still re-classify the
    same merchant (e.g. 'Swiggy') every single upload. This table means the
    LLM is only ever asked once per unique merchant, system-wide, which is
    the actual cost/latency bottleneck at scale (see README "Bottlenecks").
    """
    __tablename__ = "merchant_category_cache"

    merchant_normalized = Column(String, primary_key=True)
    category = Column(String, nullable=False)
    confidence = Column(Float, default=0.0)
    hit_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
