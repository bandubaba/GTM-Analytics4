# `/data_generation` — synthetic GTM dataset

Generates a realistic 4-table B2B SaaS dataset with **intentional anomalies** injected per the take-home spec, then loads it into a BigQuery sandbox.

## Files

| File | Purpose |
|---|---|
| `config.py` | All tunable knobs (sizes, ratios, dates, BQ defaults). |
| `generate_data.py` | Builds the four tables as CSVs under `./output/`. |
| `upload_to_bq.py` | Loads CSVs into BigQuery with explicit schemas + clustering. Time partitioning is flag-gated (see *Sandbox vs. prod* below). |
| `requirements.txt` | Pinned Python deps. |

## Run

```bash
# 1. deps
pip install -r requirements.txt

# 2. generate CSVs (deterministic — seed=42)
python generate_data.py

# 3. auth + upload (one-time auth)
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-sandbox-project-id
export BQ_DATASET=gtm_analytics          # optional
export BQ_LOCATION=US                    # optional
python upload_to_bq.py
```

## What gets generated

| Table | Rows | Notes |
|---|---:|---|
| `sales_reps` | 50 | Enterprise vs. Mid-Market; 4 regions weighted NAMER-heavy. |
| `accounts` | 1,000 | 30% Enterprise / 70% Mid-Market; rep assigned by segment. |
| `contracts` | ~1,220 | 1 base per account + ~90 mid-year expansions + ~130 renewals. |
| `daily_usage_logs` | ~194,000 | Clustered by `account_id`. Time-partitioning on `date` is off by default in sandbox and flag-gated for prod — see *Sandbox vs. prod* below. |

## Account archetypes (injected anomalies)

Each account is assigned exactly one archetype; distributions match the brief.

| Archetype | Share | Behavior |
|---|---:|---|
| `shelfware` | 10% | High `annual_commit_dollars`, **zero** rows in `daily_usage_logs`. |
| `spike_drop` | 5% | ~90% of annual credits burned in month 1 of contract, near-zero after. Contract start is clamped into the observation window so the burst is visible. |
| `overage` | 15% | Consumes 120–155% of `included_monthly_compute_credits` consistently. |
| `normal` | 70% | Noisy, healthy usage at 50–95% of included; slight weekly seasonality; mild trend per account. |

## Contract overlays

- **Mid-year expansions (~90)** — a second, larger contract starts halfway through an existing one, creating **overlapping active dates** for the same `account_id`.
- **Renewals (~130)** — sequential contracts: new contract starts near old one's end, with a mild price uplift (±15%).

## Rogue / orphaned usage

- **200 logs** with `account_id` values that do **not exist** in `accounts` (nullable-allowed, caught by FK test).
- **~150 logs** with valid `account_id` but a `date` that falls **outside any active contract** for that account (caught by temporal-join test).

## Sandbox vs. prod — partitioning trade-off

BigQuery Sandbox (free tier) enforces a **hard 60-day partition expiration** on any time-partitioned table, and the cap cannot be overridden. A naive partitioned load of our historical data silently drops any partition older than `today − 60 days` — for our generation window this meant ~77% of rows evicted immediately after the load, with no error raised.

Two behaviors are therefore gated behind the `BQ_PARTITION` env var:

| Environment | Default | Behavior |
|---|---|---|
| Sandbox (free tier) | `BQ_PARTITION` unset | No time partitioning. Clustering on `account_id` only. All rows retained for the full 60-day table TTL. |
| Billed project (prod) | `BQ_PARTITION=1` | Time-partitioned by MONTH on `date` + clustered on `account_id`. Predicate pruning kicks in for trailing-window queries. |

Clustering is safe in both environments; it has no expiration side-effect.

## Invariants (verified in `generate_data.py` summary + QA tests)

1. All log dates ∈ `[WINDOW_START, WINDOW_END]` = `[2025-01-01, 2026-04-18]`.
2. Shelfware accounts have **exactly** zero rows in `daily_usage_logs`.
3. Every `rep_id` in `accounts` exists in `sales_reps`.
4. 200 usage logs reference an unknown `account_id`.
5. Mid-year expansion accounts exhibit overlapping `[start_date, end_date]` intervals.

## Why these distributions matter for the metric

The metric (`Consumption-Adjusted ARR`) must:
- **Penalize shelfware** — committed dollars that never convert to usage shouldn't inflate GTM health.
- **Flag spike-and-drop** — rep landed a big logo but the customer is already churn-risk.
- **Reward overage** — organic expansion signal; upsell-ready.
- **Respect overlapping contracts** — use the "primary" (higher-commit) contract per day to avoid double-counting capacity.
- **Exclude orphans** — a DQ breach shouldn't distort the number reported to the CFO.

See `/specs/north_star_metric.md` (next phase) for the formal formula and edge-case handling.
