"""
=============================================================================
 TRANSACTION ANOMALY & REFUND INVESTIGATION  -  Dashboard
 DEVL Semester 5 · Experiment 11
=============================================================================

This IS the "monitoring application" required by the problem statement.
It presents the four expected outcomes:

    1. Transaction dashboard ............ this page (Overview)
    2. Reconciled payment ledger ........ tab "Reconciled ledger"
    3. Explainable review queue ......... tab "Review queue"
    4. Audit report ..................... tab "Audit report"

Run locally:   streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
DEMO = ROOT / "data" / "demo"

st.set_page_config(
    page_title="Payment Investigation Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.6rem; padding-bottom: 3rem; }
    .hero {
        background: linear-gradient(120deg, #0f2c4d 0%, #1b4f82 55%, #2376a8 100%);
        padding: 26px 32px; border-radius: 14px; color: white; margin-bottom: 18px;
    }
    .hero h1 { margin: 0 0 6px 0; font-size: 30px; letter-spacing: -0.5px; }
    .hero p  { margin: 0; font-size: 14px; opacity: .88; }
    .card {
        background: #f7f9fc; border: 1px solid #e3e9f0; border-radius: 12px;
        padding: 14px 16px; height: 100%;
    }
    .card .label { font-size: 11px; color: #5b7085; font-weight: 700;
                   text-transform: uppercase; letter-spacing: .4px; }
    .card .value { font-size: clamp(18px, 2.1vw, 28px); font-weight: 800;
                   color: #123; margin-top: 6px; white-space: nowrap;
                   overflow: hidden; text-overflow: ellipsis; }
    .card .hint  { font-size: 11px; color: #7c8da0; margin-top: 6px; line-height: 1.35; }
    .note {
        background: #eef6ff; border-left: 4px solid #2f7fd1; border-radius: 8px;
        padding: 12px 16px; font-size: 13px; margin-bottom: 16px; color: #244;
    }
    .warn {
        background: #fff8e8; border-left: 4px solid #e0a020; border-radius: 8px;
        padding: 12px 16px; font-size: 13px; margin-bottom: 16px; color: #443;
    }
    div[data-testid="stSidebar"] { background: #f4f7fb; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data loading (full output locally, committed real sample in the cloud)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_table(name: str) -> tuple[pd.DataFrame, bool]:
    full = OUT / f"{name}.parquet"
    if full.exists():
        return pd.read_parquet(full), False
    sample = DEMO / f"{name}.parquet"
    if sample.exists():
        return pd.read_parquet(sample), True
    return pd.DataFrame(), False


@st.cache_data(show_spinner=False)
def load_json(name: str) -> dict:
    for base in (OUT, DEMO):
        path = base / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


@st.cache_data(show_spinner=False)
def load_text(name: str) -> str:
    for base in (ROOT / "docs", DEMO):
        path = base / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


ledger, using_sample = load_table("reconciled_ledger")
queue, _ = load_table("review_queue")
quality = load_json("quality_report.json")
recon = load_json("reconciliation_report.json")
rules = load_json("rule_summary.json")
audit_md = load_text("audit_report.md")


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, hint: str) -> None:
    st.markdown(
        f'<div class="card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div>'
        f'<div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
PAGES = [
    "📊 Overview",
    "📒 Reconciled ledger",
    "🚩 Review queue",
    "🔎 Data quality",
    "📄 Audit report",
    "ℹ️ About",
]

# Shareable section links: dashboard/app.py?page=Review+queue
requested = st.query_params.get("page", "")
# accept short names like "Review+queue" as well as full emoji labels
requested = next(
    (p for p in PAGES if p.endswith(requested) or requested in p),
    PAGES[0],
)

with st.sidebar:
    st.markdown("## 🔍 Payment Monitor")
    st.caption("Experiment 11 · DEVL Semester 5")
    st.markdown("---")

    # No `key` and no session_state write: Streamlit warns if a widget has both
    # a default index and a session-state value.
    page = st.radio(
        "Go to",
        PAGES,
        index=PAGES.index(requested),
        label_visibility="collapsed",
    )
    if st.query_params.get("page") != page:
        st.query_params["page"] = page

    st.markdown("---")
    if using_sample:
        st.info("Cloud demo: representative sample of real pipeline rows.")
    else:
        st.success("Full pipeline output loaded.")

    with st.expander("What must this project do?"):
        st.markdown(
            "1. Reconcile transactions and refunds **without double-counting**\n"
            "2. Validate **amounts, timestamps, status, references**\n"
            "3. Compute **frequency, refund ratio, failed attempts**\n"
            "4. Explain each flag — **never confirm fraud**"
        )


# ---------------------------------------------------------------------------
# 0. Guard
# ---------------------------------------------------------------------------
if ledger.empty:
    st.error("No data found. Run `python -m src.reconcile.ledger` and `python -m src.rules.engine`.")
    st.stop()


# ===========================================================================
# OVERVIEW
# ===========================================================================
if page == "📊 Overview":
    hero(
        "Transaction Anomaly & Refund Investigation",
        "A monitoring dashboard that reconciles payments, explains unusual patterns, "
        "and sends them to a human review queue — without ever calling them fraud.",
    )

    st.markdown(
        '<div class="note"><b>How to read this dashboard</b><br>'
        "Each payment intent (one real payment, possibly paid in several parts) is "
        "reconciled into one ledger row. Rules then flag rows worth a closer look. "
        "A flag is a <b>question</b>, not a verdict — every outcome stays <b>PENDING</b> "
        "until a person decides.</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Payment intents", f"{len(ledger):,}", "one row per real payment after reconciliation")
    with c2:
        total = ledger.collected_amount.sum()
        kpi("Total collected", f"{total/1e6:,.1f}M" if total >= 1e6 else f"{total:,.0f}",
            "sum of all additive payment legs")
    with c3:
        flagged = queue.payment_intent_id.nunique() if not queue.empty else 0
        kpi("Intents flagged", f"{flagged:,}", f"{flagged/max(len(ledger),1)*100:.1f}% need a closer look")
    with c4:
        kpi("Over-refunded", f"{(ledger.refund_state == 'OVER').sum():,}",
            "refunds exceeded the amount collected")

    st.markdown("###")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Refund state")
        st.caption("How much of each payment was given back")
        state_counts = ledger.refund_state.value_counts().reset_index()
        state_counts.columns = ["Refund state", "Intents"]
        fig = px.pie(
            state_counts, values="Intents", names="Refund state", hole=0.55,
            color_discrete_sequence=["#2b7bbb", "#54a24b", "#e45756", "#f2a900"],
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    with right:
        st.markdown("#### Flags by severity")
        st.caption("HIGH = check first · LOW = context only")
        if not queue.empty:
            sev = queue.severity.value_counts().reset_index()
            sev.columns = ["Severity", "Flags"]
            order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
            sev["o"] = sev["Severity"].map(order)
            sev = sev.sort_values("o")
            colors = {"HIGH": "#e45756", "MEDIUM": "#f2a900", "LOW": "#54a24b", "INFO": "#8c8c8c"}
            fig = px.bar(
                sev, x="Severity", y="Flags", color="Severity",
                color_discrete_map=colors, text="Flags",
            )
            fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig, width="stretch")

    st.markdown("#### Flags by rule — why records were flagged")
    if not queue.empty:
        rc = queue.groupby(["rule_id", "rule_name"], as_index=False).size().sort_values("size")
        fig = px.bar(
            rc, x="size", y="rule_id", orientation="h",
            hover_data=["rule_name"], text="size",
            labels={"size": "Flags", "rule_id": "Rule"},
        )
        fig.update_layout(height=340, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Payment activity over time")
    tmp = ledger.dropna(subset=["first_ts"]).copy()
    if len(tmp):
        tmp["day"] = pd.to_datetime(tmp["first_ts"]).dt.date
        daily = tmp.groupby("day", as_index=False).size().rename(columns={"size": "Intents"})
        fig = px.line(daily, x="day", y="Intents", markers=False)
        fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")


# ===========================================================================
# LEDGER
# ===========================================================================
elif page == "📒 Reconciled ledger":
    hero("Reconciled payment ledger", "Outcome 2 — one row per payment intent, with money correctly reconciled.")

    st.markdown(
        '<div class="note"><b>What was reconciled?</b> Multiple payment legs are '
        "<b>summed</b> (they are additive). Refunds are <b>summed and capped</b> at the "
        "amount collected, so a partial or duplicate refund cannot inflate the money "
        "returned.</div>",
        unsafe_allow_html=True,
    )

    f1, f2, f3 = st.columns(3)
    src = f1.selectbox("Source system", ["All"] + sorted(ledger.source_system.unique().tolist()))
    state = f2.selectbox("Refund state", ["All"] + sorted(ledger.refund_state.unique().tolist()))
    search = f3.text_input("Search payment intent ID")

    view = ledger
    if src != "All":
        view = view[view.source_system == src]
    if state != "All":
        view = view[view.refund_state == state]
    if search.strip():
        view = view[view.payment_intent_id.astype(str).str.contains(search.strip(), case=False)]

    st.caption(f"Showing {len(view):,} of {len(ledger):,} reconciled intents")
    cols = [
        "payment_intent_id", "source_system", "leg_count", "collected_amount",
        "refunded_amount_raw", "refunded_amount", "refund_state",
        "backward_transition", "needs_review",
    ]
    cols = [c for c in cols if c in view.columns]
    st.dataframe(
        view[cols],
        width="stretch",
        height=560,
        column_config={
            "collected_amount": st.column_config.NumberColumn("Collected", format="%.2f"),
            "refunded_amount_raw": st.column_config.NumberColumn("Refunded (raw)", format="%.2f"),
            "refunded_amount": st.column_config.NumberColumn("Refunded (capped)", format="%.2f"),
            "leg_count": st.column_config.NumberColumn("Legs"),
            "needs_review": st.column_config.CheckboxColumn("Needs review"),
            "backward_transition": st.column_config.CheckboxColumn("Bad timeline"),
        },
    )
    st.download_button(
        "Download reconciled ledger (CSV)",
        data=ledger.to_csv(index=False).encode("utf-8"),
        file_name="reconciled_ledger.csv",
    )


# ===========================================================================
# REVIEW QUEUE
# ===========================================================================
elif page == "🚩 Review queue":
    hero("Explainable review queue", "Outcome 3 — every flag says what was seen and why it matters.")

    st.markdown(
        '<div class="warn"><b>Important:</b> these are <b>review candidates</b>, '
        "not confirmed fraud. Each flag carries the evidence that triggered it and "
        "an outcome that stays <b>PENDING</b> until a human investigates.</div>",
        unsafe_allow_html=True,
    )

    if queue.empty:
        st.info("No flags in the data.")
    else:
        f1, f2 = st.columns(2)
        sev = f1.selectbox("Severity", ["All"] + sorted(queue.severity.unique().tolist()))
        rule = f2.selectbox("Rule", ["All"] + sorted(queue.rule_id.unique().tolist()))

        view = queue
        if sev != "All":
            view = view[view.severity == sev]
        if rule != "All":
            view = view[view.rule_id == rule]

        a, b, c = st.columns(3)
        kpi("Flags shown", f"{len(view):,}", "after filters")
        kpi("Distinct intents", f"{view.payment_intent_id.nunique():,}", "unique records to review")
        kpi("High severity", f"{(view.severity == 'HIGH').sum():,}", "check these first")

        st.markdown("###")
        st.dataframe(
            view[["flag_id", "rule_id", "rule_name", "severity", "entity_id", "reason", "outcome"]],
            width="stretch",
            height=500,
        )

        st.markdown("#### Inspect one flag")
        pick = st.selectbox(
            "Choose a flag to see its evidence",
            ["Select…"] + view["flag_id"].head(500).tolist(),
        )
        if pick != "Select…":
            row = view[view.flag_id == pick].iloc[0]
            d1, d2 = st.columns([1, 2])
            with d1:
                st.write("**Rule:**", f"{row.rule_id} — {row.rule_name}")
                st.write("**Severity:**", row.severity)
                st.write("**Outcome:**", row.outcome)
                st.write("**Entity:**", row.entity_id)
            with d2:
                st.write("**Why it was flagged**")
                st.info(row.reason)
                st.write("**Evidence**")
                st.code(row.evidence, language="json")

        st.download_button(
            "Download review queue (CSV)",
            data=queue.to_csv(index=False).encode("utf-8"),
            file_name="review_queue.csv",
        )


# ===========================================================================
# DATA QUALITY
# ===========================================================================
elif page == "🔎 Data quality":
    hero("Data quality assessment", "Experiment 2 — defects are measured before anything is repaired.")

    if not quality:
        st.info("No quality report found.")
    else:
        st.markdown("#### Findings by severity")
        cols = st.columns(4)
        for col, (sev, icon) in zip(cols, [("HIGH", "🔴"), ("MEDIUM", "🟠"), ("INFO", "🔵"), ("OK", "🟢")]):
            with col:
                kpi(f"{icon} {sev}", str(quality.get("summary", {}).get(sev, 0)), "findings")

        st.markdown("###")
        st.markdown("#### Table profile")
        st.dataframe(
            pd.DataFrame(
                [{"Table": k, "Rows": v["rows"], "Columns": v["columns"]}
                 for k, v in quality.get("tables", {}).items()]
            ),
            width="stretch",
            hide_index=True,
        )

        st.markdown("#### High-severity findings")
        high = [f for f in quality.get("findings", []) if f.get("severity") == "HIGH"]
        if high:
            st.dataframe(
                pd.DataFrame([
                    {"Table": f.get("table", "-"), "Metric": f.get("metric", "-"),
                     "Value": f.get("value", "-"), "Detail": f.get("detail", "-")}
                    for f in high
                ]),
                width="stretch",
                hide_index=True,
            )


# ===========================================================================
# AUDIT REPORT
# ===========================================================================
elif page == "📄 Audit report":
    hero("Audit report", "Outcome 4 — a single record of what was done and what was found.")
    if audit_md:
        st.markdown(audit_md)
    else:
        st.info("No audit report found. Run `python -m src.audit_report`.")


# ===========================================================================
# ABOUT
# ===========================================================================
else:
    hero("About this project", "What the problem asks for, and where each answer lives.")

    st.markdown(
        """
        ### The problem

        An online payment service has transaction, customer, merchant, refund,
        payment-status and device-summary files. **Duplicate events, retries and
        partial refunds** make it hard to distinguish routine activity from records
        that need investigation.

        ### What the application must do

        1. Reconcile transaction/refund events **without double-counting** retries or partial refunds
        2. Validate **amounts, timestamps, status transitions and transaction references**
        3. Calculate **transaction frequency per time window, refund ratio and repeated failed attempts**
        4. Show **why** each record was flagged and keep a review outcome — **never** label an alert as confirmed fraud

        ### The four expected outcomes

        | Outcome | Where to find it here |
        |---|---|
        | Transaction dashboard | This dashboard — **Overview** |
        | Reconciled payment ledger | **Reconciled ledger** tab |
        | Explainable review queue | **Review queue** tab |
        | Audit report | **Audit report** tab |

        ### Real data used

        - **Olist Brazilian E-Commerce** — 99,441 orders, 3,095 merchants, real status lifecycle
        - **Online Retail II (UCI)** — 1,067,371 invoice lines, authentic partial returns
        - **IEEE-CIS Fraud Detection** — 590,540 card transactions, device fingerprints and ground-truth labels
        """
    )

    st.markdown("---")
    st.caption(
        "Note: a dashboard is the monitoring application required by the problem "
        "statement. No separate CRUD application is needed."
    )
