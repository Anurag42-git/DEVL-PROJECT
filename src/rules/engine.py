"""
Experiment 11 - Explainable rule engine + review queue
======================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Every rule produces a FLAG, never a verdict. A flag always carries:

    rule_id, rule_name, severity, entity_type, entity_id,
    evidence  - the actual numbers that fired the rule
    reason    - a human-readable explanation
    outcome   - PENDING (never "fraud", never "confirmed")

The system deliberately has no "fraud" label on any record. Investigators
decide the outcome; the rules only explain why something needs looking at.

Rules
-----
R001 multi-leg payment            INFO     explain why leg sums are legitimate
R002 refund exceeds amount        HIGH     summed refunds > amount collected
R003 orphan refund                HIGH     refund with no resolvable transaction
R004 backward status transition   HIGH     lifecycle moved to an earlier state
R005 refund before capture        MEDIUM   refund timestamp precedes the payment
R006 future timestamp             MEDIUM   event dated in the future
R007 non-positive amount          HIGH     zero or negative payment
R008 currency mismatch            LOW      multiple currencies in one intent
R009 high transaction velocity    MEDIUM   >N intents in a 30-minute window
R010 repeated failed attempts     MEDIUM   >=N declines in a 10-minute window
R011 high merchant refund ratio   MEDIUM   refund ratio above threshold
R012 shared device                LOW      device used by many cards
R013 refund on non-refundable     HIGH     refund against an uncaptured payment
R014 orphan reference             MEDIUM   missing customer / merchant parent
R015 duplicate event              LOW      byte-identical duplicate record

Inputs : data/output/reconciled_ledger.parquet + data/staging/*.parquet
Outputs: data/output/review_queue.{parquet,csv}
         data/output/rule_summary.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "data" / "staging"
OUTPUT = ROOT / "data" / "output"

RULE_NAMES = {
    "R001": "multi_leg_payment",
    "R002": "refund_exceeds_amount",
    "R003": "orphan_refund",
    "R004": "backward_status_transition",
    "R005": "refund_before_capture",
    "R006": "future_timestamp",
    "R007": "non_positive_amount",
    "R008": "currency_mismatch",
    "R009": "high_transaction_velocity",
    "R010": "repeated_failed_attempts",
    "R011": "high_merchant_refund_ratio",
    "R012": "shared_device",
    "R013": "refund_on_non_refundable",
    "R014": "orphan_reference",
    "R015": "duplicate_event",
}


def load_config() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class FlagCollector:
    """Accumulates flags with consistent evidence + human explanations."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seq = 0

    def add(
        self,
        rule_id: str,
        severity: str,
        entity_type: str,
        entity_id: str,
        intent_id: str,
        source_system: str,
        evidence: dict,
        reason: str,
        customer_id: str = "",
        merchant_id: str = "",
    ) -> None:
        self._seq += 1
        clean = {k: _jsonable(v) for k, v in evidence.items()}
        self.rows.append({
            "flag_id": f"FLAG{self._seq:08d}",
            "rule_id": rule_id,
            "rule_name": RULE_NAMES[rule_id],
            "severity": severity,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "payment_intent_id": str(intent_id),
            "source_system": str(source_system),
            "customer_id": str(customer_id),
            "merchant_id": str(merchant_id),
            "evidence": json.dumps(clean, sort_keys=True),
            "reason": reason,
            "outcome": "PENDING",
            "flagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    def frame(self) -> pd.DataFrame:
        cols = [
            "flag_id", "rule_id", "rule_name", "severity",
            "entity_type", "entity_id", "payment_intent_id", "source_system",
            "customer_id", "merchant_id", "evidence", "reason",
            "outcome", "flagged_at",
        ]
        return pd.DataFrame(self.rows, columns=cols)


def _jsonable(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (bool,)):
        return bool(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


# ---------------------------------------------------------------------------
# Intent-level rules
# ---------------------------------------------------------------------------
def intent_rules(ledger: pd.DataFrame, flags: FlagCollector) -> None:
    for row in ledger.itertuples(index=False):
        intent = row.payment_intent_id
        src = row.source_system
        cust, merch = str(row.customer_id), str(row.merchant_id)

        # R001 - explain multi-leg payments (never an error, just transparency)
        if row.is_multi_leg:
            flags.add(
                "R001", "INFO", "payment_intent", intent, intent, src,
                {"leg_count": int(row.leg_count),
                 "collected_amount": round(float(row.collected_amount), 2)},
                f"Payment intent was settled with {int(row.leg_count)} additive "
                f"instrument legs totalling {float(row.collected_amount):.2f}; "
                "all legs were summed, none discarded.",
                cust, merch,
            )

        # R002 - over-refund
        if row.refund_state == "OVER":
            excess = float(row.refunded_amount_raw) - float(row.collected_amount)
            flags.add(
                "R002", "HIGH", "payment_intent", intent, intent, src,
                {"collected": round(float(row.collected_amount), 2),
                 "refunded_raw": round(float(row.refunded_amount_raw), 2),
                 "excess": round(excess, 2),
                 "refund_count": int(row.refund_count)},
                f"Refunds totalling {float(row.refunded_amount_raw):.2f} exceed the "
                f"{float(row.collected_amount):.2f} collected by {excess:.2f}. "
                "The ledger capped the refund at the collected amount.",
                cust, merch,
            )

        # R004 - backward lifecycle
        if bool(row.backward_transition):
            flags.add(
                "R004", "HIGH", "payment_intent", intent, intent, src,
                {"lifecycle_events": int(row.lifecycle_event_count),
                 "resolved_status": str(row.resolved_status)},
                "Lifecycle events move to an earlier state, so the recorded "
                "timestamps contradict the expected payment process.",
                cust, merch,
            )

        # R006 - future timestamp
        if pd.notna(row.first_ts) and row.first_ts > pd.Timestamp.now():
            flags.add(
                "R006", "MEDIUM", "payment_intent", intent, intent, src,
                {"first_ts": str(row.first_ts)},
                f"Payment is timestamped {row.first_ts} which is in the future.",
                cust, merch,
            )

        # R007 - non-positive amount
        if int(row.nonpositive_legs) > 0:
            flags.add(
                "R007", "HIGH", "payment_intent", intent, intent, src,
                {"nonpositive_legs": int(row.nonpositive_legs),
                 "collected_amount": round(float(row.collected_amount), 2)},
                f"{int(row.nonpositive_legs)} payment leg(s) have a zero or "
                "negative amount and require confirmation.",
                cust, merch,
            )

        # R008 - multiple currencies
        if int(row.distinct_currencies) > 1:
            flags.add(
                "R008", "LOW", "payment_intent", intent, intent, src,
                {"distinct_currencies": int(row.distinct_currencies)},
                f"The intent's legs use {int(row.distinct_currencies)} different "
                "currencies; amounts are not directly comparable.",
                cust, merch,
            )


# ---------------------------------------------------------------------------
# Refund-level rules
# ---------------------------------------------------------------------------
def refund_rules(ledger: pd.DataFrame, refunds: pd.DataFrame, flags: FlagCollector, cfg: dict) -> None:
    if refunds.empty:
        return

    txn = pd.read_parquet(STAGING / "fact_transaction.parquet")
    leg_map = txn[["txn_id", "source_system", "idempotency_key", "created_ts", "status"]]
    leg_map = leg_map.drop_duplicates("txn_id").rename(columns={
        "idempotency_key": "payment_intent_id",
        "created_ts": "txn_ts",
        "status": "txn_status",
    })
    joined = refunds.merge(
        leg_map, on=["txn_id", "source_system"], how="left", suffixes=("", "_txn")
    )

    refundable = set(cfg["refundable_states"])

    for row in joined.itertuples(index=False):
        intent = str(getattr(row, "payment_intent_id", "") or "")
        src = row.source_system
        cust, merch = str(row.customer_id), str(row.merchant_id)

        # R003 - refund with no transaction reference
        if not intent or intent == "nan":
            flags.add(
                "R003", "HIGH", "refund", row.refund_id, "", src,
                {"refund_id": str(row.refund_id),
                 "amount": round(float(row.amount), 2),
                 "refund_type": str(row.refund_type)},
                f"Refund {row.refund_id} for {float(row.amount):.2f} has no "
                "resolvable transaction reference in the supplied files.",
                cust, merch,
            )
            continue

        # R005 - refund requested before the transaction existed
        if pd.notna(row.requested_ts) and pd.notna(row.txn_ts):
            if row.requested_ts < row.txn_ts:
                flags.add(
                    "R005", "MEDIUM", "refund", row.refund_id, intent, src,
                    {"refund_ts": str(row.requested_ts), "txn_ts": str(row.txn_ts)},
                    f"Refund was requested at {row.requested_ts}, before the "
                    f"transaction was created at {row.txn_ts}.",
                    cust, merch,
                )

        # R013 - refund against a non-refundable state
        status = str(getattr(row, "txn_status", "") or "")
        if status and status not in refundable:
            flags.add(
                "R013", "HIGH", "refund", row.refund_id, intent, src,
                {"txn_status": status, "amount": round(float(row.amount), 2)},
                f"Refund was raised against a transaction in state {status}, "
                "which is not a capturable/refundable state.",
                cust, merch,
            )


# ---------------------------------------------------------------------------
# Behavioural indicators
# ---------------------------------------------------------------------------
def indicator_rules(ledger: pd.DataFrame, flags: FlagCollector, cfg: dict) -> None:
    ind = cfg["indicators"]

    # R009 - high velocity (30-minute tumbling windows)
    from datetime import timedelta

    window = int(ind["velocity"]["window_minutes"])
    limit = int(ind["velocity"]["max_transactions"])

    tmp = ledger[["payment_intent_id", "source_system", "customer_id", "first_ts"]].copy()
    tmp = tmp.dropna(subset=["first_ts", "customer_id"])
    tmp = tmp[tmp["customer_id"].astype(str) != ""]
    tmp["bucket"] = tmp["first_ts"].dt.floor(f"{window}min")

    bursts = tmp.groupby(
        ["customer_id", "source_system", "bucket"], as_index=False
    ).size()
    bursts = bursts[bursts["size"] > limit]

    for row in bursts.itertuples(index=False):
        members = tmp[
            (tmp["customer_id"] == row.customer_id)
            & (tmp["source_system"] == row.source_system)
            & (tmp["bucket"] == row.bucket)
        ]
        for intent in members["payment_intent_id"].head(25):
            flags.add(
                "R009", "MEDIUM", "payment_intent", intent, intent, row.source_system,
                {"window_minutes": window,
                 "transactions_in_window": int(row.size),
                 "threshold": limit,
                 "window_start": str(row.bucket)},
                f"{int(row.size)} payment intents occurred in a {window}-minute "
                f"window (threshold {limit}).",
                str(row.customer_id), "",
            )

    # R010 - repeated failed attempts
    fwindow = int(ind["failed_attempts"]["window_minutes"])
    flimit = int(ind["failed_attempts"]["max_failures"])
    failed_states = {"DECLINED", "FAILED", "TIMEOUT"}

    failed = ledger[ledger["resolved_status"].isin(failed_states)][
        ["payment_intent_id", "source_system", "customer_id", "first_ts", "resolved_status"]
    ].dropna(subset=["first_ts", "customer_id"])
    failed = failed[failed["customer_id"].astype(str) != ""]
    failed["bucket"] = failed["first_ts"].dt.floor(f"{fwindow}min")

    streaks = failed.groupby(
        ["customer_id", "source_system", "bucket"], as_index=False
    ).size()
    streaks = streaks[streaks["size"] >= flimit]

    for row in streaks.itertuples(index=False):
        members = failed[
            (failed["customer_id"] == row.customer_id)
            & (failed["source_system"] == row.source_system)
            & (failed["bucket"] == row.bucket)
        ]
        for intent in members["payment_intent_id"].head(25):
            flags.add(
                "R010", "MEDIUM", "payment_intent", intent, intent, row.source_system,
                {"window_minutes": fwindow,
                 "failed_attempts": int(row.size),
                 "threshold": flimit,
                 "window_start": str(row.bucket)},
                f"{int(row.size)} failed payment attempts in {fwindow} minutes "
                f"(threshold {flimit}).",
                str(row.customer_id), "",
            )

    # R011 - high merchant refund ratio
    min_txns = int(ind["refund_ratio"]["min_transactions"])
    threshold = float(ind["refund_ratio"]["threshold"])

    merchants = ledger.groupby("merchant_id", as_index=False).agg(
        transactions=("payment_intent_id", "size"),
        refunded=("refund_count", lambda s: int((s > 0).sum())),
    )
    merchants = merchants[
        (merchants["transactions"] >= min_txns)
        & (merchants["merchant_id"].astype(str) != "")
    ].copy()
    merchants["ratio"] = merchants["refunded"] / merchants["transactions"]
    high = merchants[merchants["ratio"] > threshold]

    for row in high.itertuples(index=False):
        flags.add(
            "R011", "MEDIUM", "merchant", row.merchant_id, "", "MULTI",
            {"transactions": int(row.transactions),
             "refunded_transactions": int(row.refunded),
             "refund_ratio": round(float(row.ratio), 4),
             "threshold": threshold},
            f"Merchant {row.merchant_id} has a {row.ratio*100:.1f}% refund ratio "
            f"across {int(row.transactions)} transactions (threshold {threshold*100:.0f}%).",
            "", str(row.merchant_id),
        )

    # R012 - shared device
    device_path = STAGING / "dim_device.parquet"
    if device_path.exists():
        devices = pd.read_parquet(device_path)
        shared = devices[devices["is_shared"] == True]  # noqa: E712
        shared_ids = set(shared["device_id"])

        with_device = ledger[ledger["device_id"].astype(str).isin(shared_ids)]
        for row in with_device.itertuples(index=False):
            dev = shared[shared["device_id"] == row.device_id].iloc[0]
            flags.add(
                "R012", "LOW", "payment_intent", row.payment_intent_id,
                row.payment_intent_id, row.source_system,
                {"device_id": str(row.device_id),
                 "linked_cards": int(dev["linked_customer_count"]),
                 "device_type": str(dev["device_type"])},
                f"Device fingerprint is linked to {int(dev['linked_customer_count'])} "
                "distinct cards.",
                str(row.customer_id), str(row.merchant_id),
            )


# ---------------------------------------------------------------------------
# Dimension / duplicate rules
# ---------------------------------------------------------------------------
def reference_rules(ledger: pd.DataFrame, flags: FlagCollector) -> None:
    # R014 - orphan customer / merchant references
    for table, col, rule in (
        ("dim_customer", "customer_id", "customer"),
        ("dim_merchant", "merchant_id", "merchant"),
    ):
        path = STAGING / f"{table}.parquet"
        if not path.exists():
            continue
        valid = set(pd.read_parquet(path)[col].astype(str))
        supplied = ledger[ledger[col].astype(str) != ""]
        orphans = supplied[~supplied[col].astype(str).isin(valid)]
        for row in orphans.itertuples(index=False):
            flags.add(
                "R014", "MEDIUM", "payment_intent", row.payment_intent_id,
                row.payment_intent_id, row.source_system,
                {"column": col, "value": str(getattr(row, col))},
                f"Transaction references a {rule} that is absent from {table}.",
                str(row.customer_id), str(row.merchant_id),
            )

    # R015 - exact duplicate transaction rows
    txn = pd.read_parquet(STAGING / "fact_transaction.parquet")
    dupes = txn[txn.duplicated(keep=False)]
    for row in dupes.itertuples(index=False):
        flags.add(
            "R015", "LOW", "transaction", row.txn_id,
            str(row.idempotency_key), row.source_system,
            {"txn_id": str(row.txn_id), "amount": round(float(row.amount), 2)},
            "Transaction row is byte-identical to another row and would be "
            "double-counted if loaded naively.",
            str(row.customer_id), str(row.merchant_id),
        )


# ---------------------------------------------------------------------------
# Evaluation (labels joined only AFTER flags are produced)
# ---------------------------------------------------------------------------
def evaluate(flags: pd.DataFrame) -> dict:
    label_path = STAGING / "eval_labels.parquet"
    if not label_path.exists() or flags.empty:
        return {}

    labels = pd.read_parquet(label_path)[["txn_id", "is_fraud"]]
    ieee = flags[flags["source_system"] == "IEEE_CIS"]
    if ieee.empty:
        return {}

    # IEEE txn_id in the ledger is "IEEE_<TransactionID>"; eval uses the same.
    merged = ieee.merge(labels, left_on="payment_intent_id", right_on="txn_id", how="inner")
    intents = set(merged["payment_intent_id"])
    all_labels = labels[labels["txn_id"].isin(ieee["payment_intent_id"])].drop_duplicates("txn_id")

    flagged = all_labels[all_labels["txn_id"].isin(intents)]
    tp = int(flagged["is_fraud"].sum())
    fp = int(len(flagged) - tp)
    fn = int(all_labels["is_fraud"].sum()) - tp
    tn = int(len(all_labels) - tp - fp - fn)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "note": (
            "Flags are rule-based review candidates, not fraud predictions. "
            "is_fraud is joined only AFTER flagging (no leakage)."
        ),
        "labelled_intents": int(len(all_labels)),
        "flagged_intents": int(len(flagged)),
        "true_positives": tp, "false_positives": fp,
        "false_negatives": fn, "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    cfg = load_config()
    ledger_path = OUTPUT / "reconciled_ledger.parquet"
    if not ledger_path.exists():
        print("No ledger. Run: python -m src.reconcile.ledger")
        return 1

    print("\n" + "=" * 74)
    print("EXPLAINABLE RULE ENGINE".center(74))
    print("=" * 74)

    ledger = pd.read_parquet(ledger_path)
    refunds = pd.read_parquet(STAGING / "fact_refund.parquet")

    flags = FlagCollector()
    print("[1/4] intent-level rules ...", flush=True)
    intent_rules(ledger, flags)
    print("[2/4] refund-level rules ...", flush=True)
    refund_rules(ledger, refunds, flags, cfg)
    print("[3/4] behavioural indicators ...", flush=True)
    indicator_rules(ledger, flags, cfg)
    print("[4/4] reference and duplicate rules ...", flush=True)
    reference_rules(ledger, flags)

    queue = flags.frame()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    queue.to_parquet(OUTPUT / "review_queue.parquet", index=False)
    queue.to_csv(OUTPUT / "review_queue.csv", index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_flags": len(queue),
        "distinct_intents_flagged": int(
            queue[queue["payment_intent_id"] != ""]["payment_intent_id"].nunique()
        ),
        "by_rule": {str(k): int(v) for k, v in queue["rule_id"].value_counts().items()},
        "by_severity": {str(k): int(v) for k, v in queue["severity"].value_counts().items()},
        "evaluation": evaluate(queue),
    }
    (OUTPUT / "rule_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("\nFlags by rule")
    print("-" * 74)
    for rule, n in sorted(summary["by_rule"].items()):
        print(f"  {rule} {RULE_NAMES.get(rule, ''):<36} {n:>8,}")

    print("\nFlags by severity")
    print("-" * 74)
    for sev, n in sorted(summary["by_severity"].items()):
        print(f"  {sev:<10}{n:>8,}")

    if summary["evaluation"]:
        e = summary["evaluation"]
        print("\nLabel-based evaluation (IEEE-CIS only)")
        print("-" * 74)
        print(f"  precision={e['precision']}  recall={e['recall']}  f1={e['f1']}")
        print(f"  flagged={e['flagged_intents']:,} of {e['labelled_intents']:,}")

    print(f"\nTotal flags: {len(queue):,} across "
          f"{summary['distinct_intents_flagged']:,} payment intents")
    print("\nWritten:\n  data/output/review_queue.parquet\n"
          "  data/output/review_queue.csv\n  data/output/rule_summary.json\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
