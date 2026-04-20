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
        "ramping":           "early ramp",
        "healthy":           "healthy",
        "mixed":             "mixed signals",
    }.get(band, band)


def _driver_line(row: pd.Series) -> str:
    """Return the single largest driver sentence."""
    u = row.utilization_u
    age = row.contract_age_days
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
    if band == "ramping":
        return f"Contract is only {int(age)} days old; ramp protection holds HealthScore at 1.00."
    if band == "healthy":
        return f"Utilization at {u:.0%}, within the healthy band; no anomaly flags tripped."
    return f"Utilization at {u:.0%}; modifier={row.modifier:.2f}."


def narrate(row: pd.Series) -> str:
    """3-sentence narrative (spec 11 §3.2 template)."""
    if row is None or pd.isna(row.healthscore):
        return "No active contract on the snapshot date; metric not computed."
    s1 = (
        f"HealthScore is **{row.healthscore:.2f}** — {_band_copy(row.band)}. "
        f"cARR is ${row.carr:,.0f} against Committed ARR of ${row.committed_arr:,.0f}."
    )
    s2 = _driver_line(row)
    ramp_info = ""
    if row.ramp_w < 1.0:
        ramp_info = (
            f" Ramp weight `w` = {row.ramp_w:.2f} (contract age {int(row.contract_age_days)}d, "
            f"segment {row.segment}) — blended HealthScore is held closer to booking trust."
        )
    s3 = f"Steady-state HealthScore would be {row.healthscore_steady:.2f} absent ramp protection.{ramp_info}"
    return f"{s1}\n\n{s2}\n\n{s3}"
