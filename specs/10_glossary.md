# 10 — Glossary

| Field         | Value                                 |
|---------------|---------------------------------------|
| Spec          | `10_glossary.md`                      |
| Audience      | Everyone                              |
| Owner         | Principal PM, GTM Analytics           |
| Status        | Draft                                 |
| Version       | 0.1                                   |
| Last reviewed | 2026-04-19                            |
| Related       | All specs                             |

---

## Why this glossary exists

Because "utilization" means three different things in three different rooms, and we cannot afford that ambiguity when a rep's paycheck depends on it. This is the **one source of truth** for business and technical terms used across spec 01–09. If a term appears in any spec and is not defined here or in a specific section of another spec, it is a bug in this glossary — file a PR.

Entries cite the spec where the term is **authoritatively defined**. This glossary is for orientation; the spec is for adjudication.

---

## A

**Account**
A customer entity represented by one row in [`accounts`](02_data_model.md#32-accounts). An account is never a department or business unit — separately contracted BUs get separate `account_id`s.

**`account_id`**
Stable customer identifier of the form `ACC<nnnnnn>`. PK of `accounts`; FK in `contracts`; soft FK in `daily_usage_logs` (nullable).

**Active (contract)**
A contract `c` is active on date `T` iff `c.start_date ≤ T ≤ c.end_date`. See [spec 03 §3.2](03_north_star_metric.md#32-active-on-t).

**Active contract count**
Number of contracts active for an account on a given day; used to detect overlap (expansion or A6).

**ACV**
Annual Contract Value. Synonymous with `annual_commit_dollars` for single-year contracts. For multi-year, `annual_commit_dollars` is the annualized equivalent.

**Anomaly**
A pattern in the data that deviates from the implicit "steady utilization of committed capacity" baseline. Formalized in [spec 02 §5](02_data_model.md#5-anomaly-catalog--known-states-of-the-world). Not necessarily a data *error* — shelfware and overage are valid business states.

**`annual_commit_dollars`**
USD commitment for a contract, annualized. `NUMERIC(18,2)`. Never `FLOAT64`.

**ARR (Annual Recurring Revenue)**
Sum of `annual_commit_dollars` across active contracts at a point in time. The **legacy** GTM North Star this initiative replaces.

**As-of date (`T`)**
The date the metric is computed for. Always a parameter, never `CURRENT_DATE()`. Enforced by [spec 03 §5.4](03_north_star_metric.md#54-determinism) determinism rule.

**Assertion**
A single named test run by the DQ suite. Catalogued in [spec 05 §4](05_data_quality.md#4-assertion-catalog). Each assertion has a stable ID (`DQ-<category>-<nnn>`).

**AUC-PR**
Area under the precision-recall curve. Used in [spec 06 T3-001](06_evaluation_framework.md#t3-001-head-to-head-on-at-risk-identification) to measure cARR's advantage over baselines at identifying at-risk accounts.

**Audit trail**
Immutable record of access, writes, and changes against SOX-scoped tables. See [spec 09 §5](09_access_and_audit.md#5-audit-trail).

**Authorized View**
A BigQuery view that encapsulates a row-level filter; end users are granted the view, not the underlying table. The mechanism for rep-level RLS per [spec 09 §4.3](09_access_and_audit.md#43-row-level-security-implementation).

## B

**`base(U)`**
The piecewise-linear utilization-to-health-score mapping. Continuous at the knee points. See [spec 03 §2.1](03_north_star_metric.md#21-healthscore-definition). Not clamped — clamping is applied after the modifier.

**Break-glass access**
Time-boxed, audited elevated access for incident response or forensic queries. Process in [spec 09 §4.4](09_access_and_audit.md#44-break-glass-access).

## C

**`cARR` (Consumption-Adjusted ARR)**
The North Star metric. `cARR(a, T) = CommittedARR(a, T) × HealthScore(a, T)`. Bounded by `HealthScore` to `[0.40 × ARR, 1.30 × ARR]` per [spec 03](03_north_star_metric.md).

**Clamp**
The operation enforcing the `[0.40, 1.30]` bounds on `HealthScore`. Applied after `base × modifier`. Mathematical detail in [spec 03 §2.1](03_north_star_metric.md#21-healthscore-definition).

**Classification (data)**
Sensitivity label on a table. One of `Internal`, `Confidential`, `Confidential + PII`, `Confidential — Financial (SOX)`. Per [spec 02 §9](02_data_model.md#9-data-classification) and [spec 09 §2](09_access_and_audit.md#2-data-classification). Derived tables inherit the highest classification of their inputs.

**Cluster (BigQuery clustering)**
Storage organization that sorts rows by specified columns for faster filter pruning. We cluster `daily_usage_logs` on `account_id`. Has no expiration side-effect (unlike partitioning in sandbox — see D09).

**Committed ARR**
Sum of `annual_commit_dollars` for contracts active on `T`. Overlapping contracts **accumulate** (decision D04). The CFO's anchor number.

**`compute_credits_consumed`**
Daily aggregate of customer's credit usage. `NUMERIC(18,2)`, always ≥ 0.

**Construct validity**
Whether cARR's ranking of accounts matches what the formula was designed to rank. Tier 2 of the eval framework ([spec 06 §5](06_evaluation_framework.md#5-tier-2--construct-validity)).

**Contract**
A commercial commitment between a customer and the company. One row in `contracts`. Mid-term expansions are **separate rows**, never edits of existing rows.

**Contract age**
Days since the start of the account's **oldest active contract**, evaluated at `T`. Used by the spike-drop modifier to avoid mis-classifying a month-1 customer.

**Comp-of-record**
The mart tables whose month-end snapshots are immutable once published: `mart_carr_by_account_month_end`, `mart_carr_by_rep_month_end`, `mart_carr_restatements`. See [spec 03 §5.2](03_north_star_metric.md#52-the-freeze-rule-comp-of-record).

## D

**`daily_included(a, d)`**
For each active contract, `included_monthly_compute_credits / 30`, summed across active contracts. See [spec 03 §3.3](03_north_star_metric.md#33-trailing_90d_included_creditsa-t).

**`daily_usage_logs`**
Fact table of per-day per-account credit consumption. One of the four source tables in [spec 02](02_data_model.md).

**Data Platform (team)**
Owns `raw.*` extraction and ingestion. See RBAC matrix in [spec 09 §3](09_access_and_audit.md#3-rbac-matrix).

**Data Quality (DQ)**
Catalog of assertions, severity tiers, and alerting. [Spec 05](05_data_quality.md).

**Decision log**
ADR-style record of the contested choices in the spec stack. Lives in [`specs/README.md`](README.md#decision-log).

**Decision utility**
Whether cARR beats naive alternatives at identifying at-risk accounts. Tier 3 of the eval framework ([spec 06 §6](06_evaluation_framework.md#6-tier-3--decision-utility)).

**Determinism**
Same inputs → same outputs. No `NOW()`-family functions, no unseeded randomness. Invariant 5 in [spec 03 §7](03_north_star_metric.md#7-invariants).

**`dq.*` tables**
`dq.assertion_results`, `dq.orphaned_usage_daily`, `dq.eval_results`. See [spec 05 §5](05_data_quality.md#5-where-results-surface).

## E

**Eval / evaluation framework**
The 4-tier framework for deciding whether cARR is fit for purpose. [Spec 06](06_evaluation_framework.md).

**`expanded(a, T)`**
Boolean: account has ≥2 contracts with overlapping `[start_date, end_date]` in the trailing 365 days. Triggers the expansion credit modifier `×1.05`.

**Expansion**
Anomaly A4 in [spec 02 §5](02_data_model.md#5-anomaly-catalog--known-states-of-the-world). A mid-year expansion contract on top of an existing one; the #1 behavior a consumption model should reward.

**Expansion credit**
`×1.05` modifier applied when `expanded = true`. Small by design — the bulk of the "expansion reward" comes from higher `U` due to extra capacity being consumed. Decision D11.

## F

**Faker**
Python library used to generate synthetic company/person names. See [`data_generation/generate_data.py`](../data_generation/generate_data.py).

**Floor (HealthScore)**
The `0.40` lower bound. Prevents shelfware accounts from contributing zero to comp, which would create perverse incentives. Calibrated to historical renewal-rate of low-utilization cohorts. [Spec 03 Appendix B](03_north_star_metric.md#appendix-b--why-the-bounds-are-040-130-specifically).

**Freeze rule**
Month-end mart snapshots are immutable once published. Corrections flow via restatement, not mutation. [Spec 03 §5.2](03_north_star_metric.md#52-the-freeze-rule-comp-of-record).

## G

**Grain**
The cardinality unit of a table. E.g., `mart_carr_by_account_day` has grain `account × day`. Every mart's grain is documented in [spec 04 §3](04_pipeline_architecture.md#3-layer-responsibilities-and-invariants).

## H

**`HealthScore(a, T)`**
Bounded multiplier in `[0.40, 1.30]` applied to `CommittedARR` to produce `cARR`. Computed as `clamp(base(U) × modifier, 0.40, 1.30)`. [Spec 03 §2.1](03_north_star_metric.md#21-healthscore-definition).

## I

**Idempotent**
A pipeline is idempotent if running it multiple times with the same inputs produces the same outputs. Our pipeline is idempotent via `WRITE_TRUNCATE`. [Spec 04 §7.1](04_pipeline_architecture.md#71-idempotency).

**Immutable (snapshot)**
Once published, comp-of-record rows cannot be mutated. See freeze rule.

**`included_monthly_compute_credits`**
Contract entitlement: credits included per month of the contract term. Used as the denominator of `U`. `INT64`, always > 0 at the schema level (unlimited-tier is an open question per [spec 03 §9](03_north_star_metric.md#9-open-questions)).

**`int_*` tables**
Intermediate layer of the pipeline; `int_account_day`, `int_contract_day`. Denormalized per-day per-account state. [Spec 04 §3.3](04_pipeline_architecture.md#33-intermediate-int_).

**Invariant**
A property any valid implementation must preserve. Metric-layer invariants in [spec 03 §7](03_north_star_metric.md#7-invariants); data-quality invariants in [spec 05 §4](05_data_quality.md).

## M

**`M₁` (month-1 share)**
Fraction of trailing-90-day consumption that fell in the first 30 days of the account's oldest active contract. Triggers the spike-drop dampener when `M₁ ≥ 0.70` AND contract age ≥ 90 days. [Spec 03 §3.5](03_north_star_metric.md#35-m₁a-t--month-1-share).

**Mart**
The stable, audience-facing table layer. `mart_carr_by_*`. Read by dashboards, comp engine, ad-hoc analysts.

**MFA**
Multi-factor authentication. Required for all roles touching SOX-scoped tables. [Spec 09 §4.1](09_access_and_audit.md#41-identity).

**Modifier**
Pattern-triggered multiplier on `base(U)` in `HealthScore`. Values: `0.70` (spike-drop), `1.05` (expansion), or `1.00` (default). One at a time; tiebreak spike-drop > expansion per D11a.

## O

**Observation window**
The time range `[WINDOW_START, WINDOW_END]` the synthetic generator produces and the pipeline processes. Currently `[2025-01-01, 2026-04-18]`.

**Orphan (usage)**
A row in `daily_usage_logs` that either (A5a) has an unknown `account_id` or (A5b) has a valid `account_id` but a `date` outside any active contract. **Excluded from the metric**, **counted in DQ reports**. Decision D05.

**Overage**
Anomaly A3: consistent consumption above `included_monthly_compute_credits`. Organic expansion signal. Health-score boost, capped at `1.30`.

**Overlap (contract)**
Two or more contracts for the same account have `[start_date, end_date]` intervals that intersect. Expected case for mid-year expansion (A4).

## P

**P0 / P1 / P2**
DQ severity tiers. P0 blocks mart publication, P1 warns with SLA, P2 is informational. [Spec 05 §3](05_data_quality.md#3-severity-tiers).

**Partition (BigQuery)**
Physical table splitting by a date column for predicate pruning. We partition by `MONTH` on `date` in **prod**; **not** in sandbox due to the 60-day expiration constraint (decision D09).

**PII**
Personally identifiable information. `sales_reps.name` is PII. Classification implications in [spec 09 §2](09_access_and_audit.md#2-data-classification).

## R

**Raw layer**
Lossless landing zone for source-of-record extracts. `raw.*` tables. No filtering at this layer — even orphaned usage lands.

**RBAC**
Role-based access control. Matrix in [spec 09 §3](09_access_and_audit.md#3-rbac-matrix).

**Reconciliation**
Checking that two independently-computed numbers agree. E.g., `stg_clean + stg_orphans = raw`, or `mart_carr_by_rep = sum(mart_carr_by_account)` for that rep. [Spec 05 §4.6](05_data_quality.md#46-reconciliation--dq-recon).

**Renewal**
A new contract that starts near an old one's end date, with a mild price uplift, on the same account. Distinct from an **expansion** (which overlaps).

**Rep**
Sales Rep. One row in `sales_reps`. Owns some set of `accounts` at a given time.

**Restatement**
Formal correction to a closed (frozen) month's mart snapshot. **Never mutates** the frozen row; instead appends to `mart_carr_restatements` with approver chain. [Spec 04 §7.2](04_pipeline_architecture.md#72-backfills).

**RLS**
Row-level security. Implemented via Authorized Views in [spec 09 §4.3](09_access_and_audit.md#43-row-level-security-implementation).

**Runbook**
Documented incident-response procedure. Stubs referenced in [spec 04 §10](04_pipeline_architecture.md#10-runbook-hooks).

## S

**Sandbox (BigQuery)**
Free-tier BQ environment. Constraints: 10 GB storage, 1 TB scan/month, **60-day partition expiration (un-overridable)**. Our choice to not partition in sandbox (decision D09) directly follows from this last constraint.

**Segment**
`Enterprise` or `Mid-Market`. Enum on `sales_reps`; inherits to `accounts` via the rep.

**Shelfware**
Anomaly A1: account has contracts but zero usage logs. 10% of the synthetic dataset by design. The signal the metric most needs to surface.

**Shadow comp**
Phase 2 of the rollout: comp is computed both ways but only the legacy method pays. The most important phase. [Spec 08 §6](08_rollout_plan.md#6-phase-2--shadow-comp).

**Snapshot (month-end)**
The `mart_carr_by_*_month_end` rows published at M+2. Immutable once published.

**SOX**
Sarbanes-Oxley Act. Financial-records and controls regulation. Comp-of-record tables are SOX-adjacent; controls per [spec 09 §2](09_access_and_audit.md#2-data-classification).

**Spike-and-drop (spike_drop)**
Anomaly A2: ~90% of annual credits burned in first 30 days, then near-zero. Triggers `×0.70` modifier on health score.

**SSO**
Single sign-on. Corporate OIDC provider; gates all human access to cARR data.

**Staging (`stg_*`)**
Typed, validated layer between `raw.*` and `int_*`. Splits usage into `stg_usage_logs_clean` and `stg_usage_logs_orphans`. Invariant: `clean + orphans = raw`. Tested.

## T

**`T` (as-of date)**
See As-of date.

**T1 / T2 / T3 / T4 / T5**
Evaluation framework tiers. T1 Correctness, T2 Construct validity, T3 Decision utility, T4 Comp safety, T5 Transition fidelity. T1, T4, T5 are stop-the-line (blocking); T2, T3 warn but continue. T5 added in spec 06 v0.2 to catch regressions in the five pricing-pivot failure modes. [Spec 06](06_evaluation_framework.md).

**Tie-break (modifier precedence)**
When both spike-drop and expansion modifiers could apply, spike-drop wins. Decision D11a in [spec 03 §2.1](03_north_star_metric.md#21-healthscore-definition).

**Trailing 90-day window**
`[T − 89, T]`. The window over which `U` is computed. 90 days is non-configurable in prod without VPS + CFO sign-off.

## U

**`U` (Utilization ratio)**
`trailing_90d_consumed_credits / trailing_90d_included_credits`. The core input to `base(U)`. See [spec 03 §3](03_north_star_metric.md#3-input-computation).

## W

**`WINDOW_START` / `WINDOW_END`**
Observation window bounds configured in [`data_generation/config.py`](../data_generation/config.py). Currently `[2025-01-01, 2026-04-18]`.

**`WRITE_TRUNCATE`**
BigQuery load disposition that replaces the entire table contents. Enables pipeline idempotency. [Spec 04 §7.1](04_pipeline_architecture.md#71-idempotency).

---

## Acronyms

| Acronym | Expansion | Where used |
|---|---|---|
| ACV | Annual Contract Value | Throughout |
| ADR | Architecture Decision Record | Spec 00 decision log pattern |
| ARR | Annual Recurring Revenue | Throughout |
| AUC | Area Under the Curve | Spec 06 T3-001 |
| BQ | BigQuery | Throughout |
| CDC | Change Data Capture | Spec 02 §11 |
| CPQ | Configure-Price-Quote | Spec 02 §11 |
| CSM | Customer Success Manager | Spec 01 §4.4 |
| DAG | Directed Acyclic Graph | Spec 04 §8.1 lineage |
| DPIA | Data Protection Impact Assessment | Spec 09 §1.2 |
| DQ | Data Quality | Spec 05 |
| EL / ELT | Extract-Load / Extract-Load-Transform | Spec 04 |
| FK | Foreign Key | Spec 02 |
| GDPR | General Data Protection Regulation | Spec 09 §7.3 |
| HR | Human Resources | Spec 09 |
| IAM | Identity and Access Management | Spec 09 |
| MFA | Multi-Factor Authentication | Spec 09 §4.1 |
| NRR | Net Revenue Retention | Spec 03 Appendix A |
| OIDC | OpenID Connect | Spec 09 §4.1 |
| PI / PII | Personal Information / Personally Identifiable Information | Spec 02, 09 |
| PK | Primary Key | Spec 02 |
| PR | Pull Request | Throughout |
| PR (curve) | Precision-Recall | Spec 06 |
| RBAC | Role-Based Access Control | Spec 09 |
| RLS | Row-Level Security | Spec 09 §4.3 |
| SCD2 | Slowly Changing Dimension Type 2 | Spec 02 §12 |
| SIEM | Security Information and Event Management | Spec 09 §5, §8 |
| SLA | Service Level Agreement | Spec 04, 05, 07 |
| SOX | Sarbanes-Oxley Act | Spec 09 |
| SSO | Single Sign-On | Spec 09 |
| SRE | Site Reliability Engineering | Spec 04 audience |

---

## Decision IDs reference

Full decision log in [specs/README.md](README.md#decision-log). Quick reference:

| ID | Short form |
|---|---|
| D01 | cARR is multiplicative: `ARR × HealthScore` |
| D02 | HealthScore bounded `[0.40, 1.30]` |
| D03 | 90-day trailing window, non-configurable in prod |
| D04 | Overlapping contracts accumulate (not max) |
| D05 | Orphans excluded from metric, flagged in DQ |
| D06 | Month-end snapshots are frozen (immutable) |
| D07 | Deterministic SQL over ML |
| D08 | BigQuery as warehouse |
| D09 | No time partitioning in sandbox; clustering only |
| D10 | Spike-drop detection via rule (`M₁ ≥ 0.70` AND age ≥ 90d) |
| D11 | Expansion credit is a `+5%` modifier |
| D11a | Modifier precedence: spike-drop beats expansion |

---

## How to propose a glossary change

1. Term not defined where you expected? PR this file with the new entry citing the spec that introduces it.
2. Definition wrong or outdated? PR this file with the correction, and link the spec section that establishes authority.
3. Term is used in a spec but isn't here? That's a bug — PR both the spec (to clarify context) and this file.

Principle: **this glossary never invents a definition; it cites one.** If no spec authoritatively defines a term, add the definition to the owning spec first, then mirror here.
