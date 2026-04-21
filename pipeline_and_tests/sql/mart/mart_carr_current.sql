-- mart_carr_current
--   Ref: specs/07_dashboard_spec.md §4 (exec view), spec 11 §3.2 (narrator needs this)
--
--   Account-level snapshot, one row per active account. Classifies each
--   account into one of five interpretable OUTPUT bands that map 1:1 to
--   the brief's four input anomalies plus a `healthy` baseline:
--
--     at_risk_shelfware  ←  shelfware (HS ≤ 0.55)
--     spike_drop         ←  spike-and-drop (m1_share + contract age)
--     expansion          ←  mid-year expansion (≥2 active + U > 1.0)
--     overage            ←  consistent overage (U > 1.10)
--     healthy            ←  baseline (everything else)
--
--   Orphan / rogue usage (the brief's 5th anomaly) is excluded upstream
--   in int_orphan_usage and never reaches this classifier — see spec
--   02 §5 for why exclusion is the correct handling.

CREATE OR REPLACE TABLE mart_carr_current AS
SELECT
    m.*,
    CASE
      WHEN m.healthscore <= 0.55                                     THEN 'at_risk_shelfware'
      WHEN m.m1_share >= {spike_drop_m1_share}
           AND m.contract_age_days >= {spike_drop_min_age}           THEN 'spike_drop'
      WHEN m.n_active_contracts >= 2 AND m.utilization_u > 1.0       THEN 'expansion'
      WHEN m.utilization_u > 1.10                                    THEN 'overage'
      ELSE 'healthy'
    END AS band
FROM metric_carr m;
