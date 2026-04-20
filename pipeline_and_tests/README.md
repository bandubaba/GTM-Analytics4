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

The same 13 models run against either BigQuery (the warehouse the
assignment calls out) or DuckDB (a local mirror — same SQL, same
numbers, no cloud creds needed). Pick one:

### BigQuery path (primary — matches the brief)

Two BQ datasets by design:

| Dataset | Contents | Who writes |
|---|---|---|
| `gtm_analytics` | Exactly the **4 brief-spec source tables** (`sales_reps`, `accounts`, `contracts`, `daily_usage_logs`) | `upload_to_bq.py` |
| `gtm_metric`   | All pipeline outputs — `raw_*` bridge views, `stg_*`, `int_*`, `metric_*`, `mart_*` | `run.py` |

Keeping them separate means the reviewer can open `gtm_analytics` and see
the four tables the brief asks for, nothing more. Overridable with env
vars `BQ_SOURCE_DATASET` / `BQ_WAREHOUSE_DATASET`.

```bash
# From repo root:
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline_and_tests/requirements.txt

# 0. one-time auth
gcloud auth application-default login

# 1. Generate synthetic dataset (deterministic, SEED=42)
python data_generation/generate_data.py

# 2. Load the 4 CSVs into gtm_analytics (brief's source dataset)
GOOGLE_CLOUD_PROJECT=<your-project> \
  python data_generation/upload_to_bq.py

# 3. Run the pipeline — reads gtm_analytics, writes gtm_metric
GOOGLE_CLOUD_PROJECT=<your-project> PIPELINE_ENGINE=bigquery \
  python pipeline_and_tests/run.py

# 4. DQ + evals (read the BQ-exported parquet)
python pipeline_and_tests/dq/run_dq.py
python pipeline_and_tests/evals/run_evals.py
```

### DuckDB path (local mirror — for the reviewer)

```bash
python data_generation/generate_data.py
python pipeline_and_tests/run.py           # DuckDB by default
python pipeline_and_tests/dq/run_dq.py
python pipeline_and_tests/evals/run_evals.py
```

Expected output on a clean run (either engine):

```
[pipeline] 13 models executed
  accounts in metric   : 684
  Committed_ARR        : $93,913,628
  cARR                 : $76,668,483
  weighted HealthScore : 0.816
[dq]       16 assertions  pass=16  block=0  warn=0
[evals]    12 checks      pass=12  fail=0
```

BigQuery and DuckDB produce byte-identical metric outputs — verified
against a personal GCP sandbox (`<your-project>.gtm_analytics`).

## Why the same SQL runs on both engines

The 13 `.sql` files are written once. A thin dialect adapter in
`run.py::_translate_to_bq()` rewrites four DuckDB-isms that BigQuery
rejects before the query is submitted:

| DuckDB | BigQuery |
|---|---|
| `DATE_DIFF('day', start, end)` | `DATE_DIFF(end, start, DAY)` |
| `CAST(x AS DOUBLE)`  | `CAST(x AS FLOAT64)` |
| `CAST(x AS VARCHAR)` | `CAST(x AS STRING)` |
| `CAST(x AS BIGINT)`  | `CAST(x AS INT64)` |

The fifth divergence — interval arithmetic (`DATE '…' - INTERVAL '90' DAY`)
— is sidestepped by precomputing `window_start` and `m1_end` in Python
(`run.py::_render()`) and passing them as date params, so the SQL only
ever sees `DATE '2026-01-18'`-style literals that both engines parse
the same way.

Determinism is preserved on both sides:
- AS_OF_DATE is constant (`params.py`), no `NOW()` / `CURRENT_DATE()`
  / `RANDOM()` in any model.
- A rerun of the pipeline produces byte-identical parquet exports,
  which lets us assert D07 (immutable snapshot) in CI.

## Why DuckDB is the local mirror (not the primary)

The assignment brief calls out BigQuery, so BQ is the source of truth.
DuckDB stays in the repo because:
- A reviewer without a GCP project can clone and run the full stack in
  under a minute — no auth, no billing, no sandbox 60-day partition
  expiration (D09) to trip on.
- The same `.sql` files run on both engines, so the DuckDB path is a
  regression guard: if a model diverges between the two, the parquet
  exports won't match and evals will flag it.

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

## What would change in production

- Partitioning on `daily_usage_logs.date` (MONTH) for predicate pruning —
  currently disabled because the BQ sandbox enforces a 60-day partition
  expiration that would silently evict older partitions on load (D09).
  Flip `BQ_PARTITION=1` on a billed project.
- Row-level security on the comp marts. BQ's RLS is the right tool
  (out-of-scope for this take-home).
- Scheduled DAG (Dataform or Airflow) replacing the Python orchestrator.
  The SQL files port as-is; `run.py` is only ~60 lines of orchestration.
