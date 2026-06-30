from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    filename: str
    status: str
    row_count_raw: int
    row_count_clean: int
    duplicate_count: int
    progress_pct: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class JobStatusOut(JobOut):
    summary: Optional[Dict[str, Any]] = None


class TransactionOut(BaseModel):
    txn_id: Optional[str]
    date: Optional[str]
    merchant: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    category: Optional[str]
    account_id: Optional[str]
    notes: Optional[str]
    is_anomaly: bool
    anomaly_reason: Optional[str]
    llm_category: Optional[str]
    llm_failed: bool
    llm_from_cache: bool

    class Config:
        from_attributes = True


class JobResultsOut(BaseModel):
    job: JobOut
    transactions: List[TransactionOut]
    anomalies: List[TransactionOut]
    category_breakdown: Dict[str, float]
    summary: Optional[Dict[str, Any]] = None
