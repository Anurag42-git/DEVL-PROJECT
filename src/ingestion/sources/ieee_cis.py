"""
Experiment 1 - Ingestion adapter: IEEE-CIS -> canonical model
=============================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Source: IEEE-CIS Fraud Detection (Kaggle / Vesta Corporation)
        590,540 card transactions, 144,233 with device identity, 2017-12 to 2018-06.

What this adapter contributes
-----------------------------
* `dim_device`        - REAL device fingerprints (1,786 distinct DeviceInfo
                        values), device type, first/last seen, and how many
                        distinct cards each device has been used with. This is
                        what makes the shared-device rule (R012) real.
* `fact_transaction`  - 590,540 settled card transactions with card fingerprint,
                        region and amount.
* `eval_labels`       - the `isFraud` ground truth (20,663 positives, 3.499%).
                        Written to a SEPARATE table on purpose.

Label leakage warning
---------------------
`isFraud` is post-hoc truth from the card network. Using it as an input feature
would be leakage and would make every result meaningless. It is therefore never
placed in `fact_transaction`; it is emitted only as `eval_labels`, which the
evaluation step joins AFTER the rules have fired, to measure precision/recall.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..schema import conform

SOURCE = "IEEE_CIS"
CURRENCY = "USD"

# TransactionDT is seconds elapsed from this reference instant.
REFERENCE_TS = datetime(2017, 12, 1)

# A device is considered shared once this many distinct cards touch it.
SHARED_DEVICE_MIN_CARDS = 4

TX_COLS = [
    "TransactionID", "isFraud", "TransactionDT", "TransactionAmt",
    "ProductCD", "card1", "card2", "card4", "card6",
    "addr1", "addr2", "P_emaildomain", "dist1",
]

# NOTE: `DeviceInfo` alone is NOT a device identifier - it is a device family
# ("Windows", "MacOS"). Grouping on it produced 4,846 cards on "one device".
# A usable fingerprint is the composite below: 9,705 devices, median 1 card.
#
# Measured on the real labels (see eval step):
#   transactions WITH identity .......... 7.85% fraud  (n=144,233)
#   overall baseline .................... 3.50% fraud  (n=590,540)
#   device shared vs not shared ......... 7.91% vs 7.25%  (1.09x)
#
# So the 2.2x gap is driven by identity COVERAGE, not by sharing. Device
# sharing on its own is a weak standalone signal - which is exactly why the
# rule engine combines indicators instead of trusting any single one.
ID_COLS = ["TransactionID", "DeviceType", "DeviceInfo", "id_30", "id_31", "id_33"]

FINGERPRINT_COLS = ["DeviceInfo", "id_30", "id_31", "id_33"]


def _load(raw: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = raw / "ieee_cis"
    tx = pd.read_csv(base / "train_transaction.csv", usecols=TX_COLS)
    ident = pd.read_csv(base / "train_identity.csv", usecols=ID_COLS)
    return tx, ident


def _device_fingerprint(ident: pd.DataFrame) -> pd.Series:
    """Composite device fingerprint: device family + OS + browser + resolution."""
    composite = ident[FINGERPRINT_COLS].astype(str).agg("|".join, axis=1)
    return "IEEE_DEV_" + composite.map(
        lambda s: hashlib.md5(s.encode("utf-8")).hexdigest()[:12]
    )


def build(raw: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    tx, ident = _load(raw)
    stats: dict = {"transactions": len(tx), "identity_rows": len(ident)}

    # ------------------------------------------------------------- timestamps
    tx["created_ts"] = pd.to_datetime(
        REFERENCE_TS
    ) + pd.to_timedelta(tx["TransactionDT"], unit="s")

    # ------------------------------------------------------------- identities
    tx["customer_id"] = "IEEE_CARD_" + tx["card1"].astype("Int64").astype("string")
    tx["card_last4"] = tx["card1"].astype("Int64").astype("string").str[-4:]

    ident = ident.copy()
    ident["device_id"] = _device_fingerprint(ident)

    merged = tx.merge(
        ident[["TransactionID", "device_id", "DeviceType", "id_30"]],
        on="TransactionID", how="left",
    )
    stats["transactions_with_device"] = int(merged["device_id"].notna().sum())
    stats["device_coverage_pct"] = round(
        100 * merged["device_id"].notna().mean(), 1
    )
    stats["distinct_devices"] = int(ident["device_id"].nunique())

    # ------------------------------------------------------- dim_customer
    cust = (
        tx.groupby("customer_id", as_index=False)
        .agg(country=("addr2", "first"))
    )
    dim_customer = conform(
        pd.DataFrame({
            "customer_id": cust["customer_id"],
            "customer_unique_id": cust["customer_id"],
            "city": pd.NA,
            "state": pd.NA,
            "zip_prefix": pd.NA,
            # addr2 is a numeric country/region code in this source
            "country": cust["country"].astype("string"),
            "source_system": SOURCE,
        }),
        "dim_customer",
    )

    # ------------------------------------------------------- dim_merchant
    # The card network feed carries no merchant. One placeholder row keeps
    # referential integrity intact; real merchants come from Olist.
    dim_merchant = conform(
        pd.DataFrame([{
            "merchant_id": "IEEE_NETWORK",
            "merchant_name": "Card network (merchant unknown)",
            "category": "CARD_NETWORK",
            "city": pd.NA,
            "state": pd.NA,
            "country": pd.NA,
            "source_system": SOURCE,
        }]),
        "dim_merchant",
    )

    # ------------------------------------------------------- dim_device
    dev_rows = merged[merged["device_id"].notna()]
    dev = (
        dev_rows.groupby("device_id", as_index=False)
        .agg(
            primary_customer=("customer_id", lambda s: s.mode().iat[0] if not s.mode().empty else pd.NA),
            device_type=("DeviceType", "first"),
            os_version=("id_30", "first"),
            first_seen_ts=("created_ts", "min"),
            last_seen_ts=("created_ts", "max"),
            linked_customer_count=("customer_id", "nunique"),
        )
    )
    dev["is_shared"] = dev["linked_customer_count"] >= SHARED_DEVICE_MIN_CARDS
    stats["shared_devices"] = int(dev["is_shared"].sum())
    stats["median_cards_per_device"] = float(dev["linked_customer_count"].median())

    dim_device = conform(
        pd.DataFrame({
            "device_id": dev["device_id"],
            "customer_id": dev["primary_customer"],
            "device_type": dev["device_type"].astype("string"),
            "os_version": dev["os_version"].astype("string"),
            "first_seen_ts": dev["first_seen_ts"],
            "last_seen_ts": dev["last_seen_ts"],
            "linked_customer_count": dev["linked_customer_count"],
            "is_shared": dev["is_shared"],
            "ip_country": pd.NA,
            "source_system": SOURCE,
        }),
        "dim_device",
    )

    # ------------------------------------------------------- fact_transaction
    fact_transaction = conform(
        pd.DataFrame({
            "txn_id": "IEEE_" + merged["TransactionID"].astype("string"),
            "idempotency_key": "IEEE_" + merged["TransactionID"].astype("string"),
            "attempt_no": 1,
            "retry_of_txn_id": "",
            "customer_id": merged["customer_id"],
            "merchant_id": "IEEE_NETWORK",
            "device_id": merged["device_id"].fillna(""),
            "amount": pd.to_numeric(merged["TransactionAmt"], errors="coerce"),
            "currency": CURRENCY,
            # the feed records settled card transactions only
            "status": "SETTLED",
            "channel": "PCD_" + merged["ProductCD"].astype("string"),
            "card_last4": merged["card_last4"],
            "created_ts": merged["created_ts"],
            "updated_ts": merged["created_ts"],
            "is_retry": False,
            "source_system": SOURCE,
        }),
        "fact_transaction",
    )

    # ------------------------------------------------------- fact_refund
    # The card network feed carries no refund records.
    fact_refund = conform(pd.DataFrame(columns=["refund_id"]), "fact_refund")

    # ------------------------------------------------------- fact_payment_status
    fact_payment_status = conform(
        pd.DataFrame({
            "event_id": "EVT_IEEE_" + merged["TransactionID"].astype("string") + "_SETTLED",
            "txn_id": "IEEE_" + merged["TransactionID"].astype("string"),
            "status": "SETTLED",
            "event_ts": merged["created_ts"],
            "source": "CARD_NETWORK_SETTLEMENT",
            "latency_ms": pd.NA,
            "error_code": "",
            "source_system": SOURCE,
        }),
        "fact_payment_status",
    )

    # ------------------------------------------------------- eval labels
    # NEVER joined into the feature path. Used only to score the rule engine.
    eval_labels = pd.DataFrame({
        "txn_id": "IEEE_" + merged["TransactionID"].astype("string"),
        "is_fraud": merged["isFraud"].astype("int8"),
        "amount": pd.to_numeric(merged["TransactionAmt"], errors="coerce"),
        "product_code": merged["ProductCD"].astype("string"),
        "card_id": merged["customer_id"],
        "device_id": merged["device_id"].fillna(""),
        "txn_ts": merged["created_ts"],
        "source_system": SOURCE,
    })

    stats["frauds"] = int(eval_labels["is_fraud"].sum())
    stats["fraud_rate_pct"] = round(100 * eval_labels["is_fraud"].mean(), 3)

    return {
        "dim_customer": dim_customer,
        "dim_merchant": dim_merchant,
        "dim_device": dim_device,
        "fact_transaction": fact_transaction,
        "fact_refund": fact_refund,
        "fact_payment_status": fact_payment_status,
        "_eval_labels": eval_labels,
    }, stats
