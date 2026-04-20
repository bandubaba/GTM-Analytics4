"""
All tunable knobs for synthetic data generation.
Keep this file declarative — logic lives in generate_data.py.
"""
from datetime import date

SEED = 42

# Historical window. Today (per take-home context) = 2026-04-18.
# 16 months gives full FY2025 + trailing-12-month view.
WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2026, 4, 18)

# Table sizes (targets — actual counts may differ by a few rows for realism)
N_REPS = 50
N_ACCOUNTS = 1_000
N_USAGE_LOGS_TARGET = 200_000

# Account archetypes — sums to 1.0
ARCHETYPE_RATIOS = {
    "shelfware":  0.10,   # high commit, ~zero usage
    "spike_drop": 0.05,   # 90% of annual credits burned in month 1
    "overage":    0.15,   # consistent 120%+ of monthly included
    "normal":     0.70,   # healthy, noisy usage
}

# Contract overlays (applied on top of base 1-contract-per-account)
N_MID_YEAR_EXPANSIONS = 90   # 2nd overlapping contract mid-term
N_RENEWALS = 130             # sequential contracts (old expires, new starts)

# Orphan/rogue usage anomalies
N_ORPHAN_LOGS_BAD_ACCOUNT = 200     # account_id not in Accounts
N_ORPHAN_LOGS_OUT_OF_WINDOW = 150   # valid account, date outside any contract

# Commercials
ENTERPRISE_FRACTION = 0.30   # of accounts
ENTERPRISE_ACV_LOGNORM = (12.5, 0.6)  # mean, sigma of ln($) — ~$270K median
MIDMARKET_ACV_LOGNORM = (10.3, 0.5)   # ~$30K median

# Price per credit (used to convert credits ↔ $ in the metric layer)
PRICE_PER_CREDIT = 1.00

# Dimensions
REGIONS = ["NAMER", "EMEA", "APAC", "LATAM"]
REGION_WEIGHTS = [0.50, 0.25, 0.15, 0.10]

SEGMENTS = ["Enterprise", "Mid-Market"]

INDUSTRIES = [
    "Technology", "Financial Services", "Healthcare", "Retail",
    "Manufacturing", "Public Sector", "Education", "Media",
    "Energy", "Telecom",
]

# BigQuery defaults (can be overridden via env)
DEFAULT_DATASET = "gtm_analytics"
DEFAULT_LOCATION = "US"

TABLE_NAMES = {
    "sales_reps": "sales_reps",
    "accounts": "accounts",
    "contracts": "contracts",
    "daily_usage_logs": "daily_usage_logs",
}
