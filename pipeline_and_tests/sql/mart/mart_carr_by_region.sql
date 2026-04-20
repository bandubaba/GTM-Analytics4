-- mart_carr_by_region
--   Ref: specs/07_dashboard_spec.md §4 (exec view)

CREATE OR REPLACE TABLE mart_carr_by_region AS
SELECT
    region,
    segment,
    COUNT(*)                              AS n_accounts,
    SUM(committed_arr)                    AS committed_arr,
    SUM(carr)                             AS carr,
    CASE WHEN SUM(committed_arr) > 0
         THEN SUM(carr) / SUM(committed_arr)
         ELSE NULL END                    AS weighted_healthscore,
    SUM(CASE WHEN band = 'at_risk_shelfware' THEN 1 ELSE 0 END) AS n_at_risk
FROM mart_carr_current
GROUP BY 1, 2
ORDER BY carr DESC;
