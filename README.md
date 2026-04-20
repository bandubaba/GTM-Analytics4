# GTM North Star — Consumption-Adjusted ARR (`cARR`)

> A spec-first proposal for a single GTM North Star that balances upfront bookings with sustained platform usage, designed to survive the transition from an ARR-based to a hybrid consumption-based business model. Built end-to-end using an AI-assisted, spec-driven development workflow.
>
> **Principal PM take-home — Palo Alto Networks**

---

## Why this repo exists

The company is moving from an upfront-ARR commercial model to a hybrid consumption model. The existing North Star — Committed ARR — credits sales reps at contract signature and goes blind after. Shelfware accounts, spike-and-drop adopters, and silent churn look identical to healthy customers in the numbers leadership reviews weekly.

This repo proposes **`cARR` — Consumption-Adjusted ARR**, a single North Star number that preserves the CFO-familiar `$` anchor while adjusting for post-sale reality, and lays out the full spec stack, pipeline, evaluation framework, and rollout plan required to take it from proposal to comp-driving metric.

The headline idea, in one line:
```
cARR  =  Committed_ARR  ×  HealthScore
```
where `HealthScore` is a bounded, interpretable, rules-based multiplier in `[0.40, 1.30]` derived from trailing-90-day utilization plus explicit rules for shelfware, spike-and-drop, expansion, and overage patterns.

---

## What's in this repo

```
GTM-Analytics3/
├── README.md                   ← you are here
├── data_generation/            Synthetic dataset + BigQuery uploader
│   ├── generate_data.py        Faker + pandas; 4 tables with injected anomalies
│   ├── upload_to_bq.py         Explicit schemas, clustering, sandbox-aware
│   ├── config.py               Tunable knobs (sizes, ratios, dates)
│   ├── requirements.txt
│   └── README.md
├── specs/                      Spec-driven development artifacts
│   ├── README.md               Index, reading order, decision log (00)
│   ├── 01_problem_statement.md  Context, personas, pain, goals, non-goals
│   ├── 02_data_model.md         Schema, anomaly catalog, classification
│   ├── 03_north_star_metric.md  Formula, edge cases, invariants (v0.5)
│   ├── 04_pipeline_architecture.md  Raw → staging → int → metric → mart
│   ├── 05_data_quality.md       30 assertions, severity tiers, SLAs
│   ├── 06_evaluation_framework.md  T1 Correctness → T4 Comp safety
│   ├── 07_dashboard_spec.md     Personas, views, filters, RBAC
│   ├── 08_rollout_plan.md       Phases 0-4 with gates and rollback
│   ├── 09_access_and_audit.md   RBAC, SOX controls, retention
│   └── 10_glossary.md           Shared vocabulary; cites, never invents
├── pipeline_and_tests/         dbt-style SQL + DQ + eval suite (scaffold)
└── dashboard/                  Streamlit prototype (scaffold)
```

The specs are the source of truth; the code will cite them.

---

## Architecture at a glance

```
              Synthetic Generator  (Faker + pandas, seeded)
                        │
                        ▼
                ┌───────────────────┐
                │   BigQuery raw    │   sales_reps · accounts
                │                   │   contracts · daily_usage_logs
                └─────────┬─────────┘
                          │ dbt-style SQL
                          ▼
              ┌────────────────────────┐
              │ staging → int → metric │   Deterministic, idempotent
              └───────────┬────────────┘   WRITE_TRUNCATE, no NOW()
                          ▼
                ┌──────────────────┐       ★ immutable after M+2
                │   mart_carr_*    │────────→  comp-of-record
                └───────┬──────────┘
                        │
                        ▼
         ┌──────────────────────┐     ┌───────────────────────┐
         │ Streamlit dashboard  │     │  DQ + Eval artifacts  │
         │  (Region × Rep)      │     │  (assertion + report) │
         └──────────────────────┘     └───────────────────────┘
```

Detailed layer-by-layer in [spec 04](specs/04_pipeline_architecture.md).

---

## Reading this repo as a panel reviewer

I'd recommend this reading path — roughly 25 minutes end to end:

| Order | Doc | Time | Why |
|---:|---|---|---|
| 1 | [`specs/README.md`](specs/README.md) | 3 min | Decision log; what was contested and how I called it |
| 2 | [`specs/01_problem_statement.md`](specs/01_problem_statement.md) | 4 min | Context, personas, what success looks like |
| 3 | [`specs/03_north_star_metric.md`](specs/03_north_star_metric.md) | 6 min | The formula + worked examples; the heart of the proposal |
| 4 | [`specs/06_evaluation_framework.md`](specs/06_evaluation_framework.md) | 4 min | How I'd know it's working; 4 tiers with numeric pass criteria |
| 5 | [`specs/08_rollout_plan.md`](specs/08_rollout_plan.md) | 4 min | Phased adoption with gates and rollback |
| 6 | Any other spec as needed | — | Drill in per interest |

---

## Quick start

Deterministic, seeded (`SEED=42`). Re-runs produce byte-identical output.

```bash
# 1. Generate synthetic data locally (~15 seconds)
cd data_generation
pip install -r requirements.txt
python generate_data.py

# 2. Upload to BigQuery (requires `gcloud auth application-default login` once)
export GOOGLE_CLOUD_PROJECT=your-sandbox-project-id
export BQ_DATASET=gtm_analytics        # optional; default shown
export BQ_LOCATION=US                   # optional; default shown
# export BQ_PARTITION=1                 # optional; enable only on billed project
python upload_to_bq.py

# 3. (coming) Run the metric pipeline + eval suite
# cd ../pipeline_and_tests && python run.py

# 4. (coming) Launch the dashboard
# cd ../dashboard && streamlit run app.py
```

See [`data_generation/README.md`](data_generation/README.md) for the anomaly catalog injected into the synthetic dataset and the sandbox-vs-prod partitioning trade-off.

---

## What's been shipped

| Phase | Status |
|---|---|
| Spec stack (00–10) | ✅ Committed, drafts v0.1–v0.5 |
| Synthetic data generator | ✅ ~182k usage rows, 5 anomaly types, deterministic |
| BigQuery upload | ✅ Explicit schemas, clustering, sandbox-compatible |
| Pipeline implementation | ⏳ Scaffold only — next phase |
| DQ assertion suite | ⏳ Catalogued in spec 05; implementation next |
| Eval suite + report | ⏳ Catalogued in spec 06; implementation next |
| Dashboard prototype | ⏳ Scaffold only — after pipeline lands |

Status mirrors the commit history on `main`.

---

## Design philosophy: what makes a "Technical PM"

Four choices run through every spec in this repo and are, to me, what the role means:

1. **Every defensible decision is written down before code is written.** When the VP Sales or CFO pushes on *why* the formula is the way it is, the answer is in a spec, not in someone's head.
2. **Bounds matter more than sophistication.** The metric is bounded `[0.40 × ARR, 1.30 × ARR]` — a mathematical fence that survives any customer's extreme behavior. A CFO can sanity-check it in 3 queries.
3. **The eval framework has four tiers because the failure modes are different.** T1 fails → the code is broken. T3 fails → the *choice of metric* is wrong. These are distinct stop-the-line events; conflating them hides information.
4. **Rollback cost determines phase design.** Shadow comp is long because the only way to know a comp metric is trustworthy is to run it against real behavior for a full cycle. Skipping it is how good metrics become paycheck lawsuits.

The Q&A portion of the panel will press on these. The specs + decision log are designed so every press has an answer.

---

## AI-assisted development (spec-first workflow)

This project was built using an AI coding assistant (Claude Code) against a Markdown spec-driven workflow — the methodology Palo Alto Networks' brief explicitly calls out.

**How it worked:**

1. Write a Markdown spec describing what needs to exist (e.g., the `cARR` formula, edge-case rules, invariants).
2. Ask the AI to generate the implementation (SQL, Python, tests) citing the spec.
3. Run it. Validate the output numerically and against the spec's invariants.
4. Every surprise (e.g., the BigQuery Sandbox 60-day partition expiration — see Decision D09) triggers a spec update *and* a code update in the same PR.

**What the AI is good at** in this workflow:
- Rapid boilerplate (schema definitions, repetitive SQL, markdown tables).
- Drafting rejected-alternatives appendices from a bullet list.
- Normalizing vocabulary across 11 specs in one go.

**What the AI got wrong** (and where humans mattered):
- Confidently generated MONTH-partitioned tables and did not flag the sandbox's 60-day expiration. I ran the code, saw 41k rows instead of 182k, and traced the cause. That bug is why the decision log has D09.
- Consistently over-engineered; humans trimmed.
- Invented plausible-sounding statistics; humans replaced with measured values.

Every commit in this repo carries a `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer — a literal attribution signal for anyone auditing provenance. Not decorative.

---

## Decision log

The contested choices — 11 of them as of `main` — live in [`specs/README.md`](specs/README.md#decision-log) as a lightweight ADR. Each row: decision, status, rationale, alternatives rejected, owning spec. Every row exists because a reasonable person could have chosen differently.

Selected highlights panel reviewers are likely to press on:

- **D01.** `cARR = Committed_ARR × HealthScore` (multiplicative, not additive weighted blend). *Why:* bounded, CFO-anchored, comp-defensible.
- **D04.** Overlapping contracts *accumulate*, not `max()`. *Why:* the customer signed both checks.
- **D07.** Rules-based SQL, not ML. *Why:* no labeled training data yet; reps must be able to read the rule.
- **D09.** No time partitioning in sandbox; clustering only; flag-gated for prod. *Why:* sandbox's 60-day partition expiration silently evicts historical rows.
- **D11a.** If both spike-drop and expansion modifiers could apply, spike-drop wins. *Why:* conservative signal prevails; revisit on data.

---

## Contributing

This repo treats specs as the primary artifact. The workflow:

1. Open a branch: `git checkout -b specs/<short-name>` (for spec changes) or `feat/<short-name>` (for code).
2. Write or modify the spec first. If cross-cutting, touch every affected spec in the same PR.
3. If the change affects a decision in the decision log, add or amend a row.
4. Implementation PRs must cite the spec + section they implement in commit messages.

See [`specs/README.md` §How to propose a change](specs/README.md#how-to-propose-a-change) for the full flow and required reviewers.

Commits use the conventional-commits style:

```
docs(specs):   documentation / spec changes
feat(<area>):  new feature implementation
fix(<area>):   bug fix
chore:         scaffolding, infra, tooling
refactor:      non-functional changes
```

---

## References

- Palo Alto Networks Principal PM take-home brief (not reproduced here; supplied directly to the candidate).
- The commit graph on `main` is the project's working log — each commit is small, focused, and self-describing.

---

## License

Take-home deliverable; no public license.
