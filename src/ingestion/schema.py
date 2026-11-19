"""
Experiment 1 / Experiment 4 - Canonical schema
==============================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Three unrelated public datasets are being unified into ONE payment-monitoring
model. This module is the contract: it defines the six canonical tables, their
columns, and the conformance helper every adapter must pass through.

Why a canonical model at all?
-----------------------------
Olist (Brazilian marketplace), Online Retail II (UK wholesaler) and IEEE-CIS
(card network) share no keys, no currency and no status vocabulary. Without a
shared contract every downstream module (quality, reconciliation, rules,
indicators, ledger, dashboard) would need to know about all three sources.
With it, downstream code sees only `fact_transaction`, `fact_refund`, ...

`source_system` is carried on every fact row so the ledger can reconcile within
a source (cross-source reconciliation is meaningless - different merchants,
different currencies, different ledgers).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Canonical table definitions
# ---------------------------------------------------------------------------
CANONICAL_SCHEMA: dict[str, list[str]] = {
    # --- dimensions -------------------------------------------------------
    "dim_customer": [
        "customer_id", "customer_unique_id", "city", "state",
        "zip_prefix", "country", "source_system",
    ],
    "dim_merchant": [
        "merchant_id", "merchant_name", "category", "city", "state",
        "country", "source_system",
    ],
    "dim_device": [
        "device_id", "customer_id", "device_type", "os_version",
        "first_seen_ts", "last_seen_ts", "linked_customer_count",
        "is_shared", "ip_country", "source_system",
    ],
    # --- facts ------------------------------------------------------------
    "fact_transaction": [
        "txn_id", "idempotency_key", "attempt_no", "retry_of_txn_id",
        "customer_id", "merchant_id", "device_id",
        "amount", "currency", "status", "channel", "card_last4",
        "created_ts", "updated_ts", "is_retry", "source_system",
    ],
    "fact_refund": [
        "refund_id", "txn_id", "customer_id", "merchant_id",
        "amount", "currency", "status", "refund_type", "reason",
        "requested_ts", "processed_ts", "source_system",
    ],
    "fact_payment_status": [
        "event_id", "txn_id", "status", "event_ts", "source",
        "latency_ms", "error_code", "source_system",
    ],
}

# Canonical status vocabulary. Every source maps onto exactly these values so
# the state machine in config/settings.yaml stays source-agnostic.
CANONICAL_STATUSES = [
    "INITIATED", "AUTHORIZED", "CAPTURED", "SETTLED",
    "DECLINED", "FAILED", "TIMEOUT", "REVERSED", "REFUNDED",
]

# Terminal / failure states used by the reconciliation step.
FAILURE_STATUSES = {"DECLINED", "FAILED", "TIMEOUT"}
SUCCESS_STATUSES = {"CAPTURED", "SETTLED"}


def conform(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """
    Force a frame onto the canonical contract: exact column set, exact order.

    Missing columns are added as NA rather than raising, because real source
    files genuinely lack fields (e.g. Olist has no device_id). The quality
    report later measures how much is missing - silently inventing values
    would hide a real data gap.
    """
    expected = CANONICAL_SCHEMA[table]
    out = df.copy()
    for col in expected:
        if col not in out.columns:
            out[col] = pd.NA
    return out[expected]


def validate(df: pd.DataFrame, table: str, source: str) -> list[str]:
    """Return a list of contract violations. Empty list means conformant."""
    problems: list[str] = []
    expected = CANONICAL_SCHEMA[table]

    missing = [c for c in expected if c not in df.columns]
    if missing:
        problems.append(f"{table}/{source}: missing columns {missing}")

    if "source_system" in df.columns:
        bad = set(df["source_system"].dropna().unique()) - {source}
        if bad:
            problems.append(f"{table}/{source}: unexpected source_system values {bad}")

    if table == "fact_transaction" and "status" in df.columns:
        bad = set(df["status"].dropna().unique()) - set(CANONICAL_STATUSES)
        if bad:
            problems.append(f"{table}/{source}: non-canonical statuses {sorted(bad)}")

    if table in ("fact_transaction", "fact_refund") and "amount" in df.columns:
        if not pd.api.types.is_numeric_dtype(df["amount"]):
            problems.append(f"{table}/{source}: amount is not numeric")

    return problems


def write_tables(tables: dict[str, pd.DataFrame], out_dir: Path, fmt: str = "parquet") -> dict[str, str]:
    """Persist canonical tables to data/staging/ and return {table: path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for name, df in tables.items():
        if fmt == "parquet":
            path = out_dir / f"{name}.parquet"
            df.to_parquet(path, index=False)
        else:
            path = out_dir / f"{name}.csv"
            df.to_csv(path, index=False)
        written[name] = str(path)

    return written
