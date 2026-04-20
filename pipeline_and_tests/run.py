"""
Pipeline orchestrator — runs the 13 SQL models against BigQuery (the
warehouse called out in the brief) and exports each table as parquet
under pipeline_and_tests/data/ for the DQ suite, eval harness, and
dashboard to read locally.

Two-dataset layering (matches the brief's scoping):
  - BQ_SOURCE_DATASET (default: gtm_analytics)
      The 4 source tables from the brief — sales_reps, accounts,
      contracts, daily_usage_logs. Populated by
      data_generation/upload_to_bq.py; never mutated by run.py.
  - BQ_WAREHOUSE_DATASET (default: gtm_metric)
      All pipeline outputs — raw_* bridge views, stg_*, int_*,
      metric_*, mart_*. Rebuilt on every run.

Usage:
    gcloud auth application-default login              # one-time
    python data_generation/generate_data.py            # 1. seeded CSVs
    GOOGLE_CLOUD_PROJECT=<proj> \
      python data_generation/upload_to_bq.py           # 2. load BQ
    GOOGLE_CLOUD_PROJECT=<proj> \
      python pipeline_and_tests/run.py                 # 3. 13 models + parquet

Determinism:
  - All inputs are seeded CSVs from data_generation/.
  - AS_OF_DATE is constant (params.py).
  - No NOW(), CURRENT_DATE(), RANDOM() in any model.
  - Window bounds (window_start, m1_end) precomputed in Python and
    passed in as DATE literals, avoiding INTERVAL arithmetic.

Refs:
  specs/04_pipeline_architecture.md §3 (layer order), §5 (idempotency)
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

import params

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = REPO_ROOT / "pipeline_and_tests"
SQL_ROOT = PIPELINE_ROOT / "sql"
DATA_OUT = PIPELINE_ROOT / "data"

MODEL_ORDER = [
    # staging
    "staging/stg_sales_reps.sql",
    "staging/stg_accounts.sql",
    "staging/stg_contracts.sql",
    "staging/stg_daily_usage_logs.sql",
    # intermediate
    "intermediate/int_orphan_usage.sql",
    "intermediate/int_account_active_contracts.sql",
    "intermediate/int_usage_rolled.sql",
    # metric
    "metric/metric_healthscore.sql",
    "metric/metric_carr.sql",
    # mart
    "mart/mart_carr_current.sql",
    "mart/mart_carr_by_rep.sql",
    "mart/mart_carr_by_region.sql",
    "mart/mart_dq_summary.sql",
]

# Every pipeline-produced table is exported to parquet so that
# dq/run_dq.py, evals/run_evals.py, and the dashboard can read locally
# without hitting BQ on every question.
EXPORT_TABLES = [
    "stg_sales_reps", "stg_accounts", "stg_contracts", "stg_daily_usage_logs",
    "int_orphan_usage", "int_account_active_contracts", "int_usage_rolled",
    "metric_healthscore", "metric_carr",
    "mart_carr_current", "mart_carr_by_rep", "mart_carr_by_region", "mart_dq_summary",
]

# BQ upload lands CSVs under these (unprefixed) table names. The SQL
# models reference `raw_*`, so we create thin views at the top of the
# run to bridge the naming without mutating the source dataset.
BQ_RAW_VIEWS = {
    "raw_sales_reps":       "sales_reps",
    "raw_accounts":         "accounts",
    "raw_contracts":        "contracts",
    "raw_daily_usage_logs": "daily_usage_logs",
}


def _render(sql_path: Path) -> str:
    raw = sql_path.read_text()
    window_start = params.AS_OF_DATE - timedelta(days=params.TRAILING_WINDOW_DAYS)
    m1_end = window_start + timedelta(days=30)
    return raw.format(
        as_of_date=params.AS_OF_DATE.isoformat(),
        window_start=window_start.isoformat(),
        m1_end=m1_end.isoformat(),
        trailing_window_days=params.TRAILING_WINDOW_DAYS,
        hs_floor=params.HS_FLOOR,
        hs_cap=params.HS_CAP,
        shelfware_u_max=params.SHELFWARE_U_MAX,
        healthy_u_min=params.HEALTHY_U_MIN,
        healthy_u_max=params.HEALTHY_U_MAX,
        expansion_u_bonus_cap=params.EXPANSION_U_BONUS_CAP,
        spike_drop_m1_share=params.SPIKE_DROP_M1_SHARE,
        spike_drop_min_age=params.SPIKE_DROP_MIN_AGE_DAYS,
        spike_drop_modifier=params.SPIKE_DROP_MODIFIER,
        expansion_modifier=params.EXPANSION_MODIFIER,
        ent_ramp_full=params.RAMP_PARAMS["Enterprise"]["ramp_full"],
        ent_ramp_end=params.RAMP_PARAMS["Enterprise"]["ramp_end"],
        mm_ramp_full=params.RAMP_PARAMS["Mid-Market"]["ramp_full"],
        mm_ramp_end=params.RAMP_PARAMS["Mid-Market"]["ramp_end"],
    )


def _fetch_df(client, sql: str) -> pd.DataFrame:
    """Pull a BQ result into a parquet-safe pandas frame.

    BQ's dataframe returns DATE columns as the `dbdate` extension dtype,
    which pyarrow cannot round-trip through parquet without db-dtypes
    installed in every reader. Downstream (evals, dashboard) we want
    plain native dates.
    """
    df = client.query(sql).result().to_dataframe()
    for col in df.columns:
        if str(df[col].dtype) == "dbdate":
            df[col] = pd.to_datetime(df[col]).dt.date
    return df


def main() -> None:
    try:
        from google.cloud import bigquery
    except ImportError:
        sys.exit("ERROR: google-cloud-bigquery not installed. pip install -r pipeline_and_tests/requirements.txt")

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        sys.exit("ERROR: set GOOGLE_CLOUD_PROJECT env var to your BQ project id.")
    src_ds = os.environ.get("BQ_SOURCE_DATASET",
                            os.environ.get("BQ_DATASET", "gtm_analytics"))
    wh_ds = os.environ.get("BQ_WAREHOUSE_DATASET", "gtm_metric")
    location = os.environ.get("BQ_LOCATION", "US")

    client = bigquery.Client(project=project, location=location)
    src_ref = f"`{project}.{src_ds}`"
    wh_ref  = f"`{project}.{wh_ds}`"
    print(f"[pipeline] project={project}  location={location}")
    print(f"[pipeline] source dataset   : {src_ds}  (4 brief-spec tables)")
    print(f"[pipeline] warehouse dataset: {wh_ds}   (pipeline outputs)")
    print(f"[pipeline] as_of={params.AS_OF_DATE}  trailing={params.TRAILING_WINDOW_DAYS}d")

    # Ensure the warehouse dataset exists.
    try:
        client.get_dataset(f"{project}.{wh_ds}")
    except Exception:
        ds = bigquery.Dataset(f"{project}.{wh_ds}")
        ds.location = location
        ds.description = "cARR pipeline outputs — stg/int/metric/mart. Rebuilt by pipeline_and_tests/run.py."
        client.create_dataset(ds)
        print(f"[pipeline] created warehouse dataset {wh_ds}")

    # All unqualified table references in the .sql files resolve against
    # the warehouse dataset via default_dataset.
    def _exec(sql: str, label: str) -> None:
        job_config = bigquery.QueryJobConfig(
            default_dataset=bigquery.DatasetReference(project, wh_ds)
        )
        try:
            client.query(sql, job_config=job_config).result()
        except Exception as exc:
            print(f"\n!!! FAILED: {label}\n{exc}")
            print("---\nRendered SQL:\n" + sql)
            raise

    # raw_* bridge views live in the warehouse but point at the SOURCE
    # dataset's 4 brief-spec tables. This keeps the source dataset
    # unmodified by the pipeline.
    for view, src in BQ_RAW_VIEWS.items():
        _exec(
            f"CREATE OR REPLACE VIEW {wh_ref}.{view} AS "
            f"SELECT * FROM {src_ref}.{src}",
            f"bridge view {view} → {src_ds}.{src}",
        )
    print(f"[pipeline] bridged raw views in {wh_ds}: {', '.join(BQ_RAW_VIEWS.keys())}")

    for rel_path in MODEL_ORDER:
        sql = _render(SQL_ROOT / rel_path)
        _exec(sql, rel_path)
        print(f"[model ok] {rel_path}")

    DATA_OUT.mkdir(parents=True, exist_ok=True)
    for table in EXPORT_TABLES:
        df = _fetch_df(client, f"SELECT * FROM {wh_ref}.{table}")
        parquet_path = DATA_OUT / f"{table}.parquet"
        df.to_parquet(parquet_path, index=False)
        print(f"[export]   {table:<32} rows={len(df):>6}  →  {parquet_path.name}")

    summary = _fetch_df(client, f"SELECT * FROM {wh_ref}.mart_dq_summary").iloc[0]
    print("\n[summary]")
    print(f"  accounts in metric       : {summary['n_accounts_in_metric']}")
    print(f"  Committed_ARR (sum)      : ${float(summary['total_committed_arr']):,.0f}")
    print(f"  cARR (sum)               : ${float(summary['total_carr']):,.0f}")
    print(f"  weighted HealthScore     : {float(summary['weighted_healthscore']):.3f}")
    print(f"  at-risk / shelfware accts: {summary['n_shelfware']}")
    print(f"  spike-drop accts         : {summary['n_spike_drop']}")
    print(f"  expansion accts          : {summary['n_expansion']}")
    print(f"  ramping accts            : {summary['n_ramping']}")
    print(f"  healthy accts            : {summary['n_healthy']}")
    print(f"  orphan logs (bad acct)   : {summary['n_orphan_bad_account']}")
    print(f"  orphan logs (out of win) : {summary['n_orphan_out_of_window']}")


if __name__ == "__main__":
    main()
