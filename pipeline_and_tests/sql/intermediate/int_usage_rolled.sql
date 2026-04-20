-- int_usage_rolled
--   Ref: specs/03_north_star_metric.md §2.1 (U = actual / expected over 90d),
--         §3 (spike-drop detection uses M1 share)
--
--   Trailing-90d metrics per account (orphans excluded, D05):
--     - credits_90d           = sum of valid credits in the 90d window
--     - credits_month_1       = sum in the earliest 30d of that window
--                               (used for spike-drop M1 share)
--     - expected_credits_90d  = included_monthly_credits × 3 (spec 03 §2.1)
--     - utilization_u         = credits_90d / expected_credits_90d

CREATE OR REPLACE TABLE int_usage_rolled AS
WITH window_bounds AS (
    SELECT
        DATE '{as_of_date}'                                       AS as_of_date,
        DATE '{as_of_date}' - INTERVAL '{trailing_window_days}' DAY AS window_start
),
valid_usage AS (
    SELECT u.*
    FROM int_orphan_usage u, window_bounds w
    WHERE u.usage_class = 'valid'
      AND u.usage_date > w.window_start
      AND u.usage_date <= w.as_of_date
),
rolled AS (
    SELECT
        v.account_id,
        SUM(v.credits_consumed)                                           AS credits_90d,
        SUM(CASE
              WHEN v.usage_date > (DATE '{as_of_date}' - INTERVAL '{trailing_window_days}' DAY)
               AND v.usage_date <= (DATE '{as_of_date}' - INTERVAL '{trailing_window_days}' DAY + INTERVAL 30 DAY)
              THEN v.credits_consumed ELSE 0
            END)                                                          AS credits_month_1
    FROM valid_usage v
    GROUP BY v.account_id
)
SELECT
    a.account_id,
    COALESCE(r.credits_90d,     0)   AS credits_90d,
    COALESCE(r.credits_month_1, 0)   AS credits_month_1,
    -- expected = included_monthly_credits × 3 (3 months in 90d)
    a.included_monthly_credits * 3   AS expected_credits_90d,
    CASE
      WHEN a.included_monthly_credits IS NULL OR a.included_monthly_credits = 0 THEN NULL
      ELSE COALESCE(r.credits_90d, 0) / (a.included_monthly_credits * 3.0)
    END                              AS utilization_u,
    CASE
      WHEN COALESCE(r.credits_90d, 0) = 0 THEN NULL
      ELSE COALESCE(r.credits_month_1, 0) / NULLIF(r.credits_90d, 0)
    END                              AS m1_share
FROM int_account_active_contracts a
LEFT JOIN rolled r USING (account_id);
