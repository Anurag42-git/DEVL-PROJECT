"""
Experiment 1 - Data ingestion: raw source verification
=======================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Run this FIRST, before any pipeline step. It answers the examiner's first
question - "show me your dataset" - with a factual, per-file inventory:

    * does the file exist, and how big is it
    * how many rows / columns
    * are the columns the pipeline depends on actually present
    * which files are still missing

Usage
-----
    python -m src.ingestion.verify_raw
    python -m src.ingestion.verify_raw --quick      # skip full row counts
    python -m src.ingestion.verify_raw --json out.json

Exit code is 0 only when every REQUIRED file is present and its required
columns are found. That makes it usable as a CI / pre-flight gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


# ---------------------------------------------------------------------------
# Declarative source registry
# ---------------------------------------------------------------------------
@dataclass
class FileSpec:
    key: str
    path: str                      # relative to data/raw
    required_columns: list[str]
    description: str
    required: bool = True
    sheet: str | int | None = None  # for xlsx
    alias: list[str] = field(default_factory=list)  # alternative filenames


SOURCES: list[tuple[str, str, list[FileSpec]]] = [
    (
        "olist",
        "Brazilian E-Commerce Public Dataset (Olist)",
        [
            FileSpec(
                "customers", "olist/olist_customers_dataset.csv",
                ["customer_id", "customer_unique_id", "customer_state"],
                "99k customers with geography",
            ),
            FileSpec(
                "merchants", "olist/olist_sellers_dataset.csv",
                ["seller_id", "seller_state"],
                "3,095 real merchants (sellers)",
            ),
            FileSpec(
                "transactions", "olist/olist_orders_dataset.csv",
                ["order_id", "customer_id", "order_status",
                 "order_purchase_timestamp", "order_approved_at"],
                "order lifecycle: status + 5 timestamps",
            ),
            FileSpec(
                "payment_attempts", "olist/olist_order_payments_dataset.csv",
                ["order_id", "payment_sequential", "payment_type", "payment_value"],
                "multiple payment attempts per order (retry / partial payment trap)",
            ),
            FileSpec(
                "order_items", "olist/olist_order_items_dataset.csv",
                ["order_id", "order_item_id", "seller_id", "price", "freight_value"],
                "line items -> partial refund granularity",
            ),
            FileSpec(
                "reviews", "olist/olist_order_reviews_dataset.csv",
                ["review_id", "order_id", "review_score"],
                "customer satisfaction signal",
                required=False,
            ),
            FileSpec(
                "geolocation", "olist/olist_geolocation_dataset.csv",
                ["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng"],
                "lat/lng -> derived device/access profile",
                required=False,
            ),
            FileSpec(
                "products", "olist/olist_products_dataset.csv",
                ["product_id", "product_category_name"],
                "product dimension",
                required=False,
            ),
            FileSpec(
                "category_translation", "olist/product_category_name_translation.csv",
                ["product_category_name", "product_category_name_english"],
                "PT -> EN category names",
                required=False,
            ),
        ],
    ),
    (
        "online_retail_ii",
        "Online Retail II (UCI) - the authentic refund source",
        [
            FileSpec(
                "online_retail_ii",
                "online_retail_ii/online_retail_II.xlsx",
                ["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Customer ID"],
                "1.07M invoice lines incl. 'C' cancellations and negative quantities",
                sheet=None,
                alias=["online_retail_ii/online_retail_II.csv"],
            ),
        ],
    ),
    (
        "ieee_cis",
        "IEEE-CIS Fraud Detection - device fingerprints + fraud labels",
        [
            FileSpec(
                "ieee_transactions", "ieee_cis/train_transaction.csv",
                ["TransactionID", "TransactionDT", "TransactionAmt", "card1", "isFraud"],
                "590k card transactions with isFraud ground truth",
            ),
            FileSpec(
                "ieee_identity", "ieee_cis/train_identity.csv",
                ["TransactionID", "DeviceType", "DeviceInfo"],
                "144k device / network fingerprints",
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def count_csv_rows(path: Path, chunk: int = 250_000) -> int:
    """Count rows without loading the whole file into memory."""
    total = 0
    for block in pd.read_csv(path, usecols=[0], chunksize=chunk, low_memory=False):
        total += len(block)
    return total


def count_xlsx_rows(path: Path) -> tuple[int, list[str]]:
    """
    Count data rows across every sheet using openpyxl's read-only mode.

    Reading a 1M-row workbook through pandas would materialise the whole frame
    in memory; read-only iteration keeps it flat.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        total = 0
        for name in wb.sheetnames:
            ws = wb[name]
            total += sum(1 for _ in ws.iter_rows(min_row=2, values_only=True))
        return total, list(wb.sheetnames)
    finally:
        wb.close()


def resolve(spec: FileSpec) -> Path | None:
    primary = RAW / spec.path
    if primary.exists():
        return primary
    for alt in spec.alias:
        candidate = RAW / alt
        if candidate.exists():
            return candidate
    return None


def inspect(spec: FileSpec, quick: bool) -> dict:
    path = resolve(spec)
    result = {
        "key": spec.key,
        "path": spec.path,
        "description": spec.description,
        "required": spec.required,
        "exists": path is not None,
        "rows": None,
        "columns": None,
        "missing_columns": [],
        "size": None,
    }
    if path is None:
        result["missing_columns"] = spec.required_columns
        return result

    result["size"] = human_size(path.stat().st_size)
    result["actual_path"] = str(path.relative_to(ROOT))

    try:
        if path.suffix.lower() in (".xlsx", ".xls"):
            if quick:
                frame = pd.read_excel(path, nrows=50)
                result["rows"] = "skipped (--quick)"
                result["sheets"] = list(pd.ExcelFile(path).sheet_names)
            else:
                total, sheets = count_xlsx_rows(path)
                result["rows"] = total
                result["sheets"] = sheets
                frame = pd.read_excel(path, nrows=0)
            result["columns"] = len(frame.columns)
            result["column_names"] = list(frame.columns)
        else:
            if quick:
                frame = pd.read_csv(path, nrows=50, low_memory=False)
                result["rows"] = "skipped (--quick)"
            else:
                frame = pd.read_csv(path, nrows=50, low_memory=False)
                result["rows"] = count_csv_rows(path)
            result["columns"] = len(frame.columns)
            result["column_names"] = list(frame.columns)

        present = {str(c).strip() for c in result.get("column_names", [])}
        result["missing_columns"] = [
            c for c in spec.required_columns if c not in present
        ]
    except Exception as exc:  # noqa: BLE001 - report, do not crash the audit
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(report: list[dict]) -> None:
    width = 92
    print("\n" + "=" * width)
    print("RAW DATA VERIFICATION - Experiment 11".center(width))
    print("=" * width)

    for dataset, description, rows in report:
        print(f"\n[{dataset}]  {description}")
        print("-" * width)
        header = f"{'file':<22}{'rows':>12}{'cols':>7}{'size':>11}   status"
        print(header)
        print("-" * width)

        for r in rows:
            if not r["exists"]:
                status = "MISSING" if r["required"] else "missing (optional)"
            elif r.get("error"):
                status = "ERROR"
            elif r["missing_columns"]:
                status = "COLUMNS MISSING"
            else:
                status = "ok"

            rows_txt = f"{r['rows']:,}" if isinstance(r["rows"], int) else (r["rows"] or "-")
            cols_txt = str(r["columns"]) if r["columns"] is not None else "-"
            size_txt = r["size"] or "-"

            print(f"{r['key']:<22}{rows_txt:>12}{cols_txt:>7}{size_txt:>11}   {status}")

            if r["missing_columns"]:
                print(f"    -> missing columns: {', '.join(r['missing_columns'])}")
            if r.get("error"):
                print(f"    -> {r['error']}")

    print("\n" + "=" * width)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the raw source files.")
    parser.add_argument("--quick", action="store_true", help="skip full row counts")
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    args = parser.parse_args()

    report: list[tuple[str, str, list[dict]]] = []
    blockers: list[str] = []

    for dataset, description, specs in SOURCES:
        results = [inspect(spec, args.quick) for spec in specs]
        report.append((dataset, description, results))
        for r in results:
            if r["required"] and not r["exists"]:
                blockers.append(f"{r['path']} (missing)")
            elif r["required"] and r.get("error"):
                blockers.append(f"{r['path']} (unreadable)")
            elif r["required"] and r["missing_columns"]:
                blockers.append(
                    f"{r['path']} (missing columns: {', '.join(r['missing_columns'])})"
                )

    print_report(report)

    if args.json:
        payload = [
            {"dataset": d, "description": desc, "files": rows}
            for d, desc, rows in report
        ]
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"JSON report written to {args.json}")

    if blockers:
        print("\nBLOCKERS - fix these before running the pipeline:")
        for b in blockers:
            print(f"  - {b}")
        print("\nSee data/raw/README.md for download instructions.\n")
        return 1

    print("\nAll required files present and structurally valid. Ready for ingestion.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
