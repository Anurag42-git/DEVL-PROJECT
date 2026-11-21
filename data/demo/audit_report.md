# Audit Report

Generated: 2026-11-20 03:09 UTC

## 1. Scope

Transaction Anomaly and Refund Investigation (Experiment 11). Sources: Olist Brazilian E-Commerce, UCI Online Retail II, IEEE-CIS Fraud Detection. Pipeline: ingestion → quality assessment → canonical model → reconciliation → explainable rules → review queue.

> No record is labelled as fraud. All flags are review candidates with outcome `PENDING` and the evidence that triggered them.

## 2. Data quality (Experiment 2)

- Severity counts: {'HIGH': 4, 'MEDIUM': 2, 'INFO': 17, 'OK': 12}
- High-severity findings are listed in `docs/quality_report.md`.

## 3. Reconciliation (Experiments 4 and 7)

| Metric | Value |
|---|---|
| leg_rows_in | 736370 |
| exact_duplicate_rows_dropped | 0 |
| payment_intents_out | 731924 |
| multi_leg_intents | 2961 |
| intents_with_nonpositive_leg | 1874 |
| refund_rows_in | 21828 |
| unmatched_refund_rows | 2361 |
| intents_with_refund | 8612 |
| over_refunded_intents | 57 |
| fully_refunded_intents | 707 |
| partially_refunded_intents | 6766 |
| refunded_amount_raw_total | 795668.59 |
| refunded_amount_capped_total | 620696.18 |
| intents_with_backward_transition | 1369 |
| intents_with_skipped_transition | 1383 |
| olist_amount_mismatches | 303 |

### Refund state distribution

| Metric | Value |
|---|---|
| NONE | 724394 |
| PARTIAL | 6766 |
| FULL | 707 |
| OVER | 57 |

### Amounts

| Metric | Value |
|---|---|
| collected_total_by_source | {'IEEE_CIS': 79738946.52, 'OLIST': 16008872.12, 'ONLINE_RETAIL_II': 20317957.86} |
| refunded_raw_total | 795668.59 |
| refunded_capped_total | 620696.18 |

## 4. Explainable review queue (Experiment 11)

Total flags: **153,780** across **146,965** payment intents.

| Metric | Value |
|---|---|
| R012 | 130074 |
| R009 | 13824 |
| R001 | 2961 |
| R003 | 2361 |
| R007 | 1874 |
| R004 | 1369 |
| R014 | 775 |
| R013 | 484 |
| R002 | 57 |
| R011 | 1 |

### Severity

| Metric | Value |
|---|---|
| LOW | 130074 |
| MEDIUM | 14600 |
| HIGH | 6145 |
| INFO | 2961 |

### Label-based evaluation

| Metric | Value |
|---|---|
| note | Flags are rule-based review candidates, not fraud predictions. is_fraud is joined only AFTER flagging (no leakage). |
| labelled_intents | 139078 |
| flagged_intents | 139078 |
| true_positives | 10445 |
| false_positives | 128633 |
| false_negatives | 0 |
| true_negatives | 0 |
| precision | 0.0751 |
| recall | 1.0 |
| f1 | 0.1397 |

## 5. Limitations

- Online Retail II has no explicit refund→transaction reference; the link is reconstructed with an as-of join. The 57 over-refund flags are provisional review candidates.
- Device identity is available for 24.4% of IEEE-CIS transactions only.
- `isFraud` is post-hoc ground truth, used only to score flags after they are produced — never as a rule input.

## 6. Outputs

| File | Contents |
|---|---|
| `data/output/reconciled_ledger.parquet` | one row per payment intent |
| `data/output/review_queue.parquet` | explainable flags, all PENDING |
| `data/output/quality_report.json` | measured data defects |
| `dashboard/app.py` | Streamlit transaction dashboard |
