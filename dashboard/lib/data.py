"""Thin loaders for the Streamlit dashboard — one place to touch if the
parquet locations move.

The pipeline (pipeline_and_tests/run.py) exports every model as parquet
into DATA_DIR. Mart-level readers use pandas directly; ad-hoc SQL (the
Ask cARR NL agent) uses an in-memory DuckDB with each parquet registered
as a view so the dashboard stays usable offline without BigQuery auth.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "pipeline_and_tests" / "data"

# Tables available to the Ask cARR NL agent (spec 11 §3.1). Keep in sync
# with pipeline_and_tests/run.py::EXPORT_TABLES, but exclude staging
# tables the NL surface shouldn't expose (PII, raw-ish).
ASK_TABLES = [
    "int_orphan_usage",
    "int_account_active_contracts",
    "metric_healthscore", "metric_carr",
    "mart_carr_current", "mart_carr_by_rep",
    "mart_carr_by_region", "mart_dq_summary",
]


@st.cache_data(show_spinner=False)
def load_current() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "mart_carr_current.parquet")


@st.cache_data(show_spinner=False)
def load_by_rep() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "mart_carr_by_rep.parquet")


@st.cache_data(show_spinner=False)
def load_by_region() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "mart_carr_by_region.parquet")


@st.cache_data(show_spinner=False)
def load_dq_summary() -> pd.Series:
    return pd.read_parquet(DATA_DIR / "mart_dq_summary.parquet").iloc[0]


@st.cache_data(show_spinner=False)
def _load_archetypes_impl(source_path: str, source_mtime: float) -> pd.DataFrame:
    """Cached read keyed on (path, mtime) so regen busts the cache."""
    p = Path(source_path)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p)


def load_archetypes() -> pd.DataFrame:
    """Return per-account injected archetype label (what the generator placed).

    Archetype labels are generator provenance / eval ground truth — not a
    warehouse source table. The brief specifies 4 source tables and only
    those 4 sit in `gtm_analytics`. The pipeline snapshots the generator
    CSV into `pipeline_and_tests/data/raw_account_archetypes.parquet` on
    every run, and the dashboard reads from that parquet the same way it
    reads every other mart. Falls back to the generator CSV directly for
    bare-clone runs where the pipeline hasn't been executed yet.

    Cache invalidates when the underlying file's mtime changes, so a
    regen / pipeline rerun is picked up on the next Streamlit rerun
    without requiring a process restart. Raises if neither artifact
    exists rather than silently returning an empty DataFrame — a silent
    empty used to mask the "0 / 1000" archetype-count bug.
    """
    parquet = DATA_DIR / "raw_account_archetypes.parquet"
    if parquet.exists():
        return _load_archetypes_impl(str(parquet), parquet.stat().st_mtime)
    csv = REPO_ROOT / "data_generation" / "output" / "_account_archetypes.csv"
    if csv.exists():
        return _load_archetypes_impl(str(csv), csv.stat().st_mtime)
    raise FileNotFoundError(
        "No archetype source found. Expected either "
        f"{parquet} (pipeline export) or {csv} (generator output). "
        "Run `python pipeline_and_tests/run.py` or "
        "`python data_generation/generate_data.py` first."
    )


def connect() -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB with each mart/int parquet registered as a view.

    Ad-hoc SQL (Ask cARR) runs here — keeps the dashboard working offline
    without hitting BigQuery. A fresh connection per call so Streamlit's
    session reruns stay clean.
    """
    con = duckdb.connect(":memory:")
    for table in ASK_TABLES:
        path = DATA_DIR / f"{table}.parquet"
        if path.exists():
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
    return con


def data_available() -> bool:
    return (DATA_DIR / "mart_carr_current.parquet").exists()
