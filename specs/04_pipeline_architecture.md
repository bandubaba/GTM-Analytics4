# 04 — Pipeline Architecture

| Field         | Value                                                                         |
|---------------|-------------------------------------------------------------------------------|
| Spec          | `04_pipeline_architecture.md`                                                 |
| Audience      | Data engineers, analytics engineers, SRE, RevOps                              |
| Owner         | Principal PM, GTM Analytics (with Data Platform tech-lead co-owner in prod)   |
| Status        | Draft                                                                         |
| Version       | 0.1                                                                           |
| Last reviewed | 2026-04-19                                                                    |
| Related       | [02 — Data Model](02_data_model.md), [03 — Metric](03_north_star_metric.md), [05 — Data Quality](05_data_quality.md), [09 — Access](09_access_and_audit.md) |

---

## 1. Purpose

This spec defines **how data flows** from source-of-record systems to the published cARR marts, and the **non-negotiable properties** any implementation must preserve (determinism, idempotency, freeze semantics, cost envelope). It is implementation-technology agnostic in principle, but encodes our concrete choices (BigQuery + dbt-style SQL) and explains why.

## 2. Layer diagram

```
                             ┌──────────────────────────────────────┐
                             │   RAW  (source-of-record extracts)   │   owner: Data Platform
                             │                                      │
                             │   raw.sales_reps                     │
                             │   raw.accounts                       │
                             │   raw.contracts                      │
                             │   raw.daily_usage_logs               │
                             └──────────────────────┬───────────────┘
                                                    │   (1) Extract + Load (EL)
                                                    ▼
                             ┌──────────────────────────────────────┐
                             │   STAGING  (typed, validated)        │   owner: Analytics Eng
                             │                                      │
                             │   stg_sales_reps                     │
                             │   stg_accounts                       │
                             │   stg_contracts                      │
                             │   stg_usage_logs_clean     ─────┐    │
                             │   stg_usage_logs_orphans   ─────┼────┼──→  DQ mart
                             └──────────────────────┬──────────┘    │     (spec 05)
                                                    │   (2) Transform
                                                    ▼
                             ┌──────────────────────────────────────┐
                             │   INTERMEDIATE  (denormalized)       │   owner: Analytics Eng
                             │                                      │
                             │   int_contract_day                   │
                             │   int_account_day                    │
                             │     (one row per account × day with  │
                             │      included_credits and active     │
                             │      CommittedARR)                   │
                             └──────────────────────┬───────────────┘
                                                    │   (3) Metric layer
                                                    ▼
                             ┌──────────────────────────────────────┐
                             │   METRIC  (cARR math)                │   owner: PM (spec) +
                             │                                      │          Analytics Eng
                             │   m_trailing_90d_usage               │
                             │   m_health_score                     │
                             │   m_carr_by_account_day              │
                             └──────────────────────┬───────────────┘
                                                    │   (4) Publish
                                                    ▼
                             ┌──────────────────────────────────────┐
                             │   MART  (stable, audience-facing)    │
                             │                                      │
                             │   mart_carr_by_account_day           │
                             │   mart_carr_by_account_month_end  ★  │
                             │   mart_carr_by_rep_month_end      ★  │
                             │                                      │
                             │   ★ comp-of-record, immutable        │
                             └──────────────────────────────────────┘
```

## 3. Layer responsibilities and invariants

### 3.1 Raw

- **Purpose:** lossless landing zone. Every row from source-of-record systems arrives here unmodified.
- **Schema:** mirrors source (see [spec 02](02_data_model.md)).
- **Nullability:** whatever the source produces. Rogue usage logs with unknown `account_id` **must** land here — the pipeline does not filter at raw.
- **Mutability:** append-only for logs; overwrite-snapshot-on-change for reference tables (reps, accounts, contracts).
- **Ownership:** Data Platform team runs the EL jobs.

### 3.2 Staging

- **Purpose:** type coercion, light cleanup, split of well-formed vs. orphan rows.
- **Key behaviors:**
  - `stg_usage_logs_clean` — `INNER JOIN accounts` on `account_id`, filter to rows where date ∈ some active contract for that account.
  - `stg_usage_logs_orphans` — the complement: rows that fail either filter. Written to `dq.orphaned_usage_daily` (spec 05).
  - Trim whitespace, normalize enum casing.
- **Invariant:** Every raw row is accounted for — `stg_clean + stg_orphans = raw`. Tested.

### 3.3 Intermediate (`int_*`)

- **Purpose:** the expensive denormalizations, computed once and reused by downstream SQL.
- **Key tables:**
  - **`int_contract_day`** — one row per `(contract_id, date)` for every date the contract is active. Columns: `contract_id`, `account_id`, `date`, `annual_commit_dollars`, `included_monthly_compute_credits`. Bounded to `[WINDOW_START, T_max]` per run parameters.
  - **`int_account_day`** — one row per `(account_id, date)` aggregating across active contracts: `sum(annual_commit_dollars) AS committed_arr_on_day`, `sum(included_monthly_compute_credits)/30 AS daily_included_credits`, `count(*) AS active_contract_count`, `bool(count > 1) AS has_overlap_on_day`.
- **Why separate:** isolates the temporal join (contract spans × calendar) from the metric math. Makes invariant-testing cleaner and the metric SQL readable.

### 3.4 Metric

- **Purpose:** implement the formulas from [spec 03](03_north_star_metric.md) exactly.
- **Key tables:**
  - **`m_trailing_90d_usage`** — per `(account_id, as_of_date)`: `trailing_90d_consumed`, `trailing_90d_included`, `U`, `M1`, `contract_age`, `expanded_flag`.
  - **`m_health_score`** — per `(account_id, as_of_date)`: `base`, `modifier`, `health_score`.
  - **`m_carr_by_account_day`** — per `(account_id, as_of_date)`: `committed_arr`, `health_score`, `carr`. Joins the above with `int_account_day`.
- **Parameters** are read from `pipeline_and_tests/metrics/carr_params.yml`, not hardcoded in SQL.

### 3.5 Mart

- **Purpose:** what dashboards, exports, and comp systems read.
- **Key tables:**
  - **`mart_carr_by_account_day`** — reprojection of `m_carr_by_account_day` with human-readable joins (company name, region, segment).
  - **`mart_carr_by_account_month_end`** — month-end snapshot. **Immutable** after M+2 per §5.
  - **`mart_carr_by_rep_month_end`** — derived: sum account-grain by rep, join rep dimensional attributes.
- **Access:** see [spec 09](09_access_and_audit.md).

## 4. Technology choices

### 4.1 Warehouse: BigQuery

Decision D08. Rationale and rejected alternatives in [spec 00 decision log](README.md#decision-log).

### 4.2 Transform engine: dbt-style SQL (not PySpark / Pandas)

- **Why SQL:** every analyst in the org can read it. Dbt-style models compile to pure BQ SQL. No JVM ops burden. BigQuery's planner handles the heavy lifting.
- **Why not PySpark:** data fits in BQ comfortably (~10 GB at prod scale, <1 GB compressed at prototype scale). PySpark adds a cluster we don't need.
- **Why not Pandas:** doesn't scale past the prototype; single-machine; harder to audit (row-level lineage invisible).
- The prototype uses plain SQL files orchestrated by a thin Python runner. Productionization can swap to dbt-core with zero SQL changes.

### 4.3 Orchestration

- **Prototype:** shell script + Python runner. Runs end-to-end in <60 seconds.
- **Prod:** Airflow DAG or equivalent; see [spec 08](08_rollout_plan.md) for the adoption gate.

### 4.4 Parameter config: YAML in source control

`pipeline_and_tests/metrics/carr_params.yml` is the single source for the tunables in [spec 03 §6](03_north_star_metric.md). Changes flow through PR review, not console edits.

## 5. Refresh cadence and SLAs

| Table | Cadence | Latency SLA | Consumers |
|---|---|---|---|
| `raw.*` | Continuous / daily | source-dependent | internal |
| `stg_*` | Daily at 07:00 UTC | T+1 daily | internal |
| `int_*` | Daily at 07:15 UTC | T+1 daily | metric layer |
| `m_*` | Daily at 07:30 UTC | T+1 daily | mart layer |
| `mart_carr_by_account_day` | Daily at 08:00 UTC | T+1 daily | dashboards |
| `mart_carr_by_*_month_end` | Monthly, on calendar day M+2 | M+2 calendar days | **comp-of-record** |

The M+2 publication window is the SOX control. Nothing downstream of month-end has authority to change the frozen rows; restatements are additive and logged (spec 09).

## 6. Partitioning, clustering, cost

### 6.1 Physical design

| Table | Partitioning | Clustering | Notes |
|---|---|---|---|
| `raw.daily_usage_logs` | `DAY` on `date` (prod) / **none** (sandbox) | `account_id` | Sandbox constraint — see D09 |
| `stg_usage_logs_clean` | `DAY` on `date` (prod) / **none** (sandbox) | `account_id` | Same constraint |
| `int_account_day` | `MONTH` on `date` (prod) | `account_id` | Frequently scanned at 90-day slices |
| `mart_carr_by_account_day` | `MONTH` on `as_of_date` (prod) | `account_id`, `rep_id` | Dashboard-facing |
| `mart_carr_by_*_month_end` | **none** (small) | — | <10k rows per month-end; clustering overhead not worth it |

Sandbox: partitioning is gated behind the env var `BQ_PARTITION=1`. With partitioning off, tables are unpartitioned but still clustered. Clustering has **no expiration side-effect** and works identically in sandbox.

### 6.2 Cost envelope

At prod scale (estimated 50M usage logs / month, 20k accounts):

| Workload | Est. monthly scan | Est. cost (on-demand, $5/TB) |
|---|---:|---:|
| Daily pipeline run (all transforms) | ~2 TB | ~$10 |
| Dashboard queries (filter push-down to partition) | ~150 GB | ~$0.75 |
| Ad-hoc analyst queries | ~500 GB | ~$2.50 |
| **Total / month** | **~2.65 TB** | **~$13** |

This is a rounding error in the GCP budget. If scale grows 10x, flat-rate slots become cheaper than on-demand — revisit at that point.

### 6.3 Sandbox constraint (decision D09)

BigQuery Sandbox enforces a **hard 60-day partition expiration** un-overridable. A naive partitioned load of historical data silently evicts rows with partition-date older than `today - 60d`. The prototype sidesteps this by **not partitioning in sandbox**. Clustering is retained; partitioning is flag-gated (`BQ_PARTITION=1`) for billed projects.

## 7. Idempotency and restatement

### 7.1 Idempotency

Every transform is `WRITE_TRUNCATE` (full replace) scoped to a parameterized time window. Re-running the pipeline end-to-end with the same parameters produces byte-identical output (invariant #4 + #5 in [spec 03 §7](03_north_star_metric.md)).

### 7.2 Backfills

Backfills for open (unfrozen) months are routine — re-run the daily pipeline with a custom `as_of_date`. Backfills for **closed** (frozen) months are blocked at the mart layer and require a restatement:

```
  backfill to raw  →  transforms re-run  →  metric layer shows delta  →
  mart diff emitted  →  restatement PR opened  →  VPS + CFO approve  →
  mart_carr_restatements append-only row added (NOT a mutation of the frozen table)
```

The `mart_carr_restatements` table carries: as-of month, old value, new value, delta, rationale, approvers, changelog link. Dashboards surface restatements alongside frozen values.

### 7.3 Schema changes

Schema changes to any `mart_*` table are breaking. They require:
- Spec PR touching spec 02 or 03 as appropriate,
- Eval suite diff (spec 06),
- Downstream consumer communication (dashboards, comp engine) at least one refresh cycle before cutover.

## 8. Observability

### 8.1 Lineage

Every model in `pipeline_and_tests/` declares its upstream dependencies as SQL `FROM` clauses. A lineage graph is built by parsing the dependency DAG. Required for any PR that modifies a model.

### 8.2 Row-count monitors

Each layer emits a row-count to `observability.row_counts` on every run. Alerts fire when:
- Row count changes by >10% day-over-day without a code change,
- Orphan share exceeds 1% of total usage logs (DQ breach threshold),
- Mart row count decreases (possible deletion bug).

### 8.3 Freshness

The `observability.freshness` table records the `max(as_of_date)` for each mart after every run. Dashboards read this and display a stale-data warning if the value is >1 day behind expected.

### 8.4 Cost observability

`observability.query_costs` records the scanned-bytes per pipeline run. Alert if a single run exceeds 2x the rolling-7-day median (catches runaway joins and partition-pruning regressions).

## 9. Security and access

Full treatment in [spec 09](09_access_and_audit.md). Summary for orientation:

- `raw.*` and `stg_*` are restricted to Data Platform + Analytics Eng (service accounts).
- `int_*` and `m_*` are restricted to Analytics Eng.
- `mart_*` is readable by Sales Ops, Finance, Internal Audit, and dashboard service accounts.
- Per-rep row-level filtering is applied at the mart layer via authorized views (a rep sees only their own rows unless they have manager entitlement).

## 10. Runbook hooks

Each of the following scenarios links to a runbook (stored in `/docs/runbooks/` in prod; stubs here):

| Scenario | Runbook |
|---|---|
| A daily run fails mid-pipeline | `runbooks/pipeline_failure.md` (stub) |
| Orphan rate spikes above 1% | `runbooks/orphan_spike.md` (stub) |
| Month-end snapshot fails to publish by M+2 | `runbooks/month_end_delay.md` (stub) |
| A restatement is requested | `runbooks/restatement.md` (stub) |
| Schema change required | `runbooks/schema_change.md` (stub) |

## 11. Open questions

1. **Orchestrator choice for prod** — Airflow, Cloud Composer, or Dagster. Deferred to Data Platform tech-lead. Any choice meets this spec.
2. **Slot commitments** — at what scale do we migrate from on-demand pricing to flat-rate BQ slots? Revisit quarterly against actual scanned-bytes.
3. **Incremental materialization** — current plan is `WRITE_TRUNCATE` (full refresh). If daily scan exceeds cost envelope, switch to `MERGE`-based incrementals on the big tables. Design complete but not implemented.
4. **Ephemeral environment for PR validation** — every PR should spin up a disposable dataset for the eval suite to run against. Blocked by dev-ops capacity; deferred to Phase 2 rollout.

---

## Appendix A — Rejected architecture alternatives

| Alternative | Why rejected |
|---|---|
| ELT directly into a mart (no staging) | Forces every downstream query to re-do type coercion and filtering; breaks the "every raw row accounted for" invariant |
| Compute metric as a view over staging (no materialization) | ~5–10s query latency per dashboard load vs. <1s for a materialized mart; defeats stability — a backfill could silently change "historical" values |
| Per-rep mart shards (one mart per rep) | Denormalization without benefit; filtering at query time with authorized views is cheaper and auditable |
| Kafka streaming into BQ Streaming Inserts | Real-time cost is not worth it — GTM reporting is a weekly/monthly cadence business |
| Snowflake + Fivetran | Capability-equivalent to BQ + the warehouse D08 reasoning |
| No restatement workflow — overwrite-in-place | Violates comp-of-record control; blocked by Internal Audit |

## Appendix B — Minimal SQL skeletons (reference)

Full implementations live in `/pipeline_and_tests/`. These show shape only.

**`stg_usage_logs_clean.sql`**
```sql
SELECT u.log_id, u.account_id, u.date, u.compute_credits_consumed
FROM `{project}.gtm_analytics.daily_usage_logs` u
JOIN `{project}.gtm_analytics.accounts` a USING (account_id)
WHERE EXISTS (
  SELECT 1
  FROM `{project}.gtm_analytics.contracts` c
  WHERE c.account_id = u.account_id
    AND u.date BETWEEN c.start_date AND c.end_date
)
```

**`int_account_day.sql`** — one row per active account × day, with accumulated commitments and capacity:
```sql
SELECT
  c.account_id,
  d.date,
  SUM(c.annual_commit_dollars)                              AS committed_arr_on_day,
  SUM(c.included_monthly_compute_credits) / 30.0            AS daily_included_credits,
  COUNT(c.contract_id)                                      AS active_contract_count,
  COUNT(c.contract_id) > 1                                  AS has_overlap_on_day
FROM `{project}.gtm_analytics.contracts` c
CROSS JOIN UNNEST(GENERATE_DATE_ARRAY(c.start_date, c.end_date)) AS d(date)
GROUP BY c.account_id, d.date
```

**`m_health_score.sql`** — cites [spec 03 §2.1](03_north_star_metric.md) for every rule; parameters from YAML.
