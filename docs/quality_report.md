# Data Quality Report

Generated: 2026-11-19T23:30:57Z  
Stage: canonical staging (`data/staging/`)  
Experiment: 2 — Data Quality Assessment

> This report measures quality. It does not repair anything.
> Repair happens in the ETL stage (Experiment 4), so the audit trail
> keeps the original defect and the corrective action separate.

## Summary

| Severity | Findings |
|---|---|
| HIGH | 4 |
| MEDIUM | 2 |
| INFO | 17 |
| OK | 12 |

## Table profile

| Table | Rows | Columns |
|---|---|---|
| `dim_customer` | 118,876 | 7 |
| `dim_merchant` | 3,097 | 7 |
| `dim_device` | 9,705 | 10 |
| `fact_transaction` | 736,370 | 16 |
| `fact_refund` | 22,980 | 12 |
| `fact_payment_status` | 1,025,340 | 8 |

## High severity

| Table | Column | Metric | Value | Detail |
|---|---|---|---|---|
| `fact_refund` | `customer_id` | orphan_references | 128 | 128 of 22,980 supplied references have no parent row |
| `fact_transaction` | `amount` | non_positive_amounts | 1875 | zero or negative transaction amounts |
| `fact_refund` | `amount` | refunds_exceeding_transaction | 153 | transactions whose summed refunds exceed the amount collected |
| `fact_payment_status` | `status` | backward_transitions | 1382 | lifecycle moved to an EARLIER state - timestamps contradict the process |

## Medium severity

| Table | Column | Metric | Value | Detail |
|---|---|---|---|---|
| `fact_payment_status` | `txn_id` | orphan_references | 320 | 320 of 1,025,340 supplied references have no parent row |
| `fact_payment_status` | `status` | skipped_transitions | 2520 | an intermediate state has no event (missing timestamp), so the jump looks illegal |

## Referential integrity detail

| Child | Column | Parent | Orphans | Checked |
|---|---|---|---|---|
| `fact_transaction` | `customer_id` | `dim_customer.customer_id` | 0 | 736,370 |
| `fact_transaction` | `merchant_id` | `dim_merchant.merchant_id` | 0 | 735,540 |
| `fact_refund` | `txn_id` | `fact_transaction.txn_id` | 0 | 20,093 |
| `fact_refund` | `customer_id` | `dim_customer.customer_id` | 128 | 22,980 |
| `fact_refund` | `merchant_id` | `dim_merchant.merchant_id` | 0 | 22,957 |
| `fact_payment_status` | `txn_id` | `fact_transaction.txn_id` | 320 | 1,025,340 |
