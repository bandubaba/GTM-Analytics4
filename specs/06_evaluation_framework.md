# 06 — Evaluation Framework

| Field         | Value                                                                        |
|---------------|------------------------------------------------------------------------------|
| Spec          | `06_evaluation_framework.md`                                                 |
| Audience      | Principal PM, Data Science, VP Sales, CFO, panel reviewers                   |
| Owner         | Principal PM, GTM Analytics                                                  |
| Status        | Draft                                                                        |
| Version       | 0.1                                                                          |
| Last reviewed | 2026-04-19                                                                   |
| Related       | [03 — Metric](03_north_star_metric.md), [05 — Data Quality](05_data_quality.md), [08 — Rollout Plan](08_rollout_plan.md) |

---

## 1. Purpose

This spec defines how we know cARR is *working* — not just that it computes, but that it **measures what it claims** and **earns the trust required to drive compensation**. It moves beyond loss-function thinking into a four-tier framework with explicit business-relevant pass criteria and explicit stop-the-line consequences when a tier fails.

Data quality (spec 05) answers *"is the data consistent and the pipeline correct?"* This spec answers *"is the metric fit for purpose?"* Both run in CI; their failure modes are different.

## 2. Guiding principles

1. **Evaluation is audience-specific.** Different tiers answer different stakeholders' questions — the CFO's question is not the data team's question.
2. **Pass criteria are numeric.** A vague "looks reasonable" is not a pass. Every tier has a threshold that either holds or doesn't.
3. **Failures have different consequences.** T1 fails → don't ship the build. T3 fails → don't *adopt* the metric at all. T4 fails → don't tie it to *comp* yet. The failure mode dictates the escalation.
4. **Adversarial by default.** The metric's first critic should be us. Every eval is designed to catch a specific way we could be wrong.
5. **Baselines matter.** A metric is only good relative to the alternatives it replaces. Every tier compares cARR to at least one naive alternative.

---

## 3. The four-tier framework

| Tier | Question answered | Consequence if it fails |
|---|---|---|
| **T1 — Correctness** | *Does the pipeline compute what spec 03 says?* | **Don't ship the build.** Implementation bug; fix before publish. |
| **T2 — Construct validity** | *Does cARR actually distinguish healthy from unhealthy accounts?* | **Revisit the formula.** If shelfware doesn't floor correctly, the formula needs work. |
| **T3 — Decision utility** | *Does cARR beat the naive alternatives at the same job?* | **Don't adopt cARR at all.** If it doesn't beat pure ARR at identifying at-risk accounts, status quo wins. |
| **T4 — Comp safety** | *Is the metric stable and robust enough to pay people against?* | **Don't tie to comp.** Use as a reporting metric only; return to reporting-only phase of the rollout. |

Notice the escalating scope: T1 is about the code, T2 about the formula, T3 about the *choice* of metric, T4 about using it for comp. Each tier gates a broader decision.

---

## 4. Tier 1 — Correctness

### 4.1 What it tests

Whether the implemented pipeline produces the exact values the formula in [spec 03 §2.1](03_north_star_metric.md) specifies. This is a strict superset of the P0 metric-layer DQ assertions in [spec 05 §4.5](05_data_quality.md#45-metric-layer-invariants).

### 4.2 Tests

| ID | Test | Method | Pass threshold |
|---|---|---|---|
| `T1-001` | Per-account bounds | Every account has `0.40 ≤ HealthScore ≤ 1.30` | 100% of rows |
| `T1-002` | Worked-example parity | Re-compute [spec 03 §8](03_north_star_metric.md#8-worked-examples) from actuals; match published `cARR` | All 5 examples within `$0.01` |
| `T1-003` | Determinism | Run pipeline twice on same inputs; compare outputs byte-for-byte | Identical |
| `T1-004` | Orphan exclusion | Compute cARR with and without orphan rows; compare | Per-account diff < `1e-6` |
| `T1-005` | Freeze invariance | Re-run pipeline for a closed month; compare to published snapshot | Byte-identical |

### 4.3 Cadence and gating

Runs on every PR that touches `/pipeline_and_tests/metrics/` or the metric SQL. **Blocks merge** on any failure.

### 4.4 Pass criterion

All tests pass on the current commit. No exceptions.

### 4.5 Consequence if failing

The build is broken. Mart does not publish. Alert the Analytics Eng on-call; open a P0 ticket; do not attempt to diagnose in prod.

---

## 5. Tier 2 — Construct validity

### 5.1 What it tests

Whether cARR **distinguishes** the injected archetypes (spec 02 §5) the way the formula was designed to. This is the empirical defense of the formula itself.

### 5.2 Tests

#### T2-001: Archetype-stratified distribution

Group every account by its known archetype (A1–A4). Report `HealthScore` and `cARR / CommittedARR` distributions (median, P10, P90) per archetype.

**Expected per spec 03:**

| Archetype | HealthScore median | cARR / ARR |
|---|---:|---:|
| A1 Shelfware | 0.40 | 0.40 |
| A2 Spike-drop | 0.40–0.55 | 0.40–0.55 |
| A3 Overage | 1.12–1.30 | 1.12–1.30 |
| A4 Expansion | 1.05–1.30 | 1.05–1.30 |
| No archetype (normal) | 0.70–1.12 | 0.70–1.12 |

**Pass threshold:** observed medians within ±0.10 of expected for every archetype.

#### T2-002: Shelfware discrimination

Of the 100 injected shelfware accounts, what % fall in the bottom decile of company-wide cARR?

**Pass threshold:** ≥ 85%.

#### T2-003: Overage discrimination

Of the 150 injected overage accounts, what % fall in the top quartile of company-wide HealthScore?

**Pass threshold:** ≥ 80%.

#### T2-004: False-positive rate on normal accounts

Of the 700 normal accounts, what % receive `HealthScore < 0.50` (i.e., look like shelfware / spike-drop)?

**Pass threshold:** ≤ 5%. This is the "we didn't over-penalize normal customers" check.

### 5.3 Cadence and gating

Runs on every PR that modifies the formula (`carr.sql`), parameters (`carr_params.yml`), or this spec. **Blocks merge** on failure.

### 5.4 Consequence if failing

The formula is wrong. Do not adjust parameters to make it pass — that's overfitting. Open a spec-level PR to [spec 03](03_north_star_metric.md), discuss in the PM + Data Science review.

---

## 6. Tier 3 — Decision utility

### 6.1 What it tests

Whether cARR **beats the naive alternatives** at the decision it was designed to support: identifying at-risk accounts.

This is the most business-relevant tier. If cARR doesn't beat pure ARR at this task, the entire initiative is unjustified — there's no point replacing a simpler metric with a more complex one.

### 6.2 Tests

#### T3-001: Head-to-head on at-risk identification

Define the ground-truth label:
```
at_risk(a) = true if archetype(a) ∈ {A1 shelfware, A2 spike_drop}
```

Rank accounts by three scorers, ascending (lower = more at-risk):

1. **Baseline 1 — Committed ARR**: rank by `CommittedARR` alone.
2. **Baseline 2 — 90-day consumption revenue**: rank by realized consumption revenue over trailing 90 days.
3. **cARR**: rank by cARR.

Compute **AUC-PR** (area under precision-recall curve) for each scorer against the `at_risk` label.

**Expected:**

- Baseline 1 (ARR) AUC ≈ `at_risk_rate` (~0.15) — ARR is random with respect to adoption, by design.
- Baseline 2 (Consumption revenue) AUC ≈ 0.60–0.70 — catches shelfware (zero revenue) but misses spike-drop (revenue is fine in aggregate).
- cARR AUC ≥ 0.80 — combines both signals.

**Pass threshold:**
```
AUC(cARR) ≥ max(AUC(ARR), AUC(Consumption_Revenue)) + 0.10
```

#### T3-002: Top-k agreement

Of the top-100 highest-cARR accounts, how many are in the top-100 highest-ARR accounts? (This is an *agreement* check — we expect partial overlap; full overlap would mean cARR adds no signal, zero overlap would mean cARR is capturing a different construct entirely.)

**Pass threshold:** overlap ∈ `[0.50, 0.90]`. Outside this range, investigate.

#### T3-003: Information gain over baseline

Information-theoretic check: what fraction of the variance in `at_risk` label is explained by cARR vs. the best baseline?

**Pass threshold:** cARR has R² at least 0.15 higher than the best single-signal baseline.

### 6.3 Cadence and gating

Runs on every PR that touches the formula or parameters. Also runs monthly on the latest production data. **Blocks adoption** on failure; does not block individual builds (T1 handles that).

### 6.4 Consequence if failing

**Do not adopt cARR.** Stay on the status quo metric. Convene a review with VPS + CFO + Principal PM to decide whether to revise the formula or abandon the initiative.

---

## 7. Tier 4 — Comp safety

### 7.1 What it tests

Whether cARR is **stable enough** and **robust enough** that tying variable pay to it is fair. This is the most underappreciated tier — a metric can be correct (T1), valid (T2), and useful (T3), and *still* be a terrible comp metric because it oscillates.

### 7.2 Tests

#### T4-001: Rank stability (Spearman)

Compute `cARR(rep, T)` and `cARR(rep, T - 30d)`. Compute Spearman rank correlation across all reps.

**Pass threshold:** `ρ ≥ 0.85`.

#### T4-002: Rank movement tail

What fraction of reps moved more than ±5 ranks between `T - 30d` and `T`?

**Pass threshold:** ≤ 20%.

#### T4-003: Parameter sensitivity

Perturb:
- `HealthScore floor`: `0.30` / `0.40` / `0.50`
- `HealthScore cap`: `1.20` / `1.30` / `1.40`

Re-run pipeline at all 9 combinations. Compute `Σ cARR` (company total) and rank correlation across the grid.

**Pass thresholds:**
- Company total changes by ≤ 3% across the grid.
- Rank correlation between adjacent grid cells ≥ 0.95.

#### T4-004: Single-account sensitivity

What fraction of `Σ cARR` comes from the top-1 account?

**Pass threshold:** ≤ 3% of company total. Prevents one explosive customer from driving the whole metric.

#### T4-005: Backtested monotonicity

For accounts whose utilization trajectory is strictly monotonically increasing (no spike-drop, no expansion), their month-over-month `HealthScore` should not decrease by more than `0.05` across any two consecutive months absent a contract change.

**Pass threshold:** ≤ 2% of monotone accounts violate this.

### 7.3 Cadence and gating

Runs on every PR that touches parameters. Runs monthly on production data. **Blocks comp tie-in** on failure; does not block reporting use.

### 7.4 Consequence if failing

Revert to the previous phase in [spec 08 rollout](08_rollout_plan.md). If in shadow comp: stay in shadow comp. If in partial comp tie-in: roll back to shadow comp. Open a review with the Principal PM + VPS + CFO to agree on remediation (parameter tuning, window change, additional smoothing).

---

## 8. Reporting

### 8.1 `evaluation_report.md`

Every eval run produces a deterministic Markdown report at `/pipeline_and_tests/evals/evaluation_report.md` containing:

1. **Header** — run id, timestamp, pipeline commit SHA, dataset window.
2. **Tier summary table** — pass / fail / warn per tier.
3. **Per-test detail** — one subsection per test with: threshold, observed, status, rows affected.
4. **Baseline comparison chart reference** — link to the PR curve PNG (T3-001).
5. **Sensitivity heatmap reference** — link to the 3x3 parameter grid (T4-003).
6. **Delta vs. previous run** — diff of pass/fail status and of key observed values.

The report is **the artifact**. The PR that changes the formula or parameters must attach the report; reviewers read it before approving.

### 8.2 `dq.eval_results`

A table analogous to `dq.assertion_results` but for evals. One row per `(run_id, test_id)`:

| Column | Type | Meaning |
|---|---|---|
| `run_id` | STRING | |
| `run_ts` | TIMESTAMP | |
| `test_id` | STRING | e.g. `T3-001` |
| `tier` | STRING | `T1` / `T2` / `T3` / `T4` |
| `status` | STRING | `pass` / `fail` / `warn` |
| `observed` | STRING | Free-form, human-readable |
| `threshold` | STRING | |
| `commit_sha` | STRING | |

### 8.3 Dashboard surfacing

The **Data Health** tab surfaces eval tier status (green / yellow / red) in addition to DQ tier status. Leadership sees both.

---

## 9. CI integration

```
PR opened / updated
  ↓
Lint + unit tests (not in this spec's scope)
  ↓
DQ P0 assertions  → block on fail (spec 05)
  ↓
T1 Correctness    → block on fail
  ↓
T2 Construct      → block on fail if formula/params changed
  ↓
T3 Decision       → block "adoption tag" on fail (advisory on general PRs)
  ↓
T4 Comp safety    → block "comp-ready tag" on fail (advisory on general PRs)
  ↓
Review + merge
```

On `main` branch post-merge, full eval suite runs nightly; results trend in `dq.eval_results`.

## 10. Open questions

1. **Ground-truth label for T3.** Currently we use *injected archetype* as the at-risk label. Once we have real renewal / expansion outcomes in prod, migrate to observed outcomes for real validation. Re-baseline T3 thresholds when the label changes.
2. **T4-001 window.** We use 30 days for rank stability. Should comp-tie-in require a 90-day window? Pending VPS.
3. **Handling of the "unranked" set.** Accounts with no active contract are excluded. If this set is large, rank stability on the *active* set may mask instability in the *churn* set. Track separately.
4. **Calibration on multi-quarter data.** Thresholds above are first-pass. Tighten after two full quarters of shadow-comp data.

---

## Appendix A — Rejected evaluation approaches

| Alternative | Why rejected |
|---|---|
| "100% anomaly detection rate" as the headline success metric | Circular — we injected the anomalies. Proves nothing. |
| Single-number aggregate score (weighted sum across tiers) | Obscures which tier failed; defeats the point of tier-specific consequences |
| Compare cARR only to status quo ARR (no consumption-revenue baseline) | Would accept any metric that beats a random ranking; consumption revenue is the harder, more relevant baseline |
| ML-style train/test split on synthetic data | Overfits to our synthesis assumptions; real validation comes from prod data after rollout |
| Human-judged "looks right" review instead of numeric thresholds | Doesn't survive a CFO / panel challenge; not reproducible across reviewers |

## Appendix B — What "success" looks like to each audience

| Audience | Their success question | The tier that answers it |
|---|---|---|
| Analytics Engineer | "Is my PR safe to merge?" | T1 |
| Principal PM | "Is this formula measuring what I claim?" | T2 |
| VP Sales + CFO | "Is this metric better than what we have?" | T3 |
| VP Sales + CFO | "Is this metric safe to tie comp to?" | T4 |
| Internal Audit | "Is there a traceable artifact proving the above?" | §8.1 `evaluation_report.md` |
