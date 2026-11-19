"""
Experiment 1 / Experiment 4 - Canonical build orchestrator
==========================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Runs every source adapter, unions the results into the six canonical tables,
validates each against the contract, and writes them to data/staging/ as
Parquet (typed, compressed, fast for every later stage).

This is the "Extract + initial Transform" half of the ETL pipeline. The load
half (Postgres / MongoDB) is a separate stage so it can be re-run independently.

Usage
-----
    python -m src.ingestion.build_canonical
    python -m src.ingestion.build_canonical --csv        # also emit CSV copies
    python -m src.ingestion.build_canonical --skip orii  # skip the slow xlsx read
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from . import schema
from .sources import olist, online_retail_ii

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"

# Tables that must be unioned across sources vs. kept per source.
UNION_TABLES = [
    "dim_customer", "dim_merchant", "dim_device",
    "fact_transaction", "fact_refund", "fact_payment_status",
]


def _summarise(name: str, df: pd.DataFrame) -> str:
    n = len(df)
    if name.startswith("fact_"):
        src = df["source_system"].value_counts().to_dict() if "source_system" in df else {}
        return f"{n:>10,}  {src}"
    return f"{n:>10,}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical staging tables.")
    parser.add_argument("--csv", action="store_true", help="also write CSV copies")
    parser.add_argument("--skip-orii", action="store_true", help="skip Online Retail II")
    args = parser.parse_args()

    t0 = time.time()
    collected: dict[str, list[pd.DataFrame]] = {t: [] for t in UNION_TABLES}
    source_stats: dict[str, dict] = {}

    print("\n" + "=" * 74)
    print("CANONICAL BUILD".center(74))
    print("=" * 74)

    # ---------------------------------------------------------------- Olist
    print("\n[1/2] Olist ...", end=" ", flush=True)
    try:
        tables = olist.build(RAW)
        for name, df in tables.items():
            collected[name].append(df)
        source_stats["OLIST"] = {k: len(v) for k, v in tables.items()}
        print("ok")
    except FileNotFoundError as exc:
        print(f"SKIPPED ({exc})")

    # ------------------------------------------------------ Online Retail II
    if args.skip_orii:
        print("[2/2] Online Retail II ... skipped by flag")
    else:
        print("[2/2] Online Retail II (reading 1.07M rows) ...", end=" ", flush=True)
        try:
            tables, stats = online_retail_ii.build(RAW)
            for name, df in tables.items():
                collected[name].append(df)
            source_stats["ONLINE_RETAIL_II"] = stats
            print("ok")
        except FileNotFoundError as exc:
            print(f"SKIPPED ({exc})")

    if not any(collected.values()):
        print("\nNo sources produced data. Run: python -m src.ingestion.verify_raw\n")
        return 1

    # ------------------------------------------------------------- union + validate
    print("\n" + "-" * 74)
    print(f"{'table':<24}{'rows':>12}   detail")
    print("-" * 74)

    final: dict[str, pd.DataFrame] = {}
    problems: list[str] = []

    for name in UNION_TABLES:
        frames = [f for f in collected[name] if len(f) > 0]
        if not frames:
            final[name] = schema.conform(pd.DataFrame(), name)
            print(f"{name:<24}{0:>12,}   (empty)")
            continue

        df = pd.concat(frames, ignore_index=True)
        df = schema.conform(df, name)

        for src in df["source_system"].dropna().unique():
            problems.extend(schema.validate(df[df["source_system"] == src], name, str(src)))

        final[name] = df
        print(f"{name:<24}{_summarise(name, df)}")

    print("-" * 74)

    # ------------------------------------------------------------ key checks
    print("\nReconciliation-relevant facts:")
    txn = final["fact_transaction"]
    ref = final["fact_refund"]

    if len(txn):
        dup = txn.groupby(["source_system", "idempotency_key"]).size()
        multi = (dup > 1).sum()
        print(f"  payment intents with >1 attempt : {multi:,} of {len(dup):,}")
        print(f"  total attempts                  : {len(txn):,}")

    if len(ref):
        print("  refund types                    : "
              + ", ".join(f"{k}={v:,}" for k, v in ref["refund_type"].value_counts().items()))

    # -------------------------------------------------------------- persist
    written = schema.write_tables(final, STAGING, fmt="parquet")
    if args.csv:
        schema.write_tables(final, STAGING, fmt="csv")

    print(f"\nWritten to {STAGING}:")
    for name, path in written.items():
        size = Path(path).stat().st_size / 1024 / 1024
        print(f"  {name:<24} {size:>7.2f} MB")

    if problems:
        print("\nCONTRACT VIOLATIONS:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nAll tables conform to the canonical contract.")

    print(f"\nCompleted in {time.time() - t0:.1f}s\n")
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
