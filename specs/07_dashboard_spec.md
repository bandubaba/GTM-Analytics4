# 07 — Dashboard

| Field         | Value                                                                        |
|---------------|------------------------------------------------------------------------------|
| Spec          | `07_dashboard_spec.md`                                                       |
| Audience      | Design, frontend engineering, VPS / CFO users, PM                            |
| Owner         | Principal PM, GTM Analytics                                                  |
| Status        | Draft                                                                        |
| Version       | 0.1                                                                          |
| Last reviewed | 2026-04-19                                                                   |
| Related       | [01 — Problem Statement](01_problem_statement.md), [03 — Metric](03_north_star_metric.md), [05 — Data Quality](05_data_quality.md), [09 — Access](09_access_and_audit.md) |

---

## 1. Purpose and scope

### 1.1 What this spec defines

The **minimum viable dashboard** that exposes cARR to its five persona audiences (from [spec 01 §4](01_problem_statement.md#4-audiences--personas)). It specifies views, filters, interactions, performance SLAs, and access model — enough that a frontend engineer can build it without asking a follow-up question.

### 1.2 What this spec is NOT

- **Not a visual design system.** Component details (exact palette, font ramps) live in a design file; this spec references them but doesn't re-litigate.
- **Not a BI tool replacement.** Analysts still run ad-hoc SQL against the marts. This dashboard is for leadership narrative, not exploration.
- **Not a pricing / quoting tool.** Comp statements are delivered by the comp engine, not here — this dashboard shows the *reporting metric*, not the final paycheck.

### 1.3 Guiding principles

1. **One number on page one.** Everything in service of cARR the hero number.
2. **Persona-aware defaults, not persona-only views.** Every user sees the same views; what differs is the default filter set and landing tab.
3. **Truth over prettiness.** When the pipeline is stale or DQ has a P0 open, the dashboard *says so on the homepage*, not in a buried settings screen.
4. **No in-dashboard math.** Every number on screen traces to a mart row. If it's computed in the frontend, that's a bug.

---

## 2. Information architecture

```
  ┌────────────────────────────────────────────────────────────┐
  │  Global header                                             │
  │  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐  │
  │  │ As-of date ▾ │  │ Region / Segment │  │ Rep search ▾ │  │
  │  └──────────────┘  └──────────────────┘  └──────────────┘  │
  │                                                            │
  │  Stale-data / DQ banner (only if red)                      │
  └────────────────────────────────────────────────────────────┘
  ┌─────────┬───────────┬─────────┬──────────┬──────────────┐
  │Overview │ By Region │ By Rep  │ At-Risk  │ Data Health  │
  └─────────┴───────────┴─────────┴──────────┴──────────────┘
                           (5 tabs)
```

Tabs are flat, not nested. Users can deep-link into any tab with filter state encoded in the URL (shareable with colleagues).

### 2.1 Per-persona landing tab (default)

| Persona | Lands on | Default filters |
|---|---|---|
| VP Sales | Overview | None (all regions, all segments) |
| CFO | Overview | None |
| Enterprise rep | By Rep → self | Segment = Enterprise, Rep = self |
| Mid-Market rep | By Rep → self | Segment = Mid-Market, Rep = self |
| CSM | At-Risk | Book of business filter (own accounts only) |
| RevOps | Data Health | None |

Personas are inferred from the authenticated user's role in [spec 09 RBAC](09_access_and_audit.md).

---

## 3. View: Overview

The **hero view**. This is what a VP Sales or CFO opens on a Monday morning.

### 3.1 Layout

```
  ┌─────────────────────────────────────────────────────────────┐
  │  cARR (this month-end)           $ 42.8M       ▲ +3.2%      │
  │                                                    vs. last │
  │  Committed ARR              $ 46.1M      HealthScore  0.93  │
  └─────────────────────────────────────────────────────────────┘
  ┌──────────────┬──────────────┬───────────────┬──────────────┐
  │ 1,000 accts  │  148 at-risk │  142 overage  │  87 expansion│
  │              │  (<0.55 HS)  │  (1.12+ HS)   │  (in period) │
  └──────────────┴──────────────┴───────────────┴──────────────┘
  ┌─────────────────────────────────────────────────────────────┐
  │  12-month trend: cARR vs. Committed ARR                     │
  │                                                             │
  │   $50M ┤     ╭╯ARR                                          │
  │        │    ╱                                               │
  │   $45M ┤   ╱    ╭─╯                                         │
  │        │  ╱    ╱                                            │
  │   $40M ┤ ╱   ╱     cARR ────                                │
  │        │╱   ╱                                               │
  │        └──────────────────────────────────────              │
  │         May'25                           Apr'26             │
  └─────────────────────────────────────────────────────────────┘
  ┌───────────────────────────┬─────────────────────────────────┐
  │ Top 5 risk concentrations │ Top 5 expansion opportunities   │
  │ (rep × region bubbles)    │ (rep × region bubbles)          │
  └───────────────────────────┴─────────────────────────────────┘
```

### 3.2 Components

| Component | Data source | Notes |
|---|---|---|
| Hero cARR card | `mart_carr_by_account_month_end` summed | Month-over-month delta % and absolute |
| Committed ARR card | Same mart | Reference number; CFO anchor |
| HealthScore card | Weighted avg of HealthScore by ACV | One number summary of `cARR / ARR` |
| At-risk count | Count where `HealthScore < 0.55` at as-of date | Threshold from [spec 10](10_glossary.md) |
| Overage count | Count where `HealthScore >= 1.12` | |
| Expansion count | Count where `expanded` flag true | |
| Trend chart | Month-end series for last 12 months | Two lines; shaded area for gap |
| Bubble charts | Accounts grouped by rep × region; bubble size = at-risk / expansion ACV sum | Click a bubble → drill to By Rep with filters |

### 3.3 Interactions

- Clicking any of the four count cards filters the next tab visited to that slice (e.g., clicking **148 at-risk** → At-Risk tab opens pre-filtered).
- Hovering the trend chart shows the per-month breakdown with archetype composition.

---

## 4. View: By Region

### 4.1 Layout

A horizontal bar chart of cARR by region (`NAMER`, `EMEA`, `APAC`, `LATAM`), with a secondary axis showing **HealthScore** so users see volume and quality side-by-side.

Below the chart: a table with one row per region, columns: `cARR`, `Committed ARR`, `HealthScore`, `at-risk count`, `rep count`.

### 4.2 Interactions

- Click a region row / bar → filter global state to that region, switch to By Rep tab.
- Export-to-CSV available on the table.

---

## 5. View: By Rep

### 5.1 Layout

A **leaderboard** with one row per rep:

| Rank | Δ | Rep | Region | Segment | Accounts | cARR | ΔcARR | HealthScore | At-risk |
|---:|:---:|---|---|---|---:|---:|---:|---:|---:|
| 1 | → | Angie H. | NAMER | Enterprise | 17 | $8.9M | +$0.4M | 0.96 | 1 |
| 2 | ▲3 | Gina M. | NAMER | Enterprise | 24 | $7.3M | +$1.1M | 0.88 | 2 |
| ... |  |  |  |  |  |  |  |  |  |

- Default sort: `cARR` descending.
- Δ column shows rank movement vs. `T - 30d` (per [spec 06 T4-001](06_evaluation_framework.md#t4-001-rank-stability-spearman)).
- Reps with authorization see only themselves + reps they manage (spec 09 RBAC).

### 5.2 Rep drill (modal / side panel on row click)

| Section | Content |
|---|---|
| Header | Name, region, segment, rank, cARR, ΔcARR |
| Account breakdown | Bar chart of cARR by account, sorted desc, top 20 visible |
| Archetype mix | Donut: % of ACV in shelfware / spike-drop / normal / overage / expansion |
| Trend | Rep's cARR over trailing 12 months |
| At-risk accounts | Mini table: account, cARR, HealthScore, archetype flag |

### 5.3 The "Δ column" rule

The rank-movement column is only rendered if the rep's rank change is explainable by the data shown. If a rep's rank moved because of data outside the current filter (e.g., a contract expired in a different region), show "—" instead of a misleading arrow. Principle: **the dashboard never lies to a rep about their own number.**

---

## 6. View: At-Risk Accounts

### 6.1 Layout

A filterable list of every account with `HealthScore < 0.55`, sorted by `ACV × (1 - HealthScore)` descending (= dollars at risk, biggest first).

Columns: `account_id`, `company`, `rep`, `ACV`, `cARR`, `HealthScore`, `archetype flag`, `days to renewal`, `action taken`.

### 6.2 Interactions

- Click account → account drill (read-only view of daily usage history, contract list, CSM notes).
- "Action taken" is a free-text annotation written back to an annotations table. Writes require CSM or RevOps role.
- Export-to-CSV for CSM QBR prep.

### 6.3 Why this view exists

Per [spec 01 §4.4](01_problem_statement.md#44-customer-success-manager-lin), the CSM's biggest pain point is *reactivity* — finding out about unhealthy accounts at QBR. This view is explicitly the early-warning interface.

---

## 7. View: Data Health

### 7.1 Layout

```
  ┌─────────────────────────────────────────────────────────────┐
  │  Pipeline status         Green  (last success: 06:32 UTC)   │
  │  DQ tier summary         P0: 0 fail    P1: 2 warn    P2: 1  │
  │  Eval tier summary       T1: pass  T2: pass  T3: pass  T4: ⚠│
  │  Last restatement        —                                  │
  └─────────────────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────────────┐
  │  Open DQ tickets                                            │
  │  ID            Title              Tier  Owner     Age       │
  │  DQ-REF-003    Orphan share 1.2%  P1    PlatEng    18h      │
  │  DQ-RECON-004  CPQ drift 0.7%     P1    FinSys     2d       │
  └─────────────────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────────────┐
  │  Eval report (latest)              Link → .md artifact      │
  └─────────────────────────────────────────────────────────────┘
```

### 7.2 Components

- Pipeline status pulls from `observability.freshness` (spec 04 §8.3).
- DQ tier summary from `dq.assertion_results` latest run.
- Eval tier summary from `dq.eval_results` latest run.
- Open DQ tickets from JIRA API / equivalent.

### 7.3 Consequence for other tabs

If the **Pipeline status** is red (pipeline failed this morning, yesterday's mart is stale), a persistent banner renders on every other tab:

> "⚠︎ Data shown is from `<last success date>`. Live pipeline has been failing for 2h. Click for details."

The banner link opens the Data Health tab with the failing assertion highlighted.

---

## 8. Global filters

| Filter | Default | Behavior | Notes |
|---|---|---|---|
| As-of date | Latest published month-end | Dropdown of month-ends (12 visible, scrollable to all) | Filters every view |
| Region | All | Multi-select: NAMER / EMEA / APAC / LATAM | Propagates to all views |
| Segment | All | Multi-select: Enterprise / Mid-Market | |
| Rep | None (implies "all reps user has access to") | Typeahead search, chip-style selected | RBAC-limited |

Filter state encoded in URL query params for shareability.

---

## 9. Performance SLAs

| Operation | Target p95 | Failure mode |
|---|---:|---|
| Initial page load (Overview, cold cache) | ≤ 2.5 s | |
| Tab switch | ≤ 700 ms | Uses pre-loaded mart data |
| Filter change | ≤ 500 ms | Client-side filtering where possible |
| Rep drill modal open | ≤ 1.0 s | Streaming: header first, trend last |
| Export CSV (up to 5,000 rows) | ≤ 3 s | |
| Refresh on as-of-date change | ≤ 2 s | |

### 9.1 Caching strategy

- All mart reads hit a CDN-fronted query cache keyed by `(mart_name, as_of_date, filter_hash)`.
- Cache invalidated on pipeline success (mart publication).
- No cache on the Data Health tab — always live.

---

## 10. Access control

Full RBAC matrix in [spec 09](09_access_and_audit.md). Summary for orientation:

| Role | Can see | Can modify |
|---|---|---|
| Rep | Own row + accounts; no peer data | Account annotations on own book |
| Sales Manager | Own team's reps and accounts | Own team's annotations |
| VP Sales / CFO / CRO | All regions, all reps, all accounts | None (read-only) |
| CSM | Own book of accounts | Account annotations |
| RevOps | All read; Data Health tab | DQ ticket triage |
| Internal Audit | All read, including `dq.*` tables | None |

All access is authenticated via the corporate SSO; no anonymous access, no service-account browsers.

---

## 11. Technology stack

### 11.1 Prototype (what ships in this repo)

**Streamlit** — Python, single-file apps, reads directly from BigQuery via `google-cloud-bigquery`. Picked because:
- End-to-end in-repo demo in under a day.
- Same language as the generator + pipeline (one dependency chain).
- No npm / bundler complexity for the take-home panel.

Cost: visual polish is limited; mobile responsiveness is poor; does not scale past ~20 concurrent users.

### 11.2 Production (target after rollout)

**Next.js + Recharts + shadcn/ui**, served behind SSO, hitting a thin BigQuery query API. Picked because:
- Enterprise UX polish.
- Mobile support for reps on the road.
- Existing org familiarity with the React stack.

Decision deferred until after Phase 1 (reporting-only rollout) since the metric is the contract, not the UI. Shipping cARR through Streamlit first minimizes rework risk on the dashboard.

### 11.3 Why not Tableau / Looker / Mode

- They are capable of the above but would add vendor lock-in, license costs, and a slower change cycle.
- More importantly: the filter-state-in-URL + deep-linking + rep RBAC pattern is hard to get right in these tools.

---

## 12. Accessibility and inclusivity

- All charts accompanied by a data table view (keyboard accessible, screen-reader friendly).
- Color-blind safe palette (no red/green only — every status uses icons too).
- WCAG 2.1 AA target for contrast ratios.
- Font scaling respected; layout reflows at 200% zoom.
- Every chart has an "download as CSV" escape hatch so users who prefer raw data are not dependent on the visualization.

---

## 13. Open questions

1. **Mobile-first or desktop-first.** Reps on the road would value mobile; leadership uses desktop. Phase 1 is desktop-only; Phase 2 adds mobile. Need design direction before Phase 2.
2. **Alert subscriptions.** Should reps / managers be able to subscribe to "HealthScore dropped below threshold for any of my accounts" alerts? Nice-to-have; TBD if it cannibalizes the real alerting in the comp system.
3. **Embedded annotations vs. link-to-CRM.** Currently we plan lightweight in-dashboard annotations (§6.2) — should these instead deep-link into Salesforce notes for a single source of truth?
4. **Public-share snapshots.** A CFO may want to share a specific view on a specific date. Signed-URL snapshot export? Deferred.
5. **"Rep comp calculator."** If a rep wants to see "what would my number be if my top account grew 10%," do we support a what-if input? Pros: reduces comp disputes. Cons: fuzzes the line between *reporting* and *forecasting*. Tentatively: no for v1.

---

## Appendix A — Rejected dashboard patterns

| Alternative | Why rejected |
|---|---|
| Single-page scroll (no tabs) | At the information volume of five personas, scroll-fatigue kills it |
| Drill-into-every-account as primary view | Makes the dashboard feel like a data browser, not a leadership surface |
| Rep-facing "you owe $X commission" number | We are not the comp engine. Shows rep *performance*, not rep *pay* |
| Notifications-first (dashboard = inbox) | Inverts the use case — leadership wants a weekly pulse, not a stream |
| Raw SQL cell embedded in the UI | Great for analysts; noise for execs; analysts have other tools for this |

## Appendix B — Wireframe sketch key

ASCII diagrams in §3, §6, §7 are deliberately low-fi. They lock **information hierarchy**, not visual style. A design pass follows this spec and updates in a Figma artifact referenced here once available.
