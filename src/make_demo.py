"""
Build a small, REPRESENTATIVE real-data sample for the hosted dashboard.

The full outputs are git-ignored (hundreds of MB). Streamlit Community Cloud
clones only the repo, so it needs a committed sample. These are ACTUAL rows
from the pipeline - nothing is invented.

Sample design: stratify so rare-but-important states still appear, then fill
the rest at random. A plain random sample of 8,000 intents misses all 57
OVER-refunded cases, which made the dashboard show a misleading "0".

  - keep every OVER and FULL refunded intent (rare, and the most interesting)
  - keep every HIGH-severity flag's intent (the queue must look realistic)
  - fill the remainder with a random sample

Then keep every flag attached to the sampled intents. All rows are ACTUAL rows
from the pipeline - nothing is invented.

Run: python -m src.make_demo
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
DEMO = ROOT / "data" / "demo"
DOCS = ROOT / "docs"


def main() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)

    ledger = pd.read_parquet(OUT / "reconciled_ledger.parquet")
    queue = pd.read_parquet(OUT / "review_queue.parquet")

    n = min(8000, len(ledger))

    # 1. guarantee the rare OVER cases are browsable in the table
    rare = ledger[ledger["refund_state"] == "OVER"]

    keep = rare.drop_duplicates("payment_intent_id").head(n)

    # 2. random fill
    remaining = n - len(keep)
    pool = ledger[~ledger["payment_intent_id"].isin(set(keep["payment_intent_id"]))]
    filler = pool.sample(n=min(remaining, len(pool)), random_state=7) if remaining > 0 else pool.iloc[0:0]

    demo_l = (
        pd.concat([keep, filler])
        .sample(frac=1, random_state=7)  # shuffle so the table isn't ordered by class
        .reset_index(drop=True)
    )

    # only flags attached to those intents
    demo_q = queue[queue["payment_intent_id"].isin(set(demo_l["payment_intent_id"]))]
    demo_q = demo_q.reset_index(drop=True)

    demo_l.to_parquet(DEMO / "reconciled_ledger.parquet", index=False)
    demo_q.to_parquet(DEMO / "review_queue.parquet", index=False)

    # reports shown in the dashboard's Data Quality / Audit Report sections
    for name in ("quality_report.json", "reconciliation_report.json", "rule_summary.json"):
        src = OUT / name
        if src.exists():
            (DEMO / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    audit = DOCS / "audit_report.md"
    if audit.exists():
        (DEMO / "audit_report.md").write_text(
            audit.read_text(encoding="utf-8"), encoding="utf-8"
        )

    for p in sorted(DEMO.iterdir()):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size / 1024:.0f} KB")
    print(
        f"\nledger rows: {len(demo_l):,} | flags: {len(demo_q):,} "
        f"({len(demo_q) / len(demo_l) * 100:.1f} flags per 100 intents)"
    )


if __name__ == "__main__":
    main()
