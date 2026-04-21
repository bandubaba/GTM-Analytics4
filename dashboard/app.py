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
st.sidebar.caption(f"as of **{dq.as_of_date}**  ·  spec 03 v0.7")
st.sidebar.markdown("---")

view = st.sidebar.radio(
    "View",
    ["Executive", "Reps", "Comp impact", "Account drill", "Data quality", "Ask cARR"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "cARR = Committed_ARR × HealthScore\n\n"
    "HealthScore ∈ [0.40, 1.30]. Pre-signal trust: new logos with no usage "
    "fall through to base = 1.00 (D12b)."
)
st.sidebar.caption(f"LLM mode: **{'ON' if os.environ.get('ANTHROPIC_API_KEY') else 'OFF (offline templates)'}**")


# ---------------------------------------------------------------------------
# view: executive
# ---------------------------------------------------------------------------

def _money(x: float) -> str:
    return f"${x:,.0f}"


# Friendly display names for the mart's SQL band identifiers. Kept at the
# edge of the dashboard (not in SQL) so the warehouse still uses snake_case
# for joins / filters — the UI renders these. Labels mirror the brief's
# five anomaly names so readers see consistent wording everywhere.
_BAND_LABEL = {
    "spike_drop":        "Spike & Drop",
    "at_risk_shelfware": "Shelfware",
    "overage":           "Consistent Overages",
    "expansion":         "Mid-Year Expansions",
    "healthy":           "Healthy",
}


def _band_display(b: str) -> str:
    return _BAND_LABEL.get(b, b)


def _fmt_rows(rows: pd.DataFrame):
    """Apply sensible per-column display formatting to an arbitrary result frame.

    Used by the Ask cARR view where the column set is LLM-determined and we
    can't know it in advance. Money columns get "$1,234,567"; HealthScores
    get 3 decimals; utilization gets a percent; integer-ish counts get commas.
    Returns the original DataFrame on any failure (never breaks the view).
    """
    if rows is None or rows.empty:
        return rows
    fmt: dict = {}
    for col in rows.columns:
        c = str(col).lower()
        if (
            c in {"committed_arr", "carr", "implied_adj", "revenue", "delta", "total_carr", "total_committed_arr"}
            or c.endswith("_arr")
            or c.endswith("_carr")
        ):
            fmt[col] = "${:,.0f}"
        elif (
            c in {"healthscore", "base_score", "modifier", "weighted_healthscore"}
            or c.endswith("_healthscore")
            or c.endswith("_score")
        ):
            fmt[col] = "{:.3f}"
        # Explicit ratio columns: U can exceed 1.0 on overage, so we MUST
        # NOT route these through the pct-heuristic below.
        elif c in {"utilization_u", "utilization", "m1_share"}:
            fmt[col] = "{:.1%}"
        # General %/share/rate/ratio column names — Claude-generated SQL
        # varies: sometimes pre-multiplied (ROUND(x*100, 1) → 33.3),
        # sometimes a raw ratio (→ 0.333). Detect from the value range.
        elif any(t in c.split("_") for t in ("pct", "share", "rate", "ratio", "percent")):
            try:
                maxabs = float(rows[col].abs().max())
                already_pct = maxabs > 1.5   # if any value > 1.5, treat as already in %
            except Exception:
                already_pct = False
            fmt[col] = "{:.1f}%" if already_pct else "{:.1%}"
        elif c.startswith("n_") or c in {"contract_age_days", "count"}:
            fmt[col] = "{:,.0f}"
    try:
        return rows.style.format(fmt, na_rep="—")
    except Exception:
        return rows


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

    st.markdown("### Band distribution — the cARR formula's output")
    band_counts = df.groupby("band").agg(
        n_accounts=("account_id", "count"),
        committed_arr=("committed_arr", "sum"),
        carr=("carr", "sum"),
    ).reset_index().sort_values("carr", ascending=False)

    # % share columns — each one sums to 1.0 down the column. Placed right
    # next to its absolute twin so a reader can read "242 accounts (35.4%)
    # hold $31M Committed (33.0%) and produce $29.8M cARR (38.9%)".
    band_counts["pct_accounts"]  = band_counts.n_accounts    / band_counts.n_accounts.sum()
    band_counts["pct_committed"] = band_counts.committed_arr / band_counts.committed_arr.sum()
    band_counts["pct_carr"]      = band_counts.carr          / band_counts.carr.sum()
    band_counts = band_counts[[
        "band",
        "n_accounts", "pct_accounts",
        "committed_arr", "pct_committed",
        "carr", "pct_carr",
    ]]
    # UI-only relabel — all downstream filters already ran on snake_case.
    band_counts["band"] = band_counts["band"].map(_band_display)

    fig2 = px.bar(
        band_counts,
        x="band", y=["committed_arr", "carr"],
        barmode="group",
        labels={"value": "$", "variable": ""},
        color_discrete_map={"committed_arr": "#34495e", "carr": "#2980b9"},
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.dataframe(
        band_counts.style.format({
            "n_accounts":     "{:,.0f}",
            "pct_accounts":   "{:.1%}",
            "committed_arr":  _money,
            "pct_committed":  "{:.1%}",
            "carr":           _money,
            "pct_carr":       "{:.1%}",
        }),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("What 'band' means"):
        st.markdown(
            """
The brief names **five input anomalies** the metric must handle
(shelfware, spike-drop, consistent overage, mid-year expansion, orphans).
The mart exposes **five output bands** — four mapped 1:1 to the brief's
non-orphan anomalies, plus `healthy` as the baseline.

**Mapped to the brief's anomalies:**
- **Shelfware** (`at_risk_shelfware`) — HealthScore ≤ 0.55. Covers
  *shelfware*.
- **Spike & Drop** (`spike_drop`) — ≥ 70% of trailing-90d usage in month 1
  and contract age ≥ 90 days. Covers *spike-and-drop*.
- **Consistent Overages** (`overage`) — utilization > 1.10 × included.
  Covers *consistent overage*.
- **Mid-Year Expansions** (`expansion`) — ≥ 2 overlapping contracts and
  utilization > 1.0. Covers *mid-year expansion*.

**Baseline:**
- **Healthy** (`healthy`) — everything else. The residual "no anomaly
  flagged" bucket. Accounts here have no archetype pattern tripping.

Orphan / rogue usage (the brief's 5th anomaly) is excluded upstream
via `int_orphan_usage` and never reaches this band classifier —
that's the right handling per spec 02 §5.
            """
        )

    st.markdown("### cARR by region × segment")
    fig = px.bar(
        region,
        x="region", y="carr", color="segment",
        barmode="group",
        labels={"carr": "cARR ($)", "region": ""},
        hover_data=["committed_arr", "weighted_healthscore", "n_accounts"],
    )
    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------------
    # Edge cases from the assignment — 5 rows, in the order the assignment
    # lists them, with actuals verified against `_account_archetypes.csv`
    # and the int_orphan_usage / int_account_active_contracts marts.
    # ------------------------------------------------------------------
    st.markdown("### Edge cases injected per the assignment")
    st.caption(
        "The assignment names five anomalies the metric must handle. Here is "
        "what our generator actually injected, verified against "
        "`_account_archetypes.csv`, `int_account_active_contracts`, and "
        "`int_orphan_usage`."
    )

    arch_all = data.load_archetypes()
    gen_total = len(arch_all) if len(arch_all) else len(df)
    g = arch_all.archetype.value_counts() if len(arch_all) else pd.Series(dtype=int)

    # Mid-year expansions — accounts with ≥ 2 active contracts on as_of_date
    try:
        act = pd.read_parquet(data.DATA_DIR / "int_account_active_contracts.parquet")
        n_expansion = int((act.n_active_contracts >= 2).sum())
    except Exception:
        n_expansion = int((df.n_active_contracts >= 2).sum())

    # Orphan logs
    try:
        orph = pd.read_parquet(data.DATA_DIR / "int_orphan_usage.parquet")
        n_bad_account = int((orph.usage_class == "orphan_bad_account").sum())
        n_oow = int((orph.usage_class == "orphan_out_of_window").sum())
    except Exception:
        n_bad_account = n_oow = 0

    def _pct(n: int) -> str:
        return f"{n/gen_total:.1%}" if gen_total else "—"

    edge_table = pd.DataFrame([
        {
            "anomaly":           "1. Spike & Drop",
            "assignment":        "~5% of accounts",
            "actual":            f"{int(g.get('spike_drop', 0))} / {gen_total} accounts ({_pct(int(g.get('spike_drop', 0)))})",
        },
        {
            "anomaly":           "2. Shelfware",
            "assignment":        "~10% of accounts",
            "actual":            f"{int(g.get('shelfware', 0))} / {gen_total} accounts ({_pct(int(g.get('shelfware', 0)))})",
        },
        {
            "anomaly":           "3. Consistent Overages",
            "assignment":        "~15% of accounts",
            "actual":            f"{int(g.get('overage', 0))} / {gen_total} accounts ({_pct(int(g.get('overage', 0)))})",
        },
        {
            "anomaly":           "4. Mid-Year Expansions",
            "assignment":        "several accounts with overlapping contracts",
            "actual":            f"{n_expansion} accounts with ≥2 active contracts on the snapshot date",
        },
        {
            "anomaly":           "5. Orphaned / Rogue Usage",
            "assignment":        "a few hundred usage logs",
            "actual":            f"{n_bad_account + n_oow} logs ({n_bad_account} bad account_id + {n_oow} out-of-window)",
        },
    ])
    st.dataframe(edge_table, use_container_width=True, hide_index=True)


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
             "weighted_healthscore", "n_at_risk", "n_spike_drop", "n_expansion", "n_overage"]
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
# view: comp impact
# ---------------------------------------------------------------------------

def view_comp_impact():
    st.title("Comp impact")
    st.caption(
        "If we swap the attainment base from **Committed ARR → cARR**, which reps get paid "
        "more, which get paid less, and where does the money come from? This is the T4 "
        "comp-safety test in dollar terms (spec 06 §7)."
    )

    # commission assumption — simple linear rate on attainment, just to show the
    # magnitude. Reps can tune to match their own plan.
    rate_pct = st.slider(
        "Commission rate (applied to attainment $ delta)",
        min_value=1.0, max_value=25.0, value=10.0, step=0.5,
        help="A simple linear rate on attainment dollars. Real plans have accelerators "
             "and SPIFs; this is the baseline sensitivity before those apply."
    )
    rate = rate_pct / 100.0

    # ---- portfolio headline --------------------------------------------------
    total_committed = df.committed_arr.sum()
    total_carr = df.carr.sum()
    delta = total_carr - total_committed
    comp_delta = rate * delta

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Σ Committed ARR", _money(total_committed))
    c2.metric("Σ cARR", _money(total_carr), f"{delta/total_committed:+.1%}")
    c3.metric("Attainment $ shift", _money(delta))
    c4.metric(f"Aggregate comp shift @ {rate_pct:.1f}%", _money(comp_delta))

    st.caption(
        "Negative aggregate comp shift is expected — cARR discounts shelfware, and "
        "shelfware is where the biggest dollars sit. The interesting question is "
        "**not** the total, it's the **distribution across reps**."
    )

    # ---- where does the money move? ----------------------------------------
    st.markdown("### Where the attainment $ move — by band")
    band_flow = df.groupby("band").agg(
        n_accounts=("account_id", "count"),
        committed_arr=("committed_arr", "sum"),
        carr=("carr", "sum"),
    ).reset_index()
    band_flow["delta"] = band_flow.carr - band_flow.committed_arr
    band_flow["comp_delta"] = rate * band_flow["delta"]
    band_flow = band_flow.sort_values("delta")
    band_flow["band"] = band_flow["band"].map(_band_display)

    fig_band = px.bar(
        band_flow,
        x="band", y="delta",
        color=band_flow["delta"].apply(lambda v: "lift" if v > 0 else "cut"),
        color_discrete_map={"lift": "#16a085", "cut": "#c0392b"},
        labels={"delta": "cARR − Committed ARR ($)", "band": ""},
    )
    fig_band.update_layout(showlegend=False)
    st.plotly_chart(fig_band, use_container_width=True)

    st.dataframe(
        band_flow.rename(columns={"comp_delta": f"comp_delta_@{rate_pct:.1f}%"})
            .style.format({
                "n_accounts": "{:,.0f}",
                "committed_arr": "${:,.0f}",
                "carr": "${:,.0f}",
                "delta": "${:,.0f}",
                f"comp_delta_@{rate_pct:.1f}%": "${:,.0f}",
            }),
        use_container_width=True,
        hide_index=True,
    )

    # ---- per-rep comp delta -------------------------------------------------
    st.markdown("### Per-rep comp impact")
    rep_flow = df.groupby("rep_id").agg(
        n_accounts=("account_id", "count"),
        committed_arr=("committed_arr", "sum"),
        carr=("carr", "sum"),
    ).reset_index()
    rep_flow["delta"] = rep_flow.carr - rep_flow.committed_arr
    rep_flow["delta_pct"] = rep_flow["delta"] / rep_flow.committed_arr
    rep_flow["comp_delta"] = rate * rep_flow["delta"]
    rep_flow = rep_flow.merge(reps[["rep_id", "rep_name", "region", "segment"]], on="rep_id", how="left")

    c1, c2, c3 = st.columns(3)
    c1.metric("Reps with cut",     int((rep_flow.delta < 0).sum()))
    c2.metric("Reps roughly flat (±5%)", int(rep_flow.delta_pct.abs().le(0.05).sum()))
    c3.metric("Reps with lift",    int((rep_flow.delta > 0).sum()))

    st.markdown("#### Ranked — most cut → most lift")
    cols_shown = ["rep_name", "region", "segment", "n_accounts",
                  "committed_arr", "carr", "delta", "delta_pct", "comp_delta"]
    st.dataframe(
        rep_flow[cols_shown]
            .sort_values("delta")
            .rename(columns={"comp_delta": f"comp_Δ_@{rate_pct:.1f}%",
                             "delta": "attainment_Δ",
                             "delta_pct": "attainment_Δ_%"})
            .style.format({
                "n_accounts": "{:,.0f}",
                "committed_arr": "${:,.0f}",
                "carr": "${:,.0f}",
                "attainment_Δ": "${:,.0f}",
                "attainment_Δ_%": "{:+.1%}",
                f"comp_Δ_@{rate_pct:.1f}%": "${:,.0f}",
            }),
        use_container_width=True,
        hide_index=True,
    )

    # distribution — how many reps take big hits?
    st.markdown("#### Distribution of per-rep comp delta")
    fig_hist = px.histogram(
        rep_flow, x="comp_delta", nbins=30,
        labels={"comp_delta": f"Per-rep comp Δ @ {rate_pct:.1f}% ($)"},
        color_discrete_sequence=["#34495e"],
    )
    fig_hist.add_vline(x=0, line_dash="dash", line_color="#7f8c8d", annotation_text="no change")
    st.plotly_chart(fig_hist, use_container_width=True)

    # ---- rep × band drill ---------------------------------------------------
    st.markdown("### Pick a rep → see the dollars by band")
    rep_pick = st.selectbox(
        "Rep",
        rep_flow.sort_values("delta").rep_id.tolist(),
        format_func=lambda rid: (
            f"{rep_flow.loc[rep_flow.rep_id == rid, 'rep_name'].iloc[0]}  ·  "
            f"Δ {rep_flow.loc[rep_flow.rep_id == rid, 'delta'].iloc[0]:+,.0f}  ·  "
            f"{rep_flow.loc[rep_flow.rep_id == rid, 'delta_pct'].iloc[0]:+.1%}"
        ),
    )
    rep_bands = df[df.rep_id == rep_pick].groupby("band").agg(
        n=("account_id", "count"),
        committed_arr=("committed_arr", "sum"),
        carr=("carr", "sum"),
    ).reset_index()
    rep_bands["delta"] = rep_bands.carr - rep_bands.committed_arr
    rep_bands["comp_delta"] = rate * rep_bands["delta"]
    rep_bands = rep_bands.sort_values("delta")
    rep_bands["band"] = rep_bands["band"].map(_band_display)

    st.dataframe(
        rep_bands.rename(columns={"comp_delta": f"comp_Δ_@{rate_pct:.1f}%",
                                  "delta": "attainment_Δ"})
            .style.format({
                "n": "{:,.0f}",
                "committed_arr": "${:,.0f}",
                "carr": "${:,.0f}",
                "attainment_Δ": "${:,.0f}",
                f"comp_Δ_@{rate_pct:.1f}%": "${:,.0f}",
            }),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("How this maps to the T4 comp-safety eval"):
        st.markdown(
            """
The T4 tier in [spec 06](../specs/06_evaluation_framework.md) asks: *is the metric stable
and robust enough that tying variable pay to it is fair?* This view makes three of
those checks tangible:

- **Sensitivity to archetype concentration.** If a single band (shelfware, overage)
  drives most of a rep's attainment shift, the metric is doing its job —
  discriminating — not mis-firing. Reps whose books are archetype-balanced should
  see small deltas.
- **Tail risk.** The histogram above is the shape comp plans have to absorb. A long
  left tail is the reason rollout has a **shadow-comp quarter** before any paycheck
  impact (spec 08).
- **Single-account sensitivity.** Watch the per-rep drill: if one account drives >30%
  of a rep's delta, that rep's book is fragile to any one customer. Worth a QBR
  conversation before cARR goes into comp.
            """
        )


# ---------------------------------------------------------------------------
# view: account drill
# ---------------------------------------------------------------------------

def view_account_drill():
    st.title("Account drill-down")
    st.caption(
        "Pick an account. The narrator (spec 11 §3.2) returns a 2-sentence "
        "template-filled explanation; every number is traceable to the "
        "HealthScore decomposition below."
    )

    # Sort so interesting accounts bubble to the top
    ordered = df.sort_values("committed_arr", ascending=False)
    pick = st.selectbox(
        "Account",
        ordered.account_id.tolist(),
        index=0,
        format_func=lambda aid: f"{aid}  ·  {_band_display(ordered.loc[ordered.account_id == aid, 'band'].iloc[0])}  ·  ${ordered.loc[ordered.account_id == aid, 'committed_arr'].iloc[0]:,.0f}",
    )
    row = df[df.account_id == pick].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Committed ARR", _money(row.committed_arr))
    c2.metric("cARR", _money(row.carr))
    c3.metric("HealthScore", f"{row.healthscore:.2f}")
    c4.metric("Utilization U", f"{row.utilization_u:.0%}" if pd.notna(row.utilization_u) else "—")
    c5.metric("Band", _band_display(row.band))

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
            "HealthScore": f"{row.healthscore:.3f}",
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
            "band": [_band_display(b) for b in
                     ["at_risk_shelfware", "spike_drop", "expansion", "overage", "healthy"]],
            "count": [dq.n_shelfware, dq.n_spike_drop, dq.n_expansion, dq.n_overage, dq.n_healthy],
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
                st.dataframe(_fmt_rows(result.rows), use_container_width=True, hide_index=True)
        st.markdown("#### Generated SQL")
        st.code(result.sql, language="sql")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

routes = {
    "Executive":      view_executive,
    "Reps":           view_reps,
    "Comp impact":    view_comp_impact,
    "Account drill":  view_account_drill,
    "Data quality":   view_dq,
    "Ask cARR":       view_ask,
}
routes[view]()
