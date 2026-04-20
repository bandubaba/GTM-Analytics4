"""
'Ask cARR' — NL question agent (specs/11 §3.1 / §4).

Two modes:
  - offline (default): keyword-based router to a curated set of canned
    SQL snippets over the pipeline's parquet mart. No network calls,
    no API key. Lets the panel run the full app offline.
  - llm (ANTHROPIC_API_KEY set): Claude Sonnet generates SQL; a verifier
    dry-runs it locally (EXPLAIN against the parquet mart) before
    execution (spec 11 §4 verifier).

Both modes return the same object: {question, sql, rows, narration, mode}.
The dashboard always displays the SQL alongside the narration — per
spec 11 §3.1, showing the SQL is the antidote to hallucination anxiety.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd


@dataclass
class AskResult:
    question: str
    mode: str
    sql: str
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    narration: str = ""
    refused: bool = False
    refusal_reason: str = ""


# ---------------------------------------------------------------------------
# offline router — keyword → canned SQL
# ---------------------------------------------------------------------------

CANNED: list[dict[str, Any]] = [
    {
        "pattern": re.compile(r"total\s+cARR|overall\s+cARR|headline\s+cARR", re.I),
        "sql": "SELECT SUM(carr) AS total_carr, SUM(committed_arr) AS total_committed_arr FROM mart_carr_current",
        "narrate": lambda r: f"Total cARR is ${r.total_carr.iloc[0]:,.0f} against Committed ARR of ${r.total_committed_arr.iloc[0]:,.0f} — weighted HealthScore of {r.total_carr.iloc[0]/r.total_committed_arr.iloc[0]:.3f}.",
    },
    {
        "pattern": re.compile(r"by\s+region|region\s+breakdown|regional", re.I),
        "sql": "SELECT region, SUM(carr) AS carr, SUM(committed_arr) AS committed_arr, COUNT(*) AS n_accounts FROM mart_carr_current GROUP BY region ORDER BY carr DESC",
        "narrate": lambda r: f"{r.region.iloc[0]} is the largest region at ${r.carr.iloc[0]:,.0f} cARR across {int(r.n_accounts.iloc[0])} accounts.",
    },
    {
        "pattern": re.compile(r"by\s+segment|Enterprise\s+vs\s+Mid|segment\s+breakdown", re.I),
        "sql": "SELECT segment, SUM(carr) AS carr, SUM(committed_arr) AS committed_arr, COUNT(*) AS n_accounts FROM mart_carr_current GROUP BY segment",
        "narrate": lambda r: f"Enterprise vs Mid-Market split: " + ", ".join(f"{s}=${c:,.0f}" for s, c in zip(r.segment, r.carr)),
    },
    {
        "pattern": re.compile(r"top\s+\d*\s*reps?|best\s+reps?|who\s+is\s+winning", re.I),
        "sql": "SELECT rep_name, region, segment, carr, weighted_healthscore FROM mart_carr_by_rep ORDER BY carr DESC LIMIT 5",
        "narrate": lambda r: f"Top rep is {r.rep_name.iloc[0]} ({r.segment.iloc[0]} / {r.region.iloc[0]}) at ${r.carr.iloc[0]:,.0f} cARR with weighted HS {r.weighted_healthscore.iloc[0]:.3f}.",
    },
    {
        "pattern": re.compile(r"bottom\s+reps?|worst\s+reps?|struggling", re.I),
        "sql": "SELECT rep_name, region, segment, carr, weighted_healthscore, n_at_risk FROM mart_carr_by_rep WHERE carr > 0 ORDER BY weighted_healthscore ASC LIMIT 5",
        "narrate": lambda r: f"Lowest weighted-HS rep is {r.rep_name.iloc[0]} at {r.weighted_healthscore.iloc[0]:.3f} with {int(r.n_at_risk.iloc[0])} at-risk accounts.",
    },
    {
        "pattern": re.compile(r"shelfware|at[- ]risk|dormant", re.I),
        "sql": "SELECT account_id, committed_arr, carr, healthscore, utilization_u FROM mart_carr_current WHERE band = 'at_risk_shelfware' ORDER BY committed_arr DESC LIMIT 20",
        "narrate": lambda r: f"{len(r)} at-risk/shelfware accounts surfaced — top one has Committed ARR ${r.committed_arr.iloc[0]:,.0f} at HealthScore {r.healthscore.iloc[0]:.2f}.",
    },
    {
        "pattern": re.compile(r"spike|drop", re.I),
        "sql": "SELECT account_id, committed_arr, carr, healthscore, m1_share FROM mart_carr_current WHERE band = 'spike_drop' ORDER BY committed_arr DESC",
        "narrate": lambda r: f"{len(r)} spike-drop accounts detected" + (f" — largest by commit is ${r.committed_arr.iloc[0]:,.0f}." if len(r) else "."),
    },
    {
        "pattern": re.compile(r"expansion|expanding|growing", re.I),
        "sql": "SELECT account_id, committed_arr, carr, healthscore, n_active_contracts, utilization_u FROM mart_carr_current WHERE band = 'expansion' ORDER BY carr DESC",
        "narrate": lambda r: f"{len(r)} expansion accounts — sum of cARR ${r.carr.sum():,.0f}.",
    },
    {
        "pattern": re.compile(r"ramp|new\s+logo|ramping", re.I),
        "sql": "SELECT account_id, segment, committed_arr, carr, contract_age_days, ramp_w, healthscore FROM mart_carr_current WHERE band = 'ramping' ORDER BY contract_age_days",
        "narrate": lambda r: f"{len(r)} ramping accounts protected by D12; youngest at {int(r.contract_age_days.iloc[0])}d." if len(r) else "No ramping accounts on the snapshot.",
    },
    {
        "pattern": re.compile(r"orphan|bad\s+data|out\s+of\s+window", re.I),
        "sql": "SELECT usage_class, COUNT(*) AS n_logs, SUM(credits_consumed) AS total_credits FROM int_orphan_usage GROUP BY usage_class",
        "narrate": lambda r: "Orphan distribution: " + ", ".join(f"{c}={int(n)}" for c, n in zip(r.usage_class, r.n_logs)),
    },
    {
        "pattern": re.compile(r"data\s+quality|DQ\s+status|health\s+of\s+pipeline", re.I),
        "sql": "SELECT * FROM mart_dq_summary",
        "narrate": lambda r: f"Pipeline: {int(r.n_accounts_in_metric.iloc[0])} accounts in metric, weighted HealthScore {r.weighted_healthscore.iloc[0]:.3f}, orphans excluded {int(r.n_orphan_bad_account.iloc[0]) + int(r.n_orphan_out_of_window.iloc[0])} rows.",
    },
]

REFUSAL_PATTERNS = [
    (re.compile(r"(bonus|comp|commission|pay|payout|quota\s+attainment).*(every|all|other|any)\s+rep", re.I),
     "Refused: this query would expose rep-level compensation data outside the span-of-control policy (spec 09 RBAC)."),
    (re.compile(r"(email|phone|ssn|home\s+address|personal)", re.I),
     "Refused: PII fields are not exposed by the NL agent (spec 11 §6)."),
    (re.compile(r"predict|forecast|will\s+hit|projection", re.I),
     "Refused: forward-looking forecasts are outside v1 scope (spec 11 §7 — deferred to v1.5)."),
]


def _route_offline(question: str, con: duckdb.DuckDBPyConnection) -> AskResult:
    for pat, reason in REFUSAL_PATTERNS:
        if pat.search(question):
            return AskResult(question=question, mode="offline", sql="-- (refused)", refused=True, refusal_reason=reason, narration=reason)
    for rule in CANNED:
        if rule["pattern"].search(question):
            sql = rule["sql"]
            rows = con.execute(sql).df()
            try:
                narration = rule["narrate"](rows)
            except Exception as e:
                narration = f"(narration rendering failed: {e})"
            return AskResult(question=question, mode="offline", sql=sql, rows=rows, narration=narration)
    return AskResult(
        question=question,
        mode="offline",
        sql="-- (no match)",
        refused=True,
        refusal_reason="No offline template matched. Try one of the example questions below, or enable the LLM mode.",
        narration="No offline template matched.",
    )


# ---------------------------------------------------------------------------
# LLM mode (optional) — Claude Sonnet with a local SQL verifier
# ---------------------------------------------------------------------------

SCHEMA_HINT = """
Table: mart_carr_current
  account_id TEXT, rep_id TEXT, region TEXT, segment TEXT, industry TEXT,
  n_active_contracts INT, committed_arr DOUBLE,
  utilization_u DOUBLE, m1_share DOUBLE,
  base_score DOUBLE, modifier DOUBLE, ramp_w DOUBLE,
  healthscore_steady DOUBLE, healthscore DOUBLE, carr DOUBLE,
  contract_age_days INT, oldest_active_start DATE, as_of_date DATE,
  band TEXT  -- one of: healthy, mixed, at_risk_shelfware, spike_drop, expansion, overage, ramping

Table: mart_carr_by_rep
  rep_id TEXT, rep_name TEXT, region TEXT, segment TEXT,
  n_accounts INT, committed_arr DOUBLE, carr DOUBLE,
  weighted_healthscore DOUBLE,
  n_at_risk INT, n_spike_drop INT, n_expansion INT, n_ramping INT

Table: mart_carr_by_region
  region TEXT, segment TEXT,
  n_accounts INT, committed_arr DOUBLE, carr DOUBLE,
  weighted_healthscore DOUBLE, n_at_risk INT

Table: mart_dq_summary (single row)
  n_accounts_in_metric, total_committed_arr, total_carr,
  weighted_healthscore, n_shelfware, n_spike_drop, n_expansion,
  n_ramping, n_healthy, n_orphan_bad_account, n_orphan_out_of_window
"""

SYSTEM_PROMPT = """You are a SQL generator for a cARR analytics product.
Respond with ONE SQL query against the tables below. Do NOT wrap in markdown.
Do NOT use NOW(), CURRENT_DATE(), or RANDOM(). Do NOT mutate state.

Rules:
- If the question is outside scope (forecasting, PII, cross-rep compensation),
  respond with the single token: REFUSE
- Return plain SQL only.
- Prefer mart_* tables; never reach into raw_* or stg_*.

Schema:
""" + SCHEMA_HINT


NARRATION_PROMPT = """You are a GTM business analyst summarizing a SQL result for a CFO / VP Sales audience.

Given a question, the SQL that ran, and a preview of the result rows, write a 1-2 sentence plain-English summary.
- Lead with the headline number or count — specific figures from the rows, not paraphrase.
- Use $K / $M formatting for money (e.g., $76.7M, $658K). Use 3-decimal precision for HealthScores (0.816).
- No markdown, no bullets, no preface ("Here is a summary…"). Output the 1-2 sentences only.
- Reference the metric definition only if the question is conceptual; otherwise just answer.
- If the result is empty, say so and offer the likely reason (no matching rows on this snapshot).
"""


def _narrate_llm(client: Any, question: str, sql: str, rows: pd.DataFrame) -> str:
    """Second-pass narration: ask Claude to summarize rows in plain English."""
    if rows.empty:
        preview = "(no rows returned)"
    else:
        # Small aggregates → full table; large result sets → head(10) + shape.
        head = rows.head(10).to_string(index=False, max_colwidth=40)
        shape = f"\n\n(showing first 10 of {len(rows)} rows, {len(rows.columns)} columns)" if len(rows) > 10 else ""
        preview = head + shape
    user_msg = f"Question: {question}\n\nSQL:\n{sql}\n\nResult preview:\n{preview}"
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=NARRATION_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        return text or f"Query returned {len(rows)} rows."
    except Exception as e:
        return f"Query returned {len(rows)} rows. (Narration unavailable: {e})"


def _route_llm(question: str, con: duckdb.DuckDBPyConnection, api_key: str) -> AskResult:
    try:
        import anthropic
    except Exception:
        return AskResult(question=question, mode="llm",
                         sql="-- (anthropic SDK missing)",
                         refused=True, refusal_reason="pip install anthropic to enable LLM mode.",
                         narration="LLM mode requested but SDK not installed.")

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    raw = resp.content[0].text.strip() if resp.content else ""
    if raw.upper().startswith("REFUSE"):
        return AskResult(question=question, mode="llm", sql="-- (LLM refused)", refused=True,
                         refusal_reason="LLM refused: out of scope per system policy (spec 11 §6).",
                         narration="LLM refused: out of scope per system policy.")
    # Verifier — strip code fences, dry-run via EXPLAIN
    sql = raw.strip("`")
    if sql.lower().startswith("sql\n"):
        sql = sql[4:]
    try:
        con.execute(f"EXPLAIN {sql}")
    except Exception as e:
        return AskResult(question=question, mode="llm", sql=sql, refused=True,
                         refusal_reason=f"Verifier rejected the query: {e}",
                         narration="Generated SQL failed dry-run; not executed (spec 11 §4 verifier).")
    rows = con.execute(sql).df()
    narration = _narrate_llm(client, question, sql, rows)
    return AskResult(question=question, mode="llm", sql=sql, rows=rows, narration=narration)


def ask(question: str, con: duckdb.DuckDBPyConnection, allow_llm: bool = True) -> AskResult:
    question = question.strip()
    if not question:
        return AskResult(question=question, mode="offline", sql="", refused=True,
                         refusal_reason="Empty question.", narration="Empty question.")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if allow_llm and api_key:
        return _route_llm(question, con, api_key)
    return _route_offline(question, con)


EXAMPLES: list[str] = [
    "What is the total cARR?",
    "Show cARR by region",
    "Who are the top reps by cARR?",
    "Which reps are struggling?",
    "Show me the shelfware accounts",
    "Any spike-drop accounts?",
    "Which accounts are expanding?",
    "Which accounts are protected by ramp?",
    "What's the data quality status?",
]
