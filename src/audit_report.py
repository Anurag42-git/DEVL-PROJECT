"""
Experiment 11 - Audit report generator
Combine the JSON outputs into one human-readable audit report.

Run: python -m src.audit_report
"""

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
DOCS = ROOT / "docs"


def read(name: str) -> dict:
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def md_table(data: dict) -> list[str]:
    lines = ["| Metric | Value |", "|---|---|"]
    for k, v in data.items():
        lines.append(f"| {k} | {v} |")
    return lines


def main() -> None:
    quality = read("quality_report.json")
    recon = read("reconciliation_report.json")
    rules = read("rule_summary.json")

    lines = [
        "# Audit Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 1. Scope",
        "",
        "Transaction Anomaly and Refund Investigation (Experiment 11). "
        "Sources: Olist Brazilian E-Commerce, UCI Online Retail II, IEEE-CIS "
        "Fraud Detection. Pipeline: ingestion → quality assessment → canonical "
        "model → reconciliation → explainable rules → review queue.",
        "",
        "> No record is labelled as fraud. All flags are review candidates with "
        "outcome `PENDING` and the evidence that triggered them.",
        "",
        "## 2. Data quality (Experiment 2)",
        "",
        f"- Severity counts: {quality.get('summary', {})}",
        "- High-severity findings are listed in `docs/quality_report.md`.",
        "",
        "## 3. Reconciliation (Experiments 4 and 7)",
        "",
    ]

    lines += md_table(recon.get("stats", {}))
    lines += [
        "",
        "### Refund state distribution",
        "",
    ]
    lines += md_table(recon.get("refund_state_counts", {}))
    lines += ["", "### Amounts", ""]
    lines += md_table(recon.get("amount_summary", {}))

    lines += [
        "",
        "## 4. Explainable review queue (Experiment 11)",
        "",
        f"Total flags: **{rules.get('total_flags', 0):,}** across "
        f"**{rules.get('distinct_intents_flagged', 0):,}** payment intents.",
        "",
    ]
    lines += md_table(rules.get("by_rule", {}))
    lines += ["", "### Severity", ""]
    lines += md_table(rules.get("by_severity", {}))

    if rules.get("evaluation"):
        lines += ["", "### Label-based evaluation", ""]
        lines += md_table(rules["evaluation"])

    lines += [
        "",
        "## 5. Limitations",
        "",
        "- Online Retail II has no explicit refund→transaction reference; the "
        "link is reconstructed with an as-of join. The 57 over-refund flags are "
        "provisional review candidates.",
        "- Device identity is available for 24.4% of IEEE-CIS transactions only.",
        "- `isFraud` is post-hoc ground truth, used only to score flags after "
        "they are produced — never as a rule input.",
        "",
        "## 6. Outputs",
        "",
        "| File | Contents |",
        "|---|---|",
        "| `data/output/reconciled_ledger.parquet` | one row per payment intent |",
        "| `data/output/review_queue.parquet` | explainable flags, all PENDING |",
        "| `data/output/quality_report.json` | measured data defects |",
        "| `dashboard/app.py` | Streamlit transaction dashboard |",
        "",
    ]

    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / "audit_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Audit report written to {path}")


if __name__ == "__main__":
    main()
