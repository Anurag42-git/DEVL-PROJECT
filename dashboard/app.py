"""
=============================================================================
 TRANSACTION ANOMALY & REFUND INVESTIGATION  -  Dashboard
 DEVL Semester 5 · Final Project
=============================================================================

This IS the "monitoring application" required by the problem statement.
It presents the four expected outcomes:

    1. Transaction dashboard ............ Overview
    2. Reconciled payment ledger ........ Reconciled ledger
    3. Explainable review queue ......... Review queue
    4. Audit report ..................... Audit report

Run locally:   streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
DEMO = ROOT / "data" / "demo"

st.set_page_config(
    page_title="Payment Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
INK = "#0F172A"
MUTED = "#64748B"
FAINT = "#94A3B8"
LINE = "#E8ECF3"
INDIGO = "#4F46E5"
SERIES = ["#4F46E5", "#0EA5E9", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6"]
SEV_COLORS = {"HIGH": "#EF4444", "MEDIUM": "#F59E0B", "LOW": "#10B981", "INFO": "#94A3B8"}

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], [data-testid="stMarkdownContainer"] {
        font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    }

    /* ---- remove default Streamlit chrome ---- */
    [data-testid="stAppDeployButton"],
    [data-testid="stDecoration"],
    #MainMenu, footer { display: none !important; }
    [data-testid="stHeader"] { background: transparent; }

    .block-container {
        padding: 3.2rem 2.6rem 4rem 2.6rem;
        max-width: 1560px;
    }

    /* ---- sidebar ---- */
    section[data-testid="stSidebar"] {
        background: #0B1220;
        border-right: 1px solid #1B2740;
    }
    section[data-testid="stSidebar"] .block-container { padding-top: 1.4rem; }
    section[data-testid="stSidebar"] * { color: #C7D2E1; }
    section[data-testid="stSidebar"] hr { border-color: #1B2740; }

    .brand { display:flex; align-items:center; gap:11px; margin-bottom:2px; }
    .brand-mark {
        width: 34px; height: 34px; border-radius: 10px;
        background: linear-gradient(135deg, #6366F1, #4F46E5);
        display: grid; place-items: center; color: #fff; font-size: 16px;
        box-shadow: 0 4px 14px rgba(79,70,229,.45);
    }
    .brand-name { font-size: 15px; font-weight: 700; color: #F1F5F9; letter-spacing: -.2px; }
    .brand-sub  { font-size: 10.5px; color: #7C8DA6; letter-spacing: .8px;
                  text-transform: uppercase; font-weight: 600; }

    /* nav: hide the radio circles, style rows as pills */
    section[data-testid="stSidebar"] div[role="radiogroup"] { gap: 3px; }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {
        padding: 9px 12px; border-radius: 10px; width: 100%;
        transition: background .15s ease, box-shadow .15s ease;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child {
        display: none;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {
        font-size: 13.5px; font-weight: 500; color: #AEBACD !important;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {
        background: rgba(148,163,184,.10);
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:checked) {
        background: rgba(99,102,241,.16);
        box-shadow: inset 3px 0 0 #6366F1;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:checked) p {
        color: #FFFFFF !important; font-weight: 600;
    }

    .side-block {
        background: rgba(148,163,184,.08);
        border: 1px solid #1B2740;
        border-radius: 12px; padding: 12px 14px; margin-top: 4px;
    }
    .side-block .t { font-size: 10px; font-weight: 700; letter-spacing: .9px;
                     text-transform: uppercase; color: #7C8DA6; margin-bottom: 7px; }
    .side-block .v { font-size: 12.5px; line-height: 1.55; color: #C7D2E1; }
    .dot { display:inline-block; width:7px; height:7px; border-radius:50%;
           background:#10B981; margin-right:7px; box-shadow:0 0 0 3px rgba(16,185,129,.15); }

    /* ---- hero ---- */
    .hero {
        position: relative;
        background:
            radial-gradient(900px 320px at 8% -30%, rgba(99,102,241,.55), transparent 65%),
            radial-gradient(700px 300px at 100% 0%, rgba(14,165,233,.30), transparent 60%),
            linear-gradient(135deg, #0B1220 0%, #121C31 55%, #18243E 100%);
        border: 1px solid #22304F;
        border-radius: 20px;
        padding: 34px 38px 32px;
        color: #fff;
        margin-bottom: 20px;
        overflow: hidden;
    }
    .hero h1 {
        margin: 10px 0 8px; font-size: 30px; line-height: 1.15;
        letter-spacing: -0.8px; font-weight: 800; color: #fff;
    }
    .hero p { margin: 0; font-size: 14px; color: #A9B8CE; max-width: 780px; line-height: 1.55; }
    .hero-badge {
        display: inline-flex; align-items: center; gap: 7px;
        background: rgba(16,185,129,.14); border: 1px solid rgba(16,185,129,.35);
        color: #6EE7B7; font-size: 10.5px; font-weight: 700; letter-spacing: .7px;
        text-transform: uppercase; padding: 5px 11px; border-radius: 999px;
    }
    .hero-badge .dot { background: #10B981; margin: 0; }

    /* ---- kpi cards ---- */
    .kpi {
        background: #FFFFFF; border: 1px solid #E8ECF3; border-radius: 16px;
        padding: 18px 20px 17px; height: 100%;
        box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 6px 16px rgba(16,24,40,.035);
    }
    .kpi-head { display: flex; align-items: center; gap: 9px; }
    .kpi-ico {
        width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center;
        font-size: 14px; background: #EEF0FF; color: #4F46E5;
    }
    .kpi-label {
        font-size: 10.5px; font-weight: 700; letter-spacing: .7px;
        text-transform: uppercase; color: #64748B;
    }
    .kpi-value {
        font-size: 30px; font-weight: 800; color: #0F172A; margin: 13px 0 3px;
        letter-spacing: -1px; white-space: nowrap; line-height: 1;
    }
    .kpi-hint { font-size: 11.5px; color: #94A3B8; line-height: 1.4; }
    .kpi-indigo  .kpi-ico { background: #EEF0FF; color: #4F46E5; }
    .kpi-emerald .kpi-ico { background: #ECFDF5; color: #059669; }
    .kpi-amber   .kpi-ico { background: #FFFBEB; color: #D97706; }
    .kpi-rose    .kpi-ico { background: #FEF2F2; color: #DC2626; }
    .kpi-sky     .kpi-ico { background: #F0F9FF; color: #0284C7; }

    /* ---- section headings ---- */
    .sec { display: flex; align-items: baseline; gap: 10px; margin: 4px 0 8px; }
    .sec h3 { font-size: 15.5px; font-weight: 700; color: #0F172A; margin: 0; letter-spacing: -.2px; }
    .sec span { font-size: 12px; color: #94A3B8; }

    /* ---- callouts ---- */
    .callout {
        background: #F3F5FF; border: 1px solid #DFE3FF;
        border-left: 4px solid #6366F1; border-radius: 12px;
        padding: 13px 17px; font-size: 13px; color: #334155;
        margin-bottom: 18px; line-height: 1.55;
    }
    .callout b { color: #1E293B; }
    .callout.warn { background: #FFF9EE; border-color: #FBE7C2; border-left-color: #F59E0B; }

    /* ---- bordered panels (st.container(border=True)) ---- */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF; border-radius: 16px;
        border-color: #E8ECF3 !important;
        box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 6px 16px rgba(16,24,40,.03);
    }

    /* ---- tables & widgets ---- */
    [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
    [data-testid="stDataFrame"] div[role="columnheader"] {
        background: #F8FAFC !important; font-weight: 600 !important;
    }
    .stSelectbox div[data-baseweb="select"] > div,
    .stTextInput input {
        border-radius: 10px !important; border-color: #E2E8F0 !important;
    }
    .stDownloadButton button {
        border-radius: 10px; border: 1px solid #E2E8F0; font-weight: 600; font-size: 13px;
    }

    .foot { text-align: center; color: #A9B4C4; font-size: 11.5px; margin-top: 34px; }
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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def money(v: float) -> str:
    v = float(v or 0)
    if abs(v) >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.1f}K"
    return f"{v:,.0f}"


def hero(title: str, subtitle: str, badge: str = "Live data") -> None:
    st.markdown(
        f'<div class="hero"><div class="hero-badge"><span class="dot"></span>{badge}</div>'
        f"<h1>{title}</h1><p>{subtitle}</p></div>",
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, hint: str, icon: str = "▦", tone: str = "indigo") -> None:
    st.markdown(
        f'<div class="kpi kpi-{tone}"><div class="kpi-head">'
        f'<span class="kpi-ico">{icon}</span><span class="kpi-label">{label}</span></div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


def section(title: str, sub: str = "") -> None:
    st.markdown(
        f'<div class="sec"><h3>{title}</h3><span>{sub}</span></div>',
        unsafe_allow_html=True,
    )


def callout(html: str, warn: bool = False) -> None:
    cls = "callout warn" if warn else "callout"
    st.markdown(f'<div class="{cls}">{html}</div>', unsafe_allow_html=True)


def style_fig(fig: go.Figure, height: int, **kw) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#475569", size=12),
        margin=dict(t=14, b=10, l=10, r=14),
        height=height,
        hoverlabel=dict(bgcolor="#0B1220", font_color="#FFFFFF", bordercolor="#0B1220"),
        **kw,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=LINE, tickfont=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor="#F1F5F9", zeroline=False, tickfont=dict(size=11))
    return fig


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
PAGES = [
    "Overview",
    "Reconciled ledger",
    "Review queue",
    "Data quality",
    "Audit report",
    "About",
]

requested = st.query_params.get("page", "")
requested = next((p for p in PAGES if p.lower() == str(requested).lower()), PAGES[0])

with st.sidebar:
    st.markdown(
        '<div class="brand"><div class="brand-mark">◆</div>'
        '<div><div class="brand-name">Payment Monitor</div>'
        '<div class="brand-sub">Reconcile · Explain · Review</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    page = st.radio("Navigate", PAGES, index=PAGES.index(requested), label_visibility="collapsed")
    if st.query_params.get("page") != page:
        st.query_params["page"] = page

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    source_label = "Demo sample" if using_sample else "Full pipeline"
    source_note = (
        "Headline figures are full-pipeline; tables show a real sample"
        if using_sample
        else "All reconciled intents loaded"
    )
    st.markdown(
        f'<div class="side-block"><div class="t">Data source</div>'
        f'<div class="v"><span class="dot"></span>{source_label}<br>'
        f'<span style="color:#7C8DA6">{source_note}</span></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="side-block"><div class="t">Never a fraud label</div>'
        '<div class="v">Flags are questions for a human. Outcomes stay '
        '<b style="color:#fff">PENDING</b> until reviewed.</div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------
if ledger.empty:
    st.error("No data found. Run `python -m src.reconcile.ledger` and `python -m src.rules.engine`.")
    st.stop()

flag_intents = queue.payment_intent_id.nunique() if not queue.empty else 0

# ---------------------------------------------------------------------------
# Headline aggregates
# ---------------------------------------------------------------------------
# The committed demo tables are a SAMPLE, but the reports describe the FULL
# pipeline. Headline numbers come from the reports, so the hosted dashboard
# shows true totals instead of sample-scaled ones.
_stats = recon.get("stats", {})

TOTAL_INTENTS = int(
    recon.get("ledger_rows") or _stats.get("payment_intents_out") or len(ledger)
)
COLLECTED = float(
    sum(recon.get("amount_summary", {}).get("collected_total_by_source", {}).values())
) or float(ledger.collected_amount.sum())

STATE_COUNTS = recon.get("refund_state_counts") or ledger.refund_state.value_counts().to_dict()
STATE_COUNTS = {k: int(v) for k, v in STATE_COUNTS.items()}

SEV_COUNTS = rules.get("by_severity") or (
    queue.severity.value_counts().to_dict() if not queue.empty else {}
)
SEV_COUNTS = {k: int(v) for k, v in SEV_COUNTS.items()}

RULE_COUNTS = rules.get("by_rule") or (
    queue.rule_id.value_counts().to_dict() if not queue.empty else {}
)
RULE_COUNTS = {k: int(v) for k, v in RULE_COUNTS.items()}

RULE_NAMES = (
    queue.drop_duplicates("rule_id").set_index("rule_id")["rule_name"].to_dict()
    if not queue.empty and "rule_name" in queue
    else {}
)

REFUNDED_INTENTS = int(_stats.get("intents_with_refund") or sum(
    v for k, v in STATE_COUNTS.items() if k != "NONE"
))
FLAGGED_INTENTS = int(rules.get("distinct_intents_flagged") or flag_intents)
RAW_REFUNDS = float(_stats.get("refunded_amount_raw_total") or ledger.refunded_amount_raw.sum())
CAPPED_REFUNDS = float(_stats.get("refunded_amount_capped_total") or ledger.refunded_amount.sum())


# ===========================================================================
# OVERVIEW
# ===========================================================================
if page == "Overview":
    hero(
        "Transaction Anomaly & Refund Investigation",
        "One reconciled view of every payment, the refunds attached to it, and the "
        "records that deserve a closer look — explained, never judged.",
        badge="Live demo" if using_sample else "Live data",
    )

    callout(
        "<b>How to read this</b> &nbsp;·&nbsp; Each <b>payment intent</b> is one real payment, "
        "even when it was paid in several parts. Rules then flag intents worth a look. "
        "A flag is a <b>question</b>, not a verdict — every outcome stays "
        "<b>PENDING</b> until a person decides."
    )

    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        kpi("Payment intents", f"{TOTAL_INTENTS:,}", "one row per real payment", "▦", "indigo")
    with c2:
        kpi("Total collected", money(COLLECTED), "all additive legs summed", "$", "emerald")
    with c3:
        rate = REFUNDED_INTENTS / max(TOTAL_INTENTS, 1) * 100
        kpi("Refund rate", f"{rate:.1f}%", f"{REFUNDED_INTENTS:,} intents refunded", "↩", "amber")
    with c4:
        pct = FLAGGED_INTENTS / max(TOTAL_INTENTS, 1) * 100
        kpi("Flagged for review", f"{FLAGGED_INTENTS:,}", f"{pct:.1f}% need a closer look", "⚑", "rose")

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ---- row 1: refund mix + severity ----
    left, right = st.columns([1, 1], gap="medium")

    with left, st.container(border=True):
        section("Refund mix", "intents that received money back")
        refund_counts = {k: v for k, v in STATE_COUNTS.items() if k != "NONE" and v > 0}
        if not refund_counts:
            st.caption("No refunded intents.")
        else:
            order = [s for s in ["PARTIAL", "FULL", "OVER"] if s in refund_counts]
            counts = pd.Series({s: refund_counts[s] for s in order})
            cmap = {"PARTIAL": "#F59E0B", "FULL": "#6366F1", "OVER": "#EF4444"}
            fig = go.Figure(
                go.Pie(
                    labels=counts.index,
                    values=counts.values,
                    hole=0.68,
                    marker=dict(
                        colors=[cmap.get(s, "#CBD5E1") for s in counts.index],
                        line=dict(color="#FFFFFF", width=3),
                    ),
                    textinfo="percent",
                    textfont=dict(size=12, color="#FFFFFF"),
                    hovertemplate="%{label}<br>%{value:,} intents · %{percent}<extra></extra>",
                    sort=False,
                )
            )
            fig.add_annotation(
                text=f"<b style='font-size:22px'>{sum(counts.values):,}</b>"
                f"<br><span style='font-size:11px;color:{FAINT}'>refunded</span>",
                showarrow=False,
                font=dict(color=INK),
            )
            fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center"))
            style_fig(fig, 300, showlegend=True)
            st.plotly_chart(fig, width="stretch")

    with right, st.container(border=True):
        section("Flag severity", "HIGH first, LOW is context")
        if not SEV_COUNTS:
            st.caption("No flags.")
        else:
            sev_order = [s for s in ["HIGH", "MEDIUM", "LOW", "INFO"] if s in SEV_COUNTS]
            sev = pd.Series({s: SEV_COUNTS[s] for s in sev_order})[::-1]
            fig = go.Figure(
                go.Bar(
                    x=sev.values,
                    y=sev.index,
                    orientation="h",
                    marker=dict(color=[SEV_COLORS[s] for s in sev.index], cornerradius=6),
                    text=[f"{v:,}" for v in sev.values],
                    textposition="outside",
                    textfont=dict(size=11, color="#475569"),
                    hovertemplate="%{y}: %{x:,} flags<extra></extra>",
                )
            )
            fig.update_xaxes(showgrid=True, gridcolor="#F1F5F9")
            fig.update_yaxes(showgrid=False)
            style_fig(fig, 300)
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=40))
            st.plotly_chart(fig, width="stretch")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ---- row 2: reconciliation impact + rules ----
    a, b = st.columns([1, 1.35], gap="medium")

    with a, st.container(border=True):
        section("Reconciliation impact", "refunds capped at amount collected")
        raw = RAW_REFUNDS
        capped = CAPPED_REFUNDS
        saved = raw - capped
        fig = go.Figure(
            go.Bar(
                x=["As recorded", "After capping"],
                y=[raw, capped],
                marker=dict(color=["#FCA5A5", "#10B981"], cornerradius=8),
                text=[money(raw), money(capped)],
                textposition="outside",
                textfont=dict(size=12, color="#334155", family="Inter"),
                width=[0.5, 0.5],
                hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
            )
        )
        fig.update_yaxes(showgrid=True, gridcolor="#F1F5F9")
        fig.update_xaxes(showgrid=False)
        style_fig(fig, 250, showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Removed **{money(saved)}** of over-refunding that naive summation would report.")

    with b, st.container(border=True):
        section("Flags by rule", "what triggered the review")
        if not RULE_COUNTS:
            st.caption("No flags.")
        else:
            rc = (
                pd.Series(RULE_COUNTS)
                .sort_values(ascending=True)
                .tail(8)
                .rename_axis("rule_id")
                .reset_index(name="size")
            )
            rc["rule_name"] = rc["rule_id"].map(RULE_NAMES).fillna("")
            fig = go.Figure(
                go.Bar(
                    x=rc["size"],
                    y=rc["rule_id"],
                    orientation="h",
                    marker=dict(color=INDIGO, cornerradius=6, opacity=0.9),
                    text=[f"{v:,}" for v in rc["size"]],
                    textposition="outside",
                    textfont=dict(size=11, color="#475569"),
                    customdata=rc["rule_name"],
                    hovertemplate="<b>%{y}</b><br>%{customdata}<br>%{x:,} flags<extra></extra>",
                )
            )
            fig.update_xaxes(showgrid=True, gridcolor="#F1F5F9")
            fig.update_yaxes(showgrid=False)
            style_fig(fig, 250)
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=40))
            st.plotly_chart(fig, width="stretch")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ---- row 3: activity over time ----
    with st.container(border=True):
        section("Payment activity", "monthly intents by source system")
        tmp = ledger.dropna(subset=["first_ts"]).copy()
        if tmp.empty:
            st.caption("No timestamps available.")
        else:
            tmp["month"] = pd.to_datetime(tmp["first_ts"]).dt.to_period("M").dt.to_timestamp()
            ts = (
                tmp.groupby(["month", "source_system"], as_index=False)
                .size()
                .rename(columns={"size": "Intents"})
            )
            fig = px.area(
                ts,
                x="month",
                y="Intents",
                color="source_system",
                color_discrete_sequence=SERIES,
                labels={"source_system": "Source", "month": ""},
            )
            fig.update_traces(line=dict(width=1.6), opacity=0.85)
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="#F1F5F9")
            style_fig(fig, 280)
            fig.update_layout(legend=dict(orientation="h", y=1.12, x=0, title=None))
            st.plotly_chart(fig, width="stretch")


# ===========================================================================
# LEDGER
# ===========================================================================
elif page == "Reconciled ledger":
    hero(
        "Reconciled payment ledger",
        "One row per payment intent, with additive legs summed and refunds capped at the amount collected.",
    )

    callout(
        "<b>What was reconciled?</b> &nbsp; Multiple payment legs are <b>summed</b> — they are "
        "additive, not retries. Refunds are <b>summed and capped</b> at the amount collected, "
        "so a partial or duplicated refund cannot inflate the money returned."
    )

    f1, f2, f3, f4 = st.columns([1, 1, 1.4, 1], gap="medium")
    src = f1.selectbox("Source system", ["All"] + sorted(ledger.source_system.unique().tolist()))
    state = f2.selectbox("Refund state", ["All"] + sorted(ledger.refund_state.unique().tolist()))
    search = f3.text_input("Search payment intent ID", placeholder="e.g. OLIST_…")
    only_review = f4.toggle("Needs review only", value=False)

    view = ledger
    if src != "All":
        view = view[view.source_system == src]
    if state != "All":
        view = view[view.refund_state == state]
    if only_review and "needs_review" in view:
        view = view[view.needs_review.astype(bool)]
    if search.strip():
        view = view[view.payment_intent_id.astype(str).str.contains(search.strip(), case=False, na=False)]

    k1, k2, k3, k4 = st.columns(4, gap="medium")
    with k1:
        kpi("Rows shown", f"{len(view):,}", f"of {len(ledger):,} intents", "≡", "indigo")
    with k2:
        kpi("Collected", money(view.collected_amount.sum()), "in the current view", "$", "emerald")
    with k3:
        kpi("Refunded (capped)", money(view.refunded_amount.sum()), "after capping", "↩", "amber")
    with k4:
        kpi("Needs review", f"{int(view.needs_review.sum()) if 'needs_review' in view else 0:,}",
            "flagged in this view", "⚑", "rose")

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    cols = [
        "payment_intent_id", "source_system", "leg_count", "collected_amount",
        "refunded_amount_raw", "refunded_amount", "refund_state",
        "backward_transition", "needs_review",
    ]
    cols = [c for c in cols if c in view.columns]

    st.dataframe(
        view[cols],
        width="stretch",
        height=520,
        column_config={
            "payment_intent_id": st.column_config.TextColumn("Payment intent", width="medium"),
            "source_system": st.column_config.TextColumn("Source", width="small"),
            "leg_count": st.column_config.NumberColumn("Legs", width="small"),
            "collected_amount": st.column_config.NumberColumn("Collected", format="%.2f"),
            "refunded_amount_raw": st.column_config.NumberColumn("Refunded raw", format="%.2f"),
            "refunded_amount": st.column_config.NumberColumn("Refunded capped", format="%.2f"),
            "refund_state": st.column_config.TextColumn("State", width="small"),
            "backward_transition": st.column_config.CheckboxColumn("Bad timeline", width="small"),
            "needs_review": st.column_config.CheckboxColumn("Review", width="small"),
        },
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.download_button(
        "↓  Download reconciled ledger (CSV)",
        data=view.to_csv(index=False).encode("utf-8"),
        file_name="reconciled_ledger.csv",
    )


# ===========================================================================
# REVIEW QUEUE
# ===========================================================================
elif page == "Review queue":
    hero(
        "Explainable review queue",
        "Every flag records what was seen, why it matters, and what a human decided.",
    )

    callout(
        "<b>These are review candidates, not confirmed fraud.</b> Each flag carries the "
        "evidence that triggered it and an outcome that stays <b>PENDING</b> until a person "
        "investigates. The system never labels a record as fraud.",
        warn=True,
    )

    if queue.empty:
        st.info("No flags in the data.")
    else:
        f1, f2, f3 = st.columns([1, 1, 1.4], gap="medium")
        sev = f1.selectbox("Severity", ["All"] + sorted(queue.severity.unique().tolist()))
        rule = f2.selectbox("Rule", ["All"] + sorted(queue.rule_id.unique().tolist()))
        needle = f3.text_input("Search entity or intent", placeholder="device, customer, order…")

        view = queue
        if sev != "All":
            view = view[view.severity == sev]
        if rule != "All":
            view = view[view.rule_id == rule]
        if needle.strip():
            mask = pd.Series(False, index=view.index)
            for c in ("entity_id", "payment_intent_id"):
                if c in view:
                    mask |= view[c].astype(str).str.contains(needle.strip(), case=False, na=False)
            view = view[mask]

        k1, k2, k3 = st.columns(3, gap="medium")
        with k1:
            kpi("Flags shown", f"{len(view):,}", "after filters", "⚑", "indigo")
        with k2:
            kpi("Distinct intents", f"{view.payment_intent_id.nunique():,}", "unique records to review", "▦", "sky")
        with k3:
            kpi("High severity", f"{int((view.severity == 'HIGH').sum()):,}", "check these first", "!", "rose")

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        st.dataframe(
            view[["flag_id", "rule_id", "rule_name", "severity", "entity_id", "reason", "outcome"]],
            width="stretch",
            height=380,
            column_config={
                "flag_id": st.column_config.TextColumn("Flag", width="small"),
                "rule_id": st.column_config.TextColumn("Rule", width="small"),
                "rule_name": st.column_config.TextColumn("What it checks", width="medium"),
                "severity": st.column_config.TextColumn("Severity", width="small"),
                "entity_id": st.column_config.TextColumn("Entity", width="medium"),
                "reason": st.column_config.TextColumn("Why flagged", width="large"),
                "outcome": st.column_config.TextColumn("Outcome", width="small"),
            },
        )

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        with st.container(border=True):
            section("Inspect a flag", "the evidence behind the decision")
            pick = st.selectbox(
                "Choose a flag",
                ["Select a flag…"] + view["flag_id"].head(1000).tolist(),
                label_visibility="collapsed",
            )
            if pick != "Select a flag…":
                row = view[view.flag_id == pick].iloc[0]
                d1, d2 = st.columns([1, 2], gap="large")
                with d1:
                    st.markdown(
                        f"**{row.rule_id}** — {row.rule_name}\n\n"
                        f"**Severity** · `{row.severity}`  \n"
                        f"**Outcome** · `{row.outcome}`  \n"
                        f"**Entity** · `{row.entity_id}`"
                    )
                with d2:
                    st.markdown("**Why it was flagged**")
                    st.info(row.reason)
                    st.markdown("**Evidence**")
                    st.code(row.evidence, language="json")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.download_button(
            "↓  Download review queue (CSV)",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name="review_queue.csv",
        )


# ===========================================================================
# DATA QUALITY
# ===========================================================================
elif page == "Data quality":
    hero(
        "Data quality assessment",
        "Defects are measured before anything is repaired — so the fixes are justified, not guessed.",
    )

    if not quality:
        st.info("No quality report found.")
    else:
        summary = quality.get("summary", {})
        c1, c2, c3, c4 = st.columns(4, gap="medium")
        with c1:
            kpi("High", str(summary.get("HIGH", 0)), "blocking defects", "●", "rose")
        with c2:
            kpi("Medium", str(summary.get("MEDIUM", 0)), "needs attention", "●", "amber")
        with c3:
            kpi("Info", str(summary.get("INFO", 0)), "observations", "●", "sky")
        with c4:
            kpi("OK", str(summary.get("OK", 0)), "checks passed", "●", "emerald")

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

        a, b = st.columns([1, 1.4], gap="medium")
        with a, st.container(border=True):
            section("Table profile")
            profile = pd.DataFrame(
                [
                    {"Table": k, "Rows": v.get("rows", 0), "Columns": v.get("columns", 0)}
                    for k, v in quality.get("tables", {}).items()
                ]
            )
            st.dataframe(profile, width="stretch", hide_index=True, height=280)

        with b, st.container(border=True):
            section("High-severity findings")
            high = [f for f in quality.get("findings", []) if f.get("severity") == "HIGH"]
            if high:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Table": f.get("table", "-"),
                                "Metric": f.get("metric", "-"),
                                "Value": str(f.get("value", "-")),
                                "Detail": f.get("detail", "-"),
                            }
                            for f in high
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                    height=280,
                )
            else:
                st.caption("No high-severity findings.")


# ===========================================================================
# AUDIT REPORT
# ===========================================================================
elif page == "Audit report":
    hero(
        "Audit report",
        "A single record of what was done, what was found, and what remains open.",
    )
    if audit_md:
        with st.container(border=True):
            st.markdown(audit_md)
        st.download_button(
            "↓  Download audit report (Markdown)",
            data=audit_md.encode("utf-8"),
            file_name="audit_report.md",
        )
    else:
        st.info("No audit report found. Run `python -m src.audit_report`.")


# ===========================================================================
# ABOUT
# ===========================================================================
else:
    hero(
        "About this project",
        "The problem, the approach, and where each expected outcome lives.",
    )

    a, b = st.columns([1, 1], gap="large")

    with a:
        with st.container(border=True):
            section("The problem")
            st.markdown(
                """
An online payment service has transaction, customer, merchant, refund,
payment-status and device-summary files. **Duplicate events, retries and partial
refunds** make it hard to tell routine activity from records worth investigating.
"""
            )
            section("What the application must do")
            st.markdown(
                """
1. Reconcile transaction and refund events **without double-counting** retries or partial refunds
2. Validate **amounts, timestamps, status transitions and references**
3. Calculate **transaction frequency per window, refund ratio and repeated failed attempts**
4. Explain **why** each record was flagged and keep a review outcome — **never label an alert as confirmed fraud**
"""
            )

    with b:
        with st.container(border=True):
            section("The four expected outcomes")
            st.markdown(
                """
| Expected outcome | Where it lives |
|---|---|
| **Transaction dashboard** | Overview |
| **Reconciled payment ledger** | Reconciled ledger |
| **Explainable review queue** | Review queue |
| **Audit report** | Audit report |
"""
            )
            st.caption(
                "A dashboard *is* the monitoring application required here. "
                "No separate CRUD application is needed."
            )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        section("Real public data", "no synthetic rows")
        st.markdown(
            """
| Dataset | What it provides |
|---|---|
| **Olist Brazilian E-Commerce** | 99,441 orders, 3,095 merchants, real payment and status lifecycle |
| **Online Retail II (UCI)** | 1,067,371 invoice lines, authentic partial returns and cancellations |
| **IEEE-CIS Fraud Detection** | 590,540 card transactions, device fingerprints, held-out labels for evaluation only |
"""
        )
        st.caption(
            "Labels are isolated from the pipeline and joined only after flags are produced, "
            "so evaluation cannot leak into detection."
        )

st.markdown(
    '<div class="foot">Payment Monitor · reconciled ledger · explainable review queue · audit trail</div>',
    unsafe_allow_html=True,
)
