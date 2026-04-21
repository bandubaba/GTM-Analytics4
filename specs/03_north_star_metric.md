# 03 — North Star Metric: Consumption-Adjusted ARR (`cARR`)

| Field         | Value                                                            |
|---------------|------------------------------------------------------------------|
| Spec          | `03_north_star_metric.md`                                        |
| Audience      | VP Sales, CFO, Finance, Sales Ops, RevOps, PM, data team         |
| Owner         | Principal PM, GTM Analytics                                      |
| Status        | Draft                                                            |
| Version       | 0.7.1                                                            |
| Last reviewed | 2026-04-21                                                       |
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
| `expanded(a, T)` | Boolean: `a` has ≥2 contracts with overlapping `[start_date, end_date]` at any point in the trailing 365 days | derived |

Then:

```
 base(U) =
    0.40                                          if U < 0.30          # shelfware floor
    0.40 + (U − 0.30) × 1.50                       if 0.30 ≤ U < 0.70   # linear ramp 0.40 → 1.00
    1.00                                          if 0.70 ≤ U ≤ 1.10   # healthy plateau
    1.00 + min(U − 1.10, 0.20) × 1.00              if U > 1.10          # expansion/overage, base capped at 1.20

 modifier =
    0.50    if M₁ ≥ 0.70  AND  contract_age ≥ 90   # spike-drop dampener
    1.10    if expanded                             # expansion credit
    1.00    otherwise

 HealthScore = clamp( base(U) × modifier, 0.40, 1.30 )
```

> **v0.7.1 calibration note.** Three values above moved on 2026-04-21 after an attainment-chart review showed healthy-band accounts (U ∈ [0.70, 0.80]) being systematically dragged below 1.00, a weak spike-drop penalty, and a negligible expansion bump. See Appendix D (v0.7.1) and [D13 in the decision log](README.md#decision-log).

Only one modifier applies at a time. If an account triggers **both** spike-drop and expansion (unusual but possible), spike-drop wins — a burned-then-expanded customer is not healthier than a customer with clean steady growth, and the conservative signal prevails. This tiebreak is a policy decision, not a derivation from the business logic; it is recorded as decision **D11a** and can be revisited on data.

**New logos without a usage signal yet.** When `U` is undefined (no expected credits yet, or contract just signed and no usage has posted), `base(U)` defaults to 1.00 via the null branch in §3.6. The modifier is 1.00 (spike-drop requires ≥90d age; expansion requires overlap + `U > 1.0`), so `HealthScore = 1.00` and `cARR = CommittedARR` exactly — the rep earns full booking credit during the pre-signal window without a separate ramp parameter.

### 2.2 Removed — ramp-blended HealthScore (v0.6 only)

v0.6 carried a segment-aware ramp blend `HealthScore = (1 − w) · 1.00 + w · HealthScore_steady` with `w` rising from 0 to 1 across a `[ramp_full, ramp_end]` window. v0.7 drops it. Two reasons:

1. **Parameter fight surface.** The ramp windows (`ramp_full` / `ramp_end` per segment) introduced four new tuning parameters that every comp cycle would re-litigate. Every knob is debt.
2. **Defensibility over cleverness.** The blend was mathematically smooth but visually two curves glued together. A CFO can read `clamp(base × modifier, 0.40, 1.30)` in one breath; the blended version takes three.

New-logo comp fairness is preserved by the `U IS NULL → base = 1.00` path in §3.6: an account with no measurable usage yet lands at `HealthScore = 1.00`. This handles the first-30-day "no signal yet" case without the blend. Accounts that *do* have early usage and the usage is light will now score below 1.00 — a known and accepted trade-off. If shadow-comp data shows systematic rep harm from this, revisit with a simpler single-parameter "grace floor" (e.g., `HealthScore = max(HS_steady, 0.80)` for `contract_age < 30d`) rather than reintroducing the full blend.

### 2.3 Endpoint and continuity checks

#### 2.3.1 `base(U)` — piecewise but continuous

| `U` | `base(U)` | Archetype typically here |
|---:|---:|---|
| 0.00 | 0.40 | Shelfware (A1) |
| 0.30 | 0.40 | Shelfware boundary — continuous at the floor |
| 0.50 | 0.70 | Under-utilizing but active |
| 0.70 | 1.00 | Healthy plateau begins — no more under-use penalty |
| 0.90 | 1.00 | Healthy normal (A-none) |
| 1.10 | 1.00 | Healthy plateau ends — right at included capacity |
| 1.20 | 1.10 | Moderate overage (A3) |
| 1.30 | 1.20 | Base cap — further overage saturates before the modifier is applied |

The plateau is wider than in v0.7.0 ([0.70, 1.10] instead of [0.80, 1.10]). Rationale: enterprise customers routinely run at 70–85% of included capacity by design — this is not a rep-accountable problem and should not drag attainment. See Appendix D (v0.7.1) and D13.

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
| Active contract, **no usage posted yet** (`trailing_90d_included = 0` because contract just signed, or `consumed` is null) | undefined | 1.00 | No signal; trust the booking. This is the "pre-signal" path referenced in §2.1. |
| Active contract, `consumed = 0` over a full 90-day window | 0.00 | 0.40 | Shelfware floor |
| Active contract, `U > 0` | numeric | per §2.1 | Normal path |

**Excluded accounts are not null rows** in the published marts — they are simply absent. The mart schema does not allow null `cARR`.

### 3.7 Renewal semantics

Renewals are contract-end / contract-start boundaries for the *same* account. The metric does not have a special "renewal" code path — it reuses existing mechanics — but the behavior must be explicit, because it is the #1 source of ambiguity when reps read the rule.

| Pattern | `CommittedARR(a, T)` at the boundary | `HealthScore` behavior | `contract_age` semantics |
|---|---|---|---|
| **Overlapping renewal** (expansion signed before old contract ends — A4) | Sums both contracts during overlap | `expanded = true` → `+5%` modifier | Measured from *oldest active* contract |
| **Back-to-back renewal** (new contract `start_date` = old contract `end_date + 1`) | Transitions cleanly from old ARR → new ARR | No modifier fires on the renewal itself | Measured from *oldest active* contract |
| **Gap renewal** (new contract starts > 1 day after old ended) | Old contract's `end_date` → account has no active contract → **excluded** from rollups during gap | Not computed during gap | On new contract's start, `contract_age` *does* reset (no older active contract exists) |
| **Non-renewal** (old contract ends, no replacement) | → 0 → account excluded after `end_date` | Not computed | N/A — a separate `renewal_rate` metric covers the renewal motion |

**Why `contract_age` is measured from the oldest active contract.** The ramp blend has been removed (§2.2), but `contract_age` is still used as the age guard on the spike-drop modifier. Measuring from the oldest active contract prevents a rep from gaming the spike-drop lookback with a one-day contract gap at renewal. Tying the clock to "oldest active" closes that loophole. The price is that a customer who truly gaps out and then re-signs (rare) enters a legitimate fresh lookback — we accept this narrow case because the alternative invites systematic gaming.

**Renewal uplift is not automatically "expansion".** If a customer renews at a higher ARR via a back-to-back (non-overlapping) new contract, the `expanded` flag does **not** fire — because `expanded` is defined on *overlapping* contracts (§2.1). Rationale: the expansion credit exists to reward the mid-term land-and-expand motion; sequential renewal uplift is a different commercial motion and is owned by a separate renewal-rate metric. This is an explicit scope choice, not an oversight — revisit if VPS argues for convergence.

---

## 4. Edge-case handling (anomaly catalog from spec 02)

Each row below corresponds to one anomaly in [spec 02 §5](02_data_model.md#5-anomaly-catalog--known-states-of-the-world), with the metric's expected response.

| Anomaly ID | Name | Metric response | Expected `HealthScore` |
|---|---|---|---|
| A1 | Shelfware | `U < 0.30` → `base = 0.40`; no modifier triggers | **0.40** (floor) |
| A2 | Spike-and-drop | `U` can still be moderate (burst may be in the window), but `M₁ ≥ 0.70` + age ≥ 90d triggers dampener `×0.50` | `base × 0.50`, typically **0.40–0.55** (floor-bound for plateau cases) |
| A3 | Consistent overage | `U ∈ [1.20, 1.60]` → `base` lifts to `1.10–1.20`; capped at `1.20` before modifier | **1.10–1.20** (HS cap at 1.30 only engages with the expansion modifier) |
| A4 | Mid-year expansion | Both contracts' ARR + included sum; `expanded = true` → modifier `×1.10` | `base × 1.10`, clamped at `1.30` |
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
| Shelfware threshold (`U`) | 0.30 | 0.10–0.30 | Principal PM |
| Healthy plateau lower bound (`U`) | 0.70 | 0.70–0.80 | Principal PM (D13) |
| Healthy plateau upper bound (`U`) | 1.10 | 1.00–1.20 | Principal PM |
| Expansion base bonus cap | 0.20 | 0.10–0.30 | VP Sales |
| Spike-drop threshold (`M₁`) | 0.70 | 0.60–0.80 | Principal PM |
| Spike-drop minimum contract age | 90 days | 60 / 90 / 120 | Principal PM |
| Spike-drop dampener multiplier | 0.50 | 0.40–0.70 | CFO (D13) |
| Expansion credit multiplier | 1.10 | 1.05–1.15 | VP Sales (D13) |
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
7. **Pre-signal trust.** For any account with an active contract but no posted usage (`trailing_90d_included = 0` or `consumed = NULL`), `HealthScore = 1.00`. Tested in [spec 06](06_evaluation_framework.md) T1d (normal/new accounts median HS) and in the DQ suite.

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
| `base(U)` | `1.00` (healthy plateau, U ∈ [0.70, 1.10]) |
| modifier | 1.00 |
| **`HealthScore`** | **1.00** |
| **`cARR`** | **$48,000** |

> Under v0.7.0 this account scored 0.93 (`base(0.758) = 0.40 + (0.758 − 0.30) × 1.20 = 0.9496` — on the ramp just short of the 0.80 plateau). Under v0.7.1 the plateau starts at 0.70, so the same U lands in "healthy" and earns full booking credit. This is the change that motivated D13.

### 8.3 Overage — `ACC000337` (archetype A3)

| Input | Value |
|---|---:|
| `CommittedARR` | $33,000 |
| `trailing_90d_included_credits` | 8,250 |
| `trailing_90d_consumed_credits` | 10,900 |
| `U` | 1.321 |
| `base(U)` | `1.00 + min(0.221, 0.20) × 1.00 = 1.20` (base cap) |
| modifier | 1.00 |
| **`HealthScore`** | **1.20** |
| **`cARR`** | **$39,600** |

> "Customer consistently over-consumes included capacity. High-signal expansion lead." Note the HS cap of 1.30 does not bind here — the *base* cap at 1.20 does. `HS = 1.30` is only reachable via the expansion modifier (§2.1), which requires overlapping contracts, not pure overage.

### 8.4 Spike-and-drop — `ACC000577` (archetype A2)

| Input | Value |
|---|---:|
| `CommittedARR` | $120,000 |
| `trailing_90d_included_credits` | 30,000 |
| `trailing_90d_consumed_credits` | 22,000 |
| `U` | 0.733 |
| `base(U)` | 1.00 (healthy plateau) |
| `M₁` | 0.92 |
| `contract_age` | 160 days |
| modifier (spike-drop) | 0.50 |
| `base × modifier` | 0.50 |
| **`HealthScore`** (clamp) | **0.50** |
| **`cARR`** | **$60,000** |

> "Without the spike-drop rule, utilization alone would score this 1.00 — straight healthy. The dampener catches the front-loaded pattern that pure `U` misses, and under v0.7.1 the penalty lands the account near the shelfware floor — which is the correct signal for a customer who front-loaded their year and then stopped."

### 8.5 Mid-year expansion — `ACC000121` (archetype A4)

Two active overlapping contracts: original ($80K, 20K credits/mo) and expansion ($150K, 40K credits/mo).

| Input | Value |
|---|---:|
| `CommittedARR` (sum of active) | $230,000 |
| `trailing_90d_included_credits` | `60 × 90 / 30 = 180,000` |
| `trailing_90d_consumed_credits` | 165,000 |
| `U` | 0.917 |
| `base(U)` | 1.00 (healthy plateau) |
| `expanded` | true |
| modifier (expansion) | 1.10 |
| `base × modifier` | 1.10 |
| **`HealthScore`** | **1.10** |
| **`cARR`** | **$253,000** |

> Under v0.7.0 expansion earned a 5% bump on top of a partially-underused base — effectively a wash with normal accounts on the old ramp. Under v0.7.1 the bump is 10% on a healthy-plateau base, so a legitimate mid-term expansion is now worth ~$23K of extra cARR on this $230K book. The upside signal is finally separable from noise.

### 8.6 New-logo Enterprise — pre-signal trust

An Enterprise contract signed 2026-04-10 for $600K ARR. As of `T = 2026-04-18` (8 days old), no daily usage has posted yet — `trailing_90d_included = 0` because the contract hadn't started on any of the 90 trailing days until the last 8. Per §3.6:

| Input | Value |
|---|---:|
| `CommittedARR` | $600,000 |
| `trailing_90d_included_credits` | 0 (effectively null — contract only 8d old) |
| `trailing_90d_consumed_credits` | 0 |
| `U` | undefined |
| `base(U)` | 1.00 (pre-signal) |
| modifier | 1.00 |
| **`HealthScore`** | **1.00** |
| **`cARR`** | **$600,000** |

The rep earns full booking credit until the 90-day window contains enough contract days for a usage signal to exist. Once the account has 30+ days in the window, `U` becomes defined and `HealthScore` reflects actual adoption — no cliff, because the transition is continuous in `U`.

**Compared to the v0.6 ramp-blended approach**, v0.7 surrenders the smooth linear hand-off from "full trust" to "steady state" that `w(contract_age)` provided. In exchange, every parameter disappears from the formula except `base(U)` knobs that every sales metric already has. A known residual: a contract that's 45 days old with legitimately slow adoption (say `U = 0.5`, `HealthScore_steady = 0.72`) scores 0.72 in v0.7 versus a blended ~0.86 in v0.6. If shadow-comp data shows this is harming reps systematically, add the simpler "grace floor" from §2.2 rather than restoring the full blend.

---

## 9. Open questions

1. **Comp weighting — how much variable pay attaches to cARR vs. new-logo bookings.** Out of scope for this metric spec; owned by VPS + Finance in the FY27 comp-plan cycle.
2. **Multi-year contracts.** `annual_commit_dollars` is already annualized at source (see [spec 02 §3.3](02_data_model.md)). Confirm with Finance Systems before cutover.
3. **Unlimited-tier / public-sector contracts.** If any contract has `included_monthly_compute_credits = 0`, `U` is undefined. Proposed carve-out: `HealthScore = 1.00`, excluded from anomaly detection, flagged separately. Pending CFO decision.
4. **Leading-indicator companion.** `cARR` is trailing by construction. The comp plan will likely want a paired forward-looking indicator (pipeline-weighted forecast). Separate spec, deferred.
5. **Multi-currency.** Out of scope for v1. See [spec 02 §12](02_data_model.md#12-open-questions).
6. **Sequential-renewal uplift.** §3.7 excludes back-to-back renewal uplift from the expansion credit. If shadow-comp data shows this is consistently reps landing legitimate expansion via non-overlapping renewal, revisit — possibly by extending the `expanded` definition to "new-contract ARR > prior-contract ARR within 30 days" regardless of overlap.
7. **Grace floor for early adoption.** v0.7 removed the v0.6 ramp blend. If shadow-comp data shows early-stage adoption legitimately trails by 30–60 days and reps are being systematically penalized at `HealthScore < 1.00` during that window, consider adding a single-parameter grace floor — e.g., `HealthScore = max(HS, 0.80) if contract_age < 30d`. One knob, one threshold, one paragraph in the spec. Deferred until the data is in.

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
| **Ramp-blended HealthScore** (v0.6 behavior) | Smooth in principle but introduced four segment-specific knobs (`ramp_full`/`ramp_end` × MM/ENT) that every comp cycle would re-litigate. The `U IS NULL → base = 1.00` path in §3.6 preserves new-logo comp fairness without the blend. If shadow-comp data shows early-adoption reps harmed, add a single-parameter grace floor (§9 Q7) rather than restoring the full blend. |
| **Hard grace period then cliff** (e.g., `HealthScore = 1.00` for 90 days then snap to computed) | Creates a day-91 cliff that can move a rep's comp by tens of percent overnight. Fails stability principle. |
| **Reset `contract_age` on every new contract** | Opens a gaming vector on the spike-drop age guard: a rep could induce a one-day contract gap at renewal to reset the 90-day clock. Anchor to oldest active contract instead (§3.7). |

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
| `contract_age(a, T)` | Days since `start_date` of `a`'s oldest active contract |
| `HealthScore(a, T)` | `clamp(base(U) × modifier, 0.40, 1.30)` |
| `CommittedARR(a, T)` | Sum of active-contract ARR for `a` on `T` |
| `cARR(a, T)` | `CommittedARR × HealthScore` |

## Appendix D — v0.6 → v0.7 change summary

| Section | Change | Reason |
|---|---|---|
| §2.1 | Removed ramp blend; `HealthScore = clamp(base × modifier, 0.40, 1.30)` | One-formula defensibility beats four extra knobs |
| §2.2 | Replaced ramp-parameter table with a deprecation note | Close the door on the old knob set |
| §2.3 | Removed the ramp-blend endpoint tables | The piecewise `base(U)` check is the only continuity check that remains |
| §3.6 | Added explicit **pre-signal** row: `U` undefined → `HealthScore = 1.00` | Preserve new-logo comp fairness without the blend |
| §3.7 | Renewal semantics table edited to drop ramp-reset language | Renewal semantics now only affect `contract_age` for the spike-drop age guard |
| §6 | Dropped 4 ramp-parameter rows | Fewer knobs, smaller review surface |
| §7 | Replaced ramp monotonicity + ramp collapse invariants with a **pre-signal trust** invariant | The new fairness guarantee |
| §8.6 | Rewrote the new-logo example as a single pre-signal point | There's no blend to chart across time any more |
| §9 | Dropped segment-drift; added grace-floor escape hatch (Q7) | Keep a known path back if data shows reps harmed |
| Appendix A | Merged the four ramp-related rejections into one and kept the gaming-guard rejection | The gaming-guard reasoning still holds for the spike-drop age guard |

All v0.6 worked examples (8.1–8.5) remain valid bit-for-bit because every example had `contract_age` past `ramp_end`, so `w = 1` and `HealthScore = HealthScore_steady` — identical to the v0.7 formula.

## Appendix D — v0.7 → v0.7.1 change summary

Calibration pass on 2026-04-21 after reviewing per-band attainment. Three parameters moved; the formula structure is unchanged.

| Parameter | v0.7.0 | v0.7.1 | Why |
|---|---:|---:|---|
| `HEALTHY_U_MIN` | 0.80 | **0.70** | Enterprise customers routinely run at 70–85% of included capacity by design. Dragging them below 1.00 suppressed rep attainment on healthy accounts with no business problem. Widening the plateau from [0.80, 1.10] to [0.70, 1.10] moves ~134 accounts from a ramp slope of 0.926–0.976 into the plateau at 1.00. |
| `SPIKE_DROP_MODIFIER` | 0.70 | **0.50** | Spike-drop is a leading churn signal (customer front-loaded consumption, then stopped). A 30% haircut on a plateau-base put most spike-drops at HS ≈ 0.70, visually indistinguishable from light under-use. A 50% haircut lands the account near the shelfware floor, which is the correct read. |
| `EXPANSION_MODIFIER` | 1.05 | **1.10** | Mid-term expansion (overlapping contracts with sustained `U > 1.0`) is a genuine upside signal. The prior 5% bump was a rounding error against the base overage cap (1.20); doubling it to 10% makes the signal legible in rep attainment. |

The ramp slope follows the plateau boundary: slope = (1.00 − 0.40) / (0.70 − 0.30) = **1.50** (was 1.20 on the v0.7.0 [0.30, 0.80] ramp). A customer at U=0.50 therefore now scores `base = 0.40 + (0.20)(1.50) = 0.70` instead of `0.64` — a small mechanical uplift on truly under-utilizing accounts.

**No-eval, no-change rule.** The T1/T2/T3/T4 evals ([spec 06](06_evaluation_framework.md)) were rerun post-change; any threshold that shifted (T1d healthy-band median, T3 shelfware at-risk share) was either already green or had its threshold updated in the same commit with a one-line justification.

**Not changed in v0.7.1:** `HS_FLOOR` (0.40), `HS_CAP` (1.30), `SHELFWARE_U_MAX` (0.30), `HEALTHY_U_MAX` (1.10), `EXPANSION_U_BONUS_CAP` (0.20), `SPIKE_DROP_M1_SHARE` (0.70), `SPIKE_DROP_MIN_AGE_DAYS` (90), `OVERAGE_MODIFIER` (1.00 — neutral, the base curve already rewards overage), modifier precedence (spike-drop > expansion), and every invariant in §7.

### D.1 Reversibility

Every v0.7.1 change is a parameter flip. Reverting is a one-line change in `pipeline_and_tests/params.py` per parameter, plus eval rerun. There is no schema change, no SQL restructuring, and no historical restatement required for shadow-comp periods — `mart_carr_by_*_month_end` snapshots published before 2026-04-21 retain their frozen values (§5.2).
