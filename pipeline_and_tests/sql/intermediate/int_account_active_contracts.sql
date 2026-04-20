-- int_account_active_contracts
--   Ref: specs/03_north_star_metric.md §3.7 (renewal semantics, overlapping),
--         D04 (overlap accumulates), D12 (contract_age = oldest active)
--
--   Per account, as of AS_OF_DATE:
--     - active_committed_arr         = SUM of annual_commit_dollars over active contracts
--     - included_monthly_credits     = SUM of included_monthly_credits over active contracts
--     - n_active_contracts
--     - oldest_active_start          = MIN(start_date) across active contracts
--     - contract_age_days            = DATE_DIFF(as_of, oldest_active_start)
--                                      (gaming-resistant per D12)

CREATE OR REPLACE TABLE int_account_active_contracts AS
SELECT
    account_id,
    COUNT(*)                                      AS n_active_contracts,
    SUM(annual_commit_dollars)                    AS active_committed_arr,
    SUM(included_monthly_credits)                 AS included_monthly_credits,
    MIN(start_date)                               AS oldest_active_start,
    DATE_DIFF(DATE '{as_of_date}', MIN(start_date), DAY) AS contract_age_days
FROM stg_contracts
WHERE is_active_as_of = TRUE
GROUP BY account_id;
