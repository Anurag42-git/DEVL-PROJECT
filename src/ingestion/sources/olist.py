"""
Experiment 1 - Ingestion adapter: Olist -> canonical model
===========================================================
Experiment 11 - Transaction Anomaly and Refund Investigation

Source: Brazilian E-Commerce Public Dataset by Olist (Kaggle)
        99,441 orders, 3,095 sellers, 2016-2018, currency BRL.

What this adapter contributes
-----------------------------
* `dim_customer`   - 99k real customers with geography
* `dim_merchant`   - 3,095 real merchants (sellers), category enriched from products
* `fact_transaction` - one row per PAYMENT ATTEMPT (payment_sequential), so orders
                       paid with 2+ instruments become multiple attempts sharing
                       one idempotency_key. This is the retry / partial-payment trap.
* `fact_refund`    - orders cancelled AFTER approval = money taken then returned
* `fact_payment_status` - a REAL lifecycle rebuilt from Olist's five independent
                       timestamps (purchase -> approved -> carrier -> delivered)

Deliberate gaps (measured later by Experiment 2, never silently invented)
-------------------------------------------------------------------------
* No device information  -> device_id is empty
* No card number         -> card_last4 is empty
* No cancellation timestamp -> refund processed_ts is empty
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import conform

SOURCE = "OLIST"
CURRENCY = "BRL"
COUNTRY = "BR"

# Olist order_status -> canonical status.
# 'canceled' is resolved separately because it is ambiguous: cancelled after
# payment (refund) vs cancelled before payment ever succeeded (failed attempt).
BASE_STATUS = {
    "delivered": "SETTLED",
    "shipped": "CAPTURED",
    "invoiced": "CAPTURED",
    "processing": "AUTHORIZED",
    "approved": "AUTHORIZED",
    "created": "INITIATED",
    "unavailable": "FAILED",
}

# Five real timestamps -> lifecycle states.
LIFECYCLE = [
    ("order_purchase_timestamp", "INITIATED"),
    ("order_approved_at", "AUTHORIZED"),
    ("order_delivered_carrier_date", "CAPTURED"),
    ("order_delivered_customer_date", "SETTLED"),
]

TS_COLS = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]


def _read(raw: Path) -> dict[str, pd.DataFrame]:
    base = raw / "olist"
    return {
        "customers": pd.read_csv(base / "olist_customers_dataset.csv"),
        "sellers": pd.read_csv(base / "olist_sellers_dataset.csv"),
        "orders": pd.read_csv(base / "olist_orders_dataset.csv"),
        "payments": pd.read_csv(base / "olist_order_payments_dataset.csv"),
        "items": pd.read_csv(base / "olist_order_items_dataset.csv"),
        "products": pd.read_csv(base / "olist_products_dataset.csv"),
    }


def build(raw: Path) -> dict[str, pd.DataFrame]:
    src = _read(raw)

    orders = src["orders"].copy()
    for col in TS_COLS:
        orders[col] = pd.to_datetime(orders[col], errors="coerce")

    # ---------------------------------------------------------------- status
    orders["status"] = orders["order_status"].map(BASE_STATUS)
    canceled = orders["order_status"] == "canceled"
    paid_then_canceled = canceled & orders["order_approved_at"].notna()
    orders.loc[canceled, "status"] = "FAILED"
    orders.loc[paid_then_canceled, "status"] = "REFUNDED"

    # last known lifecycle moment, used as updated_ts
    orders["updated_ts"] = orders[[c for c, _ in LIFECYCLE]].max(axis=1)

    # ---------------------------------------------------------- merchant map
    items = src["items"]
    products = src["products"]
    items_cat = items.merge(
        products[["product_id", "product_category_name"]], on="product_id", how="left"
    )
    order_seller = items.groupby("order_id", as_index=False)["seller_id"].first()
    seller_category = (
        items_cat.groupby("seller_id")["product_category_name"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else pd.NA)
        .rename("category")
        .reset_index()
    )

    # ---------------------------------------------------------- dim_customer
    cust = src["customers"]
    dim_customer = conform(
        pd.DataFrame({
            "customer_id": cust["customer_id"],
            "customer_unique_id": cust["customer_unique_id"],
            "city": cust["customer_city"],
            "state": cust["customer_state"],
            "zip_prefix": cust["customer_zip_code_prefix"].astype(str),
            "country": COUNTRY,
            "source_system": SOURCE,
        }),
        "dim_customer",
    )

    # ---------------------------------------------------------- dim_merchant
    sel = src["sellers"].merge(seller_category, on="seller_id", how="left")
    dim_merchant = conform(
        pd.DataFrame({
            "merchant_id": sel["seller_id"],
            "merchant_name": "Seller " + sel["seller_id"].str[:8],
            "category": sel["category"].fillna("UNKNOWN"),
            "city": sel["seller_city"],
            "state": sel["seller_state"],
            "country": COUNTRY,
            "source_system": SOURCE,
        }),
        "dim_merchant",
    )

    # ------------------------------------------------------- dim_device (none)
    dim_device = conform(pd.DataFrame(columns=["device_id"]), "dim_device")

    # ------------------------------------------------------ fact_transaction
    pay = src["payments"].copy()
    pay["payment_sequential"] = pay["payment_sequential"].astype(int)

    txn = pay.merge(
        orders[["order_id", "customer_id", "order_status", "status",
                "order_purchase_timestamp", "updated_ts"]],
        on="order_id", how="left",
    ).merge(order_seller, on="order_id", how="left")

    attempt_no = txn["payment_sequential"]
    fact_transaction = conform(
        pd.DataFrame({
            # a retry gets its own txn_id but keeps the order's idempotency key
            "txn_id": txn["order_id"] + "-" + attempt_no.astype(str),
            "idempotency_key": txn["order_id"],
            "attempt_no": attempt_no,
            "retry_of_txn_id": (txn["order_id"] + "-1").where(attempt_no > 1, ""),
            "customer_id": txn["customer_id"],
            "merchant_id": txn["seller_id"],
            "device_id": "",
            "amount": pd.to_numeric(txn["payment_value"], errors="coerce"),
            "currency": CURRENCY,
            "status": txn["status"],
            "channel": txn["payment_type"],
            "card_last4": "",
            "created_ts": txn["order_purchase_timestamp"],
            "updated_ts": txn["updated_ts"],
            "is_retry": attempt_no > 1,
            "source_system": SOURCE,
        }),
        "fact_transaction",
    )

    # ----------------------------------------------------------- fact_refund
    refund_orders = orders.loc[paid_then_canceled, ["order_id", "customer_id", "order_approved_at"]]
    refund_amount = pay.groupby("order_id", as_index=False)["payment_value"].sum()
    ref = refund_orders.merge(refund_amount, on="order_id", how="left").merge(
        order_seller, on="order_id", how="left"
    )

    fact_refund = conform(
        pd.DataFrame({
            "refund_id": "RFD_" + ref["order_id"],
            "txn_id": ref["order_id"] + "-1",
            "customer_id": ref["customer_id"],
            "merchant_id": ref["seller_id"],
            "amount": pd.to_numeric(ref["payment_value"], errors="coerce"),
            "currency": CURRENCY,
            "status": "PROCESSED",
            "refund_type": "FULL",
            "reason": "ORDER_CANCELED_AFTER_PAYMENT",
            # Olist has no cancellation timestamp; approval time is the lower
            # bound and processed_ts is genuinely unknown.
            "requested_ts": ref["order_approved_at"],
            "processed_ts": pd.NaT,
            "source_system": SOURCE,
        }),
        "fact_refund",
    )

    # --------------------------------------------------- fact_payment_status
    events = []
    for ts_col, state in LIFECYCLE:
        part = orders.loc[orders[ts_col].notna(), ["order_id", ts_col]]
        events.append(pd.DataFrame({
            "event_id": "EVT_" + part["order_id"] + "_" + state,
            "txn_id": part["order_id"] + "-1",
            "status": state,
            "event_ts": part[ts_col].values,
            "source": "OLIST_TIMESTAMP",
            "latency_ms": pd.NA,
            "error_code": "",
            "source_system": SOURCE,
        }))
    fact_payment_status = conform(pd.concat(events, ignore_index=True), "fact_payment_status")

    return {
        "dim_customer": dim_customer,
        "dim_merchant": dim_merchant,
        "dim_device": dim_device,
        "fact_transaction": fact_transaction,
        "fact_refund": fact_refund,
        "fact_payment_status": fact_payment_status,
    }
