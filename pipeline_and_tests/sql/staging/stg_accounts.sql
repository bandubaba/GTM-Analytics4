-- stg_accounts
--   Ref: specs/02_data_model.md §2.2 (accounts)
--   Brings segment/region from the owning rep onto the account.

CREATE OR REPLACE TABLE stg_accounts AS
SELECT
    a.account_id,
    a.company_name,
    a.industry,
    a.rep_id,
    r.region,
    r.segment
FROM raw_accounts a
LEFT JOIN stg_sales_reps r USING (rep_id);
