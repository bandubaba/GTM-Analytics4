# 01 — Problem Statement

| Field         | Value                                               |
|---------------|-----------------------------------------------------|
| Spec          | `01_problem_statement.md`                           |
| Audience      | Exec sponsors (VP Sales, CFO, CRO), panel reviewers |
| Owner         | Principal PM, GTM Analytics                         |
| Status        | Draft                                               |
| Version       | 0.1                                                 |
| Last reviewed | 2026-04-19                                          |
| Related       | [03 — North Star Metric](03_north_star_metric.md), [08 — Rollout Plan](08_rollout_plan.md) |

---

## 1. One-line summary

We are redefining the GTM North Star so that **bookings without realized usage no longer look like success**, and so that sales reps are compensated on a number that survives the ARR → consumption business-model transition.

## 2. Context

The company is moving from a traditional Annual Recurring Revenue (ARR) commercial model — large upfront commitments, billed in advance — to a **hybrid consumption model** where a sizeable portion of revenue depends on post-sale platform usage. Contracts now ship with an `annual_commit_dollars` *and* an `included_monthly_compute_credits` allotment, and reality diverges from paper in all the usual ways:

- Some customers consume well past their included credits ("overage") — organic expansion signal.
- Some customers sign, never adopt, and quietly roll toward non-renewal ("shelfware").
- Some customers burn their full annual allotment in the first month, then drop to near-zero ("spike-and-drop") — a churn pattern that looks like adoption at first glance.
- Mid-year expansions layer new contracts on top of old ones, creating overlapping commitments that downstream tooling often double-counts or silently ignores.

**The comp plan still pays on ARR at signature.** A rep who closes a $500K contract that the customer never touches earns the same as a rep who closes a $500K contract with 140% utilization and a clear expansion path. Sales leadership sees the disconnect; so does the CFO, who is increasingly asked to forecast a quarterly number that ARR-at-signature does not predict.

## 3. Why now

1. **Commercial model is already shifting.** >35% of new-logo ARR in the last two quarters was sold with a consumption component. Every additional quarter without a unified metric compounds the measurement gap.
2. **Comp planning window is approaching.** FY27 sales comp plans are locked in Q3 FY26. A metric adopted after Q3 will not influence next year's behavior.
3. **CFO forecasting variance is widening.** The gap between quarter-start ARR-based revenue forecast and quarter-end realized revenue has grown from ~3% to ~9% over four quarters — the ARR signal is losing predictive power.
4. **Board-level visibility.** Two recent board decks have flagged "how do we measure sales in the consumption world" as an open question. A defensible answer is expected in the next cycle.

## 4. Audiences / personas

The five humans this initiative touches. Their needs are distinct; the metric must serve all of them without pretending they're the same.

### 4.1 VP Sales ("Samir")

- **Wants:** one number he can put on a weekly exec readout that correlates to the quarterly revenue forecast.
- **Cares about:** rep incentives aligned with what the company actually earns. Reps gaming the metric would be catastrophic.
- **Decisions he makes:** comp plan design, rep quota assignments, territory realignment.
- **What failure looks like:** his top reps leave because comp feels arbitrary; or the metric rewards behaviors that don't renew.

### 4.2 CFO ("Priya")

- **Wants:** a metric that reconciles to revenue within a predictable variance band; hard mathematical bounds she can sanity-check with three queries.
- **Cares about:** downside protection. "What's the floor?" is her first question, always.
- **Decisions she makes:** revenue forecast, earnings guidance, cash planning, commissions accrual.
- **What failure looks like:** quarter-end surprises; metric restated after comp is paid; audit finds comp was paid against non-GAAP-mappable numbers.

### 4.3 Sales Rep ("Marcus, Enterprise" / "Jess, Mid-Market")

- **Wants:** to know by the end of any given day what his comp stands at, and why.
- **Cares about:** fairness and predictability. If his number moves more than a few points between the 1st and the 15th without a deal closing, he loses trust in the plan.
- **Decisions he makes:** which deals to push this month vs. next, which accounts to prioritize for renewal vs. new logo, which internal resources to pull in.
- **What failure looks like:** his number changes mid-period without explanation; he can't defend his commission statement to his spouse.

### 4.4 Customer Success Manager ("Lin")

- **Wants:** a health signal that tells her which accounts need intervention this week.
- **Cares about:** early warning. A shelfware account flagged 60 days before renewal is actionable; flagged at the renewal meeting is not.
- **Decisions she makes:** which accounts to QBR this month, which to escalate to an EBR, which to hand to professional services.
- **What failure looks like:** the metric surfaces problems she already knew about (reactive), or surfaces noise she has to triage away from real signal (false positives erode credibility).

### 4.5 RevOps Analyst ("Dan")

- **Wants:** a reproducible, auditable pipeline he doesn't have to babysit. Queries he can answer in minutes, not days.
- **Cares about:** change management, documentation, reconciliation with the CRM and billing systems.
- **Decisions he makes:** how to implement the plan in the CRM / comp engine, what to report to leadership each week, which edge cases need manual review.
- **What failure looks like:** spending 10 hours each month-end reconciling mismatches between the metric, Salesforce, and Zuora.

## 5. Pain points (status quo)

Ranked by frequency and by the severity of the downstream consequence.

1. **Shelfware invisibility.** ARR reporting shows a rep's number going up when they close a deal; it does not go down if that customer never adopts. Recognition of non-adoption happens at renewal, 12 months too late.
2. **Comp misalignment with economic reality.** Reps have no incentive to select for customers who will actually *use* the product. The best-paid rep this year could be the one with the highest churn cohort next year.
3. **CFO forecasting blind spot.** ARR at signature is a leading indicator only if adoption is uniform. With 10% shelfware, 5% spike-drop, and 15% over-utilization, the distribution is anything but uniform, and aggregate ARR loses forecasting value.
4. **CSM reactivity.** CSMs learn about unhealthy accounts from quarterly business reviews or when the rep asks "hey, is ACC000412 going to renew?" — weeks or months after the health signal should have fired.
5. **No shared vocabulary.** Sales, Finance, and CS use different working definitions of "healthy account" — sometimes literally the same word ("utilization") with different formulas behind it. Cross-functional conversations waste cycles resolving definitions before addressing the actual question.
6. **Data quality surfaces as comp disputes.** Today, orphan usage logs, overlapping contracts, and out-of-window timestamps silently corrupt the numbers that drive quarterly reviews. Reps discover the data issues when their statement looks wrong — which is the worst possible time.

## 6. Goals

In priority order. Each goal has an explicit success criterion.

| # | Goal | Success criterion |
|---:|---|---|
| G1 | Define a single GTM North Star that balances booking motion with sustained usage over a customer lifecycle | Spec 03 accepted by VP Sales + CFO; formula frozen; invariants pass |
| G2 | Make the metric **defensible** to the full audience set in §4 | Every persona can read a one-paragraph explanation of how their number is computed, without a data team escort |
| G3 | Make the metric **operable** — automated, reproducible, frozen on month close | Pipeline SLA: T+2 of month-end; `mart_carr_by_rep_month_end` is byte-identical on re-runs |
| G4 | Establish an **evaluation framework** that ties the metric to business KPIs (not just loss functions) | 4-tier framework in spec 06 green on T1 + T2 + T4 for two consecutive months |
| G5 | Pilot the metric for **reporting only** in FY26 Q3; pilot comp attachment in FY26 Q4; full comp tie-in FY27 Q1 | Gated rollout per spec 08 with explicit VPS + CFO sign-off between phases |

## 7. Non-goals

What we are **not** solving in this initiative. Scope discipline matters.

1. **We are not redesigning the commercial model.** Contracts still list `annual_commit_dollars` and `included_monthly_compute_credits`. Pricing changes are a separate workstream.
2. **We are not shipping a churn prediction model.** cARR is a *measurement* metric, not a *predictive* model. A churn model would be downstream, advisory, and separately approved.
3. **We are not replacing Salesforce or the comp engine.** The metric is a new mart table; comp integrations are a later phase.
4. **We are not covering pipeline / pre-booking metrics.** Win rate, CAC, pipeline coverage are their own specs. cARR is *trailing* by definition.
5. **We are not defining variable-pay percentages** (i.e., "70% cARR / 30% new-logo"). That is a Sales + Finance negotiation captured in the comp plan, not the metric spec.
6. **We are not building a public API** for customers to see their own cARR. Internal only, for at least the first two phases of rollout.

## 8. Constraints

1. **Audit + legal.** The metric, once it drives comp, is regulated financial data. It must meet our existing SOX-style controls: immutable month-end snapshots, documented change management, role-based access, 7-year retention.
2. **Data privacy.** Rep-level detail is Personal Information under the comp data classification. RBAC is non-negotiable.
3. **Explainability.** If a rep can't read the rule their comp is computed against, we are exposed to a comp dispute with no defense. ML-based scorers are not in scope for this reason (see spec 03, D07).
4. **Infrastructure continuity.** We are committed to BigQuery as the warehouse (see D08). This is not a greenfield warehouse decision.
5. **No new vendors in FY26.** The build is constrained to tooling already in our stack (BQ, dbt, Python, and the dashboard stack chosen in spec 07).

## 9. Risks (top 5)

Full treatment in spec 08 (rollout plan). Summary here:

| # | Risk | Likelihood | Impact | Mitigation |
|---:|---|---|---|---|
| R1 | Comp plan rollout triggers rep attrition if the new metric re-ranks top performers | M | H | Phase 1 reporting-only; Phase 2 shadow-comp; historical re-compute side-by-side with old metric before tying to pay |
| R2 | CFO rejects the metric late because the monthly variance band isn't narrow enough | M | H | Eval tier T4 (Comp safety) is explicit CFO gate with a written pass criterion |
| R3 | Reps find a way to game `U` (e.g., running synthetic usage from a headless account) | L | H | Orphan / out-of-window detection in DQ spec; usage anomaly alerts; expected-utilization envelope per account size |
| R4 | Data quality issues in raw usage logs corrupt downstream comp | M | M | DQ gates in spec 05; freeze rule in spec 03 prevents silent correction; restatement workflow provides controlled correction path |
| R5 | The multiplier structure interacts badly with a future SKU / pricing change | L | M | Formula lives in one file behind a spec; parameter table in spec 03 calls out which knobs require which approvals |

## 10. Success definition — in one paragraph

This initiative succeeds when a VP Sales weekly readout opens with a single number — **cARR** — and both the CFO and the top-paid Enterprise rep can explain how their piece of that number was computed, and both agree the number is fair. That agreement is the product. Everything in the rest of this spec stack is the machinery that makes the agreement possible.

---

## Appendix A — Rejected framings

| Framing considered | Why rejected |
|---|---|
| "Consumption revenue as the North Star" | Ignores bookings motion; too volatile for comp; requires a pricing → credits translation we don't own |
| "Net Revenue Retention (NRR) as the North Star" | Backward-looking by 12 months; excludes new-logo motion; doesn't align with quarterly comp cadence |
| "Two North Stars — bookings and consumption, reported separately" | Creates exactly the cross-functional misalignment §5 item 5 describes; executive attention is a scarce resource and two numbers dilute it |
| "Leave ARR, add a health score to the rep scorecard" | The health score gets ignored in practice when it doesn't tie to comp; leadership has tried this twice and it hasn't changed rep behavior |
