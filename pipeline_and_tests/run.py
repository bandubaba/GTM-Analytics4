"""
Pipeline orchestrator — runs the same 13 SQL models against either
BigQuery (the warehouse called out in the assignment brief) or DuckDB
(a local mirror for reviewers without a GCP project).

Both engines produce identical numbers. The SQL is written once; a thin
dialect adapter in _translate_to_bq() rewrites the couple of places
where DuckDB and BigQuery disagree (DATE_DIFF arg order, DOUBLE alias).

Usage:
  # DuckDB (local, no cloud creds needed):
  python run.py
  PIPELINE_ENGINE=duckdb python run.py

  # BigQuery (the primary path — dataset already uploaded by
  # data_generation/upload_to_bq.py):
  GOOGLE_CLOUD_PROJECT=... PIPELINE_ENGINE=bigquery python run.py
  #   optional: BQ_DATASET=gtm_analytics (default), BQ_LOCATION=US (default)

Determinism (both engines):
  - All inputs are seeded CSVs from data_generation/.
  - AS_OF_DATE is constant (params.py).
  - No NOW(), CURRENT_DATE(), RANDOM() anywhere in the SQL.
  - Window bounds are precomputed in Python so the SQL is dialect-neutral.

Refs:
  specs/04_pipeline_architecture.md §3 (layer order), §5 (idempotency)
"""
from __future__ import annotations

import os
import re
import sys
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd

import params

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = REPO_ROOT / "pipeline_and_tests"
SQL_ROOT = PIPELINE_ROOT / "sql"
DATA_OUT = PIPELINE_ROOT / "data"
RAW_ROOT = REPO_ROOT / "data_generation" / "output"

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

EXPORT_MARTS = [
    "mart_carr_current",
    "mart_carr_by_rep",
    "mart_carr_by_region",
    "mart_dq_summary",
]

# BQ upload lands CSVs under these (unprefixed) table names. The SQL
# models reference `raw_*`, so in BQ mode we create thin views at the
# top of the run to bridge the naming.
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


# ---------- dialect adapter ----------------------------------------------

_DATE_DIFF_DUCKDB_RE = re.compile(
    r"DATE_DIFF\(\s*'day'\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
    flags=re.IGNORECASE | re.DOTALL,
)


def _translate_to_bq(sql: str) -> str:
    """Rewrite the handful of DuckDB-isms that BigQuery rejects.

    1. DATE_DIFF('day', start, end)  →  DATE_DIFF(end, start, DAY)
       (BigQuery reverses arg order and takes a date-part keyword, not a string.)
    2. CAST(x AS DOUBLE)             →  CAST(x AS FLOAT64)
    3. CAST(x AS VARCHAR)            →  CAST(x AS STRING)
    4. CAST(x AS BIGINT)             →  CAST(x AS INT64)
       (BigQuery uses its own scalar type names; DuckDB follows the SQL-92 ones.)

    Interval arithmetic diverges too, but we sidestep it by precomputing
    window_start / m1_end in Python (see int_usage_rolled.sql).
    """
    sql = _DATE_DIFF_DUCKDB_RE.sub(r"DATE_DIFF(\2, \1, DAY)", sql)
    sql = re.sub(r"\bAS DOUBLE\b",  "AS FLOAT64", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bAS VARCHAR\b", "AS STRING",  sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bAS BIGINT\b",  "AS INT64",   sql, flags=re.IGNORECASE)
    return sql


# ---------- DuckDB engine ------------------------------------------------

def _load_raw_duckdb(con: duckdb.DuckDBPyConnection) -> None:
    """Bind CSVs as raw_* tables."""
    tables = {
        "raw_sales_reps":       RAW_ROOT / "sales_reps.csv",
        "raw_accounts":         RAW_ROOT / "accounts.csv",
        "raw_contracts":        RAW_ROOT / "contracts.csv",
        "raw_daily_usage_logs": RAW_ROOT / "daily_usage_logs.csv",
    }
    for table, path in tables.items():
        if not path.exists():
            sys.exit(f"ERROR: raw input missing: {path}\nRun data_generation/generate_data.py first.")
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')")


def run_duckdb() -> None:
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    db_path = DATA_OUT / "carr.duckdb"
    if db_path.exists():
        db_path.unlink()  # fresh build; D07 determinism makes this safe

    con = duckdb.connect(str(db_path))
    print(f"[pipeline] engine=duckdb db={db_path}")
    print(f"[pipeline] as_of={params.AS_OF_DATE}  trailing={params.TRAILING_WINDOW_DAYS}d")

    _load_raw_duckdb(con)
    print(f"[pipeline] loaded raw tables from {RAW_ROOT}")

    for rel_path in MODEL_ORDER:
        sql = _render(SQL_ROOT / rel_path)
        try:
            con.execute(sql)
        except Exception as exc:
            print(f"\n!!! FAILED: {rel_path}\n{exc}")
            print("---\nRendered SQL:\n" + sql)
            raise
        print(f"[model ok] {rel_path}")

    for mart in EXPORT_MARTS:
        df = con.execute(f"SELECT * FROM {mart}").df()
        parquet_path = DATA_OUT / f"{mart}.parquet"
        df.to_parquet(parquet_path, index=False)
        print(f"[export]   {mart:<28} rows={len(df):>6}  →  {parquet_path.name}")

    summary = con.execute("SELECT * FROM mart_dq_summary").df().iloc[0]
    _print_summary(summary)

    con.close()


# ---------- BigQuery engine ---------------------------------------------

def run_bigquery() -> None:
    """Execute the same 13 models against BigQuery.

    Two-dataset layering (matches the brief's scoping):
      - BQ_SOURCE_DATASET  — exactly the 4 source tables from the brief
                             (sales_reps, accounts, contracts, daily_usage_logs).
                             Populated by data_generation/upload_to_bq.py.
      - BQ_WAREHOUSE_DATASET — everything the pipeline produces
                               (raw_* bridge views, stg_*, int_*, metric_*, mart_*).
                               Kept separate so the source dataset stays
                               the 4-table deliverable the brief asks for.

    Prereqs (one-time):
      1. `gcloud auth application-default login`
      2. `GOOGLE_CLOUD_PROJECT=... python data_generation/upload_to_bq.py`
         loads the 4 CSVs into {project}.{BQ_SOURCE_DATASET}.
    """
    try:
        from google.cloud import bigquery
    except ImportError:
        sys.exit("ERROR: google-cloud-bigquery not installed. pip install -r requirements.txt")

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        sys.exit("ERROR: set GOOGLE_CLOUD_PROJECT env var to your BQ project id.")
    # Source: where upload_to_bq.py landed the 4 raw tables. Still named
    # BQ_DATASET for backward-compat with the upload script's env var.
    src_ds = os.environ.get("BQ_SOURCE_DATASET",
                            os.environ.get("BQ_DATASET", "gtm_analytics"))
    # Warehouse: where the pipeline writes stg/int/metric/mart.
    wh_ds = os.environ.get("BQ_WAREHOUSE_DATASET", "gtm_metric")
    location = os.environ.get("BQ_LOCATION", "US")

    client = bigquery.Client(project=project, location=location)
    src_ref = f"`{project}.{src_ds}`"
    wh_ref  = f"`{project}.{wh_ds}`"
    print(f"[pipeline] engine=bigquery project={project}  location={location}")
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
        sql = _translate_to_bq(_render(SQL_ROOT / rel_path))
        _exec(sql, rel_path)
        print(f"[model ok] {rel_path}")

    DATA_OUT.mkdir(parents=True, exist_ok=True)
    for mart in EXPORT_MARTS:
        df = _fetch_df(client, f"SELECT * FROM {wh_ref}.{mart}")
        parquet_path = DATA_OUT / f"{mart}.parquet"
        df.to_parquet(parquet_path, index=False)
        print(f"[export]   {mart:<28} rows={len(df):>6}  →  {parquet_path.name}")

    summary = _fetch_df(client, f"SELECT * FROM {wh_ref}.mart_dq_summary").iloc[0]
    _print_summary(summary)


def _fetch_df(client, sql: str) -> pd.DataFrame:
    """Pull a BQ result into a parquet-safe pandas frame.

    BQ's dataframe returns DATE columns as the `dbdate` extension dtype,
    which pyarrow cannot round-trip through parquet without db-dtypes
    installed in every reader. Downstream (evals/dashboard) we want plain
    native dates, matching what the DuckDB path writes.
    """
    df = client.query(sql).result().to_dataframe()
    for col in df.columns:
        if str(df[col].dtype) == "dbdate":
            df[col] = pd.to_datetime(df[col]).dt.date
    return df


# ---------- shared helpers ----------------------------------------------

def _print_summary(summary: pd.Series) -> None:
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


def main() -> None:
    engine = os.environ.get("PIPELINE_ENGINE", params.DEFAULT_ENGINE).lower()
    if engine == "duckdb":
        run_duckdb()
    elif engine == "bigquery":
        run_bigquery()
    else:
        sys.exit(f"unknown PIPELINE_ENGINE={engine}")


if __name__ == "__main__":
    main()
