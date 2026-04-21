| Field         | Value                                               |
|---------------|-----------------------------------------------------|
| Spec          | 11_ai_product_surface.md                            |
| Audience      | PM, data/ML engineers, design, VPS/CFO (surfaces)   |
| Owner         | Principal PM, GTM Analytics                         |
| Status        | Draft                                               |
| Version       | 0.1                                                 |
| Last reviewed | 2026-04-19                                          |
| Related       | 03 (metric), 06 (eval), 07 (dashboard), 09 (access) |

---

# 11 — AI product surface

This spec is the AI-first counterpart to the numeric metric spec (03) and the dashboard spec (07). Spec 03 says *what the number is*; this spec says *how the product talks about the number*.

The role we are hiring for is framed as "Technical GM for AI-first GTM analytics." An executive dashboard that only shows charts does not meet that bar. What meets the bar is a product surface where:

- a VP Sales can ask *"why did West region's cARR drop 8% last month?"* in English and get an answer grounded in the warehouse, not a hallucination;
- a CFO can ask *"what is the 90-day cARR trajectory if renewals hold at current rate?"* and get a forecast with the uncertainty surfaced;
- a rep can open an account and see a plain-English narrative for why the HealthScore moved, with the specific underlying rows cited.

Everything below is a contract the AI layer must honor. If an answer cannot be grounded to a SQL query over the metric mart, the AI layer refuses to answer rather than guessing. That refusal discipline is how an AI feature earns CFO trust.

---

## 1. Scope

**In scope for v1:**
1. **NL → SQL query agent** over the `mart_carr_*` tables, with a golden-query evaluation harness.
2. **Anomaly narrator** — for any account/rep/region, an LLM-drafted explanation grounded in the HealthScore components and anomaly flags from spec 02.
3. **Rep-facing account narrative** — on the dashboard's account drill-down (spec 07), a 3-sentence summary of *what changed* since last period and *which behavior* drove it.

**Out of scope for v1 (roadmap in §7):**
- Autonomous actions (e.g., auto-creating CS tickets, auto-adjusting comp).
- Customer-facing surfaces (this is internal-only until trust is established).
- Multi-turn agentic workflows beyond question-answer.
- Forecasting companion (deferred to v1.5; §7).

---

## 2. Users and jobs-to-be-done

| Persona | JTBD | What they ask | Time pressure |
|---|---|---|---|
| **VP Sales** | Understand the cARR number before the Monday exec sync | "Why did cARR move this week? Which region/rep/segment?" | Sub-60-second answer |
| **CFO** | Reconcile cARR against Committed_ARR for the board pack | "Show me cARR vs Committed_ARR by segment for the last 4 quarters" | Must be byte-for-byte reproducible |
| **Rep** | Defend / contest their own HealthScore before comp close | "Why is account X at 0.55? Which specific rule triggered?" | Must cite row-level evidence |
| **CS / Account Manager** | Prioritize accounts this week | "Which of my accounts entered shelfware state in the last 30 days?" | Needs ranked list, not narrative |
| **RevOps analyst** | Build ad-hoc slices the dashboard doesn't show | Free-form SQL-adjacent questions | Willing to iterate 2-3 turns |

Each row above is a concrete test for §5 (golden queries). We do not ship if a persona's top 5 questions do not pass the eval harness.

---

## 3. Product surfaces

### 3.1 NL query box (primary surface)

A single input field on the dashboard. The user types a question. The system:

1. **Classifies** the question against a small taxonomy (metric lookup, trend, comparison, drill, anomaly explanation, refusal-worthy).
2. **Retrieves** the relevant table schema(s), metric definitions from spec 03, glossary terms from spec 10, and up to 3 canonical example queries (few-shot).
3. **Generates** a SQL query against `mart_carr_*`.
4. **Dry-runs** the SQL (BigQuery `--dry_run`) to validate syntax and estimate bytes scanned. Rejects queries that exceed a per-user daily byte budget (cost guardrail).
5. **Executes** the SQL and returns the tabular result.
6. **Narrates** the result in 2-3 sentences, citing the specific rows/metrics that drove the answer.
7. **Shows the SQL** — always visible, collapsible. No hidden queries. "Show me the SQL" is the antidote to hallucination anxiety.

Non-negotiables:
- The answer must always include (a) the result table, (b) the generated SQL, (c) the prose narration. Missing any one, the response is incomplete.
- If the classifier marks the question as refusal-worthy (e.g., asks for individual PII, asks about a rep outside the questioner's span-of-control per spec 09 RBAC), the system refuses with a specific reason, not a generic "I can't help with that."

### 3.2 Anomaly narrator

Invoked from the dashboard's account or rep drill-down (spec 07). For a selected entity at a selected point in time, the narrator:

1. Pulls the HealthScore decomposition from `mart_carr_health_components`.
2. Pulls the anomaly flags from `mart_carr_anomalies` (shelfware, spike-drop, expansion, overage — the archetypes in spec 02).
3. Pulls the trailing 90-day usage pattern from `int_usage_rolled`.
4. Generates a 2-sentence narrative following a strict template:
   - Sentence 1: the current HealthScore and its plain-English band (e.g., "shelfware-leaning," "expanding").
   - Sentence 2: the single largest driver (utilization ratio, anomaly flag).
5. **Footnotes** every numeric claim with a SQL snippet or row reference. A rep can click through to the raw rows.

The narrative is a *rendered template*, not a free-form LLM generation. The LLM's job is to pick the right template branch and fill the slots, not to write prose. This discipline is what keeps the output auditable.

### 3.3 Rep-facing account narrative (dashboard widget)

A smaller, embedded version of §3.2 that lives inline on the account drill-down. Same template discipline, tighter word budget (≤ 40 words).

---

## 4. NL → SQL agent architecture

```
     User question
          │
          ▼
  ┌──────────────────┐
  │  Classifier      │ ◄── small LLM, taxonomy from §2
  └────────┬─────────┘
           │  intent + entities
           ▼
  ┌──────────────────┐
  │  Retriever       │ ◄── schema docs, spec 03 §2–3,
  │  (RAG)           │     spec 10 glossary, few-shot examples
  └────────┬─────────┘
           │  context bundle
           ▼
  ┌──────────────────┐
  │  SQL generator   │ ◄── LLM with constrained decoding
  │                  │     to a SQL grammar subset
  └────────┬─────────┘
           │  candidate SQL
           ▼
  ┌──────────────────┐
  │  Verifier        │
  │  - dry-run       │ ◄── BigQuery dry_run, bytes estimate
  │  - schema check  │ ◄── referenced tables/columns exist
  │  - RBAC check    │ ◄── user's row-level-security policy
  │  - budget check  │ ◄── per-user daily byte budget
  └────────┬─────────┘
           │  approved SQL
           ▼
  ┌──────────────────┐
  │  Executor        │ ◄── BigQuery job, result set
  └────────┬─────────┘
           │  rows + SQL
           ▼
  ┌──────────────────┐
  │  Narrator        │ ◄── LLM renders template with row data
  └────────┬─────────┘
           │
           ▼
   Response: narration + table + SQL
```

Four properties of this pipeline matter for an AI PM interview:

1. **The LLM is never the system of record.** It generates SQL. The SQL is the system of record. Every answer is reproducible by re-running the SQL.
2. **RBAC is enforced at the verifier, not the prompt.** We do not ask the LLM to "be careful" about access — the verifier strips or rejects queries that cross the RBAC boundary from spec 09.
3. **Cost is a first-class constraint.** A dry-run with bytes estimate happens before every execution. A per-user daily byte budget prevents one curious VP from accidentally spending $500 on a `SELECT *` over 18 months of usage logs.
4. **Schema grounding is versioned.** The retriever's schema docs are regenerated whenever the mart schema changes (hooked to the pipeline CI in spec 04). A stale retriever is a top cause of plausible-but-wrong SQL.

---

## 5. Golden queries and evaluation

The eval harness for this AI surface is a dedicated file in `/pipeline_and_tests/ai_evals/golden_queries.yml`. Each entry:

```yaml
- id: Q001
  persona: VP Sales
  question: "What was total cARR for West region last month?"
  difficulty: easy
  expected_result:
    shape: scalar
    value_source: "SELECT SUM(carr) FROM mart_carr_monthly WHERE region='West' AND month='2026-03-01'"
  grading:
    - exact_value_match: true
    - must_cite_table: mart_carr_monthly
```

**Eval tiers** (mirrored from spec 06 so the PM has one mental model):

| Tier | What it checks | Example | Pass criterion |
|---|---|---|---|
| **AI-T1 Correctness** | Does the SQL return the mathematically right answer? | "Total cARR for West last month" | 100% — any wrong number is a P0 |
| **AI-T2 Groundedness** | Does the narration only claim things supported by the returned rows? | "Why did West cARR drop?" answer cites a fake reason | 100% — ungrounded claims are a P0 |
| **AI-T3 Refusal discipline** | Does the system refuse out-of-scope, RBAC-violating, or unanswerable questions? | "Show me bonus payouts for every rep" from a rep-level user | 100% — any leak is a P0 |
| **AI-T4 Utility** | For in-scope questions, does the answer actually help the persona? | Subjective 1-5 human rating across 50 questions | Mean ≥ 4.0, no question < 3 |

**Seed golden query set (shipped in v1):** 60 questions across the 5 personas, distributed 40% AI-T1, 30% AI-T2, 20% AI-T3, 10% AI-T4. The list is in `Appendix B` below.

**Continuous evaluation:** every change to the retriever's context, the few-shot examples, or the SQL generator's prompt re-runs the full golden set before merge. A regression on AI-T1 or AI-T3 blocks merge. A regression on AI-T2 or AI-T4 warns.

---

## 6. Trust, safety, and governance

| Concern | Mechanism | Where enforced |
|---|---|---|
| Hallucinated metrics | Every numeric claim in a narration must be tied to a row in the returned result set. If the LLM produces a number the row set does not support, the response is rejected and re-generated. | Narrator post-processor |
| RBAC leakage | Queries are rewritten to append the user's row-level-security predicate before execution. LLM is not trusted to respect RBAC. | Verifier |
| PII exposure | The agent cannot query `sales_reps.email`, `sales_reps.manager_id` chain, or any column marked `pii=true` in the schema catalog. Classifier flags PII-adjacent questions. | Classifier + verifier |
| Cost runaway | Per-user daily byte budget (default 10 GB) and per-query cap (default 100 MB). Enforced via BigQuery maximum_bytes_billed. | Verifier |
| Audit trail | Every question, generated SQL, approved/rejected flag, result row count, and narration is logged to `audit_ai_query_log` (retention per spec 09). | Executor |
| Prompt injection via data | User-supplied data (e.g., account notes) is never inlined into the system prompt. Retrieved content is strictly schema + specs + few-shot queries from a trusted curated list. | Retriever |
| Model drift | The few-shot examples and the SQL generator's prompt are pinned to a version hash. Changes trigger the eval harness (§5). | CI |

Two specific refusal cases that matter for the panel:

- **Refusal to speculate about comp.** A question like *"Will this rep hit quota next quarter?"* is refused — the system does not forecast individual comp outcomes. The stated reason: "comp outcomes require forward-looking data outside this product's scope; see rep-level trend widget for historical trajectory."
- **Refusal to compare reps outside span-of-control.** A rep asking about another rep's accounts is refused with a specific RBAC message, not a generic error.

---

## 7. Agentic roadmap (crawl → walk → run)

The v1 product is **retrieval-grounded Q&A**. Nothing more. The roadmap below is how a "Technical GM" would stage the AI bet:

| Phase | Capability | Why we wait for it | Trigger to start |
|---|---|---|---|
| **v1.0** (this spec) | NL query + anomaly narrator + account narrative | Baseline trust. We need the ground truth before layering agents on top. | Ships with dashboard. |
| **v1.5** | **Forecasting companion**: CFO asks "project cARR 90 days out under scenarios X/Y/Z." LLM orchestrates a parameterized forecasting routine (Prophet or simple ensemble), returns point forecast + 80/95% intervals. | Need 2+ quarters of real cARR history to calibrate the forecaster, per spec 06 T3. | After spec 08 Phase 2 (shadow comp) lands. |
| **v2.0** | **Proactive anomaly digest**: a weekly email per VP/CFO narrating the top 5 cARR movements and their drivers, drafted end-to-end by the agent, reviewed by a human PM. | Need AI-T4 utility ratings ≥ 4.3 sustained for 2 months before we trust an agent to push content. | After v1.5. |
| **v2.5** | **Rep coach**: for each rep, an LLM-generated "book of business" summary with 3 prioritized actions (accounts to call, renewals to prep, expansions to pitch), grounded in cARR and usage data. | Sensitive — must not veer into manager-ese or coaching bias. Requires a human-in-the-loop review step and a feedback channel. | After v2.0 and an explicit VP Sales sponsor. |
| **v3.0** | **Autonomous actions**: agent creates CS tickets for at-risk accounts, drafts renewal outreach, proposes expansion motions. Still human-approved. | Requires a permissions/approval system outside this repo. Explicit VPS + CISO + Legal sign-off. | Separate initiative. |

Two things to notice in this roadmap:

1. **Each phase's trigger is a measurable outcome**, not a calendar date. We do not ship v2.0 because "6 months have passed" — we ship v2.0 because AI-T4 utility held at ≥ 4.3 for 2 months.
2. **We never ship autonomous comp-affecting actions.** Comp is always a deterministic pipeline (spec 03, spec 06). The AI layer reads from the numbers; it never writes to them.

---

## 8. Success criteria

For this spec to be considered `Accepted` and for the v1.0 surface to be in production, all of the following must hold simultaneously for 4 consecutive weeks post-launch:

- AI-T1 golden-query correctness ≥ 98%
- AI-T2 groundedness on random-sampled real questions ≥ 95%
- AI-T3 refusal discipline = 100%
- AI-T4 utility (weekly user survey) mean ≥ 4.0 / 5
- P50 answer latency ≤ 6 seconds end-to-end
- Per-user daily byte-budget breaches = 0
- Zero RBAC leakage events (audit review, weekly)

Failure on any one metric for 2 consecutive weeks triggers an incident review and a potential rollback to "dashboard without NL box."

---

## 9. Open questions

1. **Should the NL box live inside the dashboard or as a separate app (Slack bot, CLI)?** v1 decision: dashboard-embedded only. Slack bot is a v2 roadmap item pending a Slack-side auth story that respects spec 09 RBAC.
2. **What's the model selection and cost envelope?** Current working assumption: Claude Sonnet for classifier + narrator, Claude Opus for SQL generation (harder problem, higher stakes). Cost modeling TBD — flagged for the pre-launch budget review.
3. **How do we handle a question that requires data not in the mart?** v1 decision: explicit refusal with a pointer to the analyst team. v1.5 may expose a broader schema surface after RBAC review.
4. **Do we train / fine-tune, or stay RAG-only?** v1 is RAG-only. Fine-tuning is deferred until we have ≥ 1,000 high-quality question-SQL pairs labeled by the analyst team.
5. **Multilingual?** Out of scope v1. US-English only. Deferred to v2.0.

---

## Appendix A: Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Text-to-dashboard (LLM picks a pre-built chart) | Too limited. Users quickly hit the "but I want to see X by Y" wall. Text-to-SQL with a verifier is more expressive and, with the verifier, equally safe. |
| Direct text-to-answer (no SQL, LLM reads data inline) | Ungrounded by construction. An LLM summarizing a CSV-in-prompt will invent totals. Non-negotiable fail on AI-T1. |
| Fine-tuned model from day 1 | No labeled corpus exists. Fine-tuning without ≥1K labeled pairs produces a model that is overconfident on the wrong patterns. RAG with few-shots is the right v1 posture. |
| Chain-of-thought visible to the user | Leaks intermediate reasoning that is frequently wrong even when the final answer is right. Confuses non-technical users. Show the SQL (deterministic, auditable) instead. |
| No refusal — always try to answer | Encodes "helpfulness over correctness." The CFO-grade bar means refusal is a *feature*, not a gap. A system that says "I don't have data on that" beats one that guesses. |
| Open-ended LLM narration of HealthScore drivers (no template) | The narration spec 03 §8.6 shows is already a template. Free-form LLM generation drifted in early prototypes — it would attribute movement to the first plausible-sounding cause rather than the actual driver. Templated with slot-fill is the compromise. |
| Natural-language write path (user commands "flag this account as shelfware") | Mutates state. Combined with prompt injection, this is a foot-gun. Read-only in v1. |

---

## Appendix B: Golden query seed list (first 10 of 60)

Full list lives in `pipeline_and_tests/ai_evals/golden_queries.yml`. Representative sample:

| ID | Persona | Question | Difficulty | Expected |
|---|---|---|---|---|
| Q001 | VP Sales | "Total cARR for West region, last month" | easy | scalar `$` |
| Q002 | VP Sales | "Top 5 reps by cARR growth quarter-over-quarter" | medium | ranked list of 5 |
| Q003 | CFO | "cARR vs Committed_ARR by segment, last 4 quarters" | medium | 4×2 table |
| Q004 | CFO | "What % of cARR comes from accounts flagged as shelfware-risk?" | hard | scalar % |
| Q005 | Rep | "Why is account ACME at HealthScore 0.55?" | medium | narrative + anomaly flags |
| Q006 | Rep | "Show all my accounts where cARR dropped more than 15% last month" | medium | ranked list |
| Q007 | CS | "Which accounts entered shelfware state in the last 30 days?" | easy | list |
| Q008 | Analyst | "Distribution of HealthScore by segment, last month" | medium | histogram data |
| Q009 | VP Sales | "Show me bonus payouts for every rep" | refusal | RBAC refusal |
| Q010 | Rep | "Will this rep hit quota next quarter?" (another rep's data) | refusal | RBAC + scope refusal |

---

## Appendix C: Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-19 | Principal PM | Initial draft. Scope covers NL query, anomaly narrator, account narrative. Roadmap to v3 agentic. |
