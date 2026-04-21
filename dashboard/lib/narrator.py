"""
Anomaly narrator — implements specs/11 §3.2.

Strict template discipline: the LLM (when enabled) picks a template branch
and fills slots; it does NOT write prose from scratch. That's how the
output stays auditable.

When no LLM key is configured, the narrator renders the same templates
from deterministic rules. This is the default reviewer-friendly mode.
"""
from __future__ import annotations

import pandas as pd


def _band_copy(band: str) -> str:
    return {
        "at_risk_shelfware": "shelfware-leaning",
        "spike_drop":        "spike-drop pattern",
        "expansion":         "expanding",
        "overage":           "paying overage",
        "healthy":           "healthy",
    }.get(band, band)


def _driver_line(row: pd.Series) -> str:
    """Return the single largest driver sentence."""
    u = row.utilization_u
    band = row.band
    if band == "at_risk_shelfware":
        if pd.isna(u):
            return "No usage observed in the trailing 90 days despite an active contract."
        return f"Trailing-90-day utilization is only {u:.0%} of included credits."
    if band == "spike_drop":
        return f"Month-1 of the 90-day window accounts for {row.m1_share:.0%} of total usage — classic spike-drop."
    if band == "expansion":
        return f"Utilization at {u:.0%} with {int(row.n_active_contracts)} overlapping contracts — the account is expanding."
    if band == "overage":
        return f"Utilization at {u:.0%}, consistently above included — the customer is paying overage."
    if band == "healthy":
        if pd.isna(u):
            return "No usage data yet — HealthScore defaults to booking trust."
        return f"Utilization at {u:.0%}, within the healthy band; no anomaly flags tripped."
    return f"Utilization at {u:.0%}; modifier={row.modifier:.2f}."


def narrate(row: pd.Series) -> str:
    """2-sentence narrative (spec 11 §3.2 template)."""
    if row is None or pd.isna(row.healthscore):
        return "No active contract on the snapshot date; metric not computed."
    s1 = (
        f"HealthScore is **{row.healthscore:.2f}** — {_band_copy(row.band)}. "
        f"cARR is ${row.carr:,.0f} against Committed ARR of ${row.committed_arr:,.0f}."
    )
    s2 = _driver_line(row)
    return f"{s1}\n\n{s2}"
