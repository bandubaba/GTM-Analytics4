"""
cARR metric parameters.

All values below are derived from specs/03_north_star_metric.md §6
(Parameter reference) and specs/11 (budgets). Changing a value here
without amending spec 03 breaks the spec/code contract.

Refs:
  specs/03_north_star_metric.md §2 (formula), §6 (parameters), §7 (invariants)
  specs/04_pipeline_architecture.md §3 (layering)
"""
from __future__ import annotations

from datetime import date

# -------- time window --------
# AS_OF_DATE is the pipeline "today" — the snapshot moment.
# Non-configurable for comp by D03. Overridable in tests only.
AS_OF_DATE: date = date(2026, 4, 18)

# Trailing window for HealthScore inputs (D03).
TRAILING_WINDOW_DAYS: int = 90

# -------- HealthScore bounds (D02) --------
HS_FLOOR: float = 0.40
HS_CAP: float = 1.30

# -------- base(U) piecewise rule (spec 03 §2.1) --------
# U is utilization = actual_credits_90d / expected_credits_90d
# where expected = included_monthly_credits × 3.
#
# Bands:
#   U < 0.30   → shelfware band         → base = 0.40
#   0.30 ≤ U < 0.80 → underuse           → base = 0.40 + (U − 0.30) × 1.20  (linear to 1.00)
#   0.80 ≤ U ≤ 1.10 → healthy band       → base = 1.00
#   U > 1.10   → expansion/overage band  → base = 1.00 + min(U − 1.10, 0.20) × 1.00  (up to 1.20)
SHELFWARE_U_MAX: float = 0.30
HEALTHY_U_MIN: float = 0.80
HEALTHY_U_MAX: float = 1.10
EXPANSION_U_BONUS_CAP: float = 0.20  # caps expansion base at 1.20 before modifier

# -------- modifier rules (spec 03 §3) --------
# Spike-drop: month-1 share ≥ SPIKE_DROP_M1_SHARE of trailing-90d, AND contract_age ≥ SPIKE_DROP_MIN_AGE
SPIKE_DROP_M1_SHARE: float = 0.70
SPIKE_DROP_MIN_AGE_DAYS: int = 90
SPIKE_DROP_MODIFIER: float = 0.70  # multiplicative penalty

# Expansion: account has ≥ 2 active overlapping contracts and aggregated U > 1.0 sustained
EXPANSION_MODIFIER: float = 1.05

# Overage (paying over included credits, but not runaway): small positive, capped by HS_CAP
OVERAGE_MODIFIER: float = 1.00  # neutral — the base(U) already rewards it

# -------- ramp protection (D12, spec 03 §2.2) --------
# Segment-aware ramp. contract_age is measured from the oldest active
# contract on the account as of AS_OF_DATE (spec 03 §3.7) to prevent
# gaming via renewal gaps.
#
# Blend: HealthScore = (1 − w) × 1.00 + w × HealthScore_steady
#   w = 0.0 if age ≤ ramp_full
#   w linear from 0 → 1 across (ramp_full, ramp_end)
#   w = 1.0 if age ≥ ramp_end
RAMP_PARAMS: dict[str, dict[str, int]] = {
    "Mid-Market": {"ramp_full": 15, "ramp_end": 60},
    "Enterprise": {"ramp_full": 30, "ramp_end": 120},
}

# -------- pricing --------
# Credits → dollars used for overage computation; matches data_generation/config.py.
PRICE_PER_CREDIT: float = 1.00
