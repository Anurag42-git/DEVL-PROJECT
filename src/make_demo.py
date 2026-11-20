"""
Create a small REAL sample for the hosted dashboard.

The full outputs are git-ignored (they contain hundreds of thousands of rows).
Streamlit Community Cloud clones only the repo, so it needs a small committed
sample. These are actual rows from the pipeline, not invented data.

Run: python -m src.make_demo
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
DEMO = ROOT / "data" / "demo"


def main() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)

    ledger = pd.read_parquet(OUT / "reconciled_ledger.parquet")
    queue = pd.read_parquet(OUT / "review_queue.parquet")

    # keep every HIGH flag + a random spread of the rest
    high = queue[queue["severity"].isin(["HIGH", "MEDIUM"])]
    other = queue.sample(n=min(3000, len(queue)), random_state=42)
    demo_q = (
        pd.concat([high, other])
        .drop_duplicates("flag_id")
        .sample(frac=1, random_state=42)
    )

    # keep every intent referenced by those flags + a random spread
    ids = set(demo_q.loc[demo_q["payment_intent_id"] != "", "payment_intent_id"])
    linked = ledger[ledger["payment_intent_id"].isin(ids)]
    extra = ledger.sample(n=min(3000, len(ledger)), random_state=42)
    demo_l = (
        pd.concat([linked, extra])
        .drop_duplicates("payment_intent_id")
        .sample(frac=1, random_state=42)
    )

    demo_l.to_parquet(DEMO / "reconciled_ledger.parquet", index=False)
    demo_q.to_parquet(DEMO / "review_queue.parquet", index=False)

    for p in sorted(DEMO.glob("*.parquet")):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size / 1024:.0f} KB")
    print(f"ledger rows: {len(demo_l):,} | queue rows: {len(demo_q):,}")


if __name__ == "__main__":
    main()
