# Raw data — expected layout

Drop the downloaded files into the folders below, **keeping the exact filenames**.
Nothing here is committed to git (see `.gitignore`).

```
data/raw/
├── olist/                    # Kaggle: Brazilian E-Commerce Public Dataset by Olist
├── online_retail_ii/         # UCI: Online Retail II  (the refund engine)
└── ieee_cis/                 # Kaggle: IEEE-CIS Fraud Detection (device + fraud labels)
```

---

## 1. Olist — REQUIRED

**Source:** https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
**Size:** ~45 MB zip, ~126 MB extracted

Extract **all 9 CSVs** into `data/raw/olist/`:

```
olist/
├── olist_customers_dataset.csv
├── olist_geolocation_dataset.csv
├── olist_order_items_dataset.csv
├── olist_order_payments_dataset.csv
├── olist_order_reviews_dataset.csv
├── olist_orders_dataset.csv
├── olist_products_dataset.csv
├── olist_sellers_dataset.csv
└── product_category_name_translation.csv
```

**What it gives us**

| Our file | Olist source | Why it matters |
|---|---|---|
| `customers` | `olist_customers_dataset` | 99k customers, real geo |
| `merchants` | `olist_sellers_dataset` | 3,095 real merchants |
| `transactions` | `olist_orders_dataset` | **real status lifecycle**: created → approved → invoiced → shipped → delivered / canceled / unavailable, with 5 independent timestamps |
| `payment_attempts` | `olist_order_payments_dataset` | `payment_sequential` = **multiple payment attempts per order** (split vouchers, card + voucher). This is the retry / partial-payment trap. |
| failed attempts | `orders.order_approved_at IS NULL` | genuine payment-approval failures — feeds *repeated failed attempts* |

---

## 2. Online Retail II — REQUIRED (this is the refund file)

**Source (no login needed):** https://archive.ics.uci.edu/dataset/502/online+retail+ii
**Size:** ~43 MB xlsx

```
online_retail_ii/
└── online_retail_II.xlsx
```

*Alternative (CSV, needs Kaggle account):* https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci → `online_retail_II.csv`

**What it gives us** — the only public dataset with *authentic* refunds:

- `InvoiceNo` starting with **`C`** → cancellation (≈19k invoice lines)
- **negative `Quantity`** → returned units
- a return of 2 units out of 5 on one invoice is a **genuine partial refund**
- repeated return lines on one invoice → **multiple partial refunds against one transaction**
- `CustomerID` missing on ~22% of rows → real referential-integrity problems for Experiment 2

This file is what makes "partial refunds" and "refund ratio" real instead of fabricated.

---

## 3. IEEE-CIS — REQUIRED (device summary + fraud labels)

**Source:** https://www.kaggle.com/c/ieee-fraud-detection/data
*(competition — click "Join Competition" / accept the rules, then download)*
**Size:** ~107 MB zip

Extract **only these two files** into `data/raw/ieee_cis/`:

```
ieee_cis/
├── train_transaction.csv      # 590,540 rows
└── train_identity.csv         # 144,233 rows (device/network info)
```

**What it gives us**

- `DeviceInfo`, `DeviceType`, `id_31` (browser), `id_33` (screen resolution) → **real device fingerprints**
- `card1`–`card6`, `addr1`, `P_emaildomain` → real card/identity linkage
- `TransactionDT` → real time offset (convert to timestamps)
- **`isFraud`** → real ground-truth labels, so detection quality can be *measured* instead of guessed

---

## Verify after downloading

```powershell
python -m src.ingestion.verify_raw
```

This prints a per-file check: exists, row count, columns found, encoding, and any
files still missing. Run it once your downloads are in place.

---

## Licensing / attribution

All three are public and free for academic use. Keep the attribution block in
`README.md` — it is part of the audit trail your report needs.

- Olist — CC BY-NC-SA 4.0
- Online Retail II — CC BY 4.0 (Chen, D. 2012, UCI ML Repository)
- IEEE-CIS Fraud Detection — Kaggle competition data, Vesta Corporation
