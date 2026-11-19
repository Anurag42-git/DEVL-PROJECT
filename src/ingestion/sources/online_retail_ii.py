"""
Experiment 1 - Ingestion adapter: Online Retail II -> canonical model
=====================================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Source: Online Retail II (UCI, Chen 2012)
        1,067,371 invoice lines, UK wholesaler, 2009-12 to 2011-12, GBP.

What this adapter contributes
-----------------------------
This is the project's REFUND ENGINE. It is the only public dataset in our set
that contains authentic returns, which is what makes "partial refunds" real
rather than simulated:

* `Invoice` starting with 'C'  -> cancellation invoice
* negative `Quantity`          -> returned units
* a return of 2 units where 5 were bought -> a GENUINE PARTIAL REFUND
* several return lines on one invoice      -> MULTIPLE partial refunds

How refunds are linked to transactions
--------------------------------------
The source has no explicit "refund of invoice X" column. It is recovered with
an AS-OF JOIN: for each returned line, find the most recent earlier sale of the
same (customer, stock code). That prior invoice becomes the refund's `txn_id`.
This is a real reconciliation join, not an assumption, and it is the same
technique used in the SQL pipeline (Experiment 7).

Partial vs full classification
------------------------------
    returned_qty  <  sold_qty  -> PARTIAL
    returned_qty ==  sold_qty  -> FULL
    no matching sale           -> UNKNOWN   (reported, never guessed)

Deliberate gaps
---------------
* Single merchant -> merchant dimension has one row
* One timestamp per line -> no status-transition stream (Olist covers that)
* No device, no card -> device_id / card_last4 empty
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import conform

SOURCE = "ONLINE_RETAIL_II"
CURRENCY = "GBP"
COUNTRY = "United Kingdom"
MERCHANT_ID = "ORII_MAIN"

SHEET_DTYPES = {
    "Invoice": "string",
    "StockCode": "string",
    "Quantity": "int64",
    "Price": "float64",
}


def _load(raw: Path) -> tuple[pd.DataFrame, dict]:
    """
    Read both year sheets and concatenate, reporting source-level facts.

    Parsing a 1.07M-row .xlsx takes ~5 minutes, so the cleaned frame is cached
    as Parquet. Every later stage (quality, reconcile, rules, indicators) then
    runs against typed columnar data instead of re-reading Excel.
    """
    path = raw / "online_retail_ii" / "online_retail_II.xlsx"
    if not path.exists():
        path = raw / "online_retail_ii" / "online_retail_II.csv"

    cache = raw.parent / "staging" / "_cache" / "online_retail_ii.parquet"
    stats: dict = {}

    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        df = pd.read_parquet(cache)
        stats["cache"] = "hit"
    else:
        stats["cache"] = "miss"
        if path.suffix.lower() == ".xlsx":
            xls = pd.ExcelFile(path)
            frames = [xls.parse(s, dtype=SHEET_DTYPES) for s in xls.sheet_names]
            stats["sheets"] = list(xls.sheet_names)
        else:
            frames = [pd.read_csv(path, dtype=SHEET_DTYPES)]
            stats["sheets"] = ["csv"]

        df = pd.concat(frames, ignore_index=True)
        stats["raw_rows"] = len(df)

        before = len(df)
        df = df.drop_duplicates()
        stats["duplicate_rows_dropped"] = before - len(df)

        df["Invoice"] = df["Invoice"].astype("string").str.strip()
        df["StockCode"] = df["StockCode"].astype("string").str.strip()
        if "Description" in df.columns:
            # mixed str/int in the source -> normalise so Parquet can store it
            df["Description"] = df["Description"].astype("string")
        df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
        df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")

        # Customer ID arrives as float; normalise to a stable string key.
        cid = pd.to_numeric(df["Customer ID"], errors="coerce").astype("Int64")
        df["customer_id"] = "ORII" + cid.astype("string").str.zfill(5)
        df.loc[cid.isna(), "customer_id"] = "ORII_UNKNOWN"

        df["line_amount"] = df["Quantity"] * df["Price"]
        df["is_cancellation"] = df["Invoice"].str.upper().str.startswith("C")
        df["Country"] = df["Country"].astype("string").fillna("UNKNOWN")

        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)

    cid_numeric = pd.to_numeric(df["Customer ID"], errors="coerce")
    stats["rows"] = len(df)
    stats["rows_missing_customer_id"] = int(cid_numeric.isna().sum())

    return df, stats


def build(raw: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    df, stats = _load(raw)

    sales = df[df["Quantity"] > 0].copy()
    returns = df[df["Quantity"] < 0].copy()
    stats["sale_lines"] = len(sales)
    stats["return_lines"] = len(returns)
    stats["cancellation_lines"] = int(df["is_cancellation"].sum())

    # ---------------------------------------------------------- dim_customer
    cust = (
        sales.groupby("customer_id", as_index=False)
        .agg(country=("Country", "first"))
    )
    dim_customer = conform(
        pd.DataFrame({
            "customer_id": cust["customer_id"],
            "customer_unique_id": cust["customer_id"],
            "city": pd.NA,
            "state": pd.NA,
            "zip_prefix": pd.NA,
            "country": cust["country"],
            "source_system": SOURCE,
        }),
        "dim_customer",
    )

    # ---------------------------------------------------------- dim_merchant
    dim_merchant = conform(
        pd.DataFrame([{
            "merchant_id": MERCHANT_ID,
            "merchant_name": "Online Retail II (UK wholesaler)",
            "category": "GIFTWARE",
            "city": pd.NA,
            "state": pd.NA,
            "country": COUNTRY,
            "source_system": SOURCE,
        }]),
        "dim_merchant",
    )

    dim_device = conform(pd.DataFrame(columns=["device_id"]), "dim_device")

    # ------------------------------------------------------ fact_transaction
    # One transaction per SALE invoice (cancellation invoices become refunds).
    txn = (
        sales.groupby("Invoice", as_index=False)
        .agg(
            customer_id=("customer_id", "first"),
            amount=("line_amount", "sum"),
            created_ts=("InvoiceDate", "min"),
            updated_ts=("InvoiceDate", "max"),
            n_lines=("StockCode", "size"),
        )
    )
    fact_transaction = conform(
        pd.DataFrame({
            "txn_id": txn["Invoice"],
            "idempotency_key": txn["Invoice"],
            "attempt_no": 1,
            "retry_of_txn_id": "",
            "customer_id": txn["customer_id"],
            "merchant_id": MERCHANT_ID,
            "device_id": "",
            "amount": txn["amount"].round(2),
            "currency": CURRENCY,
            "status": "SETTLED",
            "channel": "INVOICE",
            "card_last4": "",
            "created_ts": txn["created_ts"],
            "updated_ts": txn["updated_ts"],
            "is_retry": False,
            "source_system": SOURCE,
        }),
        "fact_transaction",
    )
    stats["transactions"] = len(fact_transaction)

    # ----------------------------------------------------------- fact_refund
    # AS-OF JOIN: most recent earlier sale of the same (customer, stock code).
    sale_lines = (
        sales[["customer_id", "StockCode", "InvoiceDate", "Invoice", "Quantity"]]
        .rename(columns={
            "InvoiceDate": "sale_ts",
            "Invoice": "sale_invoice",
            "Quantity": "sale_qty",
        })
        .sort_values("sale_ts")
    )

    matched = pd.merge_asof(
        returns.sort_values("InvoiceDate"),
        sale_lines,
        left_on="InvoiceDate",
        right_on="sale_ts",
        by=["customer_id", "StockCode"],
        direction="backward",
        allow_exact_matches=False,
    )

    returned = matched["Quantity"].abs()
    refund_type = pd.Series("UNKNOWN", index=matched.index, dtype="object")
    has_match = matched["sale_qty"].notna()
    refund_type[has_match & (returned < matched["sale_qty"])] = "PARTIAL"
    refund_type[has_match & (returned >= matched["sale_qty"])] = "FULL"

    stats["refund_type_counts"] = refund_type.value_counts().to_dict()

    fact_refund = conform(
        pd.DataFrame({
            "refund_id": "ORII_" + matched["Invoice"].astype("string") + "_" + matched["StockCode"].astype("string"),
            # the invoice the money originally came from; falls back to the
            # cancellation invoice itself when no sale could be matched
            "txn_id": matched["sale_invoice"].fillna(matched["Invoice"]),
            "customer_id": matched["customer_id"],
            "merchant_id": MERCHANT_ID,
            "amount": (returned * matched["Price"].abs()).round(2),
            "currency": CURRENCY,
            "status": "PROCESSED",
            "refund_type": refund_type,
            "reason": matched["is_cancellation"].map({True: "CANCELLATION", False: "RETURN"}),
            "requested_ts": matched["InvoiceDate"],
            "processed_ts": pd.NaT,
            "source_system": SOURCE,
        }),
        "fact_refund",
    )
    stats["refunds"] = len(fact_refund)
    stats["refunds_unmatched"] = int((refund_type == "UNKNOWN").sum())

    # --------------------------------------------------- fact_payment_status
    # The source carries a single timestamp per line, so only the initiation
    # event is real. We do not invent settlement times.
    fact_payment_status = conform(
        pd.DataFrame({
            "event_id": "EVT_" + txn["Invoice"].astype("string") + "_INITIATED",
            "txn_id": txn["Invoice"],
            "status": "INITIATED",
            "event_ts": txn["created_ts"],
            "source": "INVOICE_TIMESTAMP",
            "latency_ms": pd.NA,
            "error_code": "",
            "source_system": SOURCE,
        }),
        "fact_payment_status",
    )

    return {
        "dim_customer": dim_customer,
        "dim_merchant": dim_merchant,
        "dim_device": dim_device,
        "fact_transaction": fact_transaction,
        "fact_refund": fact_refund,
        "fact_payment_status": fact_payment_status,
    }, stats
