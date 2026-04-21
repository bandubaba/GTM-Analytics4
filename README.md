# GTM North Star — Consumption-Adjusted ARR (`cARR`)

> A spec-first proposal for a single GTM North Star that balances upfront bookings with sustained platform usage, designed to survive the transition from an ARR-based to a hybrid consumption-based business model. Built end-to-end using an AI-assisted, spec-driven development workflow.
>
> **Principal PM take-home — Palo Alto Networks** · `JR-014632`

---

## Why this repo exists

The company is moving from an upfront-ARR commercial model to a hybrid consumption model. The existing North Star — Committed ARR — credits sales reps at contract signature and goes blind after. Shelfware accounts, spike-and-drop adopters, and silent churn look identical to healthy customers in the numbers leadership reviews weekly.

This repo proposes **`cARR` — Consumption-Adjusted ARR**, a single North Star number that preserves the CFO-familiar `$` anchor while adjusting for post-sale reality. The headline, in one line:

```
cARR  =  Committed_ARR  ×  HealthScore
```

where `HealthScore` is a bounded, interpretable, rules-based multiplier in `[0.40, 1.30]` derived from trailing-90-day utilization, with explicit rules for shelfware / spike-and-drop / expansion / overage. New logos are protected by a **pre-signal trust** rule — accounts with no usage signal yet default to `HealthScore = 1.00`, so a rep earns full booking credit through the first usage-free days without adding a ramp parameter (spec 03 v0.7, D12b).

Everything — the formula, the parameters, the pipeline, the eval framework, the rollout plan — is written in a spec *before* it is coded. Code cites specs by section.

---

## What you can run

### Easiest — open the live dashboard

🔗 **[gtm-analytics.streamlit.app](https://gtm-analytics.streamlit.app)** — no install, no auth. All 5 views + Ask cARR work in-browser.

### Run the dashboard locally (~30 seconds)

The 13 parquet files under `pipeline_and_tests/data/` are committed as a
deterministic snapshot of the BQ pipeline, so the dashboard runs cold
without GCP auth.

```bash
git clone https://github.com/bandubaba/GTM-Analytics4.git && cd GTM-Analytics4
python -m venv .venv && source .venv/bin/activate
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py                   # opens localhost:8501
```

Optional — turn on the Claude-powered NL query layer:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run dashboard/app.py
```

The default NL mode is an offline keyword router, so the app runs cold
without an API key.

### Reproduce the pipeline end-to-end (BQ required)

The 13 SQL models execute against **BigQuery** (the warehouse the brief
calls out). `run.py` exports every model as parquet into
`pipeline_and_tests/data/` — the same files committed above.

```bash
pip install -r pipeline_and_tests/requirements.txt
gcloud auth application-default login                          # one-time
python data_generation/generate_data.py                        # 1. seeded CSVs
GOOGLE_CLOUD_PROJECT=<your-proj> python data_generation/upload_to_bq.py  # 2. load BQ
GOOGLE_CLOUD_PROJECT=<your-proj> python pipeline_and_tests/run.py        # 3. 13 models → BQ + parquet
python pipeline_and_tests/dq/run_dq.py                         # 4. 16 DQ checks
python pipeline_and_tests/evals/run_evals.py                   # 5. 11 T1-T4 evals
```

Rerun is byte-identical (seeded generator + deterministic SQL, D07).

---

## What's in this repo

```
GTM-Analytics4/
├── README.md                        ← you are here
├── specs/                           Source of truth. Read first.
│   ├── README.md                    Reading order + decision log (13 ADRs, D01–D12b)
│   ├── 01_problem_statement.md
│   ├── 02_data_model.md             4 tables + anomaly catalog
│   ├── 03_north_star_metric.md      v0.7 — cARR formula, renewals, invariants
│   ├── 04_pipeline_architecture.md
│   ├── 05_data_quality.md
│   ├── 06_evaluation_framework.md   T1 Correctness → T4 Comp safety
│   ├── 07_dashboard_spec.md
│   ├── 08_rollout_plan.md
│   ├── 09_access_and_audit.md
│   ├── 10_glossary.md
│   └── 11_ai_product_surface.md     NL query agent, narrator, agentic roadmap
├── data_generation/                 Synthetic dataset + BigQuery uploader
│   ├── generate_data.py             Faker + pandas; 4 tables with injected anomalies
│   ├── upload_to_bq.py              Explicit schemas, clustering, sandbox-aware
│   ├── config.py                    Tunable knobs
│   └── README.md
├── pipeline_and_tests/              dbt-style SQL + DQ + evals
│   ├── run.py                       BQ orchestrator + parquet export
│   ├── params.py                    Parameters cite spec 03 §6
│   ├── sql/                         13 models: staging → intermediate → metric → mart
│   ├── dq/run_dq.py                 16 assertions (block + warn tiers)
│   ├── evals/run_evals.py           11 checks across T1-T4
│   └── README.md
└── dashboard/                       Streamlit prototype
    ├── app.py                       5 views: exec / reps / account drill / DQ / Ask
    ├── lib/ask.py                   NL agent: offline router OR Claude Sonnet + verifier
    ├── lib/narrator.py              Template-filled anomaly narrative (spec 11 §3.2)
    └── README.md
```

The specs are the source of truth; the code cites them.

---

## What the pipeline produces

Running against the seeded dataset (SEED=42, 1,000 accounts, ~215K usage rows),
verified against a personal GCP sandbox (source tables in `gtm_analytics`,
pipeline outputs in `gtm_metric`):

| Metric | Value |
|---|---:|
| Accounts in metric | 1,000 |
| Committed ARR (sum) | $133,203,215 |
| cARR (sum) | $112,715,015 |
| Weighted HealthScore | 0.846 |
| Healthy accounts | 612 |
| At-risk / shelfware accounts | 196 |
| Overage accounts | 178 |
| Spike-drop accounts | 8 |
| Expansion accounts | 6 |
| Orphan usage excluded from metric | 350 logs ($73K credit value) |

Rerun produces byte-identical parquet — no `NOW()`, no random seeds in the models (D07).

All 16 DQ assertions pass. All 11 evals (T1 Correctness, T2 Construct validity, T3 Decision utility, T4 Comp safety) pass.

---

## Architecture at a glance

```
              Synthetic Generator  (Faker + pandas, seeded)
                        │
                        ▼
                ┌───────────────────┐
                │   BigQuery raw    │   sales_reps · accounts
                │  (gtm_analytics)  │   contracts · daily_usage_logs
                └─────────┬─────────┘
                          │ dbt-style SQL models
                          ▼
              ┌────────────────────────────┐
              │ staging → int → metric     │   deterministic, idempotent
              │  (gtm_metric in BQ)        │   no NOW(), no RANDOM()
              └────────────┬───────────────┘
                           ▼
                 ┌──────────────────┐          ★ immutable month-end
                 │   mart_carr_*    │──────────→  snapshot (D06)
                 └────────┬─────────┘
                          │ parquet export (pipeline_and_tests/data/)
                          ▼
           ┌──────────────────────────────────┐
           ▼                                  ▼
    ┌──────────────────┐        ┌───────────────────────┐
    │ Streamlit        │        │ DQ (16)  +  Evals (11)│
    │  5 views +       │        │  block / warn / T1-T4 │
    │  NL "Ask cARR"   │        └───────────────────────┘
    └──────────────────┘
           ▲
           │ (LLM mode, optional)
    ┌──────────────────┐
    │  Claude Sonnet   │   system-of-record stays the SQL,
    │  + SQL verifier  │   never the LLM (spec 11 §4)
    └──────────────────┘
```

Detailed layer-by-layer in [spec 04](specs/04_pipeline_architecture.md); AI surface in [spec 11](specs/11_ai_product_surface.md).

---

## Reading this repo as a panel reviewer

Recommended path — ~30 minutes end-to-end:

| Order | Doc | Time | Why |
|---:|---|---|---|
| 1 | [`specs/README.md`](specs/README.md) | 3 min | Decision log (13 ADRs, incl. one supersedence); what was contested and how I called it |
| 2 | [`specs/01_problem_statement.md`](specs/01_problem_statement.md) | 3 min | Context, personas, what success looks like |
| 3 | [`specs/03_north_star_metric.md`](specs/03_north_star_metric.md) | 7 min | The formula + worked examples + new-logo fairness rule (the heart of the proposal) |
| 4 | [`specs/11_ai_product_surface.md`](specs/11_ai_product_surface.md) | 5 min | The AI layer on top of the metric, incl. golden queries and the agentic roadmap |
| 5 | [`specs/06_evaluation_framework.md`](specs/06_evaluation_framework.md) | 3 min | How I'd know it's working; 4 tiers with numeric pass criteria |
| 6 | [`specs/08_rollout_plan.md`](specs/08_rollout_plan.md) | 3 min | Phased adoption with gates and rollback |
| 7 | Run the stack | 5 min | See §"What you can run" above |
| 8 | Any other spec | — | Drill in per interest |

---

## Design philosophy: what makes a "Technical GM"

The role brief frames this PM as a *Technical GM*, not a requirements middleman. Four choices run through every artifact in this repo, and are, to me, what that means:

1. **Every defensible decision is written down before code is written.** When the VP Sales or CFO pushes on *why* the formula is the way it is, the answer is in a spec, not someone's head. The decision log (`specs/README.md`) has 13 ADRs as of this snapshot (including one supersedence, D12 → D12b); every one exists because a reasonable person could have chosen differently.

2. **Bounds matter more than sophistication.** The metric is bounded `[0.40 × Committed, 1.30 × Committed]` — a mathematical fence that survives any customer's extreme behavior. A CFO can sanity-check it in three queries. The v0.7 pre-signal trust rule (D12b) is similarly bounded: a single-branch default, not a new parameter space.

3. **The AI layer is a product surface with the same rigor as the metric.** The NL query agent is not a wrapper around an LLM — it is a retriever, a generator, a *verifier*, an executor, and a narrator with an explicit refusal policy and a four-tier eval harness (spec 11 §5). The LLM is never the system of record; the SQL is. Hiding the SQL from the user is the thing I refused to let the product do.

4. **Rollback cost determines phase design.** Shadow comp is long (spec 08) because the only way to know a comp metric is trustworthy is to run it against real behavior for a full cycle. Skipping that is how good metrics become paycheck lawsuits.

The Q&A portion of the panel will press on these. The specs + decision log are designed so every press has an answer.

---

## Decision log (quick index)

The contested choices — 13 of them as of `main`, including one supersedence — live in [`specs/README.md#decision-log`](specs/README.md#decision-log) as a lightweight ADR catalog. Selected highlights the panel is likely to press on:

- **D01.** `cARR = Committed_ARR × HealthScore` (multiplicative, not a weighted blend or ML). *Why:* bounded, CFO-anchored, comp-defensible, rep-readable.
- **D04.** Overlapping contracts *accumulate*, not `max()`. *Why:* the customer signed both checks.
- **D07.** Rules-based SQL, not ML. *Why:* no labeled training data yet; reps must be able to read the rule.
- **D09.** No time partitioning in sandbox; clustering only; flag-gated for prod. *Why:* sandbox's 60-day partition expiration silently evicted 77% of rows until caught.
- **D11.** Expansion credit is a small `+5%` modifier, not a formula-level feature. *Why:* rewards behavior without blowing up the multiplier.
- **D12 → D12b.** v0.6 tried a segment-aware ramp blend for new logos; v0.7 supersedes it with a **pre-signal trust** rule — when `U` is undefined (no usage posted yet), `HealthScore = 1.00` by default. *Why the change:* the blend introduced four tuning parameters that every comp cycle would re-litigate; the pre-signal default preserves new-logo comp fairness with zero extra knobs.

---

## AI-assisted development (spec-first workflow)

This project was built using an AI coding assistant (Claude Code) against a Markdown spec-driven workflow — the methodology Palo Alto Networks' brief explicitly calls out.

**How it worked:**
1. Write a Markdown spec describing what needs to exist (e.g., the `cARR` formula, edge-case rules, invariants).
2. Ask the AI to generate the implementation (SQL, Python, tests) citing the spec.
3. Run it. Validate the output numerically and against the spec's invariants.
4. Every surprise (e.g., BigQuery Sandbox's 60-day partition expiration — D09; the v0.5 new-logo penalty — D12) triggers a spec update *and* a code update in the same PR.

**What the AI is good at in this workflow:**
- Rapid boilerplate (schema definitions, repetitive SQL, markdown tables).
- Drafting rejected-alternatives appendices from a bullet list.
- Normalizing vocabulary across 12 specs in one pass.

**What the AI got wrong** (and where human judgment mattered):
- Confidently generated MONTH-partitioned tables and did not flag the sandbox's 60-day expiration. I ran the code, saw 41K rows instead of 182K, traced it — that bug is why D09 exists.
- Defaulted v0.5 of the metric to a no-grace-period design that would have penalized every new logo. The v0.6 fix (D12, ramp blend) overcorrected by adding four tuning parameters; v0.7 supersedes it with a one-line pre-signal-trust rule (D12b) that preserves new-logo fairness without the parameter fight surface.
- Consistently over-engineered; humans trimmed.
- Invented plausible-sounding statistics; humans replaced with measured values.

Every commit in this repo carries a `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer — a literal attribution signal for anyone auditing provenance.

---

## Contributing

This repo treats specs as the primary artifact. The workflow:

1. Open a branch: `git checkout -b specs/<short-name>` (for spec changes) or `feat/<area>-<short-name>` (for code).
2. Write or modify the spec first. Cross-cutting changes touch every affected spec in the same PR.
3. If the change affects a decision in the decision log, add or amend a row.
4. Implementation PRs cite the spec + section they implement in commit messages.

See [`specs/README.md` §How to propose a change](specs/README.md#how-to-propose-a-change) for the full flow and required reviewers.

Commits use conventional-commits style:

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

## License

Take-home deliverable; no public license.
