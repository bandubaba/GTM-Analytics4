-- stg_sales_reps
--   Ref: specs/02_data_model.md §2.1 (reps table)
--   Typed + trimmed source for downstream joins.

CREATE OR REPLACE TABLE stg_sales_reps AS
SELECT
    CAST(rep_id    AS VARCHAR) AS rep_id,
    CAST(name      AS VARCHAR) AS rep_name,
    CAST(region    AS VARCHAR) AS region,
    CAST(segment   AS VARCHAR) AS segment
FROM raw_sales_reps;
