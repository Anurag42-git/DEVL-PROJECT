"""
Experiment 2 - Data quality assessment
======================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Profiles the canonical staging tables and runs the six quality dimensions a
payment system actually cares about:

    1. Completeness       - null / empty rates per column
    2. Uniqueness         - duplicate event records, duplicate refund ids
    3. Referential integrity - orphan customer / merchant / device / refund refs
    4. Amount validity    - non-positive, extreme outliers, refund > transaction
    5. Timestamp validity - created after updated, future-dated records
    6. Status transitions - illegal jumps against the declared state machine

Every finding is quantified and given a severity. Nothing is repaired here:
Experiment 2 measures, Experiment 4 repairs. Keeping them separate is what
makes the audit report defensible.

Outputs
-------
    data/output/quality_report.json
    docs/quality_report.md

Usage
-----
    python -m src.quality.assess
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
DOCS = ROOT / "docs"

TABLES = [
    "dim_customer", "dim_merchant", "dim_device",
    "fact_transaction", "fact_refund", "fact_payment_status",
]

# Referential integrity: (child table, child col, parent table, parent col)
REFERENTIAL_CHECKS = [
    ("fact_transaction", "customer_id", "dim_customer", "customer_id"),
    ("fact_transaction", "merchant_id", "dim_merchant", "merchant_id"),
    ("fact_refund", "txn_id", "fact_transaction", "txn_id"),
    ("fact_refund", "customer_id", "dim_customer", "customer_id"),
    ("fact_refund", "merchant_id", "dim_merchant", "merchant_id"),
    ("fact_payment_status", "txn_id", "fact_transaction", "txn_id"),
]

# IEEE-CIS placeholders that are intentionally not in the dimensions.
KNOWN_PLACEHOLDERS = {"device_id": {""}}

# Columns that are null BY DESIGN. Reporting these as HIGH severity would bury
# the real defects, so they are recorded as INFO with the reason attached.
EXPECTED_NULLS: dict[tuple[str, str], str] = {
    ("fact_refund", "processed_ts"): "no source provides a refund processing timestamp",
    ("fact_payment_status", "latency_ms"): "latency is not present in any source",
    ("dim_device", "ip_country"): "IEEE-CIS exposes no IP country",
    ("dim_device", "os_version"): "id_30 (OS) is missing for some fingerprints",
    ("dim_customer", "city"): "card-network customers have no city",
    ("dim_customer", "state"): "card-network customers have no state",
    ("dim_customer", "zip_prefix"): "card-network customers have no postcode",
    ("fact_transaction", "device_id"): "only 24.4% of card transactions carry identity",
    ("fact_transaction", "card_last4"): "Olist / Online Retail II carry no card number",
}

# Lifecycle ordering, used to tell a skipped state from a backward jump.
LIFECYCLE_ORDER = {"INITIATED": 0, "AUTHORIZED": 1, "CAPTURED": 2, "SETTLED": 3}


def load_config() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_tables() -> dict[str, pd.DataFrame]:
    out = {}
    for name in TABLES:
        path = STAGING / f"{name}.parquet"
        if path.exists():
            out[name] = pd.read_parquet(path)
    return out


# ---------------------------------------------------------------------------
# 1. Completeness
# ---------------------------------------------------------------------------
def check_completeness(tables: dict[str, pd.DataFrame], max_null: float) -> list[dict]:
    findings = []
    for name, df in tables.items():
        if not len(df):
            findings.append({
                "dimension": "completeness", "table": name, "column": "*",
                "metric": "row_count", "value": 0, "severity": "HIGH",
                "detail": "table is empty",
            })
            continue
        for col in df.columns:
            nulls = int(df[col].isna().sum())
            if not nulls:
                continue
            frac = nulls / len(df)
            expected = EXPECTED_NULLS.get((name, col))
            if expected:
                severity = "INFO"
                detail = f"{frac*100:.2f}% null by design - {expected}"
            else:
                severity = "HIGH" if frac > max_null else "INFO"
                detail = f"{frac*100:.2f}% null ({nulls:,} of {len(df):,})"

            findings.append({
                "dimension": "completeness",
                "table": name,
                "column": col,
                "metric": "null_count",
                "value": nulls,
                "fraction": round(frac, 4),
                "severity": severity,
                "detail": detail,
            })
    return findings


# ---------------------------------------------------------------------------
# 2. Uniqueness
# ---------------------------------------------------------------------------
def check_uniqueness(tables: dict[str, pd.DataFrame]) -> list[dict]:
    findings = []

    txn = tables.get("fact_transaction")
    if txn is not None and len(txn):
        exact = int(txn.duplicated().sum())
        findings.append({
            "dimension": "uniqueness", "table": "fact_transaction",
            "column": "*", "metric": "exact_duplicate_rows",
            "value": exact, "fraction": round(exact / len(txn), 6),
            "severity": "HIGH" if exact else "OK",
            "detail": "byte-identical rows - the true double-counting defect",
        })

        # Same intent + same amount + same timestamp is NOT automatically a
        # duplicate: Olist splits a payment across identical vouchers. Measured
        # and reported, deliberately not counted as an error.
        identical = int(txn.duplicated(
            subset=["idempotency_key", "amount", "created_ts", "source_system"]
        ).sum())
        findings.append({
            "dimension": "uniqueness", "table": "fact_transaction",
            "column": "idempotency_key+amount+created_ts",
            "metric": "identical_legs",
            "value": identical, "severity": "INFO",
            "detail": (
                "distinct legs sharing intent, amount and timestamp - legitimate "
                "multi-instrument payments (e.g. two identical vouchers), not duplicates"
            ),
        })

        dup_txn = int(txn["txn_id"].duplicated().sum())
        findings.append({
            "dimension": "uniqueness", "table": "fact_transaction",
            "column": "txn_id", "metric": "duplicate_primary_key",
            "value": dup_txn, "severity": "HIGH" if dup_txn else "OK",
            "detail": "txn_id must be unique",
        })

    ref = tables.get("fact_refund")
    if ref is not None and len(ref):
        dup = int(ref["refund_id"].duplicated().sum())
        findings.append({
            "dimension": "uniqueness", "table": "fact_refund",
            "column": "refund_id", "metric": "duplicate_primary_key",
            "value": dup, "severity": "HIGH" if dup else "OK",
            "detail": "refund_id must be unique",
        })

    ev = tables.get("fact_payment_status")
    if ev is not None and len(ev):
        dup = int(ev.duplicated(subset=["txn_id", "status", "event_ts"]).sum())
        findings.append({
            "dimension": "uniqueness", "table": "fact_payment_status",
            "column": "txn_id+status+event_ts", "metric": "duplicate_events",
            "value": dup, "fraction": round(dup / len(ev), 6),
            "severity": "MEDIUM" if dup else "OK",
            "detail": "the same lifecycle event recorded more than once",
        })

    return findings


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------
def check_referential(tables: dict[str, pd.DataFrame]) -> list[dict]:
    findings = []
    for child, ccol, parent, pcol in REFERENTIAL_CHECKS:
        cdf = tables.get(child)
        pdf = tables.get(parent)
        if cdf is None or pdf is None or not len(cdf):
            continue

        values = cdf[ccol]
        # only judge rows where a reference is actually supplied
        mask = values.notna() & (values.astype("string") != "")
        if ccol in KNOWN_PLACEHOLDERS:
            mask &= ~values.astype("string").isin(KNOWN_PLACEHOLDERS[ccol])

        checked = int(mask.sum())
        if not checked:
            continue

        valid = set(pdf[pcol].dropna().astype("string").unique())
        orphans = int((~values[mask].astype("string").isin(valid)).sum())

        findings.append({
            "dimension": "referential_integrity",
            "table": child,
            "column": ccol,
            "parent": f"{parent}.{pcol}",
            "metric": "orphan_references",
            "value": orphans,
            "fraction": round(orphans / checked, 6),
            "checked": checked,
            "severity": "HIGH" if orphans / checked > 0.001 else ("MEDIUM" if orphans else "OK"),
            "detail": f"{orphans:,} of {checked:,} supplied references have no parent row",
        })
    return findings


# ---------------------------------------------------------------------------
# 4. Amount validity
# ---------------------------------------------------------------------------
def check_amounts(tables: dict[str, pd.DataFrame], cfg: dict) -> list[dict]:
    findings = []
    q = cfg["quality"]
    lo, hi = q["amount_min"], q["amount_max"]

    txn = tables.get("fact_transaction")
    if txn is not None and len(txn):
        amt = pd.to_numeric(txn["amount"], errors="coerce")
        nonpos = int((amt <= 0).sum())
        findings.append({
            "dimension": "amount_validity", "table": "fact_transaction",
            "column": "amount", "metric": "non_positive_amounts",
            "value": nonpos, "severity": "HIGH" if nonpos else "OK",
            "detail": "zero or negative transaction amounts",
        })
        extreme = int(((amt > hi) | ((amt < lo) & (amt > 0))).sum())
        findings.append({
            "dimension": "amount_validity", "table": "fact_transaction",
            "column": "amount", "metric": "out_of_range_amounts",
            "value": extreme, "severity": "MEDIUM" if extreme else "OK",
            "detail": f"outside declared range [{lo}, {hi}]",
        })

    ref = tables.get("fact_refund")
    if ref is not None and len(ref):
        refunded = ref.groupby("txn_id", as_index=False)["amount"].sum()
        merged = refunded.merge(
            txn[["txn_id", "amount"]].rename(columns={"amount": "txn_amount"}),
            on="txn_id", how="inner",
        )
        over = int((merged["amount"] > merged["txn_amount"] + 0.01).sum())
        findings.append({
            "dimension": "amount_validity", "table": "fact_refund",
            "column": "amount", "metric": "refunds_exceeding_transaction",
            "value": over, "severity": "HIGH" if over else "OK",
            "detail": "transactions whose summed refunds exceed the amount collected",
        })
    return findings


# ---------------------------------------------------------------------------
# 5. Timestamp validity
# ---------------------------------------------------------------------------
def check_timestamps(tables: dict[str, pd.DataFrame]) -> list[dict]:
    findings = []
    now = pd.Timestamp.now(tz=None)

    txn = tables.get("fact_transaction")
    if txn is not None and len(txn):
        created = pd.to_datetime(txn["created_ts"], errors="coerce")
        updated = pd.to_datetime(txn["updated_ts"], errors="coerce")

        reversed_order = int((updated < created).sum())
        findings.append({
            "dimension": "timestamp_validity", "table": "fact_transaction",
            "column": "created_ts/updated_ts", "metric": "updated_before_created",
            "value": reversed_order, "severity": "HIGH" if reversed_order else "OK",
            "detail": "updated_ts earlier than created_ts",
        })

        future = int((created > now).sum())
        findings.append({
            "dimension": "timestamp_validity", "table": "fact_transaction",
            "column": "created_ts", "metric": "future_dated",
            "value": future, "severity": "MEDIUM" if future else "OK",
            "detail": "transaction timestamped in the future",
        })

    ref = tables.get("fact_refund")
    if ref is not None and len(ref) and txn is not None:
        r = ref[["refund_id", "txn_id", "requested_ts"]].merge(
            txn[["txn_id", "created_ts"]], on="txn_id", how="inner"
        )
        before = int(
            (pd.to_datetime(r["requested_ts"], errors="coerce")
             < pd.to_datetime(r["created_ts"], errors="coerce")).sum()
        )
        findings.append({
            "dimension": "timestamp_validity", "table": "fact_refund",
            "column": "requested_ts", "metric": "refund_before_transaction",
            "value": before, "severity": "HIGH" if before else "OK",
            "detail": "refund timestamped before the transaction existed",
        })
    return findings


# ---------------------------------------------------------------------------
# 6. Status transitions
# ---------------------------------------------------------------------------
def check_status_transitions(
    tables: dict[str, pd.DataFrame], machine: dict[str, list[str]]
) -> list[dict]:
    ev = tables.get("fact_payment_status")
    if ev is None or not len(ev):
        return []

    allowed = {k: set(v or []) for k, v in machine.items()}

    ordered = ev.sort_values(["txn_id", "event_ts"], kind="stable")
    prev = ordered.groupby("txn_id", sort=False)["status"].shift()

    pairs = pd.DataFrame({
        "prev": prev,
        "curr": ordered["status"],
        "source": ordered["source_system"],
    }).dropna(subset=["prev"])

    if not len(pairs):
        return []

    legal_lookup = {(k, v) for k, vals in allowed.items() for v in vals}

    def classify(p: str, c: str) -> str:
        if (p, c) in legal_lookup:
            return "legal"
        # moving to an EARLIER lifecycle state is a genuine integrity defect
        if p in LIFECYCLE_ORDER and c in LIFECYCLE_ORDER:
            return "backward" if LIFECYCLE_ORDER[c] < LIFECYCLE_ORDER[p] else "skipped"
        return "invalid"

    pairs["verdict"] = [classify(p, c) for p, c in zip(pairs["prev"], pairs["curr"])]
    pairs["pair"] = pairs["prev"] + " -> " + pairs["curr"]

    out = []
    for verdict, severity, explanation in (
        ("backward", "HIGH",
         "lifecycle moved to an EARLIER state - timestamps contradict the process"),
        ("invalid", "HIGH",
         "transition not permitted by the state machine"),
        ("skipped", "MEDIUM",
         "an intermediate state has no event (missing timestamp), so the jump looks illegal"),
    ):
        subset = pairs[pairs["verdict"] == verdict]
        if not len(subset):
            continue
        out.append({
            "dimension": "status_transitions",
            "table": "fact_payment_status",
            "column": "status",
            "metric": f"{verdict}_transitions",
            "value": int(len(subset)),
            "fraction": round(len(subset) / len(pairs), 6),
            "severity": severity,
            "detail": explanation,
        })
        top = subset.groupby(["source", "pair"]).size().sort_values(ascending=False).head(8)
        out.append({
            "dimension": "status_transitions",
            "metric": f"top_{verdict}_pairs",
            "value": {f"{s}: {p}": int(n) for (s, p), n in top.items()},
            "severity": "INFO",
            "detail": f"most frequent {verdict} transitions",
        })

    out.append({
        "dimension": "status_transitions", "table": "fact_payment_status",
        "column": "status", "metric": "transitions_checked",
        "value": int(len(pairs)), "severity": "INFO",
        "detail": "consecutive lifecycle event pairs evaluated",
    })
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def summarise(findings: list[dict]) -> dict:
    counts = {"HIGH": 0, "MEDIUM": 0, "INFO": 0, "OK": 0}
    for f in findings:
        counts[f.get("severity", "INFO")] = counts.get(f.get("severity", "INFO"), 0) + 1
    return counts


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Data Quality Report",
        "",
        f"Generated: {report['generated_at']}  ",
        f"Stage: canonical staging (`data/staging/`)  ",
        "Experiment: 2 — Data Quality Assessment",
        "",
        "> This report measures quality. It does not repair anything.",
        "> Repair happens in the ETL stage (Experiment 4), so the audit trail",
        "> keeps the original defect and the corrective action separate.",
        "",
        "## Summary",
        "",
        "| Severity | Findings |",
        "|---|---|",
    ]
    for sev, n in report["summary"].items():
        lines.append(f"| {sev} | {n} |")

    lines += ["", "## Table profile", "", "| Table | Rows | Columns |", "|---|---|---|"]
    for name, p in report["tables"].items():
        lines.append(f"| `{name}` | {p['rows']:,} | {p['columns']} |")

    high = [f for f in report["findings"] if f["severity"] == "HIGH"]
    med = [f for f in report["findings"] if f["severity"] == "MEDIUM"]

    for title, group in (("High severity", high), ("Medium severity", med)):
        if not group:
            continue
        lines += ["", f"## {title}", "", "| Table | Column | Metric | Value | Detail |", "|---|---|---|---|---|"]
        for f in group:
            lines.append(
                f"| `{f.get('table','-')}` | `{f.get('column','-')}` | "
                f"{f.get('metric','-')} | {f.get('value','-')} | {f.get('detail','-')} |"
            )

    lines += [
        "",
        "## Referential integrity detail",
        "",
        "| Child | Column | Parent | Orphans | Checked |",
        "|---|---|---|---|---|",
    ]
    for f in report["findings"]:
        if f["dimension"] == "referential_integrity":
            lines.append(
                f"| `{f['table']}` | `{f['column']}` | `{f['parent']}` | "
                f"{f['value']:,} | {f['checked']:,} |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    cfg = load_config()
    tables = load_tables()

    if not tables:
        print("No staging tables found. Run: python -m src.ingestion.build_canonical")
        return 1

    print("\n" + "=" * 74)
    print("DATA QUALITY ASSESSMENT - Experiment 2".center(74))
    print("=" * 74)

    findings: list[dict] = []
    findings += check_completeness(tables, cfg["quality"]["max_null_fraction"])
    findings += check_uniqueness(tables)
    findings += check_referential(tables)
    findings += check_amounts(tables, cfg)
    findings += check_timestamps(tables)
    findings += check_status_transitions(tables, cfg["status_machine"])

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tables": {
            name: {"rows": int(len(df)), "columns": int(df.shape[1])}
            for name, df in tables.items()
        },
        "summary": summarise(findings),
        "findings": findings,
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "quality_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    write_markdown(report, DOCS / "quality_report.md")

    # ------------------------------------------------------------- console
    print("\nTable profile")
    print("-" * 74)
    for name, p in report["tables"].items():
        print(f"  {name:<24}{p['rows']:>10,} rows   {p['columns']:>3} cols")

    print("\nFindings by severity")
    print("-" * 74)
    for sev in ("HIGH", "MEDIUM", "INFO", "OK"):
        print(f"  {sev:<8} {report['summary'].get(sev, 0):>4}")

    print("\nKey findings")
    print("-" * 74)
    interesting = [f for f in findings if f["severity"] in ("HIGH", "MEDIUM")]
    if not interesting:
        print("  none")
    for f in interesting:
        print(f"  [{f['severity']:<6}] {f.get('table','-'):<22} "
              f"{f.get('metric','-'):<34} {f.get('value')}")
        print(f"           {f.get('detail','')}")

    print(f"\nWritten:\n  data/output/quality_report.json\n  docs/quality_report.md\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
