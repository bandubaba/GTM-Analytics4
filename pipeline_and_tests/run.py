"""
Pipeline orchestrator — DuckDB-first, BigQuery-compatible.

Runs dbt-style models in dependency order:
  staging → intermediate → metric → mart

Usage:
  python run.py                     # DuckDB, writes /data/carr.duckdb and parquet exports
  PIPELINE_ENGINE=bigquery python run.py   # TODO(v1.5): route to BQ

Why DuckDB-first:
  - The panel should be able to clone and run without cloud credentials.
  - DuckDB's SQL dialect is close enough to BigQuery that most models
    are portable verbatim; the few divergences are called out in comments.
  - BigQuery path reuses the same .sql files with a thin adapter
    (DATE_SUB / DATE_DIFF shim).

Determinism:
  - All inputs are seeded CSVs from data_generation/.
  - AS_OF_DATE is constant (params.py).
  - No NOW(), CURRENT_DATE(), RANDOM() anywhere in the SQL.
  - A repeat run produces byte-identical parquet (D07 determinism).

Refs:
  specs/04_pipeline_architecture.md §3 (layer order), §5 (idempotency)
"""
from __future__ import annotations

import os
import sys
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


def _render(sql_path: Path) -> str:
    raw = sql_path.read_text()
    return raw.format(
        as_of_date=params.AS_OF_DATE.isoformat(),
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


def _load_raw(con: duckdb.DuckDBPyConnection) -> None:
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

    _load_raw(con)
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

    # Quick sanity print: headline numbers
    summary = con.execute("SELECT * FROM mart_dq_summary").df().iloc[0]
    print("\n[summary]")
    print(f"  accounts in metric       : {summary['n_accounts_in_metric']}")
    print(f"  Committed_ARR (sum)      : ${summary['total_committed_arr']:,.0f}")
    print(f"  cARR (sum)               : ${summary['total_carr']:,.0f}")
    print(f"  weighted HealthScore     : {summary['weighted_healthscore']:.3f}")
    print(f"  at-risk / shelfware accts: {summary['n_shelfware']}")
    print(f"  spike-drop accts         : {summary['n_spike_drop']}")
    print(f"  expansion accts          : {summary['n_expansion']}")
    print(f"  ramping accts            : {summary['n_ramping']}")
    print(f"  healthy accts            : {summary['n_healthy']}")
    print(f"  orphan logs (bad acct)   : {summary['n_orphan_bad_account']}")
    print(f"  orphan logs (out of win) : {summary['n_orphan_out_of_window']}")

    con.close()


def main() -> None:
    engine = os.environ.get("PIPELINE_ENGINE", params.DEFAULT_ENGINE).lower()
    if engine == "duckdb":
        run_duckdb()
    elif engine == "bigquery":
        sys.exit("BigQuery engine is not yet implemented — see specs/04 roadmap. Run with engine=duckdb for now.")
    else:
        sys.exit(f"unknown PIPELINE_ENGINE={engine}")


if __name__ == "__main__":
    main()
