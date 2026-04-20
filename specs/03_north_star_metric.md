# 03 — North Star Metric: Consumption-Adjusted ARR (`cARR`)

| Field         | Value                                                            |
|---------------|------------------------------------------------------------------|
| Spec          | `03_north_star_metric.md`                                        |
| Audience      | VP Sales, CFO, Finance, Sales Ops, RevOps, PM, data team         |
| Owner         | Principal PM, GTM Analytics                                      |
| Status        | Draft                                                            |
| Version       | 0.6                                                              |
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

The metric is designed against five constraints, in priority order:

1. **Defensibility** — a rep disputing their comp can read the rule.
2. **Boundedness** — hard mathematical floor and cap per account.
3. **Stability** — smoothed over 90 days so noise doesn't drive paychecks.
4. **Reconcilability** — company total maps to a CFO-auditable `$` bound.
5. **Booking fairness** — a rep closing a brand-new contract is not instantly penalized for an adoption signal that does not yet exist. Reality lag is a property of the system, not of the rep.

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
| `segment(a)` | `a`'s segment via `accounts.rep_id → sales_reps.segment` (`Enterprise` or `Mid-Market`) | [spec 02](02_data_model.md) |
| `ramp_full(segment)` | Days of full booking-trust by segment (see §2.2) | parameter |
| `ramp_end(segment)` | Day at which ramp protection ends and the original formula takes over (see §2.2) | parameter |
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

 HealthScore_steady = clamp( base(U) × modifier, 0.40, 1.30 )

 # New in v0.6 — ramp protection for new-logo fairness (Decision D12)
 w(contract_age, segment) =
     0.0                                              if contract_age ≤ ramp_full(segment)
     (contract_age − ramp_full) / (ramp_end − ramp_full)   if ramp_full < contract_age < ramp_end
     1.0                                              if contract_age ≥ ramp_end

 HealthScore = (1 − w) × 1.00  +  w × HealthScore_steady
```

**Reading the composition.** During the full-trust window (`contract_age ≤ ramp_full`) the weight `w = 0`, so `HealthScore = 1.00` and `cARR = CommittedARR` exactly. Past `ramp_end`, `w = 1` and the formula collapses to `HealthScore_steady` — identical to the v0.5 definition. In between, the two blend linearly. No cliffs; no step-functions in a rep's paycheck.

Only one modifier applies at a time. If an account triggers **both** spike-drop and expansion (unusual but possible), spike-drop wins — a burned-then-expanded customer is not healthier than a customer with clean steady growth, and the conservative signal prevails. This tiebreak is a policy decision, not a derivation from the business logic; it is recorded as decision **D11a** and can be revisited on data.

### 2.2 Ramp protection parameters

`contract_age` is measured from the `start_date` of the account's **oldest active contract**, not the most recent — this prevents a rep from gaming ramp protection by triggering a tiny contract gap at renewal (see §3.7).

| Segment | `ramp_full` (days of full trust) | `ramp_end` (ramp ends) | Rationale |
|---|---:|---:|---|
| Mid-Market | 15 | 60 | Fast time-to-value: self-serve onboarding, shorter procurement, usage signal emerges in weeks |
| Enterprise | 30 | 120 | Complex procurement, security review, multi-quarter deployment; usage signal legitimately lags |
| (unknown / `NULL`) | 30 | 120 | Conservative default — treat as Enterprise |

Segment is resolved from `accounts.rep_id → sales_reps.segment` at the **as-of date `T`**, consistent with the rest of the metric. Mid-cycle segment reassignment is out of scope for v1 (see [spec 02 §12](02_data_model.md#12-open-questions)).

See §6 for how parameter changes are controlled.

### 2.3 Endpoint and continuity checks

#### 2.3.1 `base(U)` — piecewise but continuous

| `U` | `base(U)` | Archetype typically here |
|---:|---:|---|
| 0.00 | 0.40 | Shelfware (A1) |
| 0.10 | 0.40 | Ramp boundary — continuous at the floor |
| 0.50 | 0.72 | Under-utilizing but active |
| 0.80 | 0.96 | Healthy normal (A-none) |
| 1.00 | 1.12 | Fully utilizing included capacity |
| 1.20 | 1.24 | Moderate overage (A3) |
| 1.30 | 1.30 | Cap — further overage saturates |

#### 2.3.2 Ramp blend — Enterprise shelfware example

An Enterprise account that will eventually become shelfware (`HealthScore_steady = 0.40`). Watch the blend glide from 1.00 at signing to the steady-state floor at day 120 — no step, no cliff.

| `contract_age` | `w` | `HealthScore` | cARR / ARR |
|---:|---:|---:|---:|
| 0 | 0.00 | 1.00 | 1.00 |
| 30 | 0.00 | 1.00 | 1.00 |
| 60 | 0.33 | 0.80 | 0.80 |
| 90 | 0.67 | 0.60 | 0.60 |
| 120 | 1.00 | 0.40 | 0.40 |
| 150 | 1.00 | 0.40 | 0.40 |

#### 2.3.3 Ramp blend — Mid-Market overage example

A Mid-Market account that will reach `HealthScore_steady = 1.20` (consistent overage). Upside is earned faster because MM time-to-value is faster.

| `contract_age` | `w` | `HealthScore` | cARR / ARR |
|---:|---:|---:|---:|
| 0 | 0.00 | 1.00 | 1.00 |
| 15 | 0.00 | 1.00 | 1.00 |
| 30 | 0.33 | 1.07 | 1.07 |
| 45 | 0.67 | 1.13 | 1.13 |
| 60 | 1.00 | 1.20 | 1.20 |

**Symmetry note.** Ramp protection can both *raise* a would-be shelfware account (example above) and *suppress* a would-be overage account during the trust window. This is deliberate: letting overage push a rep above 1.00 during the customer's ramp would create the inverse of the shelfware unfairness problem. Reality lag is two-sided — so the protection is two-sided.

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
| Active contract, `consumed = 0`, `contract_age ≥ ramp_end` | 0.00 | 0.40 | Steady-state shelfware floor |
| Active contract, `consumed = 0`, `contract_age < ramp_end` | 0.00 | per §2.1 blend | Ramp-protected: steady-state floor is blended with 1.00 |
| Active contract, `U > 0` | numeric | per §2.1 | Normal path (still ramp-aware) |

**Excluded accounts are not null rows** in the published marts — they are simply absent. The mart schema does not allow null `cARR`.

### 3.7 Renewal semantics (new in v0.6)

Renewals are contract-end / contract-start boundaries for the *same* account. The metric does not have a special "renewal" code path — it reuses existing mechanics — but the behavior must be explicit, because it is the #1 source of ambiguity when reps read the rule.

| Pattern | `CommittedARR(a, T)` at the boundary | `HealthScore` behavior | `contract_age` semantics |
|---|---|---|---|
| **Overlapping renewal** (expansion signed before old contract ends — A4) | Sums both contracts during overlap | `expanded = true` → `+5%` modifier | Measured from *oldest active* contract — ramp does not reset |
| **Back-to-back renewal** (new contract `start_date` = old contract `end_date + 1`) | Transitions cleanly from old ARR → new ARR | No modifier fires on the renewal itself | Measured from *oldest active* — **ramp does not reset** at the boundary |
| **Gap renewal** (new contract starts > 1 day after old ended) | Old contract's `end_date` → account has no active contract → **excluded** from rollups during gap | Not computed during gap | On new contract's start, `contract_age` *does* reset (no older active contract exists) — ramp protection applies fresh |
| **Non-renewal** (old contract ends, no replacement) | → 0 → account excluded after `end_date` | Not computed | N/A — a separate `renewal_rate` metric covers the renewal motion |

**Why `contract_age` is measured from the oldest active contract.** If `contract_age` reset on every new contract, a rep could game ramp protection by triggering a one-day gap at renewal to reset the 120-day ramp clock. Tying the clock to "oldest active" closes that loophole. The price is that a customer who truly gaps out and then re-signs (rare) enters a legitimate fresh ramp — we accept this narrow case because the alternative invites systematic gaming.

**Renewal uplift is not automatically "expansion".** If a customer renews at a higher ARR via a back-to-back (non-overlapping) new contract, the `expanded` flag does **not** fire — because `expanded` is defined on *overlapping* contracts (§2.1). Rationale: the expansion credit exists to reward the mid-term land-and-expand motion; sequential renewal uplift is a different commercial motion and is owned by a separate renewal-rate metric. This is an explicit scope choice, not an oversight — revisit if VPS argues for convergence.

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
| Ramp `ramp_full` — Mid-Market | 15 days | 7 / 15 / 30 | VP Sales + CFO (joint) |
| Ramp `ramp_end` — Mid-Market | 60 days | 30 / 60 / 90 | VP Sales + CFO (joint) |
| Ramp `ramp_full` — Enterprise | 30 days | 15 / 30 / 60 | VP Sales + CFO (joint) |
| Ramp `ramp_end` — Enterprise | 120 days | 90 / 120 / 180 | VP Sales + CFO (joint) |

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
7. **Ramp monotonicity (new in v0.6).** For any account `a` whose inputs are frozen except for `contract_age`, `HealthScore(a, T)` is monotone in `contract_age` **toward** `HealthScore_steady(a, T)` — either non-decreasing (if `HealthScore_steady < 1.00`) or non-increasing (if `HealthScore_steady > 1.00`). The blend never overshoots `HealthScore_steady`. This is tested in [spec 06 T4](06_evaluation_framework.md) as part of the monotonicity check.
8. **Ramp collapse.** When `contract_age ≥ ramp_end(segment)` for every active contract of `a`, `HealthScore(a, T) = HealthScore_steady(a, T)` exactly — no residual ramp contribution. This guarantees steady-state accounts match v0.5 behavior bit-for-bit, so v0.5 comparability for regression tests remains intact.

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
| **`HealthScore_steady`** | **1.11** |
| `contract_age` | 400 days (far past `ramp_end`) |
| `w` | 1.00 |
| **`HealthScore`** | **1.11** |
| **`cARR`** | **$255,300** |

### 8.6 New-logo Enterprise — worked at 4 points in time (new in v0.6)

An Enterprise contract signed 2026-02-15 for $600K ARR. The customer will eventually settle into healthy utilization (`HealthScore_steady ≈ 0.93`). Segment: `Enterprise` → `ramp_full = 30`, `ramp_end = 120`.

We evaluate at four as-of dates — `T₀ = 2026-02-20` (5 days in), `T₁ = 2026-03-15` (28 days in), `T₂ = 2026-04-30` (74 days in), `T₃ = 2026-07-01` (136 days in, past ramp). Assume usage has started ramping and `HealthScore_steady` rises smoothly from 0.40 at T₀ to 0.93 at T₃ as adoption builds.

| As-of | `contract_age` | `HealthScore_steady` (computed) | `w` | `HealthScore` (final) | `cARR` |
|---|---:|---:|---:|---:|---:|
| T₀ 2026-02-20 | 5 | 0.40 | 0.00 | **1.00** | **$600,000** |
| T₁ 2026-03-15 | 28 | 0.55 | 0.00 | **1.00** | **$600,000** |
| T₂ 2026-04-30 | 74 | 0.78 | 0.49 | **0.89** | **$534,000** |
| T₃ 2026-07-01 | 136 | 0.93 | 1.00 | **0.93** | **$558,000** |

Reading the table:

- **T₀–T₁ (first 30 days).** The rep gets full booking credit. No usage signal is yet available that could legitimately discount the ARR; any discount would be punishing the rep for lag, not performance.
- **T₂ (74 days in).** Blended. The adoption signal is real but not yet definitive; we give it half-weight. cARR has come down from $600K → $534K as the customer's slow ramp becomes visible.
- **T₃ (136 days in, past ramp).** Full steady-state formula. The customer has reached healthy utilization (0.93); cARR settles at $558K. The rep finished the year at 93% of the booking — a fair reflection of a mostly-healthy account.

**Without ramp protection**, T₀ would have been $240K (0.40 × $600K) on a contract that was literally 5 days old. The rep would have lost $360K in visible North Star value overnight, despite doing exactly the job the old comp plan paid them to do.

---

## 9. Open questions

1. **Comp weighting — how much variable pay attaches to cARR vs. new-logo bookings.** Out of scope for this metric spec; owned by VPS + Finance in the FY27 comp-plan cycle.
2. **Multi-year contracts.** `annual_commit_dollars` is already annualized at source (see [spec 02 §3.3](02_data_model.md)). Confirm with Finance Systems before cutover.
3. **Unlimited-tier / public-sector contracts.** If any contract has `included_monthly_compute_credits = 0`, `U` is undefined. Proposed carve-out: `HealthScore = 1.00`, excluded from anomaly detection, flagged separately. Pending CFO decision.
4. **Leading-indicator companion.** `cARR` is trailing by construction. The comp plan will likely want a paired forward-looking indicator (pipeline-weighted forecast). Separate spec, deferred.
5. **Multi-currency.** Out of scope for v1. See [spec 02 §12](02_data_model.md#12-open-questions).
6. **Segment drift mid-ramp (new in v0.6).** If a rep changes segment (MM → ENT) while an account is still in ramp protection, which segment's ramp curve applies? Current spec: segment is resolved at `T`, so the ramp window changes mid-flight. Alternative: pin segment to contract start. Proposal: pin at contract start, to keep the rep's signed ramp bargain stable. Pending Sales Ops review.
7. **Sequential-renewal uplift (new in v0.6).** §3.7 excludes back-to-back renewal uplift from the expansion credit. If shadow-comp data shows this is consistently reps landing legitimate expansion via non-overlapping renewal, revisit — possibly by extending the `expanded` definition to "new-contract ARR > prior-contract ARR within 30 days" regardless of overlap.

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
| **No ramp protection** (v0.5 behavior) | Penalizes reps for adoption lag that is structurally outside their control; produces `0.40 × ARR` on day-1 bookings. Violates booking-fairness principle (§1.3 item 5). Decision D12. |
| **Hard grace period then cliff** (e.g., `HealthScore = 1.00` for 90 days then snap to computed) | Creates a day-91 cliff that can move a rep's comp by tens of percent overnight. Fails stability principle. Decision D12. |
| **Expected-ramp curve from historical data** (industry or internal calibration as denominator for `U`) | Requires historical adoption curves we don't have yet; adds an empirically fitted curve surface that the CFO cannot read off the rule. Revisit after one full quarter of shadow-comp data. Decision D12. |
| **Single ramp curve across segments** | ENT and MM ramps differ by 2–3× in reality; forcing one curve either under-protects ENT or over-protects MM. Segment-aware defaults are the lower-regret choice. |
| **Reset `contract_age` on every new contract** | Opens a gaming vector: a rep could induce a one-day contract gap at renewal to reset the ramp clock and re-earn 120 days of full booking trust. Anchor to oldest active contract instead (§3.7). |

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
| `HealthScore_steady(a, T)` | `clamp(base × modifier, 0.40, 1.30)` — the v0.5 formula |
| `ramp_full(segment)`, `ramp_end(segment)` | Segment-aware ramp window parameters (§2.2) |
| `contract_age(a, T)` | Days since `start_date` of `a`'s oldest active contract |
| `w(contract_age, segment)` | Ramp blend weight in `[0, 1]` — see §2.1 |
| `HealthScore(a, T)` | `(1 − w) × 1.00 + w × HealthScore_steady` — the v0.6 formula |
| `CommittedARR(a, T)` | Sum of active-contract ARR for `a` on `T` |
| `cARR(a, T)` | `CommittedARR × HealthScore` |

## Appendix D — v0.5 → v0.6 change summary

| Section | Change | Reason |
|---|---|---|
| §1.3 | Added 5th guiding principle: **booking fairness** | New-logo unfairness was the largest unaddressed attack surface in v0.5 |
| §2.1 | Introduced `HealthScore_steady` and a ramp-blended `HealthScore` | The core change — ramp protection for new-logo reps |
| §2.2 (new) | Segment-aware `ramp_full` / `ramp_end` parameters | ENT and MM have structurally different ramp realities |
| §2.3 | Added ramp-curve continuity tables | Defensibility — the blend is smooth and visible |
| §3.6 | Added ramp-awareness rows to the null/zero table | Disambiguate shelfware-floor from ramp-blended-floor |
| §3.7 (new) | Explicit renewal semantics | Most common rep question; needed a single-source answer |
| §6 | 4 new rows for ramp parameters | Make the knobs reviewable |
| §7 | 2 new invariants: ramp monotonicity, ramp collapse | Guarantee behavior; auto-testable |
| §8.6 (new) | Worked example for an Enterprise new-logo across 4 time-points | The single most important example for the exec pitch |
| §9 | 2 new open questions (segment drift, sequential-renewal uplift) | Surface the v0.6 residuals honestly |
| Appendix A | 5 new rejected alternatives | Show the shape of the decision, not just the answer |

All v0.5 worked examples (8.1–8.5) remain valid bit-for-bit because `contract_age ≥ ramp_end` in each — this is the Ramp collapse invariant (§7 item 8). v0.5 and v0.6 agree on steady-state accounts.
