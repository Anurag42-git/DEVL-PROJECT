"""
Experiment 4 / Experiment 7 - Reconciled payment ledger
=======================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

This is the heart of the project. It collapses all payment activity into one
row per PAYMENT INTENT (source_system + idempotency_key) and answers, for every
intent:

    how much was actually collected?
    how much was refunded (including partial + multiple refunds)?
    is the refund state NONE / PARTIAL / FULL / OVER?
    which quality defects were observed on this intent?

Rules applied (in order)
------------------------
1. Drop byte-identical transaction rows (double-counted events).
2. SUM the remaining legs. Legs are ADDITIVE - verified at 99.4% against Olist
   order totals. Taking MAX would understate revenue.
3. Aggregate refunds per intent. Sum them - do NOT assume one refund per txn.
4. Cap the *ledger* refund amount at the collected amount, but keep the raw
   figure so an over-refund remains visible and explainable.
5. Attach lifecycle and quality flags from the canonical tables.

Performance note: this runs over 736k legs and 1.03M lifecycle events. Every
transformation is vectorised; there are no per-row `.apply()` calls on the hot
path (the first implementation timed out at 15 minutes for that reason).

Inputs : data/staging/*.parquet
Outputs: data/output/reconciled_ledger.{parquet,csv}
         data/output/reconciliation_report.json

Usage
-----
    python -m src.reconcile.ledger
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "data" / "staging"
OUTPUT = ROOT / "data" / "output"

# Highest-priority terminal state wins when a payment intent has several legs.
STATUS_PRIORITY = {
    "REFUNDED": 7,
    "SETTLED": 6,
    "CAPTURED": 5,
    "REVERSED": 4,
    "AUTHORIZED": 3,
    "INITIATED": 2,
    "DECLINED": 1,
    "FAILED": 1,
    "TIMEOUT": 1,
}
RANK_TO_STATUS = {v: k for k, v in STATUS_PRIORITY.items()}

ALLOWED_TRANSITIONS = {
    "INITIATED": ["AUTHORIZED", "DECLINED", "FAILED", "TIMEOUT"],
    "AUTHORIZED": ["CAPTURED", "REVERSED", "FAILED"],
    "CAPTURED": ["SETTLED", "REVERSED"],
    "SETTLED": ["REVERSED"],
}
LIFECYCLE_ORDER = {"INITIATED": 0, "AUTHORIZED": 1, "CAPTURED": 2, "SETTLED": 3}

KEYS = ["source_system", "idempotency_key"]


def _load() -> dict[str, pd.DataFrame]:
    names = ["fact_transaction", "fact_refund", "fact_payment_status"]
    return {
        n: pd.read_parquet(STAGING / f"{n}.parquet")
        for n in names if (STAGING / f"{n}.parquet").exists()
    }


# ---------------------------------------------------------------------------
# Step 1-2: transaction legs -> intents
# ---------------------------------------------------------------------------
def build_intents(txn: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats: dict = {"leg_rows_in": len(txn)}

    before = len(txn)
    txn = txn.drop_duplicates().copy()
    stats["exact_duplicate_rows_dropped"] = before - len(txn)

    txn["amount"] = pd.to_numeric(txn["amount"], errors="coerce")
    txn["_rank"] = txn["status"].map(STATUS_PRIORITY).fillna(0).astype("int16")
    txn["_nonpos"] = (txn["amount"] <= 0).astype("int8")

    # groupby.first() skips NA, so turn empty strings into NA before grouping
    for col in ("customer_id", "merchant_id", "device_id"):
        txn[col] = txn[col].replace("", pd.NA)

    grouped = txn.groupby(KEYS, sort=False)
    intents = grouped.agg(
        leg_count=("txn_id", "size"),
        collected_amount=("amount", "sum"),
        _max_rank=("_rank", "max"),
        customer_id=("customer_id", "first"),
        merchant_id=("merchant_id", "first"),
        device_id=("device_id", "first"),
        first_ts=("created_ts", "min"),
        last_ts=("updated_ts", "max"),
        distinct_currencies=("currency", "nunique"),
        distinct_channels=("channel", "nunique"),
        nonpositive_legs=("_nonpos", "sum"),
    ).reset_index()

    intents["resolved_status"] = intents.pop("_max_rank").map(RANK_TO_STATUS)
    intents = intents.rename(columns={"idempotency_key": "payment_intent_id"})
    intents["collected_amount"] = intents["collected_amount"].round(2)
    intents["is_multi_leg"] = intents["leg_count"] > 1

    stats["payment_intents_out"] = len(intents)
    stats["multi_leg_intents"] = int(intents["is_multi_leg"].sum())
    stats["intents_with_nonpositive_leg"] = int((intents["nonpositive_legs"] > 0).sum())
    return intents, stats


# ---------------------------------------------------------------------------
# Step 3-4: refunds -> intents, with capping
# ---------------------------------------------------------------------------
def attach_refunds(intents: pd.DataFrame, ref: pd.DataFrame, txn: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats: dict = {}
    if ref.empty:
        intents["refund_count"] = 0
        intents["partial_refunds"] = 0
        intents["unknown_refunds"] = 0
        intents["refunded_amount_raw"] = 0.0
        intents["refunded_amount"] = 0.0
        intents["refundable_balance"] = intents["collected_amount"]
        intents["refund_state"] = "NONE"
        stats["refund_rows_in"] = 0
        return intents, stats

    ref = ref.copy()
    ref["amount"] = pd.to_numeric(ref["amount"], errors="coerce")
    stats["refund_rows_in"] = len(ref)

    # map the leg-level txn_id used by refunds back to the payment intent
    leg_map = txn[["txn_id", "source_system", "idempotency_key"]].drop_duplicates("txn_id")
    ref = ref.merge(leg_map, on=["txn_id", "source_system"], how="left")
    stats["unmatched_refund_rows"] = int(ref["idempotency_key"].isna().sum())

    ref["_partial"] = (ref["refund_type"] == "PARTIAL").astype("int8")
    ref["_unknown"] = (ref["refund_type"] == "UNKNOWN").astype("int8")
    matched = ref[ref["idempotency_key"].notna()]

    by_intent = matched.groupby(KEYS, as_index=False).agg(
        refund_count=("refund_id", "size"),
        refunded_amount_raw=("amount", "sum"),
        first_refund_ts=("requested_ts", "min"),
        last_refund_ts=("processed_ts", "max"),
        partial_refunds=("_partial", "sum"),
        unknown_refunds=("_unknown", "sum"),
    )

    intents = intents.merge(
        by_intent.rename(columns={"idempotency_key": "payment_intent_id"}),
        on=["source_system", "payment_intent_id"], how="left",
    )

    for col in ("refund_count", "partial_refunds", "unknown_refunds"):
        intents[col] = intents[col].fillna(0).astype(int)
    intents["refunded_amount_raw"] = pd.to_numeric(
        intents["refunded_amount_raw"], errors="coerce"
    ).fillna(0.0)

    raw = intents["refunded_amount_raw"]
    collected = intents["collected_amount"].fillna(0.0)
    intents["refunded_amount"] = raw.clip(upper=collected).round(2)
    intents["refundable_balance"] = (collected - intents["refunded_amount"]).round(2)

    # vectorised state classification
    intents["refund_state"] = np.select(
        [
            raw <= 0,
            raw > collected + 0.01,
            (raw - collected).abs() <= 0.01,
        ],
        ["NONE", "OVER", "FULL"],
        default="PARTIAL",
    )

    stats["intents_with_refund"] = int((intents["refund_count"] > 0).sum())
    stats["over_refunded_intents"] = int((intents["refund_state"] == "OVER").sum())
    stats["fully_refunded_intents"] = int((intents["refund_state"] == "FULL").sum())
    stats["partially_refunded_intents"] = int((intents["refund_state"] == "PARTIAL").sum())
    stats["refunded_amount_raw_total"] = round(float(raw.sum()), 2)
    stats["refunded_amount_capped_total"] = round(float(intents["refunded_amount"].sum()), 2)
    return intents, stats


# ---------------------------------------------------------------------------
# Step 5: lifecycle + quality flags
# ---------------------------------------------------------------------------
def _build_verdict_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    legal = {(k, v) for k, vals in ALLOWED_TRANSITIONS.items() for v in vals}
    all_states = list(STATUS_PRIORITY)
    for p in all_states:
        for c in all_states:
            pair = f"{p}|{c}"
            if (p, c) in legal:
                lookup[pair] = "legal"
            elif p in LIFECYCLE_ORDER and c in LIFECYCLE_ORDER:
                lookup[pair] = (
                    "backward"
                    if LIFECYCLE_ORDER[c] < LIFECYCLE_ORDER[p]
                    else "skipped"
                )
            else:
                lookup[pair] = "invalid"
    return lookup


def attach_lifecycle(intents: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats: dict = {}
    if events.empty:
        intents["lifecycle_event_count"] = 0
        intents["backward_transition"] = False
        intents["skipped_transition"] = False
        return intents, stats

    ev = events.sort_values(["txn_id", "event_ts"], kind="stable").copy()
    ev["prev"] = ev.groupby("txn_id", sort=False)["status"].shift()
    ev = ev[ev["prev"].notna()]

    if len(ev):
        pair = ev["prev"].astype(str) + "|" + ev["status"].astype(str)
        ev["verdict"] = pair.map(_build_verdict_lookup()).fillna("invalid")
        ev["_backward"] = (ev["verdict"] == "backward").astype("int8")
        ev["_skipped"] = (ev["verdict"] == "skipped").astype("int8")

        flags_by_txn = ev.groupby("txn_id", as_index=False).agg(
            backward_transition=("_backward", "max"),
            skipped_transition=("_skipped", "max"),
        )
        flags_by_txn["backward_transition"] = flags_by_txn["backward_transition"].astype(bool)
        flags_by_txn["skipped_transition"] = flags_by_txn["skipped_transition"].astype(bool)
    else:
        flags_by_txn = pd.DataFrame(columns=[
            "txn_id", "backward_transition", "skipped_transition"
        ])

    counts_by_txn = events.groupby("txn_id", as_index=False).size().rename(
        columns={"size": "lifecycle_event_count"}
    )

    leg = pd.read_parquet(STAGING / "fact_transaction.parquet")
    leg = leg[["txn_id", "source_system", "idempotency_key"]].drop_duplicates("txn_id")

    counts = counts_by_txn.merge(leg, on="txn_id", how="left").dropna(
        subset=["idempotency_key"]
    ).groupby(KEYS, as_index=False)["lifecycle_event_count"].max()

    flags = flags_by_txn.merge(leg, on="txn_id", how="left").dropna(
        subset=["idempotency_key"]
    ).groupby(KEYS, as_index=False).agg(
        backward_transition=("backward_transition", "any"),
        skipped_transition=("skipped_transition", "any"),
    )

    intents = intents.merge(
        counts.rename(columns={"idempotency_key": "payment_intent_id"}),
        on=["source_system", "payment_intent_id"], how="left",
    ).merge(
        flags.rename(columns={"idempotency_key": "payment_intent_id"}),
        on=["source_system", "payment_intent_id"], how="left",
    )

    intents["lifecycle_event_count"] = intents["lifecycle_event_count"].fillna(0).astype(int)
    for c in ("backward_transition", "skipped_transition"):
        intents[c] = intents[c].astype("boolean").fillna(False).astype(bool)

    stats["intents_with_backward_transition"] = int(intents["backward_transition"].sum())
    stats["intents_with_skipped_transition"] = int(intents["skipped_transition"].sum())
    return intents, stats


# ---------------------------------------------------------------------------
# Olist amount discrepancy (raw source check)
# ---------------------------------------------------------------------------
def attach_amount_discrepancy(intents: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Compare what Olist paid against what the order items actually cost."""
    stats: dict = {}
    intents["expected_order_amount"] = np.nan
    intents["amount_discrepancy"] = np.nan

    items_path = ROOT / "data" / "raw" / "olist" / "olist_order_items_dataset.csv"
    if not items_path.exists():
        return intents, stats

    items = pd.read_csv(items_path, usecols=["order_id", "price", "freight_value"])
    expected = items.assign(expected=items["price"] + items["freight_value"]).groupby(
        "order_id", as_index=False
    )["expected"].sum()

    mask = intents["source_system"] == "OLIST"
    join = intents.loc[mask, ["payment_intent_id", "collected_amount"]].merge(
        expected.rename(columns={"order_id": "payment_intent_id"}),
        on="payment_intent_id", how="left",
    )
    join["diff"] = (join["collected_amount"] - join["expected"]).round(2)

    idx = intents.index[mask]
    intents.loc[idx, "expected_order_amount"] = join["expected"].to_numpy()
    intents.loc[idx, "amount_discrepancy"] = join["diff"].to_numpy()

    stats["olist_amount_mismatches"] = int((join["diff"].abs() > 0.01).sum())
    return intents, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    data = _load()
    if "fact_transaction" not in data or data["fact_transaction"].empty:
        print("No staging data. Run: python -m src.ingestion.build_canonical")
        return 1

    print("\n" + "=" * 74)
    print("RECONCILED PAYMENT LEDGER".center(74))
    print("=" * 74)

    intents, stats = build_intents(data["fact_transaction"])
    print("[1/4] collapsed payment legs into intents ...", len(intents), flush=True)

    intents, ref_stats = attach_refunds(
        intents, data.get("fact_refund", pd.DataFrame()), data["fact_transaction"]
    )
    stats.update(ref_stats)
    print("[2/4] aggregated and capped refunds ...",
          stats.get("intents_with_refund", 0), "intents", flush=True)

    intents, life_stats = attach_lifecycle(
        intents, data.get("fact_payment_status", pd.DataFrame())
    )
    stats.update(life_stats)
    print("[3/4] attached lifecycle flags", flush=True)

    intents, disc_stats = attach_amount_discrepancy(intents)
    stats.update(disc_stats)
    print("[4/4] checked Olist amount discrepancies", flush=True)

    intents["reconciled_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    discrepancy = intents["amount_discrepancy"].abs().fillna(0) > 0.01
    intents["needs_review"] = (
        intents["refund_state"].eq("OVER")
        | intents["backward_transition"]
        | discrepancy
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    intents.to_parquet(OUTPUT / "reconciled_ledger.parquet", index=False)
    intents.to_csv(OUTPUT / "reconciled_ledger.csv", index=False)

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ledger_rows": len(intents),
        "stats": stats,
        "amount_summary": {
            "collected_total_by_source": {
                str(k): round(float(v), 2)
                for k, v in intents.groupby("source_system")["collected_amount"].sum().items()
            },
            "refunded_raw_total": stats.get("refunded_amount_raw_total", 0),
            "refunded_capped_total": stats.get("refunded_amount_capped_total", 0),
        },
        "refund_state_counts": {
            str(k): int(v) for k, v in intents["refund_state"].value_counts().items()
        },
    }
    (OUTPUT / "reconciliation_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    print("\n" + "-" * 74)
    print(f"{'metric':<44}{'value':>14}")
    print("-" * 74)
    for key, value in stats.items():
        print(f"{key:<44}{str(value):>14}")

    print("\nRefund state distribution")
    print("-" * 74)
    for state, n in report["refund_state_counts"].items():
        print(f"  {state:<12}{n:>10,}")

    print("\nCollected by source")
    print("-" * 74)
    for src, amt in report["amount_summary"]["collected_total_by_source"].items():
        print(f"  {src:<20}{amt:>16,.2f}")

    print(f"\nintents needing review: {int(intents['needs_review'].sum()):,}")
    print("\nWritten:\n  data/output/reconciled_ledger.parquet\n"
          "  data/output/reconciled_ledger.csv\n"
          "  data/output/reconciliation_report.json\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
