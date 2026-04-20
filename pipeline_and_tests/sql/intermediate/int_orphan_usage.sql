-- int_orphan_usage
--   Ref: specs/03_north_star_metric.md §3 (orphan handling, D05)
--         specs/05_data_quality.md §A2 (orphan assertion)
--
--   Splits usage into two worlds:
--     - valid: account exists AND date is inside some active contract window
--     - orphan: either account_id unknown, or date outside every contract window
--
--   Orphans are EXCLUDED from the metric (D05) but counted in DQ mart.

CREATE OR REPLACE TABLE int_orphan_usage AS
WITH account_contract_spans AS (
    SELECT account_id, MIN(start_date) AS earliest_start, MAX(end_date) AS latest_end
    FROM stg_contracts
    GROUP BY account_id
),
joined AS (
    SELECT
        u.log_id,
        u.account_id,
        u.usage_date,
        u.credits_consumed,
        a.account_id IS NOT NULL                       AS account_exists,
        s.earliest_start,
        s.latest_end,
        (s.earliest_start IS NOT NULL
            AND u.usage_date BETWEEN s.earliest_start AND s.latest_end) AS within_contract_span
    FROM stg_daily_usage_logs u
    LEFT JOIN stg_accounts a ON u.account_id = a.account_id
    LEFT JOIN account_contract_spans s ON u.account_id = s.account_id
)
SELECT
    log_id,
    account_id,
    usage_date,
    credits_consumed,
    CASE
        WHEN NOT account_exists           THEN 'orphan_bad_account'
        WHEN NOT within_contract_span     THEN 'orphan_out_of_window'
        ELSE 'valid'
    END AS usage_class
FROM joined;
