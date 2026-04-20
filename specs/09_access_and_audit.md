# 09 — Access & Audit

| Field         | Value                                                                             |
|---------------|-----------------------------------------------------------------------------------|
| Spec          | `09_access_and_audit.md`                                                          |
| Audience      | CISO, Internal Audit, Legal, IT, Principal PM, Data Platform tech-lead            |
| Owner         | Principal PM, GTM Analytics (co-owned with CISO delegate in prod)                 |
| Status        | Draft                                                                             |
| Version       | 0.1                                                                               |
| Last reviewed | 2026-04-19                                                                        |
| Related       | [02 — Data Model](02_data_model.md), [04 — Pipeline](04_pipeline_architecture.md), [05 — DQ](05_data_quality.md), [08 — Rollout](08_rollout_plan.md) |

---

## 1. Purpose and scope

### 1.1 What this spec defines

The **security, access, audit, retention, and change-management controls** that apply to cARR data end to end, from raw source tables to published marts and the compensation records derived from them. It is written to satisfy:

- Internal Audit's SOX-adjacent compensation-data review.
- Legal's data-retention and legal-hold requirements.
- CISO's data-classification and access-control framework.
- Engineering's operational need for working, testable permissions.

### 1.2 What this spec is NOT

- **Not the corporate access-control policy.** This spec *implements* the policy; the policy itself lives in the corporate InfoSec handbook.
- **Not a privacy impact assessment.** A DPIA on rep-level data is a separate document executed by Privacy Counsel.
- **Not the detailed RBAC configuration file.** The *matrix* is here; the concrete IAM policy / BigQuery roles live in `/infra/` (not in this repo's scope).

### 1.3 Guiding principles

1. **Least privilege, always.** Default access is none. Each role earns each permission explicitly.
2. **Separation of duties on comp data.** The person who *writes* the metric cannot also *approve* the restatement; the person who sees all rep-level data cannot also modify it.
3. **Audit trail is non-negotiable.** Every read of rep-level data, every write to the mart layer, every parameter change is logged with an immutable audit record.
4. **Classification inherits.** A derived table is classified at the highest classification of its inputs. No exceptions.
5. **The pipeline is not a person.** Service accounts have distinct permissions from humans; humans cannot act "as" the pipeline for ad-hoc queries.

---

## 2. Data classification

Authoritative classification per table. Inherits to every derived model.

| Table / mart | Classification | Why | Handling |
|---|---|---|---|
| `raw.sales_reps` | **Confidential + PII** | Rep legal names | Masked in non-prod; full audit on reads |
| `raw.accounts` | **Confidential** | Customer names are commercially sensitive | Access restricted; no export outside approved tools |
| `raw.contracts` | **Confidential — Financial (SOX)** | Material non-public financial terms | Full SOX controls; change management; retention 7y |
| `raw.daily_usage_logs` | **Internal** | Aggregated daily totals; tied to customers | Role-gated; row-level customer filter for partner access |
| `stg_*` | Same as source | Inherits | Same controls |
| `int_*` | Same as highest source input | Inherits (typically SOX-financial) | Same controls |
| `m_*` / `mart_carr_by_account_*` | **Confidential — Financial (SOX) + PII** (indirect — ties to reps) | Derived from SOX-scoped contracts + rep identity | Full controls + rep-level RLS |
| `mart_carr_by_rep_month_end` | **Confidential — Financial (SOX) + PII** | Comp-adjacent rep-level data | Full controls + strict role gate |
| `mart_carr_restatements` | **Confidential — Financial (SOX)** | Formal record of comp-impacting corrections | Append-only; approver chain logged per row |
| `dq.*` | **Confidential** | May surface customer identifiers in error messages | Access gated to Data Platform, Analytics Eng, Internal Audit |
| `observability.*` | **Internal** | Row counts, cost, freshness — no customer data | Broader access |

**Derived marts inherit.** If you join a SOX-scoped input and a Confidential input, the derived table is SOX-scoped. Downgrading requires a formal classification review.

---

## 3. RBAC matrix

### 3.1 Human roles

| Role | Realm | `raw.*` | `stg_*` `int_*` | `m_*` | `mart_carr_by_account_*` | `mart_carr_by_rep_month_end` | `mart_carr_restatements` | `dq.*` | `observability.*` |
|---|---|---|---|---|---|---|---|---|---|
| Rep | Sales | — | — | — | Own book only (RLS) | Own row only (RLS) | — | — | — |
| Sales Manager | Sales | — | — | — | Own team's books (RLS) | Own team's rows (RLS) | Read on own team | — | — |
| VP Sales / CRO | Sales | — | — | — | Read all | Read all | Read all | — | Read all |
| CFO / Finance leadership | Finance | — | — | — | Read all | Read all | Read + approve | — | Read all |
| Finance Systems | Finance | Read `raw.contracts` | Read | Read | Read all | Read all | Read + approve (backup) | Read | Read |
| RevOps | Ops | — | Read | Read | Read all | Read all | Triage + propose | Read + ticket | Read all |
| CSM | CS | — | — | — | Own book only (RLS) | — | — | — | — |
| Data Platform Eng | Eng | Read/Write | Read/Write | Read | Read (no write) | Read (no write) | — | Read/Write | Read/Write |
| Analytics Eng | Eng | Read | Read/Write | Read/Write | Read/Write | Read/Write | Append only (via approved process) | Read/Write | Read/Write |
| Principal PM | PM | Read | Read | Read | Read all | Read all | Read + propose | Read | Read |
| Internal Audit | Audit | Read | Read | Read | Read | Read | Read | Read | Read |
| Legal | Legal | Read (need-to-know) | Read (need-to-know) | Read (need-to-know) | Read (need-to-know) | Read (need-to-know) | Read (need-to-know) | — | — |
| CISO Security Ops | Sec | — | — | — | — | — | — | Read | Read |

**RLS** = row-level security, enforced via BigQuery Authorized Views keyed by the caller's identity (see §4.3).

### 3.2 Service accounts

| Service account | Purpose | Permissions |
|---|---|---|
| `sa-pipeline-daily@...` | Runs the daily pipeline | Read/Write on `raw.*`, `stg_*`, `int_*`, `m_*`, `mart_carr_by_account_*`, `mart_carr_by_rep_month_end`, `dq.*`, `observability.*`. **No access** to `mart_carr_restatements` (writes require human approval) |
| `sa-dashboard@...` | Serves the dashboard backend | Read on `mart_carr_by_*`, `mart_carr_restatements`, `observability.*`. No write. No row-level filtering exception (RLS enforced at the view layer, not by the service account) |
| `sa-comp-engine@...` | Export to the comp engine | Read on `mart_carr_by_rep_month_end` **only**. No other access. |
| `sa-audit-export@...` | Internal Audit extracts | Read on everything; write only to its own audit-report bucket |

Service accounts are non-interactive. **No human can impersonate a service account** for ad-hoc queries — audit would be unable to distinguish pipeline writes from human writes. Explicitly forbidden.

---

## 4. Identity, authentication, row-level security

### 4.1 Identity

- All human access is via corporate SSO (OIDC).
- MFA required for every role that touches SOX-scoped tables (effectively all non-Internal roles).
- Session length: 8 hours for standard roles; 4 hours for CFO / VP Sales / CRO; 2 hours for Internal Audit when exporting.

### 4.2 Authentication edges

| Surface | Auth |
|---|---|
| BigQuery direct (SQL) | SSO → BigQuery IAM |
| Dashboard | SSO → dashboard app → `sa-dashboard` service account reads with user identity forwarded for RLS |
| Comp engine | Service-account-to-service-account, no user interaction |
| Internal Audit tool | SSO → audit-tool → `sa-audit-export`; exports logged |

### 4.3 Row-level security implementation

For any table requiring per-rep filtering, we publish an **Authorized View** named `vw_<table>_filtered` that resolves the caller's identity and filters rows to only those the caller is entitled to see.

Example, for `mart_carr_by_account_month_end`:

```sql
-- vw_mart_carr_by_account_month_end_filtered
CREATE OR REPLACE VIEW `...vw_mart_carr_by_account_month_end_filtered` AS
SELECT m.*
FROM `...mart_carr_by_account_month_end` m
JOIN `...rbac.rep_book_visibility` v
  ON v.viewer_email = SESSION_USER()
 AND v.account_id   = m.account_id
```

Only the view is granted to end users; the underlying table is not. The `rbac.rep_book_visibility` table is populated from the same HR + Salesforce data that drives rep-account ownership; it updates daily and includes the manager hierarchy.

### 4.4 Break-glass access

Rare scenarios (incident response, forensic query) may require a human to bypass RLS. The process:

1. Requester files a break-glass ticket naming the business reason, the tables needed, and the duration.
2. Approver (CISO or delegate + the data's classification owner) approves in writing.
3. IT grants temporary elevated group membership for the stated duration (max 24h).
4. Every query run under elevated access is logged to `audit.break_glass_queries` with SQL text.
5. Post-incident review within 5 business days.

---

## 5. Audit trail

### 5.1 What is logged

| Event | Logged to | Retention |
|---|---|---|
| Every query against SOX-scoped tables | `audit.query_log` | 7 years |
| Every mart write | `audit.mart_writes` | 7 years |
| Every parameter change (`carr_params.yml`) | git history + `audit.param_changes` | indefinite |
| Every restatement append | `audit.restatements` + `mart_carr_restatements` row | indefinite |
| RBAC grant / revoke | `audit.rbac_changes` | 7 years |
| Break-glass grant + queries | `audit.break_glass_*` | indefinite |
| Failed auth attempts | Standard corporate SIEM | per SIEM policy |

### 5.2 Audit log immutability

- Audit tables are **append-only** at the BigQuery IAM level (`bigquery.dataEditor` revoked; only `bigquery.dataViewer` granted to humans; writes via the auth'd pipeline service account only).
- Row-level deletions on audit tables are impossible without a formal BigQuery "dataset deletion" event, which itself is logged in the GCP platform audit log.

### 5.3 Who can read audit logs

- Internal Audit: full read on all audit tables.
- CISO Security Ops: full read.
- Principal PM: read on own project's audit events; no cross-team access.
- Nobody: write or delete.

---

## 6. Change management

Cross-reference with each spec's change-management section. This spec enumerates what kinds of changes require what approvers.

| Change kind | Approvers required | Artifact |
|---|---|---|
| cARR formula change (spec 03 §2) | VP Sales + CFO + Principal PM + T-level eval suite pass | PR + eval report |
| cARR parameter change (spec 03 §6) | Owner per row of the param table + T-level eval pass | PR + eval report |
| Schema change on `raw.*` | Upstream owner (RevOps / Finance Systems / Platform Eng) + Analytics Eng + Principal PM | PR + downstream impact analysis |
| Mart schema change | Analytics Eng + consumers (dashboard, comp engine) + Principal PM | PR + downstream migration plan |
| RBAC change | Role owner + CISO delegate | Ticket + PR on `rbac.*` config |
| DQ assertion change (spec 05) | Assertion owner + Principal PM | PR |
| Rollout phase gate (spec 08) | Per the phase's named approvers | Exit-gate template per [spec 08 Appendix B](08_rollout_plan.md#appendix-b--exit-gate-decision-template) |
| Break-glass access | CISO or delegate + classification owner | Ticket + post-review |

---

## 7. Retention and legal hold

### 7.1 Retention ladder

Authoritative source: [spec 02 §10](02_data_model.md#10-retention). Reproduced here for access-policy completeness.

| Table | Hot (queryable) | Warm (archive) | Legal hold rules |
|---|---|---|---|
| `raw.sales_reps` | Indefinite while rep active; 7y post-departure | — | Employment records |
| `raw.accounts` | Indefinite for active; 7y post-close | — | CRM data |
| `raw.contracts` | 7 years | Indefinite | SOX |
| `raw.daily_usage_logs` | 25 months | 7 years (aggregated) | Per-account detail purged at 25mo |
| `mart_carr_by_account_day` | 25 months | Aggregated after | |
| `mart_carr_by_*_month_end` | Indefinite | Indefinite | **Comp-of-record** |
| `mart_carr_restatements` | Indefinite | Indefinite | **Comp-of-record** |
| `dq.*` | 2 years | Aggregated after | |
| `audit.*` | 7 years minimum | Indefinite for SOX events | Per section §5.2 |

### 7.2 Legal hold

If a dispute, investigation, or regulatory inquiry triggers a legal hold:

1. Legal files the hold via the corporate legal-hold tool, naming: scope (tables, timeframe, parties), expected duration.
2. IT applies a **hold label** to the affected tables that blocks all deletion and expiration.
3. The retention ladder above is **paused** for held data until the hold is released.
4. Held periods are logged in `audit.legal_holds`.

Comp-of-record tables (`mart_carr_*_month_end`, `mart_carr_restatements`) are effectively always under "permanent hold" — no deletion without a formal business-records-destruction process that involves Legal + Internal Audit.

### 7.3 Deletion and data subject requests

- Rep departure: PII fields (`name`) on `sales_reps` may be redacted 7 years post-departure on written request from Legal; `rep_id` remains for historical integrity.
- Customer data: contracted customers have enterprise agreements governing retention; no mid-contract deletion.
- GDPR / CPRA data subject requests: routed to the Privacy team; if the subject is an individual contact inside a contracted customer, handled per the corporate privacy process (out of scope for this spec).

---

## 8. Breach response

In scope for this spec: what the cARR pipeline *does* if a breach is detected. Out of scope: corporate-wide IR runbooks.

1. **Detection source:** abnormal access pattern on SOX tables → triggers SIEM alert → CISO Security Ops.
2. **Containment:** CISO may disable any service account or IAM role governing cARR data without approval from the data owner; notification follows.
3. **Pipeline impact:** if `sa-pipeline-daily` is disabled, the daily pipeline fails; mart is stale; dashboard shows stale banner; runbook `runbooks/pipeline_service_account_disabled.md` engages.
4. **Restatement consequence:** a breach that caused unauthorized *writes* (as opposed to reads) triggers a full pipeline audit and possibly a restatement of affected periods. Process per [spec 04 §7.2](04_pipeline_architecture.md#72-backfills) + approval from VPS + CFO + Internal Audit + Legal.

---

## 9. Developer access in non-prod

- A sanitized sandbox dataset (current repo state) is available with no customer-identifiable data. Synthetic accounts / companies / names.
- Real prod tables are accessible only via break-glass (§4.4).
- PR CI runs against the sandbox only. No PR can reach prod tables via CI.

---

## 10. Open questions

1. **Cross-region replication.** If we expand to multi-region BQ, does replication cross residency boundaries (e.g., EU customer data outside EU)? Pending Legal review.
2. **AI-tooling access.** This spec doesn't address whether AI coding assistants (Cursor, Claude Code) are allowed to view SOX-scoped SQL or data in the developer workflow. Proposed: yes for SQL (code review flow); never for data (sandboxed synthetic only). Pending CISO sign-off.
3. **Access recertification cadence.** Quarterly by default; Internal Audit may demand monthly for SOX scope. TBD.
4. **Comp engine sync frequency.** Real-time from mart or daily batch? Affects audit trail granularity on `sa-comp-engine`. Pending comp-engine owner.

---

## Appendix A — Rejected access patterns

| Alternative | Why rejected |
|---|---|
| "Analysts have read-all" — single broad Analytics role | Violates least privilege; cannot explain to SOX auditors |
| Rep sees peer rows via opt-in transparency | Comp data is PII; peer visibility invites HR issues |
| Row-level security via application code | Breaks the invariant — direct BigQuery access would bypass it |
| Pipeline writes with a human user's credentials (simplifies setup) | Pipeline events become indistinguishable from human writes; audit destroyed |
| Audit logs retained 90 days only | Fails SOX's 7-year retention for comp-impacting records |
| Break-glass with email-only approval | Unauditable; must go through ticket + written classification owner + time-boxed grant |

## Appendix B — SOX scope summary (for audit intake)

The following controls from this spec map to the key SOX-style assertions an auditor will test:

| Audit assertion | Control reference |
|---|---|
| Comp-of-record completeness | Spec 03 §5.2 freeze rule + Spec 04 §7 restatement workflow |
| Restriction of access to financial data | §3.1 RBAC matrix (contracts + mart rows) |
| Segregation of duties | §2 classification inherits + §6 change management approvers |
| Retention of evidence | §5 audit trail + §7 retention ladder |
| Change management | §6 change management table + per-spec §10 sections |
| Timely detection of issues | Spec 05 DQ tier + §5.1 audit events |
| Appropriate response to issues | Spec 04 runbooks + §8 breach response |
