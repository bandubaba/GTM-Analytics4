# Specs

This directory is the **source of truth** for the GTM North Star initiative. Code in `/pipeline_and_tests/` and `/dashboard/` must cite a spec; spec changes trigger a downstream code review.

We work spec-first: every non-trivial decision is written here *before* implementation, reviewed, and cited by the pull request that implements it.

---

## Reading order

Read top to bottom if this is your first pass. The specs build on each other.

| # | Spec | Primary audience | Why you'd read it |
|---:|---|---|---|
| 00 | **This file** — `README.md` | Anyone new to the project | Orientation, reading path, decision log |
| 01 | [`01_problem_statement.md`](01_problem_statement.md) | Exec sponsors, panel reviewers | What we're solving, for whom, what success looks like, what's out of scope |
| 02 | [`02_data_model.md`](02_data_model.md) | Data engineers, analysts | The 4 source tables, keys, cardinalities, and the anomaly catalog formalized as known states of the world |
| 03 | [`03_north_star_metric.md`](03_north_star_metric.md) | CFO, VP Sales, PM, data team | The formula, the parameters, the invariants, worked examples per archetype |
| 04 | [`04_pipeline_architecture.md`](04_pipeline_architecture.md) | Data engineers, SRE | How data flows, refresh cadence, cost envelope, partition/cluster decisions |
| 05 | [`05_data_quality.md`](05_data_quality.md) | Data engineers, data stewards | DQ assertion catalog, severity tiers, block-on-fail vs warn-on-fail rules |
| 06 | [`06_evaluation_framework.md`](06_evaluation_framework.md) | PM, data science, panel reviewers | 4-tier eval framework (T1 Correctness → T4 Comp safety), pass criteria, stop-the-line consequences |
| 07 | [`07_dashboard_spec.md`](07_dashboard_spec.md) | Design, frontend, VPS/CFO users | Personas, views, filters, drill paths, what each audience sees first |
| 08 | [`08_rollout_plan.md`](08_rollout_plan.md) | VPS, CFO, People Ops, RevOps | Phased adoption (reporting → shadow comp → partial tie-in → full), gates, risks, rollback |
| 09 | [`09_access_and_audit.md`](09_access_and_audit.md) | Security, Legal, IT, Internal Audit | Comp data classification, RBAC matrix, audit trail, change management, retention |
| 10 | [`10_glossary.md`](10_glossary.md) | Everyone | Shared vocabulary — single source of truth for business + technical terms |

---

## Spec status

| # | Spec | Version | Status | Owner | Last reviewed |
|---:|---|---|---|---|---|
| 00 | README (this file) | 1.0 | Living | Principal PM | 2026-04-19 |
| 01 | Problem statement | 0.1 | Draft | Principal PM | 2026-04-19 |
| 02 | Data model | 0.1 | Draft | Principal PM | 2026-04-19 |
| 03 | North Star metric | 0.6 | Draft | Principal PM | 2026-04-19 |
| 04 | Pipeline architecture | 0.1 | Draft | Principal PM | 2026-04-19 |
| 05 | Data quality | 0.1 | Draft | Principal PM | 2026-04-19 |
| 06 | Evaluation framework | 0.1 | Draft | Principal PM | 2026-04-19 |
| 07 | Dashboard | 0.1 | Draft | Principal PM | 2026-04-19 |
| 08 | Rollout plan | 0.1 | Draft | Principal PM | 2026-04-19 |
| 09 | Access & audit | 0.1 | Draft | Principal PM | 2026-04-19 |
| 10 | Glossary | 0.1 | Draft | Principal PM | 2026-04-19 |
| 11 | AI product surface | 0.1 | Draft | Principal PM | 2026-04-19 |

**Status ladder:** `Pending → Draft → In Review → Accepted → Superseded`

A spec is **Accepted** when its listed approvers (typically VP Sales + CFO for business specs; CISO + Internal Audit for access specs) have signed off in the review thread. An accepted spec is frozen except via the change-management process in the spec itself.

---

## Document header convention

Every spec opens with this block so readers know the state at a glance:

```
| Field         | Value                                    |
|---------------|------------------------------------------|
| Spec          | NN_name.md                               |
| Audience      | <primary readers>                        |
| Owner         | Principal PM, GTM Analytics              |
| Status        | Pending / Draft / In Review / Accepted   |
| Version       | <semver; 0.x while drafting>             |
| Last reviewed | YYYY-MM-DD                               |
| Related       | <sibling specs, code paths>              |
```

Every spec closes with **Appendix: Rejected alternatives** listing the options we considered and why we passed. The appendix is how future-us (or an auditor) recovers the intent of a choice.

---

## Decision log

The contested calls we made during design. Each row is an Architecture Decision Record (ADR) in miniature. If you disagree with a decision, open a PR that amends both the relevant spec *and* this row (status → `Superseded`).

| # | Decision | Status | Date | Rationale | Alternatives rejected | Spec |
|---:|---|---|---|---|---|---|
| D01 | cARR takes multiplicative form (`Committed_ARR × HealthScore`) instead of a weighted blend or an ML-predicted score | Proposed | 2026-04-18 | Keeps `$` as the anchor the CFO already forecasts; bounded by construction (floor and cap); readable by a rep disputing comp | `α·ARR + β·Consumption + γ·Trajectory` (more knobs to fight over), ML-predicted churn × ACV (no labels, not explainable) | 03 |
| D02 | HealthScore bounded to `[0.40, 1.30]` | Proposed | 2026-04-18 | Floor avoids paying zero on a still-contracted account (perverse incentive); cap prevents one explosive customer from distorting quota attainment | `[0, unbounded]` (tail risk), `[0.50, 1.20]` (under-rewards expansion), `[0.30, 1.50]` (too wide for comp) | 03 |
| D03 | Trailing 90-day window, non-configurable for comp | Proposed | 2026-04-18 | Aligns with quarterly comp cadence; 30d too noisy, 180d too laggy | 30 / 60 / 180 / 365 days | 03 |
| D04 | Overlapping contracts **accumulate** (sum ARR + sum included credits) rather than `max()` | Proposed | 2026-04-18 | Customer committed to both contracts — both dollars are real. `max()` would under-report expansion commitment | `max()` of primary contract, weighted average | 03 |
| D05 | Orphans (rogue / out-of-window usage) are **excluded** from the metric, flagged in a DQ report | Proposed | 2026-04-18 | Comp cannot pay against broken data. Imputation would distort a CFO-grade number | Impute via neighbor accounts, include with a penalty tier | 03 |
| D06 | Month-end metric snapshots are **frozen** (immutable) once published | Proposed | 2026-04-18 | A rep's quota attainment cannot legally shift after period close; finance-style restatement workflow handles any corrections | View-on-demand (recomputed every load), overwrite-in-place | 03, 04 |
| D07 | Deterministic SQL (with explicit rules for edge cases) instead of ML | Proposed | 2026-04-18 | No labeled outcomes yet; reps must be able to read the rule; maintenance tax of model drift / retraining not justified at 1K accounts | Unsupervised anomaly detector, supervised churn scorer, LLM-generated health score | 03, 06 |
| D08 | BigQuery as the warehouse | Proposed | 2026-04-18 | Serverless (no ops), IAM + row-level security for comp data, free sandbox for prototype, on-demand pricing fits bursty sales-ops queries | Snowflake (capability parity, no prototype-friendly free tier), Postgres (ops burden, scale ceiling), DuckDB (single-user) | 04 |
| D09 | No time partitioning in sandbox; clustering only; partitioning flag-gated (`BQ_PARTITION=1`) for billed projects | Accepted | 2026-04-18 | Sandbox's 60-day partition expiration silently evicts historical rows on load (77% loss observed). Clustering has no expiration side-effect | Partition by MONTH in sandbox (silently drops data), partition by DAY (same issue), no clustering either | 04 |
| D10 | Spike-drop detection via explicit rule (`M₁ share ≥ 70%` AND `contract_age ≥ 90 days`) | Proposed | 2026-04-18 | Interpretable to reps; the archetype is already the business's language | Unsupervised anomaly detection on usage patterns, hand-labeled dataset + classifier | 03 |
| D11 | Expansion credit is a small `+5%` modifier, not a formula-level feature | Proposed | 2026-04-18 | Rewards the #1 behavior a consumption model should encourage while keeping the multiplier bounded. Flagged for revisit if the CFO argues double-count with higher `U` | No expansion credit (metric-neutral), full commit re-baseline (too disruptive to comp) | 03 |
| D12 | ~~Ramp protection: blended HealthScore for new contracts, segment-aware days (MM 15/60, ENT 30/120)~~ **Superseded by D12b.** Original v0.6 decision retained for history | Superseded | 2026-04-20 | Originally: address booking-fairness principle. Withdrawn because the blend introduced four tuning parameters that every comp cycle would re-litigate; pre-signal fairness is preserved by the `U IS NULL → base = 1.00` branch instead | — | 03 |
| D12b | New-logo fairness via **pre-signal trust** (no ramp blend): when `trailing_90d_included_credits = 0` or `U` is undefined, `HealthScore = 1.00`. `contract_age` still anchors to oldest active contract for the spike-drop age guard | Proposed | 2026-04-20 | Preserves new-logo comp fairness without introducing segment-specific ramp parameters. Trade-off: an account with legitimately slow early adoption now scores below 1.00 once `U` is defined; escape hatch documented in spec 03 §9 Q7 (single-parameter grace floor) | Full v0.6 ramp blend (four extra knobs), hard grace-then-cliff (day-91 paycheck cliff), expected-ramp curve (needs historical labels we don't have) | 03 |

Decisions listed as **Proposed** need VPS + CFO sign-off before the pipeline is wired to comp. Decisions listed as **Accepted** are locked and require a superseding PR to change.

---

## How to propose a change

1. Open a branch: `git checkout -b specs/<short-name>`.
2. Edit the relevant spec. If the change is cross-cutting, update each affected spec in the same PR.
3. If the change affects a decision in the **Decision log** above, add a row (or amend an existing row with a `Superseded` status and a pointer to the new decision).
4. Open a PR. Require review from:
   - **Principal PM** (always)
   - **VP Sales + CFO** if the change alters the cARR formula, parameters, or comp-tying behavior
   - **CISO / Internal Audit** if the change touches access, audit, or retention
5. Merge only when all T1 + T4 eval suites pass (see spec 06).

Commit message pattern:

```
docs(specs): <short summary>

<why the change; link to issue / conversation>

Refs: specs/<NN>_<name>.md
Co-Authored-By: <name> <email>
```

---

## AI-assisted authorship note

These specs were drafted using an AI coding assistant (Claude Code / Cursor) against a Markdown spec-driven workflow. The AI wrote the first draft; a human reviewed, edited, and pressure-tested every section against a hypothetical hostile panel before status moved past `Draft`.

Every commit in this repo carries a `Co-Authored-By` trailer attributing the AI's contribution, per the brief's expectation that we leverage AI-first development. The trailer is not decorative — it is a literal attribution signal for anyone auditing provenance.
