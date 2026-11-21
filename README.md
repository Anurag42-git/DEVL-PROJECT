# Transaction Anomaly & Refund Investigation

**DEVL · Semester 5 · Final Project**

---

## 1. The problem statement

An online payment service has transaction, customer, merchant, refund,
payment-status and device-summary files. **Duplicate events, retries and partial
refunds** make it hard to distinguish routine activity from records that need
investigation.

Build a monitoring application that:

1. Reconciles transaction/refund events **without double-counting** retries or partial refunds
2. Validates **amounts, timestamps, status transitions and transaction references**
3. Calculates **transaction frequency per time window, refund ratio and repeated failed attempts**
4. Shows **why** each record was flagged, keeps a review outcome, and **never labels an alert as confirmed fraud**

> **Important:** the "monitoring application" required here **is the dashboard**.
> No separate CRUD app is needed.

---

## 2. Expected outcomes — where to find each one

| # | Expected outcome | Delivered as | How to view |
|---|---|---|---|
| 1 | **Transaction dashboard** | `dashboard/app.py` | `streamlit run dashboard/app.py` |
| 2 | **Reconciled payment ledger** | `data/output/reconciled_ledger.parquet` / `.csv` | Dashboard → *Reconciled ledger* |
| 3 | **Explainable review queue** | `data/output/review_queue.parquet` / `.csv` | Dashboard → *Review queue* |
| 4 | **Audit report** | `docs/audit_report.md` | Dashboard → *Audit report* |

The dashboard has six sections: **Overview**, **Reconciled ledger**, **Review queue**,
**Data quality**, **Audit report** and **About** (which restates the problem and
maps it to the outcomes). Sections have shareable links, e.g.
`?page=Review+queue`.

---

## 3. Datasets (real, public, verifiable)

| Dataset | Source | Size | Role |
|---|---|---|---|
| Olist Brazilian E-Commerce | [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | 99,441 orders · 3,095 sellers | customers, merchants, real status lifecycle |
| Online Retail II | [UCI](https://archive.ics.uci.edu/dataset/502/online+retail+ii) | 1,067,371 invoice lines | authentic partial returns and cancellations |
| IEEE-CIS Fraud Detection | [Kaggle](https://www.kaggle.com/c/ieee-fraud-detection) | 590,540 transactions | device fingerprints, ground-truth labels |

No single public file has all six source types, so the system is framed as a
**payment service provider** ingesting multiple merchant settlement feeds plus a
card-network authorisation feed — the real shape of a PSP's data landscape.

Attribution: Olist (CC BY-NC-SA 4.0) · Online Retail II, Chen 2012 (CC BY 4.0) ·
IEEE-CIS / Vesta Corporation (Kaggle competition data).

---

## 4. Pipeline

```
raw CSV/XLSX (3 sources)
      │
      ▼
src/ingestion/           → canonical 6-table model in data/staging/
src/quality/assess.py    → Experiment 2: measured defects
src/reconcile/ledger.py  → one row per payment intent, refunds capped
src/rules/engine.py      → 15 explainable rules → review queue
src/audit_report.py      → audit report
      │
      ▼
dashboard/app.py         → the four outcomes, presented
```

Canonical model: `dim_customer`, `dim_merchant`, `dim_device`,
`fact_transaction`, `fact_refund`, `fact_payment_status`.

### The two reconciliation traps

- **Payment legs are additive.** 2,961 Olist orders were paid with 2+ instruments
  (up to 29 legs). Verified: 99.4% sum exactly to the order total. They must be
  **summed**, not deduplicated.
- **Refunds are additive and must be capped.** Total refunded is the sum of
  individual refunds, capped at the amount collected. Raw **795,669 → capped
  620,696**, removing **174,972** of over-refunding.

---

## 5. Results

| Metric | Value |
|---|---|
| Payment intents reconciled | 731,924 |
| Multi-leg intents | 2,961 |
| Intents with refunds | 8,612 |
| Refund states | PARTIAL 6,766 · FULL 707 · OVER 57 · NONE 724,394 |
| Backward status transitions | 1,369 intents |
| Skipped status transitions | 1,383 intents |
| Olist amount mismatches | 303 |
| Review flags | 153,780 across 146,966 intents, all `PENDING` |
| Data quality | 4 HIGH · 2 MEDIUM · 17 INFO · 12 OK |

Every flag records `rule_id`, `severity`, `evidence` (the actual numbers), a
human-readable `reason`, and `outcome = PENDING`. No record is ever called fraud.

---

## 6. Run it

```powershell
python -m pip install -r requirements.txt

python -m src.ingestion.verify_raw          # inventory of the raw datasets
python -m src.ingestion.build_canonical     # ingest + unify
python -m src.quality.assess                # Experiment 2 report
python -m src.reconcile.ledger              # outcome 2
python -m src.rules.engine                  # outcome 3
python -m src.audit_report                  # outcome 4
streamlit run dashboard/app.py              # outcome 1
```

For the hosted dashboard, only `dashboard/requirements.txt` is needed.
`src/make_demo.py` produces a small **representative sample of real rows** in
`data/demo/` for Streamlit Cloud, because the full outputs are git-ignored.

---

## 7. Documented limitations

| Limitation | Handling |
|---|---|
| Online Retail II has no explicit refund→transaction link | reconstructed with an as-of join; 57 `OVER` flags are provisional review candidates |
| Device identity on only 24.4% of card transactions | `device_id` is empty elsewhere, never invented |
| `isFraud` is post-hoc truth | isolated in `eval_labels`, joined only **after** flags are produced |
| Olist has no cancellation timestamp | `refund.processed_ts` left null and reported in the quality report |
| Non-product stock codes (`AMAZONFEE`, `POST`, …) | excluded from refund matching after they created fake 127k over-refunds |
