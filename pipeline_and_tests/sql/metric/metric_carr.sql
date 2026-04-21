-- metric_carr
--   Ref: specs/03_north_star_metric.md §2 (core formula), D01
--
--   cARR = active_committed_arr × HealthScore (D01 multiplicative form)
--
--   Accounts with no active contract are excluded — the metric is defined
--   only over accounts that have a live commitment on AS_OF_DATE.

CREATE OR REPLACE TABLE metric_carr AS
SELECT
    a.account_id,
    acc.rep_id,
    acc.region,
    acc.segment,
    acc.industry,
    a.n_active_contracts,
    a.active_committed_arr       AS committed_arr,
    h.utilization_u,
    h.m1_share,
    h.base_score,
    h.modifier,
    h.healthscore,
    a.active_committed_arr * h.healthscore AS carr,
    a.contract_age_days,
    a.oldest_active_start,
    DATE '{as_of_date}'          AS as_of_date
FROM int_account_active_contracts a
JOIN metric_healthscore h  USING (account_id)
JOIN stg_accounts       acc USING (account_id);
