"""
cARR dashboard — Streamlit.

Views:
  1. Executive     — headline cARR, region/segment splits, band distribution
  2. Reps          — leaderboard, filterable; dispersion of weighted HS
  3. Account drill — pick an account; see HealthScore decomposition and
                     the narrator (specs/11 §3.2)
  4. DQ            — pipeline health, orphan counts, assertion status
  5. Ask cARR      — NL query layer (specs/11 §3.1 / §4)

Run:
    streamlit run dashboard/app.py

Requires a prior `python pipeline_and_tests/run.py` to populate
pipeline_and_tests/data/ with the parquet exports.
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st

from lib import data, narrator, ask as ask_mod

st.set_page_config(page_title="cARR — GTM North Star", layout="wide", page_icon="📊")

# Streamlit Cloud secrets → env vars so the existing os.environ.get(...) paths
# work unchanged in both local (exported env var) and cloud (st.secrets) runs.
# st.secrets raises if no secrets.toml exists locally; swallow that case.
try:
    for _key in ("ANTHROPIC_API_KEY",):
        if _key not in os.environ and _key in st.secrets:
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass


# ---------------------------------------------------------------------------
# guardrail: did the pipeline run?
# ---------------------------------------------------------------------------

if not data.data_available():
    st.error(
        "Pipeline artifact missing. Run `python pipeline_and_tests/run.py` "
        "from the repo root before launching the dashboard."
    )
    st.stop()

# ---------------------------------------------------------------------------
# shared data
# ---------------------------------------------------------------------------

df = data.load_current()
reps = data.load_by_rep()
region = data.load_by_region()
dq = data.load_dq_summary()


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("cARR — GTM North Star")
st.sidebar.caption(f"as of **{dq.as_of_date}**  ·  spec 03 v0.6")
st.sidebar.markdown("---")

view = st.sidebar.radio(
    "View",
    ["Executive", "Reps", "Account drill", "Data quality", "Ask cARR"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "cARR = Committed_ARR × HealthScore\n\n"
    "HealthScore ∈ [0.40, 1.30], ramp-blended for new contracts (D12)."
)
st.sidebar.caption(f"LLM mode: **{'ON' if os.environ.get('ANTHROPIC_API_KEY') else 'OFF (offline templates)'}**")


# ---------------------------------------------------------------------------
# view: executive
# ---------------------------------------------------------------------------

def _money(x: float) -> str:
    return f"${x:,.0f}"


def view_executive():
    st.title("Executive view")
    st.caption(
        "One row, one number the CFO can anchor on: cARR vs Committed ARR. "
        "Everything below drills into why the number looks the way it does."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Committed ARR", _money(dq.total_committed_arr))
    c2.metric("cARR", _money(dq.total_carr))
    delta_pct = (dq.total_carr - dq.total_committed_arr) / dq.total_committed_arr
    c3.metric("cARR / Committed", f"{dq.weighted_healthscore:.1%}", f"{delta_pct:+.1%}")
    c4.metric("Accounts in metric", int(dq.n_accounts_in_metric))

    st.markdown("### cARR by region × segment")
    fig = px.bar(
        region,
        x="region", y="carr", color="segment",
        barmode="group",
        labels={"carr": "cARR ($)", "region": ""},
        hover_data=["committed_arr", "weighted_healthscore", "n_accounts"],
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Band distribution")
    band_counts = df.groupby("band").agg(
        n_accounts=("account_id", "count"),
        committed_arr=("committed_arr", "sum"),
        carr=("carr", "sum"),
    ).reset_index().sort_values("carr", ascending=False)

    colors = {
        "healthy": "#2ecc71",
        "expansion": "#1abc9c",
        "overage": "#16a085",
        "mixed": "#f39c12",
        "ramping": "#3498db",
        "spike_drop": "#e67e22",
        "at_risk_shelfware": "#e74c3c",
    }
    fig2 = px.bar(
        band_counts,
        x="band", y=["committed_arr", "carr"],
        barmode="group",
        labels={"value": "$", "variable": ""},
        color_discrete_map={"committed_arr": "#34495e", "carr": "#2980b9"},
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.dataframe(band_counts.style.format({"committed_arr": _money, "carr": _money}), use_container_width=True)

    with st.expander("What 'band' means"):
        st.markdown(
            """
- **healthy** — HealthScore in [0.85, 1.15]; nothing flagged.
- **expansion** — ≥ 2 overlapping contracts and utilization above included.
- **overage** — sustained utilization above included; customer is paying overage.
- **ramping** — contract age inside the segment's ramp window; HealthScore
  is held near booking trust per D12 (new-logo protection).
- **spike_drop** — ≥ 70% of 90-day usage in month 1 and contract age ≥ 90 days.
- **at_risk_shelfware** — HealthScore ≤ 0.55.
- **mixed** — everything else (borderline; warrants human review).
            """
        )


# ---------------------------------------------------------------------------
# view: reps
# ---------------------------------------------------------------------------

def view_reps():
    st.title("Reps")
    st.caption(
        "Rep-level weighted HealthScore. Spread tells you whether cARR "
        "actually separates strong books from weak ones (T3 dispersion check)."
    )
    segment_filter = st.multiselect("Segment", sorted(reps.segment.dropna().unique()), default=list(reps.segment.dropna().unique()))
    region_filter = st.multiselect("Region", sorted(reps.region.dropna().unique()), default=list(reps.region.dropna().unique()))
    rf = reps[reps.segment.isin(segment_filter) & reps.region.isin(region_filter)].copy()

    c1, c2, c3 = st.columns(3)
    c1.metric("Reps shown", len(rf))
    c2.metric("Σ cARR", _money(rf.carr.sum()))
    if rf.weighted_healthscore.notna().any():
        c3.metric("Weighted HS spread", f"{rf.weighted_healthscore.max() - rf.weighted_healthscore.min():.2f}")

    st.markdown("#### Leaderboard")
    st.dataframe(
        rf.sort_values("carr", ascending=False)[
            ["rep_name", "region", "segment", "n_accounts", "committed_arr", "carr",
             "weighted_healthscore", "n_at_risk", "n_spike_drop", "n_expansion", "n_ramping"]
        ].style.format({"committed_arr": _money, "carr": _money, "weighted_healthscore": "{:.3f}"}),
        use_container_width=True,
        hide_index=True,
    )

    if len(rf) > 0:
        st.markdown("#### Weighted HealthScore distribution")
        fig = px.histogram(rf.dropna(subset=["weighted_healthscore"]), x="weighted_healthscore", color="segment", nbins=20)
        fig.add_vline(x=1.0, line_dash="dash", annotation_text="parity")
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# view: account drill
# ---------------------------------------------------------------------------

def view_account_drill():
    st.title("Account drill-down")
    st.caption(
        "Pick an account. The narrator (spec 11 §3.2) returns a 3-sentence "
        "template-filled explanation; every number is traceable to the "
        "HealthScore decomposition below."
    )

    # Sort so interesting accounts bubble to the top
    ordered = df.sort_values("committed_arr", ascending=False)
    pick = st.selectbox(
        "Account",
        ordered.account_id.tolist(),
        index=0,
        format_func=lambda aid: f"{aid}  ·  {ordered.loc[ordered.account_id == aid, 'band'].iloc[0]}  ·  ${ordered.loc[ordered.account_id == aid, 'committed_arr'].iloc[0]:,.0f}",
    )
    row = df[df.account_id == pick].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Committed ARR", _money(row.committed_arr))
    c2.metric("cARR", _money(row.carr))
    c3.metric("HealthScore", f"{row.healthscore:.2f}")
    c4.metric("Utilization U", f"{row.utilization_u:.0%}" if pd.notna(row.utilization_u) else "—")
    c5.metric("Band", row.band)

    st.markdown("### Narrator")
    st.info(narrator.narrate(row))

    st.markdown("### HealthScore decomposition")
    st.dataframe(
        pd.DataFrame([{
            "segment": row.segment,
            "contract_age_days": int(row.contract_age_days) if pd.notna(row.contract_age_days) else None,
            "n_active_contracts": int(row.n_active_contracts),
            "credits_90d (inferred)": "—",
            "utilization_u": f"{row.utilization_u:.3f}" if pd.notna(row.utilization_u) else "—",
            "m1_share": f"{row.m1_share:.3f}" if pd.notna(row.m1_share) else "—",
            "base(U)": f"{row.base_score:.3f}",
            "modifier": f"{row.modifier:.3f}",
            "ramp_w": f"{row.ramp_w:.3f}",
            "HS_steady": f"{row.healthscore_steady:.3f}",
            "HS (blended)": f"{row.healthscore:.3f}",
            "cARR": _money(row.carr),
        }]).T.rename(columns={0: "value"}),
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# view: DQ
# ---------------------------------------------------------------------------

def view_dq():
    st.title("Data quality")
    st.caption(
        "Pipeline-level health. All counts drawn from mart_dq_summary, "
        "which is the same source the DQ assertion suite reads (spec 05)."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accounts (total)", int(dq.n_accounts))
    c2.metric("w/ active contract", int(dq.n_accounts_with_active_contract))
    c3.metric("in metric", int(dq.n_accounts_in_metric))
    c4.metric("Reps", int(dq.n_reps))

    c1, c2, c3 = st.columns(3)
    c1.metric("Usage logs", int(dq.n_usage_logs))
    c2.metric("Orphan (bad account)", int(dq.n_orphan_bad_account))
    c3.metric("Orphan (out of window)", int(dq.n_orphan_out_of_window))

    st.markdown("### Band mix")
    st.dataframe(
        pd.DataFrame({
            "band": ["at_risk_shelfware", "spike_drop", "expansion", "ramping", "healthy"],
            "count": [dq.n_shelfware, dq.n_spike_drop, dq.n_expansion, dq.n_ramping, dq.n_healthy],
        }),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("### Headline")
    st.info(
        f"Total Committed ARR: **{_money(dq.total_committed_arr)}**  ·  "
        f"Total cARR: **{_money(dq.total_carr)}**  ·  "
        f"weighted HealthScore **{dq.weighted_healthscore:.3f}**"
    )
    st.caption("Run `python pipeline_and_tests/dq/run_dq.py` in the terminal for the full 16-assertion audit.")


# ---------------------------------------------------------------------------
# view: Ask cARR (NL query)
# ---------------------------------------------------------------------------

def view_ask():
    st.title("Ask cARR")
    st.caption(
        "Natural-language query layer over the metric mart "
        "(spec 11 §3.1). Offline template mode is always on; setting "
        "ANTHROPIC_API_KEY enables Claude-generated SQL with a local "
        "verifier (dry-run EXPLAIN) in front (spec 11 §4)."
    )

    examples = ask_mod.EXAMPLES
    cols = st.columns(3)
    picked = None
    for i, ex in enumerate(examples):
        if cols[i % 3].button(ex, key=f"ex_{i}", use_container_width=True):
            picked = ex

    q = st.text_input(
        "Ask a question about cARR, reps, regions, or anomalies.",
        value=picked or "",
        placeholder="e.g. Show cARR by region",
    )

    if q:
        with data.connect() as con:
            result = ask_mod.ask(q, con)
        st.markdown(f"**Mode:** `{result.mode}`{' · **refused**' if result.refused else ''}")
        if result.refused:
            st.warning(result.refusal_reason)
        else:
            st.markdown("#### Answer")
            st.info(result.narration)
            if not result.rows.empty:
                st.markdown("#### Rows")
                st.dataframe(result.rows, use_container_width=True)
        st.markdown("#### Generated SQL")
        st.code(result.sql, language="sql")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

routes = {
    "Executive":      view_executive,
    "Reps":           view_reps,
    "Account drill":  view_account_drill,
    "Data quality":   view_dq,
    "Ask cARR":       view_ask,
}
routes[view]()
