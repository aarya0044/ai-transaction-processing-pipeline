import pandas as pd

from app.services.cleaning import DOMESTIC_ONLY_BRANDS


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_anomaly"] = False
    df["anomaly_reason"] = None

    # 1) statistical outlier: amount > 3x account's median amount
    medians = df.groupby("account_id")["amount"].median()

    def check_outlier(row):
        reasons = []
        med = medians.get(row["account_id"])
        if pd.notna(row["amount"]) and pd.notna(med) and med > 0 and row["amount"] > 3 * med:
            reasons.append(f"amount {row['amount']} exceeds 3x account median ({round(med, 2)})")

        merchant_lower = str(row["merchant"]).strip().lower() if row["merchant"] else ""
        if row["currency"] == "USD" and merchant_lower in DOMESTIC_ONLY_BRANDS:
            reasons.append(f"USD currency on domestic-only merchant '{row['merchant']}'")

        return reasons

    reasons_series = df.apply(check_outlier, axis=1)
    df["is_anomaly"] = reasons_series.apply(lambda r: len(r) > 0)
    df["anomaly_reason"] = reasons_series.apply(lambda r: "; ".join(r) if r else None)

    return df
