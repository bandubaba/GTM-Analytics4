# 03 — North Star Metric: Consumption-Adjusted ARR (`cARR`)

| Field         | Value                                                            |
|---------------|------------------------------------------------------------------|
| Spec          | `03_north_star_metric.md`                                        |
| Audience      | VP Sales, CFO, Finance, Sales Ops, RevOps, PM, data team         |
| Owner         | Principal PM, GTM Analytics                                      |
| Status        | Draft                                                            |
| Version       | 0.5                                                              |
| Last reviewed | 2026-04-19                                                       |
| Related       | [01 — Problem Statement](01_problem_statement.md), [02 — Data Model](02_data_model.md), [06 — Evaluation Framework](06_evaluation_framework.md), [10 — Glossary](10_glossary.md) |

---

## 1. Purpose and scope

### 1.1 What this spec is

The authoritative, implementation-ready definition of **cARR** — the single GTM North Star number proposed in [spec 01](01_problem_statement.md). It specifies: the formula, the inputs, how every anomaly from [spec 02's catalog](02_data_model.md) is handled, the invariants any implementation must preserve, and the parameters exposed for future tuning.

### 1.2 What this spec is NOT

- **Not a comp plan.** This spec defines the metric; how variable pay attaches to it is decided in the FY27 comp planning cycle and lives in a separate doc.
- **Not a forecast model.** `cARR` is a measurement metric, not a predictive one. A forward-looking pipeline-weighted variant is a separate spec (deferred).
- **Not a churn classifier.** We explicitly reject an ML-scored health metric for the reasons in Decision D07 ([spec 00 decision log](README.md#decision-log)).

### 1.3 Guiding principles

The metric is designed against four constraints, in priority order:

1. **Defensibility** — a rep disputing their comp can read the rule.
2. **Boundedness** — hard mathematical floor and cap per account.
3. **Stability** — smoothed over 90 days so noise doesn't drive paychecks.
4. **Reconcilability** — company total maps to a CFO-auditable `$` bound.

Every formula choice below trades against at least one of these — and the trade-off is documented.

---

## 2. Formula (authoritative)

For a given **as-of date `T`** and each **account `a`**:

```
cARR(a, T)  =  CommittedARR(a, T)  ×  HealthScore(a, T)
```

- `CommittedARR(a, T)` — sum of `annual_commit_dollars` across **all contracts** for `a` that are active on `T` (see §3.2 for active-on-T definition; overlapping contracts accumulate per Decision D04).
- `HealthScore(a, T)` — a bounded multiplier in `[0.40, 1.30]` per Decision D02, computed in §2.1.

At the **rep grain**, for a rep `r`:

```
cARR(r, T)  =  Σ  cARR(a, T)     over accounts a where accounts.rep_id = r.rep_id
```

Region / segment rollups use the same sum-over-accounts pattern.

### 2.1 HealthScore definition

Let, for account `a` and as-of date `T`:

| Symbol | Meaning | Source |
|---|---|---|
| `U(a, T)` | Trailing 90-day utilization ratio: `trailing_90d_consumed / trailing_90d_included` | §3.3, §3.4 |
| `M₁(a, T)` | Share of trailing-90-day consumption that occurred in the first 30 days of `a`'s oldest active contract | §3.5 |
| `contract_age(a, T)` | Days since `start_date` of `a`'s oldest active contract | derived |
| `expanded(a, T)` | Boolean: `a` has ≥2 contracts with overlapping `[start_date, end_date]` at any point in the trailing 365 days | derived |

Then:

```
 base(U) =
    0.40                                          if U < 0.10          # shelfware floor
    0.40 + (U − 0.10) × 0.80                       if 0.10 ≤ U ≤ 1.00   # linear ramp 0.40 → 1.12
    1.12 + min(U − 1.00, 0.30) × 0.60              if U > 1.00          # overage bonus, capped

 modifier =
    0.70    if M₁ ≥ 0.70  AND  contract_age ≥ 90   # spike-drop dampener
    1.05    if expanded                             # expansion credit
    1.00    otherwise

 HealthScore = clamp(  base(U) × modifier,  0.40,  1.30  )
```

Only one modifier applies at a time. If an account triggers **both** spike-drop and expansion (unusual but possible), spike-drop wins — a burned-then-expanded customer is not healthier than a customer with clean steady growth, and the conservative signal prevails. This tiebreak is a policy decision, not a derivation from the business logic; it is recorded as decision **D11a** and can be revisited on data.

### 2.2 Endpoint and continuity check

The base function is piecewise but continuous. Sanity values:

| `U` | `base(U)` | Archetype typically here |
|---:|---:|---|
| 0.00 | 0.40 | Shelfware (A1) |
| 0.10 | 0.40 | Ramp boundary — continuous at the floor |
| 0.50 | 0.72 | Under-utilizing but active |
| 0.80 | 0.96 | Healthy normal (A-none) |
| 1.00 | 1.12 | Fully utilizing included capacity |
| 1.20 | 1.24 | Moderate overage (A3) |
| 1.30 | 1.30 | Cap — further overage saturates |

---

## 3. Input computation

### 3.1 Trailing window

- **Window length:** 90 calendar days ending on `T` inclusive.
- **Grain:** computed daily, reported at month-end for comp purposes.
- **Rationale for 90:** matches quarterly comp cadence. See Decision D03 for rejected alternatives. Non-configurable in prod without VPS + CFO sign-off per §6.

### 3.2 "Active on `T`"

A contract `c` is **active on `T`** iff `c.start_date ≤ T ≤ c.end_date`. An account has overlapping active contracts whenever multiple contracts satisfy this simultaneously — the expected case for mid-year expansions (A4 in [spec 02](02_data_model.md)).

### 3.3 `trailing_90d_included_credits(a, T)`

For each day `d ∈ [T − 89, T]`:

```
daily_included(a, d) = Σ (c.included_monthly_compute_credits / 30)
                       for every contract c of a where c.start_date ≤ d ≤ c.end_date
```

`trailing_90d_included_credits(a, T)` is the sum of `daily_included(a, d)` over the 90-day window. Overlapping contracts **accumulate** (D04) — both capacities count because the customer committed to both.

The `/ 30` assumes a canonical 30-day month. Month-length variability is <3% and irrelevant at the 90-day grain.

### 3.4 `trailing_90d_consumed_credits(a, T)`

Sum of `compute_credits_consumed` from `daily_usage_logs` satisfying **all** of:

1. `log.account_id = a` (FK resolves — excludes A5a orphans)
2. `log.date ∈ [T − 89, T]`
3. `∃ contract c of a such that c.start_date ≤ log.date ≤ c.end_date` (excludes A5b orphans)

Both orphan classes flow to the DQ mart (see [spec 05](05_data_quality.md)) and are counted there — they do not silently disappear.

### 3.5 `M₁(a, T)` — month-1 share

Let `c*` be the **oldest active contract** of `a` on `T` (tie-breaker: smallest `contract_id`).

```
m1_window  = [ c*.start_date, c*.start_date + 29 days ]
m1_consumed = Σ compute_credits_consumed where account_id = a AND date ∈ m1_window
                                         AND date ∈ [T − 89, T]

M₁(a, T) = m1_consumed / trailing_90d_consumed_credits(a, T)
```

If `trailing_90d_consumed_credits(a, T) = 0`, `M₁` is undefined and the spike-drop modifier does **not** fire (shelfware path already covers the zero-consumption case).

### 3.6 Null and zero handling

| Condition | `U` | `HealthScore` | Rationale |
|---|---|---|---|
| No active contract on `T` | N/A | **undefined — excluded from rollups** | No commitment, no contribution |
| Active contract, `included = 0` (impossible by schema; caught by DQ) | N/A | **undefined — DQ alert** | Data integrity breach |
| Active contract, `consumed = 0` | 0.00 | 0.40 | Shelfware floor |
| Active contract, `U > 0` | numeric | per §2.1 | Normal path |

**Excluded accounts are not null rows** in the published marts — they are simply absent. The mart schema does not allow null `cARR`.

---

## 4. Edge-case handling (anomaly catalog from spec 02)

Each row below corresponds to one anomaly in [spec 02 §5](02_data_model.md#5-anomaly-catalog--known-states-of-the-world), with the metric's expected response.

| Anomaly ID | Name | Metric response | Expected `HealthScore` |
|---|---|---|---|
| A1 | Shelfware | `U = 0` → `base = 0.40`; no modifier triggers | **0.40** (floor) |
| A2 | Spike-and-drop | `U` can still be moderate (burst may be in the window), but `M₁ ≥ 0.70` + age ≥ 90d triggers dampener `×0.70` | `base × 0.70`, typically **0.30–0.55**; clamped at `0.40` floor |
| A3 | Consistent overage | `U ∈ [1.20, 1.60]` → `base` lifts past `1.12`; cap at `1.30` | **1.12–1.30** |
| A4 | Mid-year expansion | Both contracts' ARR + included sum; `expanded = true` → modifier `×1.05` | `base × 1.05`, clamped at `1.30` |
| A5a | Orphan usage — unknown account | Filtered at §3.4 step 1 | No direct effect; counted in DQ mart |
| A5b | Orphan usage — out-of-window | Filtered at §3.4 step 3 | No direct effect; counted in DQ mart |
| A6 | Overlapping contracts, non-expansion | Same math as A4 (sum both) | Same response; DQ flags for review |

### 4.1 Why spike-drop thresholds are `M₁ ≥ 0.70` AND `age ≥ 90d`

- **`M₁ ≥ 0.70`** separates the archetype (≥90% of annual credits consumed in month 1 by design) from a normal customer with an aggressive early ramp (typically `M₁ ≤ 0.35` at 90 days of contract age, because two more months of later usage sit in the denominator).
- **`age ≥ 90d`** prevents an early-ramp customer from being mislabeled as spike-drop during their *own* month 1 simply because nothing else has happened yet.

Sensitivity analysis (spec 06 T4) confirms these thresholds leave <3% of "normal" accounts incorrectly dampened.

### 4.2 Why overlapping contracts accumulate (not `max`)

A customer who signs a $150K expansion on top of a $100K base commits to **both** commercial obligations — both dollars are real. Using `max()` would under-report expansion commitment and defeat the purpose of the expansion credit modifier. Double-counting of capacity is not a risk because `U` is a *ratio*: if both numerator and denominator scale proportionally, `U` is unchanged.

Decision D04; rejected alternatives (`max()`, weighted average) in [spec 00 decision log](README.md#decision-log).

### 4.3 Why orphans are excluded, not imputed

Orphan usage indicates a **data integrity failure** upstream, not a business signal. Imputing orphan credits into a comp metric would literally be paying reps against broken data. Orphans flow to `dq_reports.orphaned_usage_daily` for the data team to fix at source. Decision D05.

---

## 5. Computation model

### 5.1 Output grain

| Mart table | Grain | Refresh | Retention |
|---|---|---|---|
| `mart_carr_by_account_day` | `account × day` | Daily, T+1 | 25 months hot |
| `mart_carr_by_account_month_end` | `account × month-end` | Monthly, M+2 calendar days | Indefinite — **comp-of-record** |
| `mart_carr_by_rep_month_end` | `rep × month-end` | Derived from above | Indefinite — **comp-of-record** |

See [spec 04](04_pipeline_architecture.md) for the physical pipeline and [spec 09](09_access_and_audit.md) for retention + audit.

### 5.2 The freeze rule (comp-of-record)

Once a **month-end snapshot** is published (M+2 calendar days after month close), rows in `mart_carr_by_*_month_end` for that month are **immutable**. Backfills or corrections to `daily_usage_logs` for past months do **not** retroactively change frozen cARR values. Corrections flow through the restatement workflow in [spec 09](09_access_and_audit.md).

**Why:** a rep's quota attainment cannot legally shift after the period closes without an explicit, logged restatement. This is a SOX-adjacent control for a metric that drives cash compensation.

### 5.3 Time-travel for rank simulations

The daily-grain table `mart_carr_by_account_day` enables "what would the rankings have been on day `D`" queries without re-running the whole pipeline. This is required by the **rank stability** eval in [spec 06 T4](06_evaluation_framework.md).

### 5.4 Determinism

- No `CURRENT_DATE()`, `NOW()`, or `CURRENT_TIMESTAMP()` in the metric SQL.
- No random sampling or non-deterministic window functions.
- As-of date `T` is always a parameter to the pipeline, never a function of execution time.

Determinism is enforced by the invariant in §7 item 5 and tested in spec 06 T1.

---

## 6. Parameters

| Parameter | Default | Range explored | Owner for change |
|---|---:|---|---|
| Window length | 90 days | 30 / 60 / 90 / 180 | VP Sales + CFO (joint) |
| `HealthScore` floor | 0.40 | 0.30–0.50 | CFO (downside risk) |
| `HealthScore` cap | 1.30 | 1.20–1.50 | VP Sales (upside) |
| Shelfware threshold (`U`) | 0.10 | 0.05–0.20 | Principal PM |
| Spike-drop threshold (`M₁`) | 0.70 | 0.60–0.80 | Principal PM |
| Spike-drop minimum contract age | 90 days | 60 / 90 / 120 | Principal PM |
| Spike-drop dampener multiplier | 0.70 | 0.50–0.80 | CFO |
| Expansion credit multiplier | 1.05 | 1.00–1.10 | VP Sales |
| Modifier precedence (tiebreak) | spike-drop > expansion | — | Principal PM |

Parameter changes require:
1. PR modifying `pipeline_and_tests/metrics/carr_params.yml` only,
2. Eval-suite diff report attached to the PR (`run_evals.py` output),
3. Spec-level approval chain from the "Owner for change" column,
4. Restatement memo if adopted after any month-end freeze.

---

## 7. Invariants

Tests under `/pipeline_and_tests/evals/` must pass before a monthly snapshot is published. See [spec 06](06_evaluation_framework.md) for the test harness; invariants below are the contract.

1. **Per-account bounds.** For every account `a` with defined `cARR(a, T)`:
   ```
   0.40 × CommittedARR(a, T)  ≤  cARR(a, T)  ≤  1.30 × CommittedARR(a, T)
   ```
2. **Company-total bounds.**
   ```
   0.40 × Σ CommittedARR(·, T)  ≤  Σ cARR(·, T)  ≤  1.30 × Σ CommittedARR(·, T)
   ```
3. **Orphan exclusion.** Removing all orphan usage logs from `daily_usage_logs` does not change any `cARR(a, T)` by more than floating-point tolerance (`1e-6`).
4. **Freeze invariant.** For any closed month `M`, re-running the pipeline from scratch produces byte-identical `mart_carr_by_*_month_end` rows for `M`.
5. **Determinism.** Same inputs → same outputs. No `NOW()`-family functions or unseeded randomness anywhere in the metric layer.
6. **No-null.** Published marts contain no rows with null `cARR`. Accounts without an active contract on `T` are absent, not null.

---

## 8. Worked examples

All `T = 2026-03-31`. Values illustrative, matched to real archetypes in the seed-42 dataset.

### 8.1 Shelfware — `ACC000412` (archetype A1)

| Input | Value |
|---|---:|
| `CommittedARR` | $220,000 |
| `trailing_90d_included_credits` | 60,000 |
| `trailing_90d_consumed_credits` | 0 |
| `U` | 0.00 |
| `base(U)` | 0.40 |
| modifier | 1.00 |
| **`HealthScore`** | **0.40** |
| **`cARR`** | **$88,000** |

> "This account is still committed on paper, but our confidence in its ARR is 40%. Renewal probability is low. Rep comp is floored at `0.40 × ACV`; CSM should be engaged."

### 8.2 Normal — `ACC000088`

| Input | Value |
|---|---:|
| `CommittedARR` | $48,000 |
| `trailing_90d_included_credits` | 12,000 |
| `trailing_90d_consumed_credits` | 9,100 |
| `U` | 0.758 |
| `base(U)` | `0.40 + 0.658 × 0.80 = 0.926` |
| modifier | 1.00 |
| **`HealthScore`** | **0.93** |
| **`cARR`** | **$44,640** |

### 8.3 Overage — `ACC000337` (archetype A3)

| Input | Value |
|---|---:|
| `CommittedARR` | $33,000 |
| `trailing_90d_included_credits` | 8,250 |
| `trailing_90d_consumed_credits` | 10,900 |
| `U` | 1.321 |
| `base(U)` | `1.12 + min(0.321, 0.30) × 0.60 = 1.30` (cap) |
| modifier | 1.00 |
| **`HealthScore`** | **1.30** |
| **`cARR`** | **$42,900** |

> "Customer consistently over-consumes included capacity. High-signal expansion lead."

### 8.4 Spike-and-drop — `ACC000577` (archetype A2)

| Input | Value |
|---|---:|
| `CommittedARR` | $120,000 |
| `trailing_90d_included_credits` | 30,000 |
| `trailing_90d_consumed_credits` | 22,000 |
| `U` | 0.733 |
| `base(U)` | 0.906 |
| `M₁` | 0.92 |
| `contract_age` | 160 days |
| modifier (spike-drop) | 0.70 |
| `base × modifier` | 0.634 |
| **`HealthScore`** (clamp) | **0.634** |
| **`cARR`** | **$76,080** |

> "Without the spike-drop rule, utilization alone would score this 0.91 — close to healthy. The dampener catches the front-loaded pattern that pure `U` misses."

### 8.5 Mid-year expansion — `ACC000121` (archetype A4)

Two active overlapping contracts: original ($80K, 20K credits/mo) and expansion ($150K, 40K credits/mo).

| Input | Value |
|---|---:|
| `CommittedARR` (sum of active) | $230,000 |
| `trailing_90d_included_credits` | `60 × 90 / 30 = 180,000` |
| `trailing_90d_consumed_credits` | 165,000 |
| `U` | 0.917 |
| `base(U)` | 1.054 |
| `expanded` | true |
| modifier (expansion) | 1.05 |
| `base × modifier` | 1.106 |
| **`HealthScore`** | **1.11** |
| **`cARR`** | **$255,300** |

---

## 9. Open questions

1. **Comp weighting — how much variable pay attaches to cARR vs. new-logo bookings.** Out of scope for this metric spec; owned by VPS + Finance in the FY27 comp-plan cycle.
2. **Multi-year contracts.** `annual_commit_dollars` is already annualized at source (see [spec 02 §3.3](02_data_model.md)). Confirm with Finance Systems before cutover.
3. **Unlimited-tier / public-sector contracts.** If any contract has `included_monthly_compute_credits = 0`, `U` is undefined. Proposed carve-out: `HealthScore = 1.00`, excluded from anomaly detection, flagged separately. Pending CFO decision.
4. **Leading-indicator companion.** `cARR` is trailing by construction. The comp plan will likely want a paired forward-looking indicator (pipeline-weighted forecast). Separate spec, deferred.
5. **Multi-currency.** Out of scope for v1. See [spec 02 §12](02_data_model.md#12-open-questions).

---

## 10. Change management

- **Formula changes** require a PR that modifies this spec + `pipeline_and_tests/metrics/carr.sql` in the same commit, with spec-level approvers.
- **Parameter changes** require a PR to `carr_params.yml` only, per §6.
- **Neither** can merge without T1 + T2 + T4 evals green ([spec 06](06_evaluation_framework.md)).
- **Published month-end snapshots are immutable** (§5.2). Corrections go through the restatement workflow in [spec 09](09_access_and_audit.md).

---

## Appendix A — Rationale for rejected alternatives

| Alternative considered | Why rejected |
|---|---|
| Pure 90-day realized consumption revenue | Throws away booking motion Sales still runs; too volatile for comp; fails stability principle (§1.3). |
| Pure Committed ARR (status quo) | Blind to shelfware / spike-drop — the problem we're solving. |
| Net Revenue Retention (NRR) | Backward-looking by 12 months; excludes new-logo motion; doesn't support quarterly comp cadence. |
| Health Score only (0–100, no `$` anchor) | Same analytical content as cARR without the dollar anchor; CFO still needs dollars on page 1. Decision D01. |
| ML-predicted churn score × ACV | No labeled training data; not explainable to reps; fails defensibility principle (§1.3). Decision D07. |
| Weighted blend: `α·ARR + β·ConsumptionRev + γ·Trajectory` | More parameters to fight over in every comp cycle; multiplier form is bounded and simpler to defend. Decision D01. |

## Appendix B — Why the bounds are `[0.40, 1.30]` specifically

- **Floor at 0.40**, not 0: a fully-contracted shelfware account still has *some* residual realization probability (renewal negotiation, migration, makegood credit). Zero would over-penalize and create the perverse incentive to hide accounts. Calibrated against internal renewal-rate data on low-utilization cohorts in the prior model era (~42% effective retention).
- **Cap at 1.30**, not unbounded: comp planning requires a per-account ceiling so one explosive overage customer does not distort quota attainment. 1.30 aligns with the 30% uplift Finance already models for "best case" overage pricing realization.
- Both endpoints are **parameters** (§6) — the defaults above are the recommended starting point and can be tuned after one full quarter of shadow-comp data.

## Appendix C — Symbol reference

See [spec 10 — Glossary](10_glossary.md) for full definitions. Quick reference:

| Symbol | Name |
|---|---|
| `T` | As-of date |
| `a` | Account |
| `r` | Sales rep |
| `U(a, T)` | Trailing-90d utilization ratio |
| `M₁(a, T)` | Month-1 consumption share |
| `base(U)` | Piecewise utilization → base health mapping |
| `modifier` | Pattern-triggered multiplier on `base` |
| `HealthScore(a, T)` | `clamp(base × modifier, 0.40, 1.30)` |
| `CommittedARR(a, T)` | Sum of active-contract ARR for `a` on `T` |
| `cARR(a, T)` | `CommittedARR × HealthScore` |
