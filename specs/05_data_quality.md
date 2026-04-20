# 05 — Data Quality

| Field         | Value                                                                          |
|---------------|--------------------------------------------------------------------------------|
| Spec          | `05_data_quality.md`                                                           |
| Audience      | Data engineers, analytics engineers, data stewards, Internal Audit             |
| Owner         | Principal PM, GTM Analytics (co-owned with Data Platform tech-lead in prod)    |
| Status        | Draft                                                                          |
| Version       | 0.1                                                                            |
| Last reviewed | 2026-04-19                                                                     |
| Related       | [02 — Data Model](02_data_model.md), [04 — Pipeline](04_pipeline_architecture.md), [06 — Evaluation Framework](06_evaluation_framework.md), [09 — Access](09_access_and_audit.md) |

---

## 1. Purpose

This spec is the **authoritative catalog** of every assertion the pipeline runs on its data, with severity tiers, failure behavior, and SLAs. Every assertion has a stable ID (`DQ-<category>-<nnn>`) so audit trails, dashboards, and change-management docs can reference specific checks without ambiguity.

## 2. Guiding principles

1. **DQ gates comp, period.** A failing P0 assertion blocks publication of the mart. No exceptions.
2. **Every raw row is accounted for.** `stg_usage_logs_clean + stg_usage_logs_orphans = raw.daily_usage_logs` — tested. Orphan data is preserved, not deleted.
3. **Orphans are data, not errors.** The *existence* of orphans is informational; the *rate* is what we alert on.
4. **Tests are code, not UI config.** Every assertion is a versioned SQL file under `/pipeline_and_tests/dq/`, reviewed like any other PR.
5. **DQ failures have owners.** Each assertion has a named owning team so alerts route to a human, not a shared inbox.

## 3. Severity tiers

| Tier | Meaning | Pipeline behavior | SLA to resolve |
|---|---|---|---|
| **P0 — Block** | Data is unusable or the contract with downstream is broken. Publishing would be unsafe. | Mart publication halts. Previous mart snapshot remains queryable (staleness alert fires on dashboards). | Resolve before next scheduled run. |
| **P1 — Warn** | Data is usable but a drift signal fired. Pipeline completes but a notification is raised. | Mart publishes; notification to owning team; elevated review on next daily standup. | 24h to triage, 72h to resolve or reclassify. |
| **P2 — Info** | Known-state observation, counted for trending. | Pipeline completes; counts land in `dq.assertion_results`. | Reviewed weekly. |

**Closed months.** A P0 discovered *after* a month-end snapshot is frozen (§3.3 below) does not retroactively invalidate the frozen mart — it opens a **restatement ticket** per [spec 04 §7.2](04_pipeline_architecture.md). This prevents a late-arriving DQ issue from silently changing a rep's already-paid commission.

## 4. Assertion catalog

Each assertion has ID, title, tier, owner, SQL location, and a 1-line description. Every P0 has an explicit runbook link (prod) or stub (prototype).

### 4.1 Schema invariants — `DQ-SCHEMA-*`

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-SCHEMA-001` | All required columns present | P0 | Data Platform | Every expected column from spec 02 exists on every table. |
| `DQ-SCHEMA-002` | Column types match spec 02 | P0 | Data Platform | Types are `STRING`/`DATE`/`INT64`/`NUMERIC(18,2)` per spec. `FLOAT64` for money is a P0 failure. |
| `DQ-SCHEMA-003` | `NOT NULL` columns have no nulls | P0 | Data Platform | `rep_id`, `account_id`, `contract_id`, `log_id`, all dates and dollar columns are non-null. `daily_usage_logs.account_id` is exempt (nullable by design per spec 02). |
| `DQ-SCHEMA-004` | Enum columns respect taxonomy | P0 | Data Platform | `region`, `segment`, `industry` ∈ sanctioned values from [spec 02 §8](02_data_model.md#8-enumerations). |
| `DQ-SCHEMA-005` | Primary-key uniqueness | P0 | Data Platform | `rep_id`, `account_id`, `contract_id`, `log_id` unique per table. |

### 4.2 Referential integrity — `DQ-REF-*`

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-REF-001` | Every `accounts.rep_id` exists in `sales_reps.rep_id` | P0 | RevOps | Hard FK per spec 02 §4. |
| `DQ-REF-002` | Every `contracts.account_id` exists in `accounts.account_id` | P0 | RevOps | Hard FK per spec 02 §4. |
| `DQ-REF-003` | Orphan usage share (unknown `account_id`) | P1 | Platform Eng | `COUNT(WHERE account_id NOT IN accounts) / COUNT(*)` < 1% of daily volume. Expected baseline ~0.1%; exceeding 1% alerts. |
| `DQ-REF-004` | Every account with active contract has ≥1 active rep | P1 | RevOps | Detects rep-assignment drift during territory changes. |

### 4.3 Business-rule invariants — `DQ-BIZ-*`

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-BIZ-001` | `annual_commit_dollars > 0` | P0 | Finance Systems | Contracts with zero or negative commit are data errors. |
| `DQ-BIZ-002` | `included_monthly_compute_credits > 0` | P0 | Finance Systems | Zero-credit contracts violate the metric's denominator invariant; carve-out for unlimited-tier pending ([spec 03 §9](03_north_star_metric.md#9-open-questions)). |
| `DQ-BIZ-003` | `compute_credits_consumed ≥ 0` | P0 | Platform Eng | Negative usage is a telemetry bug. |
| `DQ-BIZ-004` | Contract `end_date > start_date` | P0 | Finance Systems | Zero- or negative-duration contracts are data errors. |
| `DQ-BIZ-005` | Usage log `date` ∈ observation window | P0 | Platform Eng | Prevents leakage from dev/test environments. Window bounds come from pipeline parameters. |
| `DQ-BIZ-006` | Out-of-window usage share (valid account, outside contract span) | P1 | Platform Eng | Expected baseline ~0.05–0.2%; alerts above 1%. |

### 4.4 Anomaly-rate guardrails — `DQ-RATE-*`

These assertions watch the rate at which anomalies from [spec 02 §5](02_data_model.md#5-anomaly-catalog--known-states-of-the-world) appear. The *existence* of the anomalies is expected; a *rate change* is the signal.

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-RATE-001` | Shelfware share (A1) | P1 | PM + CSM | Expected range 3%–15%. Alerts outside; sustained breach triggers PM review. |
| `DQ-RATE-002` | Spike-and-drop share (A2) | P1 | PM | Expected range 2%–8%. |
| `DQ-RATE-003` | Overage share (A3) | P1 | PM | Expected range 8%–25%. Upside drift is watched, not alarming. |
| `DQ-RATE-004` | Mid-year expansion share (A4) | P2 | PM | Trended; no alert threshold. |
| `DQ-RATE-005` | Orphan log share (A5a + A5b) | P1 | Platform Eng | Combined, below 1% of daily volume. |
| `DQ-RATE-006` | Daily log count vs. trailing-7d median | P1 | Platform Eng | Alerts if a day's count deviates ±30%. Catches ETL failures + spikes. |

### 4.5 Metric-layer invariants — `DQ-METRIC-*`

These implement the invariants in [spec 03 §7](03_north_star_metric.md#7-invariants). They gate mart publication.

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-METRIC-001` | Per-account bounds: `0.40 × CommittedARR ≤ cARR ≤ 1.30 × CommittedARR` | P0 | PM + Analytics Eng | Any out-of-bounds row is a metric-implementation bug. |
| `DQ-METRIC-002` | Company-total bounds | P0 | PM + Analytics Eng | `0.40 × Σ CommittedARR ≤ Σ cARR ≤ 1.30 × Σ CommittedARR` |
| `DQ-METRIC-003` | No-null `cARR` in published marts | P0 | Analytics Eng | Accounts without an active contract must be absent, not null. |
| `DQ-METRIC-004` | Orphan exclusion | P0 | Analytics Eng | Removing all orphan rows from input changes no `cARR` by more than `1e-6`. Asserted via two-run A/B. |
| `DQ-METRIC-005` | Determinism | P0 | Analytics Eng | Re-running pipeline on same inputs produces byte-identical marts. Asserted via checksum. |
| `DQ-METRIC-006` | Freeze invariant | P0 | Analytics Eng | Re-running pipeline for a closed month produces byte-identical `mart_carr_by_*_month_end`. Asserted via checksum vs. previously published snapshot. |

### 4.6 Reconciliation — `DQ-RECON-*`

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-RECON-001` | Staging lossless: `stg_clean + stg_orphans = raw` | P0 | Analytics Eng | Row counts reconcile exactly. |
| `DQ-RECON-002` | Rep-grain rollup matches account-grain sum | P0 | Analytics Eng | `mart_carr_by_rep_month_end.carr = sum over mart_carr_by_account_month_end.carr for that rep`. |
| `DQ-RECON-003` | Mart row count decrease alert | P1 | Analytics Eng | Alerts if any mart's row count decreases DoD (possible deletion). |
| `DQ-RECON-004` | `Σ CommittedARR` vs Salesforce CPQ monthly report | P1 | Finance Systems | Tolerance ±0.5%. Detects contract-sync lag. |

### 4.7 Freshness — `DQ-FRESH-*`

| ID | Title | Tier | Owner | Description |
|---|---|---|---|---|
| `DQ-FRESH-001` | `max(daily_usage_logs.date) ≥ T - 1` | P0 | Platform Eng | Daily data pipeline must be caught up before downstream runs. |
| `DQ-FRESH-002` | Every mart has `updated_at` within last 26h | P0 | Analytics Eng | Any mart older than 26h is a staleness alert on the dashboard. |
| `DQ-FRESH-003` | Month-end snapshot published by M+2 calendar days | P0 | Analytics Eng | The SOX-adjacent SLA per [spec 04 §5](04_pipeline_architecture.md#5-refresh-cadence-and-slas). |

## 5. Where results surface

### 5.1 `dq.assertion_results`

A table with one row per assertion per run:

| Column | Type | Meaning |
|---|---|---|
| `run_id` | STRING | Unique pipeline run identifier |
| `run_ts` | TIMESTAMP | UTC execution time |
| `assertion_id` | STRING | e.g. `DQ-METRIC-001` |
| `severity` | STRING | `P0` / `P1` / `P2` |
| `status` | STRING | `pass` / `warn` / `fail` |
| `observed_value` | STRING | Free-form, human-readable |
| `threshold` | STRING | Free-form, human-readable |
| `rows_affected` | INT64 | Count of rows triggering the assertion |
| `owning_team` | STRING | From the catalog above |

### 5.2 `dq.orphaned_usage_daily`

Per-day counts of A5a and A5b orphans, split by `account_id` where known. Drives runbook triage.

### 5.3 Alerting

- **P0 fail:** PagerDuty to the owning-team rotation, Slack to `#data-pipelines`, email to the Principal PM + Analytics Eng tech-lead.
- **P1 warn:** Slack-only to `#data-quality`. Ticket auto-created in owning-team queue with 72h SLA.
- **P2 info:** no alert; dashboard tile only.

### 5.4 Dashboard surfacing

A dedicated **Data Health** tab on the exec dashboard (see [spec 07 §5](07_dashboard_spec.md)) shows:
- Green / yellow / red status for each severity tier,
- Top 5 open DQ tickets,
- Last restatement event (if any),
- Pipeline last-success timestamp.

Leadership sees this once a week; Internal Audit sees it on demand.

## 6. SLAs and escalation

| Tier | First response | Resolution | Escalation if missed |
|---|---|---|---|
| P0 | 15 minutes (on-call) | Before next scheduled pipeline run | VP Data (after 2 missed SLAs) + Internal Audit notification |
| P1 | 24 hours | 72 hours | Data Platform tech-lead, then Principal PM |
| P2 | Weekly review | Next spec review cycle | None — by design |

## 7. How DQ interacts with the freeze rule

Reminder from [spec 03 §5.2](03_north_star_metric.md#52-the-freeze-rule-comp-of-record): once a month-end snapshot is published, its rows are **immutable**. This has a specific interaction with DQ:

- A P0 failure on **open data** (before M+2 publish): pipeline blocks, mart does not publish, runbook engages, data is corrected, pipeline re-runs. Normal path.
- A P0 failure on **closed data** (found after M+2 publish, e.g. a backfill revealed a missing contract): mart does **not** mutate. Instead, a restatement is opened per [spec 04 §7.2](04_pipeline_architecture.md#72-backfills). Frozen rows stay; `mart_carr_restatements` gets an append-only row; VPS + CFO approve; dashboards surface the restatement alongside the original.

This asymmetry is deliberate: comp already paid cannot be silently unpaid.

## 8. Test authoring conventions

Every file in `/pipeline_and_tests/dq/` follows this pattern:

```
-- DQ-METRIC-001
-- Per-account cARR bounds: 0.40 × CommittedARR ≤ cARR ≤ 1.30 × CommittedARR
-- Owner: PM + Analytics Eng
-- Severity: P0
-- Spec ref: 03 §7 invariant #1

WITH offenders AS (
  SELECT
    account_id,
    committed_arr,
    carr,
    carr / NULLIF(committed_arr, 0) AS ratio
  FROM `{project}.gtm_analytics.mart_carr_by_account_day`
  WHERE as_of_date = @as_of_date
    AND (carr < 0.40 * committed_arr OR carr > 1.30 * committed_arr)
)
SELECT
  'DQ-METRIC-001' AS assertion_id,
  COUNT(*) AS rows_affected,
  MIN(ratio) AS min_observed_ratio,
  MAX(ratio) AS max_observed_ratio
FROM offenders
```

Header comment is mandatory (id, title, owner, severity, spec ref). Body is a single SELECT that returns one row with the assertion's observation. The test harness interprets `rows_affected > 0` as failure for correctness assertions.

## 9. Open questions

1. **Auto-restatement threshold.** How big a delta triggers a restatement vs. a one-line note? Proposed: any per-account delta > $500 or any rep-total delta > $5,000. Pending CFO review.
2. **Unlimited-tier carve-out.** `DQ-BIZ-002` (`included_monthly_compute_credits > 0`) will become a warn-not-block once unlimited contracts exist in the dataset, per [spec 03 §9](03_north_star_metric.md#9-open-questions).
3. **DQ budget for "known brokenness".** Early prod will likely carry a handful of accepted P1 warnings (e.g., test accounts). Need a formal exception register so accumulated warn-tolerance doesn't become risk-tolerance.
4. **Upstream DQ contracts.** Ideally Salesforce CPQ and the telemetry stream publish their own DQ guarantees (e.g., "every contract row has a non-null start_date"). Deferred until we have Data Platform capacity for a cross-team DQ contract.

---

## Appendix A — Rejected DQ approaches

| Alternative | Why rejected |
|---|---|
| Pipeline-level `try/except` with silent fallbacks | Hides DQ issues until they manifest as comp disputes — the exact failure mode this spec exists to prevent |
| GUI-based DQ tools (e.g., Monte Carlo, Soda) as primary source of truth | Vendor lock-in; tests should live in source control next to the SQL they validate; GUI tools are fine as notification layer |
| Single-tier "all failures block" | Too brittle — a 0.01% orphan-rate wobble should not stop comp publication |
| Single-tier "all failures warn" | Opposite failure mode — comp would publish against broken data |
| Running DQ post-publication | Defeats the purpose for P0 assertions; comp consumers would see broken data before the first alert |

## Appendix B — Assertion summary

Total initial assertion set:

- **P0 (block):** 18 assertions — schema (5), RI (2), business rules (5), metric (6)
- **P1 (warn):** 11 assertions — RI (2), business rules (1), rate guardrails (5), reconciliation (1), freshness (0 — freshness is P0)
- **P2 (info):** 1 assertion — rate guardrail (1)

Each has a stable ID. New assertions get the next sequential number in the relevant category; retired assertions are marked `DEPRECATED` in the catalog but the ID is never reused.
