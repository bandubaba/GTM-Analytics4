"""
Data quality assertion suite — implements a subset of specs/05_data_quality.md.

Two severity tiers:
    block   — pipeline MUST stop; non-zero exit. A block failure means
              the downstream metric cannot be trusted.
    warn    — pipeline continues; surfaced in the dashboard DQ panel.
              A warn failure means the metric is computable but a
              human should look.

Each assertion is a pure SQL predicate evaluated against the parquet
exports in pipeline_and_tests/data/ (written by run.py). Uses an
in-memory DuckDB to run SQL over the parquet files locally so the DQ
suite doesn't have to hit BigQuery on every run.

Usage:
    python dq/run_dq.py
    python dq/run_dq.py --strict     # warn failures also exit non-zero
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "pipeline_and_tests" / "data"

# Tables the assertions below reference — must match run.py's EXPORT_TABLES.
REQUIRED_TABLES = [
    "stg_sales_reps", "stg_accounts", "stg_contracts", "stg_daily_usage_logs",
    "int_orphan_usage", "int_account_active_contracts",
    "metric_healthscore", "metric_carr",
    "mart_carr_current", "mart_carr_by_rep",
]


@dataclass
class Assertion:
    id: str
    name: str
    severity: str           # block | warn
    sql: str                # expected to return a single integer; 0 means pass
    explain: str            # plain-English failure interpretation


ASSERTIONS: list[Assertion] = [
    # ---- uniqueness (spec 05 §3.1) ------------------------------------
    Assertion(
        "A01", "rep_id is unique", "block",
        "SELECT COUNT(*) - COUNT(DISTINCT rep_id) FROM stg_sales_reps",
        "duplicate rep_id — breaks rep-level aggregation",
    ),
    Assertion(
        "A02", "account_id is unique", "block",
        "SELECT COUNT(*) - COUNT(DISTINCT account_id) FROM stg_accounts",
        "duplicate account_id — would double-count commit",
    ),
    Assertion(
        "A03", "contract_id is unique", "block",
        "SELECT COUNT(*) - COUNT(DISTINCT contract_id) FROM stg_contracts",
        "duplicate contract_id — breaks D04 accumulation",
    ),
    Assertion(
        "A04", "log_id is unique", "block",
        "SELECT COUNT(*) - COUNT(DISTINCT log_id) FROM stg_daily_usage_logs",
        "duplicate log_id — inflates utilization",
    ),

    # ---- referential integrity (spec 05 §3.2) -------------------------
    Assertion(
        "A05", "every account references a valid rep", "block",
        """SELECT COUNT(*) FROM stg_accounts a
           LEFT JOIN stg_sales_reps r USING (rep_id)
           WHERE r.rep_id IS NULL""",
        "account with dangling rep_id — rep view breaks",
    ),
    Assertion(
        "A06", "every contract references a valid account", "block",
        """SELECT COUNT(*) FROM stg_contracts c
           LEFT JOIN stg_accounts a USING (account_id)
           WHERE a.account_id IS NULL""",
        "contract for unknown account — commit will be orphaned",
    ),

    # ---- value sanity (spec 05 §3.3) ----------------------------------
    Assertion(
        "A07", "annual_commit_dollars is non-negative", "block",
        "SELECT COUNT(*) FROM stg_contracts WHERE annual_commit_dollars < 0",
        "negative commit — would produce negative cARR",
    ),
    Assertion(
        "A08", "included_monthly_credits is non-negative", "block",
        "SELECT COUNT(*) FROM stg_contracts WHERE included_monthly_credits < 0",
        "negative included credits — utilization denominator sign-flipped",
    ),
    Assertion(
        "A09", "contract end_date ≥ start_date", "block",
        "SELECT COUNT(*) FROM stg_contracts WHERE end_date < start_date",
        "end before start — active-contract logic silently excludes these",
    ),
    Assertion(
        "A10", "credits_consumed is non-negative", "block",
        "SELECT COUNT(*) FROM stg_daily_usage_logs WHERE credits_consumed < 0",
        "negative usage — masks a real accounting bug upstream",
    ),

    # ---- metric health (spec 05 §3.4) ---------------------------------
    Assertion(
        "A11", "HealthScore within [0.40, 1.30]", "block",
        "SELECT COUNT(*) FROM metric_healthscore WHERE healthscore < 0.40 OR healthscore > 1.30 + 1e-9",
        "out-of-bound HS — D02 violated; comp-unsafe",
    ),
    Assertion(
        "A12", "cARR equals Committed_ARR × HealthScore", "block",
        """SELECT COUNT(*) FROM metric_carr
           WHERE ABS(carr - committed_arr * healthscore) > 1e-6""",
        "D01 formula violated — metric definition and mart disagree",
    ),

    # ---- warn-tier ----------------------------------------------------
    Assertion(
        "A13", "orphan rate below 5% of usage logs", "warn",
        """SELECT CASE
             WHEN (SELECT COUNT(*) FROM int_orphan_usage) = 0 THEN 0
             WHEN (SELECT COUNT(*) FROM int_orphan_usage WHERE usage_class <> 'valid') * 1.0
                  / (SELECT COUNT(*) FROM int_orphan_usage) > 0.05 THEN 1
             ELSE 0 END""",
        "orphan rate > 5% — look for ingestion drift or schema rename",
    ),
    Assertion(
        "A14", "at least 50% of accounts have an active contract as of AS_OF_DATE", "warn",
        """SELECT CASE
             WHEN (SELECT COUNT(*) FROM stg_accounts) = 0 THEN 1
             WHEN (SELECT COUNT(*) FROM int_account_active_contracts) * 1.0
                  / (SELECT COUNT(*) FROM stg_accounts) < 0.50 THEN 1
             ELSE 0 END""",
        "low active coverage — snapshot date may be misaligned with contract calendar",
    ),
    Assertion(
        "A15", "shelfware rate within 5-25% band", "warn",
        """SELECT CASE
             WHEN (SELECT COUNT(*) FROM mart_carr_current) = 0 THEN 1
             WHEN (SELECT COUNT(*) FROM mart_carr_current WHERE band = 'at_risk_shelfware') * 1.0
                  / (SELECT COUNT(*) FROM mart_carr_current) NOT BETWEEN 0.05 AND 0.25 THEN 1
             ELSE 0 END""",
        "shelfware share outside expected band — either the metric is off or the book shifted",
    ),
    Assertion(
        "A16", "no rep concentrates > 30% of total cARR", "warn",
        """SELECT CASE
             WHEN (SELECT MAX(carr) / NULLIF(SUM(carr), 0) FROM mart_carr_by_rep) > 0.30 THEN 1
             ELSE 0 END""",
        "one rep dominates cARR — comp safety risk, manual review",
    ),
]


def _connect_parquet() -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB and register each pipeline parquet as a view."""
    con = duckdb.connect(":memory:")
    for table in REQUIRED_TABLES:
        path = DATA_DIR / f"{table}.parquet"
        if not path.exists():
            sys.exit(f"ERROR: {path} missing. Run `python pipeline_and_tests/run.py` first.")
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
    return con


def run(strict: bool = False) -> int:
    con = _connect_parquet()

    block_fails: list[Assertion] = []
    warn_fails: list[Assertion] = []

    print(f"[dq] running {len(ASSERTIONS)} assertions against {DATA_DIR}\n")
    for a in ASSERTIONS:
        count = con.execute(a.sql).fetchone()[0]
        passed = count == 0
        mark = "PASS" if passed else ("BLOCK" if a.severity == "block" else "WARN")
        print(f"[{mark:<5}] {a.id}  {a.name}")
        if not passed:
            print(f"         └─ {a.explain}  (count={count})")
            (block_fails if a.severity == "block" else warn_fails).append(a)

    con.close()

    print()
    print(f"[dq] pass={len(ASSERTIONS) - len(block_fails) - len(warn_fails)}  block={len(block_fails)}  warn={len(warn_fails)}")
    if block_fails:
        print("[dq] STOP: block-tier DQ failure. Pipeline output is not comp-safe.")
        return 1
    if warn_fails and strict:
        print("[dq] STOP: warn-tier DQ failure under --strict.")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strict", action="store_true", help="exit non-zero on warn failures too")
    args = p.parse_args()
    return run(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
