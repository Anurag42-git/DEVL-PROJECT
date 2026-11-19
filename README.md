# Transaction Anomaly and Refund Investigation

**DEVL — Semester 5 · Experiment 11 (capstone)**
A payment-monitoring application that reconciles transaction and refund events,
validates them, scores them with explainable rules, and routes unusual patterns
to a human review queue.

> **No record in this system is ever labelled "fraud".** The output is always
> *flagged for review*, with the evidence that triggered it and an outcome of
> `PENDING`, `CLEARED` or `ESCALATED`.

---

## Problem statement

An online payment service has transaction, customer, merchant, refund,
payment-status and device-summary files. Duplicate events, retries and partial
refunds make it difficult to distinguish routine activity from records
requiring investigation.

Build a monitoring application that:

1. Reconciles transaction/refund events **without double-counting retries or
   partial refunds**
2. Validates **amounts, timestamps, status transitions and transaction references**
3. Calculates indicators: **transaction frequency per time window, refund ratio,
   repeated failed attempts**
4. Shows **why each record was flagged** and retains a review outcome, without
   ever confirming fraud

**Expected outputs:** transaction dashboard · reconciled payment ledger ·
explainable review queue · audit report.

---

## Datasets (real, public, verifiable)

No single public dataset contains all six required files, so the system is
modelled as a **payment service provider (PSP)** that ingests heterogeneous
merchant settlement feeds plus a card-network authorisation feed. This is the
real shape of a PSP's data landscape.

| Dataset | Source | Size | Contributes |
|---|---|---|---|
| **Olist Brazilian E-Commerce** | [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | 99,441 orders · 3,095 sellers | customers, merchants, **order status lifecycle** (5 real timestamps), multi-attempt payments |
| **Online Retail II** | [UCI](https://archive.ics.uci.edu/dataset/502/online+retail+ii) | 1,067,371 invoice lines | **authentic refunds** — 22,950 return lines, true partial refunds |
| **IEEE-CIS Fraud Detection** | [Kaggle](https://www.kaggle.com/c/ieee-fraud-detection) | 590,540 transactions | **device fingerprints** + real `isFraud` labels for objective evaluation |

Verified inventory (run `python -m src.ingestion.verify_raw`):

```
olist/customers              99,441     olist/sellers                 3,095
olist/orders                 99,441     olist/payments              103,886
olist/items                 112,650     online_retail_II          1,067,371
```

### Why these three

- **Olist** is the only source with a genuine multi-step status lifecycle
  (`created → approved → invoiced → shipped → delivered / canceled`), which is
  required to validate *status transitions*.
- **Online Retail II** is the only source with *authentic* returns. A return of
  2 units out of 5 is a real partial refund — not a simulated one. This is the
  core of the investigation.
- **IEEE-CIS** provides real device fingerprints and real fraud labels, so
  detection quality can be **measured** rather than asserted.

### Licence / attribution

- Olist — CC BY-NC-SA 4.0
- Online Retail II — Chen, D. (2012), UCI ML Repository, CC BY 4.0
- IEEE-CIS — Kaggle competition data, Vesta Corporation

---

## Canonical model

Three schemas that share no keys or vocabularies are normalised into six tables
(`src/ingestion/schema.py`). Every fact row carries `source_system`, because
cross-source reconciliation is meaningless — different merchants, currencies
and ledgers.

| Table | Purpose |
|---|---|
| `dim_customer` | unified customer dimension |
| `dim_merchant` | unified merchant dimension |
| `dim_device` | device fingerprints + shared-device flags |
| `fact_transaction` | one row per **payment attempt** |
| `fact_refund` | one row per refund event (partial or full) |
| `fact_payment_status` | lifecycle event stream (status transitions) |

### The two traps this project exists to solve

**1. Retries must not be double-counted.**
A retry gets a *new* `txn_id` but keeps the original `idempotency_key`:

```
txn_id              idempotency_key   attempt_no   amount    status
e481f5...-1          e481f5...         1            58.90     AUTHORIZED
e481f5...-2          e481f5...         2            58.90     SETTLED
```

`GROUP BY txn_id` and `SUM(amount)` therefore report **117.80 collected** when
only **58.90** was ever collected. The ledger must reconcile on
`idempotency_key`. Current data: **2,961 payment intents have more than one
attempt**.

**2. Partial refunds are additive and must be capped.**
Refunds are individual rows. Total refunded is their sum, capped at the
transaction amount. Current data: **10,600 PARTIAL + 9,493 FULL** refunds.

---

## Architecture

```
data/raw/ ──► src/ingestion/ ──► data/staging/ ──► src/reconcile/ ──► ledger
 (3 sources)   adapters +          Parquet          retry collapse
               canonical          (6 tables)        refund capping
                 │
                 ├──► src/quality/    Experiment 2 - data quality report
                 ├──► src/rules/      rule engine R001..R015 (explainable)
                 ├──► src/indicators/ velocity, refund ratio, failed streaks
                 ├──► src/db/         PostgreSQL (Exp 5,7) + MongoDB (Exp 8,9)
                 ├──► src/spark/      PySpark aggregation (Exp 10)
                 ├──► src/api/        FastAPI: case CRUD + audit trail (Exp 3,6,9)
                 └──► dashboard/      Streamlit (Exp 3)
```

## Experiment → module map

| Exp | Experiment | Where it lives |
|---|---|---|
| 1 | Data ingestion | `src/ingestion/` — 3 adapters → canonical model |
| 2 | Data quality assessment | `src/quality/` |
| 3 | API integration & visualization | `src/api/` + `dashboard/` |
| 4 | ETL pipeline development | `src/etl/` (idempotent, watermark-driven) |
| 5 | PostgreSQL setup & loading | `sql/schema.sql` + `src/db/postgres.py` |
| 6 | Employee CRUD system | repurposed → **review case CRUD** |
| 7 | SQL data pipeline | `sql/queries/` — window functions, as-of joins |
| 8 | MongoDB PyMongo operations | `src/db/mongo.py` — evidence + raw events |
| 9 | MongoDB application development | case notes, audit trail |
| 10 | DataFrame in PySpark | `src/spark/` |
| 11 | **This capstone** | integrates all of the above |

---

## Quick start

```powershell
# 1. install
python -m pip install -r requirements.txt

# 2. verify the raw files are present
python -m src.ingestion.verify_raw

# 3. build the canonical staging tables
python -m src.ingestion.build_canonical
```

Expected output:

```
dim_customer               105,323
dim_merchant                 3,096
dim_device                         0   (pending IEEE-CIS)
fact_transaction           145,830   {'OLIST': 103,886, 'ONLINE_RETAIL_II': 41,944}
fact_refund                 22,980   {'ONLINE_RETAIL_II': 22,496, 'OLIST': 484}
fact_payment_status        434,800

payment intents with >1 attempt : 2,961 of 141,384
refund types                    : PARTIAL=10,600, FULL=9,493, UNKNOWN=2,887
```

---

## Status

- [x] Project scaffold, config, dependency pinning
- [x] Dataset selection + verification tooling (`verify_raw`)
- [x] Olist adapter → canonical model
- [x] Online Retail II adapter → canonical model (as-of join for refund linkage)
- [x] Canonical build + Parquet caching (346s → 25s on re-run)
- [ ] IEEE-CIS adapter — **blocked: competition rules not accepted yet**
- [ ] Experiment 2 — data quality report
- [ ] Reconciled ledger (retry collapse + refund capping)
- [ ] Rule engine R001–R015 with evidence
- [ ] PostgreSQL schema + load
- [ ] MongoDB evidence store
- [ ] FastAPI case CRUD
- [ ] Streamlit dashboard
- [ ] PySpark indicator job
- [ ] Audit report

### Known data gaps (measured, not hidden)

| Gap | Source | Handling |
|---|---|---|
| No device info | Olist, Online Retail II | `device_id` empty; filled by IEEE-CIS |
| No cancellation timestamp | Olist | `processed_ts` left null, reported in Exp 2 |
| 243,007 rows missing Customer ID | Online Retail II | keyed as `ORII_UNKNOWN`, counted |
| 2,887 refunds with no matching sale | Online Retail II | `refund_type = UNKNOWN`, reported not guessed |
| No lifecycle stream | Online Retail II | only `INITIATED` is real; settlement not invented |
