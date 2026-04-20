-- stg_daily_usage_logs
--   Ref: specs/02_data_model.md §2.4 (usage logs)
--   Typed; orphan-flagged in intermediate layer (D05).

CREATE OR REPLACE TABLE stg_daily_usage_logs AS
SELECT
    log_id,
    account_id,
    CAST(date AS DATE) AS usage_date,
    CAST(compute_credits_consumed AS FLOAT64) AS credits_consumed
FROM raw_daily_usage_logs;
