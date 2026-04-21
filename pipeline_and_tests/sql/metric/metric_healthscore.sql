-- metric_healthscore
--   Ref: specs/03_north_star_metric.md §2 (formula), §3 (modifiers), D02
--
--   Produces per-account HealthScore:
--     HealthScore = clamp(base(U) × modifier, HS_FLOOR, HS_CAP)
--
--   v0.6 removed the ramp-blend (§2.2) — the segment-aware ramp windows
--   were defensible in principle but noisy in practice and drew scope
--   objections. v0.7 uses the steady-state formula directly for every
--   active-contract account; new logos with no usage yet default to
--   base = 1.00 via the `utilization_u IS NULL` branch, which keeps
--   new-logo comp reasonable without a separate blend parameter.
--
--   Every input column is surfaced so the dashboard's "why is my score X?"
--   widget (spec 07 §3, spec 11 §3.2) can cite them.

CREATE OR REPLACE TABLE metric_healthscore AS
WITH base_with_ctx AS (
    SELECT
        a.account_id,
        acc.segment,
        a.n_active_contracts,
        a.contract_age_days,
        u.utilization_u,
        u.m1_share,
        u.credits_90d,
        u.expected_credits_90d,
        -- base(U) piecewise (spec 03 §2.1)
        CASE
          WHEN u.utilization_u IS NULL                                 THEN 1.00       -- no expected → no evidence; trust booking
          WHEN u.utilization_u < {shelfware_u_max}                     THEN {hs_floor} -- shelfware band
          WHEN u.utilization_u < {healthy_u_min}                       THEN {hs_floor} + (u.utilization_u - {shelfware_u_max}) * (1.00 - {hs_floor}) / ({healthy_u_min} - {shelfware_u_max})
          WHEN u.utilization_u <= {healthy_u_max}                      THEN 1.00
          ELSE 1.00 + LEAST(u.utilization_u - {healthy_u_max}, {expansion_u_bonus_cap}) * 1.00
        END AS base_score,
        -- modifier rules
        CASE
          WHEN u.m1_share >= {spike_drop_m1_share}
               AND a.contract_age_days >= {spike_drop_min_age}         THEN {spike_drop_modifier}
          WHEN a.n_active_contracts >= 2
               AND u.utilization_u > 1.00                              THEN {expansion_modifier}
          ELSE 1.00
        END AS modifier
    FROM int_account_active_contracts a
    LEFT JOIN int_usage_rolled u USING (account_id)
    LEFT JOIN stg_accounts     acc USING (account_id)
)
SELECT
    account_id,
    segment,
    contract_age_days,
    n_active_contracts,
    utilization_u,
    m1_share,
    credits_90d,
    expected_credits_90d,
    base_score,
    modifier,
    -- HealthScore: steady-state, clamped to bounds (D02)
    GREATEST({hs_floor}, LEAST({hs_cap}, base_score * modifier)) AS healthscore
FROM base_with_ctx;
