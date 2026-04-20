# Pipeline & tests

Implements the cARR pipeline from [`../specs/04_pipeline_architecture.md`](../specs/04_pipeline_architecture.md),
the DQ catalog from [`../specs/05_data_quality.md`](../specs/05_data_quality.md),
and the eval framework from [`../specs/06_evaluation_framework.md`](../specs/06_evaluation_framework.md).

## What's in here

```
pipeline_and_tests/
├── params.py                   Parameters (ref specs/03 §6). Changing a value
│                               here without amending the spec breaks the contract.
├── run.py                      Orchestrator — DuckDB-first (reviewer-friendly);
│                               BigQuery engine reserved for v1.5.
├── sql/
│   ├── staging/                4 typed mirrors of the raw CSVs
│   ├── intermediate/           orphan split (D05), active-contract aggregation
│   │                           (D04/D12), 90-day usage roll
│   ├── metric/                 HealthScore (with ramp blend) and cARR
│   └── mart/                   4 presentation tables for the dashboard
├── dq/
│   └── run_dq.py               16 assertions in two severity tiers (block/warn)
├── evals/
│   └── run_evals.py            12 checks across T1/T2/T3/T4 from spec 06
└── data/                       (gitignored) generated parquet + duckdb artifact
```

## Run

```bash
# From repo root:
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline_and_tests/requirements.txt

# 1. Generate the synthetic dataset (once — deterministic, SEED=42)
python data_generation/generate_data.py

# 2. Run the pipeline (DuckDB, ~3 seconds)
python pipeline_and_tests/run.py

# 3. Verify data quality (16 assertions)
python pipeline_and_tests/dq/run_dq.py

# 4. Run the eval harness (12 checks across T1-T4)
python pipeline_and_tests/evals/run_evals.py
```

Expected output on a clean run:

```
[pipeline] 13 models executed
[dq]       16 assertions  pass=16  block=0  warn=0
[evals]    12 checks      pass=12  fail=0
```

## Why DuckDB-first

- The panel reviewer can clone and run the full end-to-end stack with
  zero cloud credentials. BigQuery adds friction without adding value
  for a take-home.
- DuckDB's SQL dialect is close enough to BigQuery that the models
  port verbatim in most cases. The few divergences (`DATE_SUB` with
  interval syntax, `DATE_DIFF` argument order) are called out in
  per-model comments.
- Determinism is easier — a single-file DuckDB artifact is byte-stable
  across runs, which lets us assert D07 (immutable snapshot) in CI.

BigQuery execution is a one-flag switch; see the `run_bigquery()`
stub in `run.py`. The panel brief asks for BigQuery as the warehouse,
and the `data_generation/upload_to_bq.py` path populates the same
table names the pipeline models reference, so switching is low-risk.

## Parameter hygiene

All metric parameters live in [`params.py`](params.py). Every value cites
its source section in spec 03. A code change to a parameter without an
accompanying spec change is a merge blocker per [`../specs/README.md#how-to-propose-a-change`](../specs/README.md#how-to-propose-a-change).

## How the evals tie to the metric design

| Tier | Checks | What a failure means |
|---|---|---|
| **T1 Correctness** | shelfware → floor, overage → [1.00, 1.30], spike-drop → detected, normal → healthy band | The SQL is implementing the metric wrong. P0. |
| **T2 Construct validity** | HS bounds, ramp weight [0,1] + monotonic, `cARR = Commit × HS` to 6 decimals | The formula as coded disagrees with the spec. P0. |
| **T3 Decision utility** | shelfware visibly at-risk, rep-level weighted-HS dispersion | The metric is computable but doesn't help decide anything. Design issue. |
| **T4 Comp safety** | no cARR/Commit > HS_CAP, new-logo protection (HS=1.00), orphan exclusion | A rep could be paid wrong. P0 for comp. |

T1 and T4 failures exit non-zero (stop-the-line); T2/T3 warn but continue.

## When this pipeline would move to BigQuery

When any of these becomes true:
- Dataset exceeds ~10M usage rows (DuckDB is fine up to that on a laptop).
- The dashboard has to read from a shared team database, not a local file.
- Row-level security for comp data is needed — BQ's RLS beats anything
  we'd build on top of DuckDB.

Until then, DuckDB-first is strictly faster for iteration, cheaper, and
deterministic without cloud-side quirks like the sandbox 60-day partition
expiration that tripped us earlier (spec `README.md` D09).
