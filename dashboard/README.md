# Dashboard

Streamlit prototype for the cARR metric. Implements the four dashboard views
from [`../specs/07_dashboard_spec.md`](../specs/07_dashboard_spec.md) and the
AI product surface from [`../specs/11_ai_product_surface.md`](../specs/11_ai_product_surface.md).

## Views

| View | Who it's for | What it answers |
|---|---|---|
| **Executive** | VPS, CFO | What's the headline cARR vs Committed ARR? How does it split by region × segment? What's the band mix? |
| **Reps** | VPS, RevOps | Which reps disperse on weighted HealthScore? Who's carrying at-risk, spike-drop, expansion, ramping books? |
| **Account drill** | Rep, CS, audit | For a single account — 3-sentence narrator + full HealthScore decomposition (every slot in the formula is shown) |
| **Data quality** | Data team, audit | Pipeline totals, orphan exclusions, band mix in one panel |
| **Ask cARR** | Everyone | NL-query layer over the metric mart; returns narration + rows + SQL (never just prose) |

## Run

```bash
# From repo root:
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline_and_tests/requirements.txt
pip install -r dashboard/requirements.txt

# 1. populate the pipeline mart
python pipeline_and_tests/run.py

# 2. launch dashboard
streamlit run dashboard/app.py
```

Open `http://localhost:8501`.

## Ask cARR — the NL query layer

Two modes, same interface:

- **Offline (default)** — keyword router to a curated set of canned SQL
  snippets. Works without network or API keys; the panel can run it cold.
- **LLM** — if `ANTHROPIC_API_KEY` is set, Claude Sonnet generates SQL.
  Every generated query passes through a local dry-run verifier
  (EXPLAIN) before execution (spec 11 §4). Refusals are explicit.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # optional
streamlit run dashboard/app.py
```

The dashboard always shows:
1. The natural-language narration of the answer.
2. The result rows.
3. The generated SQL.

Per spec 11 §3.1, hiding any of those three is non-negotiable — showing the
SQL is what lets a CFO trust an AI-generated number.

Out-of-scope questions (PII, cross-rep compensation, forecasting) are
explicitly refused with a reason citing the relevant spec.

## Files

```
dashboard/
├── app.py              Streamlit entry; routes to views
├── requirements.txt
├── lib/
│   ├── data.py         Parquet loaders
│   ├── narrator.py     Template-based anomaly narrative (spec 11 §3.2)
│   └── ask.py          NL agent (offline router + optional LLM)
└── README.md           this file
```
