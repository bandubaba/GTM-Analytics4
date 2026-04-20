"""Thin loaders for the Streamlit dashboard — one place to touch if the
parquet locations move."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "pipeline_and_tests" / "data"
DB_PATH = DATA_DIR / "carr.duckdb"


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


def connect(readonly: bool = True) -> duckdb.DuckDBPyConnection:
    """Open a fresh DuckDB connection to the pipeline artifact for ad-hoc queries."""
    return duckdb.connect(str(DB_PATH), read_only=readonly)


def data_available() -> bool:
    return DB_PATH.exists() and (DATA_DIR / "mart_carr_current.parquet").exists()
