-- mart_dq_summary
--   Ref: specs/05_data_quality.md (DQ catalog), D05 (orphans excluded + reported)
--
--   Single-row summary of data-quality counts for the dashboard's DQ panel.

CREATE OR REPLACE TABLE mart_dq_summary AS
SELECT
    (SELECT COUNT(*) FROM raw_sales_reps)                                            AS n_reps,
    (SELECT COUNT(*) FROM raw_accounts)                                              AS n_accounts,
    (SELECT COUNT(*) FROM raw_contracts)                                             AS n_contracts,
    (SELECT COUNT(*) FROM raw_daily_usage_logs)                                      AS n_usage_logs,
    (SELECT COUNT(*) FROM int_account_active_contracts)                              AS n_accounts_with_active_contract,
    (SELECT COUNT(*) FROM mart_carr_current)                                         AS n_accounts_in_metric,
    (SELECT COUNT(*) FROM int_orphan_usage WHERE usage_class = 'orphan_bad_account')   AS n_orphan_bad_account,
    (SELECT COUNT(*) FROM int_orphan_usage WHERE usage_class = 'orphan_out_of_window') AS n_orphan_out_of_window,
    (SELECT SUM(credits_consumed) FROM int_orphan_usage WHERE usage_class <> 'valid') AS orphan_credits_total,
    (SELECT COUNT(*) FROM mart_carr_current WHERE band = 'at_risk_shelfware')         AS n_shelfware,
    (SELECT COUNT(*) FROM mart_carr_current WHERE band = 'spike_drop')                AS n_spike_drop,
    (SELECT COUNT(*) FROM mart_carr_current WHERE band = 'expansion')                 AS n_expansion,
    (SELECT COUNT(*) FROM mart_carr_current WHERE band = 'ramping')                   AS n_ramping,
    (SELECT COUNT(*) FROM mart_carr_current WHERE band = 'healthy')                   AS n_healthy,
    (SELECT SUM(committed_arr) FROM mart_carr_current)                                AS total_committed_arr,
    (SELECT SUM(carr) FROM mart_carr_current)                                         AS total_carr,
    CASE WHEN (SELECT SUM(committed_arr) FROM mart_carr_current) > 0
         THEN (SELECT SUM(carr) FROM mart_carr_current)
              / (SELECT SUM(committed_arr) FROM mart_carr_current)
         ELSE NULL END                                                                AS weighted_healthscore,
    DATE '{as_of_date}'                                                               AS as_of_date;
