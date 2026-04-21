# 02 — Data Model

| Field         | Value                                                  |
|---------------|--------------------------------------------------------|
| Spec          | `02_data_model.md`                                     |
| Audience      | Data engineers, analysts, RevOps, auditors             |
| Owner         | Principal PM, GTM Analytics                            |
| Status        | Draft                                                  |
| Version       | 0.1                                                    |
| Last reviewed | 2026-04-19                                             |
| Related       | [04 — Pipeline](04_pipeline_architecture.md), [05 — DQ](05_data_quality.md), [09 — Access](09_access_and_audit.md) |

---

## 1. Purpose

This spec is the **authoritative description** of the four source tables that feed the cARR pipeline. Every downstream SQL, test, and chart cites this document for column semantics, nullability rules, and the full anomaly catalog.

Changes here ripple. Update this spec *before* you change the generator, the schema, or the pipeline.

## 2. Entity-Relationship diagram

```
  ┌──────────────────┐           ┌──────────────────┐
  │   sales_reps     │           │     accounts     │
  ├──────────────────┤           ├──────────────────┤
  │ PK rep_id        │◀──────────│ FK rep_id        │
  │    name          │   1:N     │ PK account_id    │
  │    region        │           │    company_name  │
  │    segment       │           │    industry      │
  └──────────────────┘           └──────┬───────────┘
                                        │
                                        │ 1:N
                                        ▼
                            ┌──────────────────────────────────────┐
                            │           contracts                  │
                            ├──────────────────────────────────────┤
                            │ PK contract_id                       │
                            │ FK account_id                        │
                            │    start_date                        │
                            │    end_date                          │
                            │    annual_commit_dollars             │
                            │    included_monthly_compute_credits  │
                            └──────────────────────────────────────┘

  ┌────────────────────────────────┐
  │      daily_usage_logs          │
  ├────────────────────────────────┤
  │ PK  log_id                     │
  │ FK? account_id  (NULLABLE)     │      ◀── FK *intentionally* nullable;
  │     date                       │          rogue logs in the wild reference
  │     compute_credits_consumed   │          unknown accounts and we keep
  └────────────────────────────────┘          them for DQ reporting
```

`account_id` in `daily_usage_logs` is deliberately **nullable-allowed** at the schema level: the raw layer preserves anomalies as they arrive; filtering happens in the staging layer (see spec 04).

## 3. Tables

### 3.1 `sales_reps`

| Column  | Type   | Nullable | Key | Semantic meaning |
|---|---|---|---|---|
| `rep_id` | `STRING` | N | **PK** | Stable internal rep identifier. Format: `R<nnn>` (e.g. `R001`). Not reused after rep departure. |
| `name`   | `STRING` | N | — | Human name. Classified as PII — see spec 09. |
| `region` | `STRING` | N | — | Geography the rep operates in. Enum: `NAMER`, `EMEA`, `APAC`, `LATAM`. |
| `segment`| `STRING` | N | — | Rep's account-size alignment. Enum: `Enterprise`, `Mid-Market`. |

**Cardinality:** ~50 rows (prototype). Expected prod scale: 100–500.
**Source of record (prod):** Workday → internal HR sync.
**Refresh cadence (prod):** Daily.
**Grain:** One row per rep.

### 3.2 `accounts`

| Column        | Type   | Nullable | Key | Semantic meaning |
|---|---|---|---|---|
| `account_id`   | `STRING` | N | **PK** | Stable customer identifier. Format: `ACC<nnnnnn>` (e.g. `ACC000412`). |
| `company_name` | `STRING` | N | — | Customer legal or display name. Classified as Confidential — see spec 09. |
| `industry`     | `STRING` | N | — | Vertical taxonomy. Enum of ~10 values; see §8. |
| `rep_id`       | `STRING` | N | **FK → `sales_reps.rep_id`** | Current owning rep. Historical ownership lives in a separate slowly-changing dimension table (out of scope for this prototype). |

**Cardinality:** 1,000 rows (prototype). Expected prod scale: 5,000–20,000.
**Source of record (prod):** Salesforce Account object (via nightly CDC).
**Refresh cadence (prod):** Hourly (CDC) in prod; static snapshot in prototype.
**Grain:** One row per customer. An account never represents a department or business unit of a larger parent — if two BUs are separately contracted they get separate `account_id`s.

### 3.3 `contracts`

| Column                              | Type           | Nullable | Key | Semantic meaning |
|---|---|---|---|---|
| `contract_id`                        | `STRING`        | N | **PK** | Unique contract identifier. Format: `CT<nnnnnn>`. |
| `account_id`                         | `STRING`        | N | **FK → `accounts.account_id`** | Customer the contract is against. |
| `start_date`                         | `DATE`          | N | — | First day the contract is active, inclusive. |
| `end_date`                           | `DATE`          | N | — | Last day the contract is active, inclusive. |
| `annual_commit_dollars`              | `NUMERIC(18,2)` | N | — | Committed ARR in USD for the contract term, expressed on an annualized basis (a 24-month $600K contract reports `300000.00`). |
| `included_monthly_compute_credits`   | `INT64`         | N | — | Monthly compute-credit entitlement included in the contract. Used as the denominator of `U` in the cARR formula. |

**Cardinality:** ~1,220 rows (prototype). Expected prod scale: 8,000–30,000.
**Source of record (prod):** CPQ (Salesforce CPQ) → Zuora, reconciled nightly. CPQ is authoritative for `start_date` and `annual_commit_dollars`; Zuora is authoritative for `included_monthly_compute_credits` (since it reflects what was ultimately invoiced).
**Refresh cadence (prod):** Daily full sync + same-day CDC for contract state changes.
**Grain:** One row per contract. Expansions and renewals are **separate rows** — never edit an existing row to reflect an expansion.
**Multi-year contracts:** `annual_commit_dollars` is already annualized by the source systems, so the pipeline treats a 24-month contract identically to a 12-month one.

### 3.4 `daily_usage_logs`

| Column                    | Type           | Nullable | Key | Semantic meaning |
|---|---|---|---|---|
| `log_id`                   | `STRING`        | N | **PK** | Unique log identifier. Format: `UL<nnnnnnnnn>`. |
| `account_id`               | `STRING`        | **Y** | FK → `accounts.account_id` *(soft)* | Customer whose usage this log represents. **Nullable / unknown values allowed**: rogue upstream events reference unrecognized accounts and the raw layer must preserve them for DQ reporting. |
| `date`                     | `DATE`          | N | — | Calendar day the consumption occurred. Must be ≥ `WINDOW_START` and ≤ `WINDOW_END` of the observation window. |
| `compute_credits_consumed` | `NUMERIC(18,2)` | N | — | Credits consumed on that date for that account. Always ≥ 0. A value of 0 is a valid but uninteresting observation (we prefer to suppress the row entirely upstream, but never filter zero-valued rows in the warehouse). |

**Cardinality:** ~182,000 rows (prototype). Expected prod scale: 10M–50M per month; retention policy in §10.
**Source of record (prod):** Product telemetry event stream → daily roll-up job in the data platform.
**Refresh cadence (prod):** Daily, T+1 (yesterday's logs finalized by 06:00 UTC today).
**Grain:** One row per `(account_id, date)` **in practice**, but the schema does not enforce this — late-arriving events can produce multiple rows for the same key and the staging layer reconciles them.

## 4. Referential integrity rules

| From → To | Rule | Enforced where |
|---|---|---|
| `accounts.rep_id` → `sales_reps.rep_id` | **Hard**. Every account must reference a known rep. | Pipeline test (fails build) |
| `contracts.account_id` → `accounts.account_id` | **Hard**. No contract without an account. | Pipeline test (fails build) |
| `daily_usage_logs.account_id` → `accounts.account_id` | **Soft**. Unknown accounts are *expected* at a known rate (see §5). | DQ report (warns + counts, never blocks) |

No cascading deletes — any delete in prod goes through a soft-delete + retention workflow (see spec 09).

## 5. Anomaly catalog — known states of the world

These patterns are intentional in the synthetic dataset and **expected** in production. The metric, the pipeline, and the DQ suite each cite this list explicitly. See spec 03 §4 for how the metric responds to each.

| ID | Anomaly | Synthetic share | Definition | Why it occurs in prod | Expected handling |
|---|---|---:|---|---|---|
| A1 | **Shelfware** | 10% of accounts | Account has one or more active contracts but **zero** rows in `daily_usage_logs`. | Customer bought, never onboarded. Exec sponsor left, project reprioritized, incumbent tool kept. | Metric: `U = 0 → HealthScore = 0.40` (floor). DQ: **informational** (not an error). |
| A2 | **Spike-and-drop** | 5% of accounts | ≥70% of trailing-90-day consumption concentrated in the first 30 days of the oldest active contract, with contract age ≥ 90 days. | Customer ran a one-time migration or burst workload, never settled into steady-state use. | Metric: spike-drop modifier `0.70` on `HealthScore`. DQ: **informational**. |
| A3 | **Consistent overage** | 15% of accounts | Trailing-90-day consumption ≥ 120% of trailing-90-day included credits. | Organic expansion: customer's usage grew past committed capacity. | Metric: `base(U)` lifts; capped at `1.30`. DQ: **informational**; feeds expansion / upsell motion. |
| A4 | **Mid-year expansion** | ~9% of accounts | Account has two or more contracts with **overlapping** `[start_date, end_date]` intervals at any point in the trailing 365 days. | Customer signed an additional contract on top of an existing one before the first expired. | Metric: ARR and included credits **sum** during overlap; `expanded = true` triggers `+5%` credit. Pipeline: uses account-day intermediate table to avoid double-counting capacity distinct from commitment (see spec 04). |
| A5a | **Orphan usage — unknown account** | ~200 logs (0.1%) | `daily_usage_logs.account_id` references a value not present in `accounts.account_id`. | Upstream telemetry emits an event for an account that hasn't synced from Salesforce yet, or an internal test account not in the CRM. | Metric: **excluded**. DQ: **warning**; row count trended; alert if > 1% of daily volume. |
| A5b | **Orphan usage — out-of-window** | ~150 logs | Valid `account_id`, but `date` falls outside any active contract for that account. | Free-trial usage before contract start; test-system leakage; edge-case billing events. | Metric: **excluded**. DQ: **warning**; per-account count trended. |
| A6 | **Overlapping contracts, non-expansion** | ~0% (not intentionally generated) | Two contracts for the same account, overlap > 30 days, **both** with decreasing `included_monthly_compute_credits` relative to the previous. | Contract amendment gone sideways; billing system lag; ops error. | Metric: same math as A4 (sum both). DQ: **warning** — flag for human review. |

**"Known state" ≠ "good state".** The catalog exists so that the pipeline and tests know what they're seeing, not because any of these are desirable. In particular, A1 is the signal the metric is specifically designed to surface.

## 6. Keys, uniqueness, and idempotency

- Every `*_id` column is a string with a prefix (`R`, `ACC`, `CT`, `UL`). Prefixes are for human debuggability and are **not** significant to the pipeline — never pattern-match on them in SQL.
- `log_id` is unique per load run in the prototype. In prod, `log_id` must be globally unique across replays (derived from upstream event id, not generated).
- Re-running the generator with `SEED = 42` reproduces the exact same tables byte-for-byte. Re-running the pipeline produces the same marts byte-for-byte (determinism invariant per spec 03 §7).

## 7. Types, precision, and units

| Concept | Canonical type | Notes |
|---|---|---|
| Money (USD) | `NUMERIC(18,2)` | Never `FLOAT64` for dollars. Rounded to two decimals at write time. |
| Credits | `INT64` for included, `NUMERIC(18,2)` for consumed | Consumed is fractional because some telemetry events report partial credits. |
| Dates | `DATE` | Always local to UTC. We do not store datetimes — the daily roll-up happens upstream. |
| Ratios (`U`, `M₁`) | `FLOAT64` | Derived, not stored in raw. |

All monetary values are **USD**. Multi-currency handling is out of scope for v1 (deferred to a future spec).

## 8. Enumerations

### 8.1 `region`

`NAMER` · `EMEA` · `APAC` · `LATAM`

Open enum at the schema level (strings, not an ENUM type) for migration safety, but the pipeline rejects any value outside this list as a DQ error.

### 8.2 `segment`

`Enterprise` · `Mid-Market`

Future addition `Public Sector` is planned but not yet supported — see spec 03 §9 open questions.

### 8.3 `industry`

`Technology` · `Financial Services` · `Healthcare` · `Retail` · `Manufacturing` · `Public Sector` · `Education` · `Media` · `Energy` · `Telecom`

Any additional value requires a taxonomy update and a spec PR.

## 9. Data classification

Full treatment in spec 09. Summary for orientation only:

| Table | Classification | Notes |
|---|---|---|
| `sales_reps` | **Confidential + PII** | Names are PII. Row-level access restricted to Sales Ops + HR. |
| `accounts` | **Confidential** | Customer names are commercially sensitive. |
| `contracts` | **Confidential — Financial** | ARR and contract terms are material non-public financial information. SOX scope. |
| `daily_usage_logs` | **Internal** | Aggregated daily totals are less sensitive than per-event detail, but still customer-linked. |

Marts derived from any of the above inherit the **highest** classification of their sources.

## 10. Retention

| Table | Hot (queryable) | Warm (archive) | Legal hold rules |
|---|---|---|---|
| `sales_reps` | Indefinite | N/A | Employment records per HR policy |
| `accounts` | Indefinite | N/A | Core CRM data |
| `contracts` | 7 years | Indefinite | SOX financial records retention |
| `daily_usage_logs` | 25 months | 7 years (aggregated) | Aggregate only after 25 months; per-account daily detail purged |
| `mart_carr_by_account_month_end` | Indefinite | Indefinite | **Comp-of-record**: never purged |
| `mart_carr_by_rep_month_end` | Indefinite | Indefinite | **Comp-of-record**: never purged |

## 11. Synthetic vs. production mapping

The prototype uses a 4-table synthetic dataset generated by `/data_generation/generate_data.py`. In production, these same logical tables are **materialized views** on top of the following source-of-record systems:

| Logical table | Synthetic source | Production source | Upstream owner |
|---|---|---|---|
| `sales_reps` | Faker + `R<nnn>` IDs | Workday HR system | People Ops |
| `accounts` | Faker + `ACC<nnnnnn>` IDs | Salesforce Account object (CDC) | RevOps |
| `contracts` | Quarter-end-biased random dates + lognormal ACV | Salesforce CPQ (primary) + Zuora (billing reconciliation) | Finance Systems |
| `daily_usage_logs` | Archetype-driven usage patterns | Product telemetry event stream, daily roll-up | Platform Eng |

Synthetic data **intentionally over-represents** anomalies relative to prod (e.g., 10% shelfware vs. an estimated prod rate of 3–5%) so the pipeline and tests are stress-tested.

## 12. Open questions

1. **Multi-currency.** How do we handle contracts in EUR / GBP / JPY? Proposed: normalize to USD at contract signing using the month-end FX rate, store both `ccy_original` and `usd_amount`. Deferred to v2.
2. **Contract amendments (not renewals, not expansions).** A mid-term change to `included_monthly_compute_credits` that isn't a new contract row — does it become a new row (preferred) or edit-in-place (CPQ default)? Finance Systems decision pending.
3. **Rep history.** A rep changing territory mid-year isn't representable without an SCD2 `rep_history` table. Scoped for v2 once `accounts` moves to an SCD2 design upstream.

---

## Appendix A — Rejected schema alternatives

| Alternative | Why rejected |
|---|---|
| Store `annual_commit_dollars` as `FLOAT64` | Dollar amounts never use floats — rounding errors break reconciliation |
| Enforce FK from `daily_usage_logs.account_id` to `accounts.account_id` | Would drop rogue logs on ingestion and hide DQ issues the team must actually see |
| Single `usage_logs` table with event-level detail (per API call) | Cardinality explodes (~10⁹/day at prod scale) with no analytical gain — daily roll-up is the right grain |
| Merge `contracts` and `accounts` into one wide table with array-of-contracts | Blocks time-travel queries, inflates scan cost, and prevents per-contract row-level access controls |
| Store `segment` on `accounts` redundantly (denormalized from `sales_reps`) | Creates drift risk between the two; the segment of an account *is* the segment of its current rep by definition |
| Use `TIMESTAMP` for `daily_usage_logs.date` | Timezone is meaningless for a daily roll-up and invites subtle UTC/local bugs in downstream queries |
