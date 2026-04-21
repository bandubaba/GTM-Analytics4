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
# Bands (v0.7.1 — healthy plateau widened from [0.80, 1.10] to [0.70, 1.10]):
#   U < 0.30   → shelfware band         → base = 0.40
#   0.30 ≤ U < 0.70 → underuse           → base = 0.40 + (U − 0.30) × 1.50  (linear to 1.00)
#   0.70 ≤ U ≤ 1.10 → healthy band       → base = 1.00
#   U > 1.10   → expansion/overage band  → base = 1.00 + min(U − 1.10, 0.20) × 1.00  (up to 1.20)
#
# Why the wider plateau: normal under-utilization (70–95%) is not a rep-
# accountable problem — many enterprise customers run at 80% of included
# credits by design. Penalizing them suppressed attainment on accounts
# that weren't actually at risk. See specs/03 Appendix D (v0.7.1).
SHELFWARE_U_MAX: float = 0.30
HEALTHY_U_MIN: float = 0.70
HEALTHY_U_MAX: float = 1.10
EXPANSION_U_BONUS_CAP: float = 0.20  # caps expansion base at 1.20 before modifier

# -------- modifier rules (spec 03 §3) --------
# Spike-drop: month-1 share ≥ SPIKE_DROP_M1_SHARE of trailing-90d, AND contract_age ≥ SPIKE_DROP_MIN_AGE
# v0.7.1 — penalty strengthened from 0.70 to 0.50: the pattern is a high-
# churn-risk leading indicator (customer front-loaded consumption then
# stopped), and the prior 30% haircut under-weighted it relative to the
# shelfware floor. See specs/03 Appendix D (v0.7.1).
SPIKE_DROP_M1_SHARE: float = 0.70
SPIKE_DROP_MIN_AGE_DAYS: int = 90
SPIKE_DROP_MODIFIER: float = 0.50  # multiplicative penalty

# Expansion: account has ≥ 2 active overlapping contracts and aggregated U > 1.0 sustained
# v0.7.1 — boost raised from 1.05 to 1.10: mid-contract expansion is a
# genuine upside signal (customer bought more during the term) and the
# prior 5% bump was a rounding error against the overage band.
EXPANSION_MODIFIER: float = 1.10

# Overage (paying over included credits, but not runaway): small positive, capped by HS_CAP
OVERAGE_MODIFIER: float = 1.00  # neutral — the base(U) already rewards it

# -------- ramp protection --------
# v0.6 included a segment-aware ramp blend (HS = (1 − w)·1.00 + w·HS_steady).
# v0.7 removes it: the ramp windows were defensible in principle but
# noisy in practice, and a blended metric is harder to explain than the
# straight clamp(base × modifier). New logos without usage history hit
# the `utilization_u IS NULL → base = 1.00` branch of base(U), which
# gives a reasonable default without a separate blend parameter.
# Kept this comment as a pointer so the deleted spec block (03 §2.2) is
# discoverable in git history.

# -------- pricing --------
# Credits → dollars used for overage computation; matches data_generation/config.py.
PRICE_PER_CREDIT: float = 1.00
