import hashlib
import re
from datetime import datetime
from typing import Optional

import pandas as pd

REQUIRED_COLUMNS = [
    "txn_id", "date", "merchant", "amount", "currency",
    "status", "category", "account_id", "notes",
]

DOMESTIC_ONLY_BRANDS = {"swiggy", "ola", "irctc", "zomato", "jio recharge", "hdfc atm"}


def _parse_date(raw: str) -> Optional[str]:
    if not raw or pd.isna(raw):
        return None
    raw = str(raw).strip()
    formats = ["%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None  # leave null if genuinely unparseable rather than guessing


def _parse_amount(raw) -> Optional[float]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    s = re.sub(r"[^0-9.\-]", "", s)  # strips $, commas, currency symbols
    if s in ("", "-", "."):
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def row_hash(row: dict) -> str:
    """Hash on normalized business fields (not txn_id) so true duplicate
    rows are caught even if txn_id differs or is blank."""
    key = "|".join([
        str(row.get("date") or ""),
        str(row.get("merchant") or "").strip().lower(),
        str(row.get("amount") or ""),
        str(row.get("currency") or "").strip().lower(),
        str(row.get("account_id") or "").strip().lower(),
    ])
    return hashlib.sha256(key.encode()).hexdigest()


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df["date"] = df["date"].apply(_parse_date)
    df["amount"] = df["amount"].apply(_parse_amount)
    df["currency"] = df["currency"].apply(lambda x: str(x).strip().upper() if pd.notna(x) and str(x).strip() else None)
    df["status"] = df["status"].apply(lambda x: str(x).strip().upper() if pd.notna(x) and str(x).strip() else None)
    df["category"] = df["category"].apply(
        lambda x: x.strip() if isinstance(x, str) and x.strip() else "Uncategorised"
    )
    df["merchant"] = df["merchant"].apply(lambda x: str(x).strip() if pd.notna(x) else None)
    df["txn_id"] = df["txn_id"].apply(lambda x: str(x).strip() if pd.notna(x) and str(x).strip() else None)
    df["account_id"] = df["account_id"].apply(lambda x: str(x).strip() if pd.notna(x) else None)
    df["notes"] = df["notes"].apply(lambda x: str(x).strip() if pd.notna(x) else None)

    df["row_hash"] = df.apply(lambda r: row_hash(r.to_dict()), axis=1)
    before = len(df)
    df = df.drop_duplicates(subset=["row_hash"], keep="first")
    duplicate_count = before - len(df)

    # Drop rows with no usable amount or merchant at all - genuinely unusable
    df = df[~(df["amount"].isna() & df["merchant"].isna())]

    return df, duplicate_count
