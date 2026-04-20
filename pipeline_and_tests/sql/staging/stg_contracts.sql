-- stg_contracts
--   Ref: specs/02_data_model.md §2.3 (contracts)
--   Typed + adds derived columns (is_active_as_of, contract_age_days).

CREATE OR REPLACE TABLE stg_contracts AS
SELECT
    contract_id,
    account_id,
    CAST(start_date AS DATE) AS start_date,
    CAST(end_date   AS DATE) AS end_date,
    CAST(annual_commit_dollars AS FLOAT64) AS annual_commit_dollars,
    CAST(included_monthly_compute_credits AS INT64) AS included_monthly_credits,
    -- Active means AS_OF_DATE falls within [start_date, end_date] inclusive.
    (CAST(start_date AS DATE) <= DATE '{as_of_date}'
        AND DATE '{as_of_date}' <= CAST(end_date AS DATE)) AS is_active_as_of,
    -- Days elapsed since this specific contract started (signed; negative for future starts).
    DATE_DIFF(DATE '{as_of_date}', CAST(start_date AS DATE), DAY) AS contract_age_days
FROM raw_contracts;
