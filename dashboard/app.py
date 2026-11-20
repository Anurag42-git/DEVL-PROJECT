"""
Experiment 3 - Transaction dashboard (Streamlit)
Experiment 11 - Transaction Anomaly and Refund Investigation

Run:  streamlit run dashboard/app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"

st.set_page_config(page_title="Transaction Monitoring", layout="wide")
st.title("Transaction Anomaly & Refund Investigation")
st.caption("DEVL Semester 5 · Experiment 11 · real public datasets")


@st.cache_data
def load(name: str) -> pd.DataFrame:
    path = OUT / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


ledger = load("reconciled_ledger")
queue = load("review_queue")

if ledger.empty:
    st.error("No ledger found. Run: python -m src.reconcile.ledger")
    st.stop()

# ---------------------------------------------------------------- KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Payment intents", f"{len(ledger):,}")
c2.metric("Total collected", f"{ledger.collected_amount.sum():,.0f}")
c3.metric("Flagged intents", f"{queue.payment_intent_id.nunique():,}" if not queue.empty else "0")
c4.metric("Over-refunded", f"{(ledger.refund_state == 'OVER').sum():,}")

tab1, tab2, tab3 = st.tabs(["Overview", "Reconciled ledger", "Review queue"])

# ---------------------------------------------------------------- Overview
with tab1:
    st.subheader("Refund state")
    st.bar_chart(ledger.refund_state.value_counts())

    if not queue.empty:
        st.subheader("Flags by rule")
        st.bar_chart(queue.groupby("rule_id").size())

    st.subheader("Collected by source")
    st.bar_chart(ledger.groupby("source_system").collected_amount.sum())

# ---------------------------------------------------------------- Ledger
with tab2:
    col1, col2 = st.columns(2)
    sources = ["ALL"] + sorted(ledger.source_system.unique().tolist())
    src = col1.selectbox("Source", sources)
    states = ["ALL"] + sorted(ledger.refund_state.unique().tolist())
    state = col2.selectbox("Refund state", states)

    view = ledger
    if src != "ALL":
        view = view[view.source_system == src]
    if state != "ALL":
        view = view[view.refund_state == state]

    st.caption(f"{len(view):,} rows")
    cols = [
        "payment_intent_id", "source_system", "leg_count", "collected_amount",
        "refunded_amount", "refund_state", "backward_transition", "needs_review",
    ]
    st.dataframe(view[cols].head(2000), use_container_width=True, height=500)
    st.download_button(
        "Download full ledger (CSV)",
        data=ledger.to_csv(index=False).encode("utf-8"),
        file_name="reconciled_ledger.csv",
    )

# ---------------------------------------------------------------- Queue
with tab3:
    if queue.empty:
        st.info("No review flags.")
    else:
        col1, col2 = st.columns(2)
        sev = col1.multiselect(
            "Severity", sorted(queue.severity.unique()), default=["HIGH", "MEDIUM"]
        )
        rule = col2.multiselect("Rule", sorted(queue.rule_id.unique()))

        qv = queue[queue.severity.isin(sev)]
        if rule:
            qv = qv[qv.rule_id.isin(rule)]

        st.caption(f"{len(qv):,} flags · outcomes are PENDING, never 'fraud'")
        st.dataframe(
            qv[["flag_id", "rule_id", "rule_name", "severity", "entity_id",
                "reason", "outcome"]].head(2000),
            use_container_width=True,
            height=500,
        )
