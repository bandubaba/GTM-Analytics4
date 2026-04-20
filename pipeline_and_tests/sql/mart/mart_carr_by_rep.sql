-- mart_carr_by_rep
--   Ref: specs/07_dashboard_spec.md §5 (rep view)

CREATE OR REPLACE TABLE mart_carr_by_rep AS
SELECT
    r.rep_id,
    r.rep_name,
    r.region,
    r.segment,
    COUNT(m.account_id)                           AS n_accounts,
    SUM(m.committed_arr)                          AS committed_arr,
    SUM(m.carr)                                   AS carr,
    CASE WHEN SUM(m.committed_arr) > 0
         THEN SUM(m.carr) / SUM(m.committed_arr)
         ELSE NULL END                            AS weighted_healthscore,
    SUM(CASE WHEN m.band = 'at_risk_shelfware' THEN 1 ELSE 0 END) AS n_at_risk,
    SUM(CASE WHEN m.band = 'spike_drop'        THEN 1 ELSE 0 END) AS n_spike_drop,
    SUM(CASE WHEN m.band = 'expansion'         THEN 1 ELSE 0 END) AS n_expansion,
    SUM(CASE WHEN m.band = 'ramping'           THEN 1 ELSE 0 END) AS n_ramping
FROM stg_sales_reps r
LEFT JOIN mart_carr_current m USING (rep_id)
GROUP BY 1, 2, 3, 4;
