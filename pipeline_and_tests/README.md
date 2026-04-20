# Pipeline & tests

Implements the cARR pipeline from [`../specs/04_pipeline_architecture.md`](../specs/04_pipeline_architecture.md),
the DQ catalog from [`../specs/05_data_quality.md`](../specs/05_data_quality.md),
and the eval framework from [`../specs/06_evaluation_framework.md`](../specs/06_evaluation_framework.md).

## What's in here

```
pipeline_and_tests/
├── params.py                   Parameters (ref specs/03 §6). Changing a value
│                               here without amending the spec breaks the contract.
├── run.py                      BigQuery orchestrator — runs the 13 models
│                               and exports each as parquet for DQ/evals/dashboard.
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
└── data/                       (gitignored) parquet exports of every model
```

## Run

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

# 3. Run the pipeline — reads gtm_analytics, writes gtm_metric,
#    exports every model as parquet under pipeline_and_tests/data/
GOOGLE_CLOUD_PROJECT=<your-project> \
  python pipeline_and_tests/run.py

# 4. DQ + evals read the parquet exports (no BQ round-trip)
python pipeline_and_tests/dq/run_dq.py
python pipeline_and_tests/evals/run_evals.py
```

Expected output on a clean run:

```
[pipeline] 13 models executed
  accounts in metric   : 684
  Committed_ARR        : $93,913,628
  cARR                 : $76,668,483
  weighted HealthScore : 0.816
[dq]       16 assertions  pass=16  block=0  warn=0
[evals]    12 checks      pass=12  fail=0
```

## Why parquet exports (not BQ round-trips)

Every model run writes a parquet snapshot to
`pipeline_and_tests/data/<table>.parquet`. The DQ suite, eval harness,
and dashboard read parquet locally rather than hitting BigQuery on every
invocation. Reasons:

- **Deterministic.** A rerun of the pipeline produces byte-identical
  parquet, which is how D07 (immutable snapshot) is asserted in CI.
- **Fast dashboard.** Streamlit renders instantly; no BQ latency, no
  per-session cost.
- **Reviewer-friendly.** DQ and evals run cold without re-auth; useful
  when iterating on an assertion without re-querying BQ.

The warehouse is still BigQuery — the parquet files are an export, not a
second engine.

## Determinism

- `AS_OF_DATE` is a constant (`params.py`). No `NOW()` / `CURRENT_DATE()`
  / `RANDOM()` in any model.
- Window bounds (`window_start`, `m1_end`) precomputed in Python
  (`run.py::_render()`) and passed as DATE literals so the SQL is a flat
  string — no INTERVAL arithmetic.
- Seeded generator + typed loads + deterministic SQL → byte-identical
  parquet across reruns.

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
