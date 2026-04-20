# 08 — Rollout Plan

| Field         | Value                                                                   |
|---------------|-------------------------------------------------------------------------|
| Spec          | `08_rollout_plan.md`                                                    |
| Audience      | VP Sales, CFO, CRO, People Ops, RevOps, Principal PM, Internal Audit    |
| Owner         | Principal PM, GTM Analytics (with VP Sales as exec sponsor)             |
| Status        | Draft                                                                   |
| Version       | 0.1                                                                     |
| Last reviewed | 2026-04-19                                                              |
| Related       | [01 — Problem Statement](01_problem_statement.md), [03 — Metric](03_north_star_metric.md), [06 — Eval](06_evaluation_framework.md), [09 — Access](09_access_and_audit.md) |

---

## 1. Purpose

This spec defines **how cARR moves from a PM's proposal to a live comp-driving metric** without blowing up the sales organization. It is a phased, gated rollout — each phase is a separate decision with explicit pass / rollback criteria, and the decision rights at each gate are named.

The central idea: the metric is the contract. We de-risk the rollout by making the *consequences* incremental, not the *metric* incremental.

---

## 2. Guiding principles

1. **De-risk the exposure, not the metric.** cARR ships at its full definition from day one; what changes per phase is how much of a rep's paycheck is exposed to it.
2. **Every phase is an opt-in decision, not an opt-out.** We never move forward by default — each gate requires an explicit sign-off.
3. **Rollback is cheaper than reputation repair.** Rolling back one phase is annoying; shipping a broken comp metric is unrecoverable for the year.
4. **Comms cadence matches risk cadence.** Tight comms where stakes are high (Phase 2 → 3 gate), lower cadence where stakes are low (Phase 1 reporting-only).
5. **Shadow comp is the most valuable phase.** More time in Phase 2 than any other. It's the one where we learn without risk.

---

## 3. Phase overview

| Phase | Name | Duration | What changes | Who approves entry |
|---|---|---|---|---|
| **0** | Foundation | FY26 Q2 | Spec stack, pipeline, evals, dashboard exist. No audience yet. | Principal PM |
| **1** | Reporting-only | FY26 Q3 (1 quarter) | Exec audience sees cARR; metric is advisory | VP Sales + Principal PM |
| **2** | Shadow comp | FY26 Q4 (1 quarter) | Comp calculated on cARR *in parallel* with old plan; not paid | VP Sales + CFO |
| **3** | Partial comp tie-in | FY27 H1 (2 quarters) | 30% of variable pay attached to cARR; 70% legacy | VP Sales + CFO + CRO |
| **4** | Full comp tie-in | FY27 Q3+ (ongoing) | Full variable pay driven by cARR blend | VP Sales + CFO + CRO |

Quarters refer to the fiscal calendar in this prototype; map to actual calendar months at rollout time.

---

## 4. Phase 0 — Foundation

**Entry criteria:** project kickoff.

**What we build:**
- Spec stack 01–10 (this one is 08).
- Pipeline implementation per [spec 04](04_pipeline_architecture.md), green on T1 + T2 evals per [spec 06](06_evaluation_framework.md).
- Synthetic-data harness for testing and demos ([data_generation](../data_generation/README.md)).
- Prototype dashboard per [spec 07](07_dashboard_spec.md).

**Success criteria:**
- All 11 specs at `Draft` or better.
- T1 + T2 evals green on latest prod-like data.
- DQ P0 assertions 100% passing.
- Prototype dashboard demoable end-to-end.

**Exit to Phase 1:** Principal PM sign-off; VP Sales quick review.

**Rollback from Phase 0:** n/a — failure here means the project doesn't start, not that we roll back.

---

## 5. Phase 1 — Reporting-only

**Entry criteria:** Phase 0 exit met + VPS quick review complete.

**What changes:**
- cARR becomes visible on the exec dashboard alongside the legacy ARR number.
- Weekly GTM exec readout includes a cARR line.
- No rep-facing visibility. No comp tie.

**What does NOT change:**
- Rep comp is still computed from legacy ARR.
- CSMs still use existing processes.
- No public communication.

**Success criteria (measured at end of quarter):**
- cARR has been published month-end on time, per [spec 04 §5](04_pipeline_architecture.md#5-refresh-cadence-and-slas), 3/3 months.
- T1 + T2 evals green every week.
- T3 Decision utility green at least twice.
- CFO signs off on: "the cARR number I see each month is reconcilable to our revenue forecast within ±5%."
- No DQ P0 incidents on closed data (P0 on open data is fine, it's why the pipeline exists).

**Exit to Phase 2:** VP Sales + CFO joint review; documented approval.

**Rollback criteria (any of):**
- DQ P0 incident on a closed month → open restatement and pause rollout.
- T3 Decision utility fails twice in the quarter → formula revision required.
- CFO variance reconciliation exceeds ±5% → extend Phase 1.

**Stakeholder comms in Phase 1:**
- Internal: weekly GTM exec readout footnote.
- No broader comms — avoid speculation in the sales org before the metric is real.

---

## 6. Phase 2 — Shadow comp

The most important phase. Slow down, spend real time here.

**Entry criteria:** Phase 1 exit met + VPS + CFO signed.

**What changes:**
- The comp engine computes the variable pay **two ways** for every rep:
  - Legacy method (paid)
  - cARR-based blend (shadow, not paid)
- Reps see both numbers on their comp statement with a clear "shadow — not paid" label on the new number.
- A comp-impact report lands monthly with the CFO + CRO showing: rep-by-rep delta, aggregate impact, extreme movers.
- Rep-facing dashboard access begins — reps can see their own cARR breakdown (see [spec 07 §6 RBAC](07_dashboard_spec.md#10-access-control)).

**What does NOT change:**
- Nobody is paid differently.
- Legacy comp plan is still the authoritative one.

**Success criteria (measured at end of quarter):**
- Reps have asked < N clarification questions per 100 reps (threshold TBD — defines "was the rule clear enough to not generate support tickets").
- T4 Comp safety eval green every week (rank stability ≥ 0.85, ≤ 20% rep movement, parameter sensitivity ≤ 3%).
- No cARR restatements triggered by a rep-raised dispute.
- Delta distribution: median |Δpay| < 8% of legacy, P95 |Δpay| < 25%. Larger shifts signal either (a) a real behavior / book issue the legacy metric was hiding, or (b) a metric-design issue. Either way, we triage before moving on.
- VPS signs off: "if this were real, I would be comfortable paying it."
- CRO signs off: "the top reps aren't being punished for behavior we actually want."
- CFO signs off: "quarterly forecast reconciles under shadow; I can model FY27 against it."

**Exit to Phase 3:** three-way signed review (VPS + CFO + CRO), comp-plan-design PR approved for FY27.

**Rollback criteria (any of):**
- T4 Comp safety fails twice in the quarter.
- >3 reps escalate comp disputes to HR against the shadow number.
- CFO reconciliation drift exceeds ±5% over the quarter.
- CRO raises an "unintended behavior" flag after rep conversations.

**Stakeholder comms in Phase 2:**
- Rep all-hands announcement at phase entry with comp statement walkthrough.
- Weekly "cARR q&a" office hours run by RevOps + Principal PM.
- Monthly impact report distributed to VPS + CFO + CRO + HR.
- FAQ live-document maintained by RevOps.

**Why this phase is long:** because the only way to know if a comp metric is trustworthy is to run it against real behavior, over a full compensation cycle, and see if the humans it governs trust the number.

---

## 7. Phase 3 — Partial comp tie-in

**Entry criteria:** Phase 2 exit met + FY27 comp plan PR approved.

**What changes:**
- FY27 comp plan attaches **30%** of variable pay to cARR (the remaining 70% to legacy). Percentages are placeholder — the real split lives in the comp plan doc, not this spec.
- Dispute process formalized with RevOps and People Ops. A rep who disputes a cARR-driven pay figure gets a same-day walk-through of the formula and inputs.
- Dashboard access expanded to sales managers (team-level view).

**What does NOT change:**
- cARR formula itself. No parameter changes during a comp cycle.

**Success criteria (measured at end of H1):**
- Dispute rate ≤ 2% of reps (i.e., ≤ 2 per 100).
- Attrition rate of top quartile cARR reps ≤ historical baseline + 1pp. (Attrition is the real test — if the metric is unfair to high performers they leave.)
- T1, T2, T3, T4 all green every week.
- Two full quarters of restatement-free closed-month snapshots.
- External auditor review of the pipeline passes with no findings (SOX-adjacent).

**Exit to Phase 4:** VPS + CFO + CRO + Internal Audit joint sign-off.

**Rollback criteria (any of):**
- Dispute rate > 5%.
- Top-quartile attrition > baseline + 3pp.
- SOX/Internal Audit finding.
- T4 failure ≥ 3 times in the half-year.

If we roll back: return to Phase 2 (shadow), not to Phase 1 (reporting-only). Removing rep visibility is worse than removing pay attachment.

**Stakeholder comms in Phase 3:**
- FY27 comp plan announcement at H1 all-hands.
- Monthly office hours continue.
- Dispute resolution SLA published and held: 5 business days from filing to resolution.

---

## 8. Phase 4 — Full comp tie-in

**Entry criteria:** Phase 3 exit met.

**What changes:**
- Variable pay blend shifts to its target (placeholder: 70% cARR / 30% legacy retained for floor protection + transition).
- Metric becomes the North Star everywhere — exec readouts, board decks, investor narrative.
- Historical legacy-ARR reporting kept for at least 2 years for comparative analysis.

**What does NOT change:**
- Spec discipline. Changes to the formula still require the PR + review process.

**Success criteria (ongoing):**
- All the metrics in Phase 3 continue to pass.
- CFO can explain cARR variance to external auditors and investors without a data-team translator.
- New rep onboarding includes a ~15-minute cARR explainer as a standard module; no SME required.

**Rollback from Phase 4:**
- Requires board-level (or equivalent) approval. At this point we are out of "rollback" territory and into "revise the spec + run the change through the change management process in [spec 03 §10](03_north_star_metric.md#10-change-management)."

---

## 9. Timeline (summary)

```
  FY26 Q2            FY26 Q3        FY26 Q4         FY27 H1           FY27 H2+
  ──────────         ──────────    ──────────       ──────────────    ──────────
  Phase 0            Phase 1       Phase 2          Phase 3           Phase 4
  Foundation         Reporting     Shadow comp      30% tie-in        Full tie-in
                     only
  2.0 months         1 quarter     1 quarter        2 quarters        ongoing

  Spec stack         cARR on       Comp engine      FY27 comp plan    Legacy ARR
  Pipeline           exec          runs dual        live with 30%     retained for
  Prototype          dashboard     Shadow on        cARR weighting    2y compare
  dashboard          only          rep statements
```

Interview-relevant note: the phasing assumes we're starting planning ~6 months before FY27 begins. Compressing it is possible but each compression adds risk at Phase 2 (shadow comp learning time) or Phase 3 (attrition signal visibility).

---

## 10. Risk register

Cross-linked to [spec 01 §9](01_problem_statement.md#9-risks-top-5). Rollout-specific additions:

| # | Risk | Likelihood | Impact | Phase affected | Mitigation |
|---:|---|---|---|---|---|
| R6 | Comp-dispute volume overwhelms RevOps | M | M | 2, 3 | Office hours + FAQ; pre-compute the 10 most common "why does my number look weird" scenarios into account-level narrative strings in the dashboard |
| R7 | A customer-side billing issue inflates an account's cARR mid-period | L | H | 2, 3, 4 | DQ-BIZ-003 + upstream contract; freeze rule prevents silent mid-period shifts |
| R8 | Regional variance (one geography's accounts behave differently) shows up as rep-unfairness | M | M | 2, 3 | Sensitivity tests by region in the eval suite; parameter per-segment if justified |
| R9 | Board-level demand to accelerate shortens Phase 2 | M | H | 2 | Spec-level veto: Phase 2 is minimum 1 quarter; acceleration requires written exec-sponsor acknowledgment of the risk |
| R10 | Legal / SOX review finds a gap in the audit trail pre-Phase-3 | L | H | 3 | Engage Internal Audit in Phase 1; spec 09 access + audit is prerequisite for Phase 3 entry |

---

## 11. Change communication templates

### 11.1 Phase 1 exec footnote (Reporting-only)

> "This week's GTM readout includes a new line: **cARR** — Consumption-Adjusted ARR. It is advisory and does not affect compensation. cARR is committed ARR adjusted by a bounded utilization health score (`[0.40, 1.30]`). See [spec 03](03_north_star_metric.md) for the formula."

### 11.2 Phase 2 rep all-hands opener (Shadow comp)

> "Your comp statement next month will show two numbers: the current plan (**which you are still paid on**) and a new shadow number computed from **cARR**. We are running both side-by-side for one quarter. Nothing about your pay changes yet. The second number is how we expect to compensate you starting FY27, pending review. If your two numbers differ significantly, there's a real reason, and we'd like to discuss it. Office hours with the Principal PM + RevOps every Wednesday at noon."

### 11.3 Phase 3 FY27 comp plan announcement (Partial tie-in)

Deferred to the FY27 comp plan document itself.

---

## 12. Open questions

1. **Who owns the rep dispute process in Phase 2 onward?** Proposed: RevOps triage, People Ops escalation. Pending.
2. **Does Public Sector carve out of cARR-based comp entirely, or participate?** Depends on resolution of the unlimited-tier carve-out in [spec 03 §9](03_north_star_metric.md#9-open-questions).
3. **Does the Phase 3 30/70 split hold across all segments?** Possibly 50/50 for Mid-Market (more volatile book) and 20/80 for Enterprise (more stable ACV). Compensation design, not this spec.
4. **Exec sponsor during the CRO transition.** If the CRO changes mid-rollout, how do we keep continuity? Written exec sponsor assignment and a VPS fallback.

---

## Appendix A — Rejected rollout patterns

| Alternative | Why rejected |
|---|---|
| Single big-bang switch on Jan 1 | Zero learning time; unrecoverable if the metric is wrong; reps would not trust an untested formula with their paycheck |
| Roll out by region (NAMER first) | Creates a two-tier comp experience within the same org; legal and fairness issues |
| Roll out by segment (Enterprise first) | Same fairness issues; also Mid-Market sees larger effect sizes and is the better stress test |
| Keep Phase 1 open-ended until "we feel good" | Without an exit criterion, the initiative dies from inertia |
| Skip shadow comp and go straight to 10% tie-in | A small tie-in is still a tie-in — reps will dispute it as if it's the whole thing, without a quarter of data to point at |

## Appendix B — Exit-gate decision template

Copy-paste template for the sign-off doc that moves the rollout through each gate.

```
GATE: Phase N → Phase N+1
Date: YYYY-MM-DD
Quorum: VP Sales, CFO [, CRO, Internal Audit]

Entry criteria met?
  [ ] Phase N exit criteria per spec 08 §<phase section>
  [ ] T1 / T2 / T3 / T4 eval history reviewed
  [ ] DQ incident history reviewed
  [ ] Risk register reviewed; no new P0 risks unmitigated

Decision:
  [ ] APPROVE — move to Phase N+1 on <date>
  [ ] DEFER  — remain in Phase N for <duration>, revisit on <date>
  [ ] ROLL BACK — return to Phase N-1, reason: <...>

Signatures:
  VP Sales   ____________________  Date ____________
  CFO        ____________________  Date ____________
  CRO        ____________________  Date ____________  (if Phase 3+)
  Internal   ____________________  Date ____________  (if Phase 3+)
   Audit
```
