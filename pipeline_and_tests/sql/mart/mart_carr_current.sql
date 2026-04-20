-- mart_carr_current
--   Ref: specs/07_dashboard_spec.md §4 (exec view), spec 11 §3.2 (narrator needs this)
--
--   Account-level snapshot, one row per active account.
--   Classifies each account into an interpretable band for the anomaly narrator.

CREATE OR REPLACE TABLE mart_carr_current AS
SELECT
    m.*,
    CASE
      WHEN m.healthscore <= 0.55                                     THEN 'at_risk_shelfware'
      WHEN m.m1_share >= {spike_drop_m1_share}
           AND m.contract_age_days >= {spike_drop_min_age}           THEN 'spike_drop'
      WHEN m.n_active_contracts >= 2 AND m.utilization_u > 1.0       THEN 'expansion'
      WHEN m.utilization_u > 1.10                                    THEN 'overage'
      WHEN m.ramp_w < 1.0                                            THEN 'ramping'
      WHEN m.healthscore BETWEEN 0.85 AND 1.15                       THEN 'healthy'
      ELSE 'mixed'
    END AS band
FROM metric_carr m;
