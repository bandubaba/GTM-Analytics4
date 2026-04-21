"""
Evaluation harness for cARR.

Four tiers, mirroring specs/06_evaluation_framework.md:
  T1 Correctness        — each archetype lands in its expected HealthScore band
                          (gated by ramp: only test accounts past ramp_end)
  T2 Construct validity — bounds honored, determinism, bilinearity invariants
  T3 Decision utility   — shelfware visibility, rep ranking separation
  T4 Comp safety        — no unbounded multipliers, no ramp-only cliffs, no
                          rep pay shift from data volume alone

Each check returns (name, tier, passed, detail). A run prints a summary
and exits non-zero if any T1/T4 check fails (stop-the-line events).
T2 failures are warn-only here (bounds violations are physically impossible
given the CLAMP in metric_healthscore.sql, but we still assert it so the
check is audited).

Usage:
  python evals/run_evals.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "pipeline_and_tests" / "data"
# BQ is source of truth for every table the evals touch — including
# archetype labels, exposed as the `raw_account_archetypes` bridge view
# in `gtm_metric` and exported to parquet on every pipeline run. The
# local generator CSV is a fallback for bare-clone runs where the
# pipeline hasn't been executed yet.
ARCHETYPE_PARQUET = DATA_DIR / "raw_account_archetypes.parquet"
ARCHETYPE_CSV = REPO_ROOT / "data_generation" / "output" / "_account_archetypes.csv"

# Import pipeline params so checks reflect the current spec.
sys.path.insert(0, str(REPO_ROOT / "pipeline_and_tests"))
import params  # noqa: E402


# ---------------------------------------------------------------------------
# check protocol
# ---------------------------------------------------------------------------

@dataclass
class Result:
    name: str
    tier: str      # T1 | T2 | T3 | T4
    passed: bool
    detail: str

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] [{self.tier}] {self.name}\n       {self.detail}"


# ---------------------------------------------------------------------------
# data loaders
# ---------------------------------------------------------------------------

def _load_carr() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "mart_carr_current.parquet")


def _load_archetypes() -> pd.DataFrame:
    # Prefer the BQ-exported parquet so the eval reads from the same
    # source-of-truth artifact as the dashboard. Fall back to the
    # generator CSV for bare-clone dev (pipeline not yet run).
    if ARCHETYPE_PARQUET.exists():
        return pd.read_parquet(ARCHETYPE_PARQUET)
    return pd.read_csv(ARCHETYPE_CSV)


def _joined() -> pd.DataFrame:
    carr = _load_carr()
    arch = _load_archetypes()
    return carr.merge(arch, on="account_id", how="left").assign(
        archetype=lambda d: d.archetype.fillna("normal")
    )


# ---------------------------------------------------------------------------
# T1 — archetype correctness (post-ramp only)
# ---------------------------------------------------------------------------
# Post-ramp: contract_age_days >= ramp_end for the account's segment.
# Pre-ramp accounts are excluded from T1 because the blended HS is designed
# to hold them at 1.00. That's a feature, not a failure.

def _post_ramp_mask(df: pd.DataFrame) -> pd.Series:
    ent_end = params.RAMP_PARAMS["Enterprise"]["ramp_end"]
    mm_end = params.RAMP_PARAMS["Mid-Market"]["ramp_end"]
    return (
        ((df.segment == "Enterprise") & (df.contract_age_days >= ent_end))
        | ((df.segment == "Mid-Market") & (df.contract_age_days >= mm_end))
    )


def check_shelfware(df: pd.DataFrame) -> Result:
    post = df[_post_ramp_mask(df)]
    shelf = post[post.archetype == "shelfware"]
    if len(shelf) == 0:
        return Result("T1a shelfware lands at floor", "T1", False, "no post-ramp shelfware accounts to test")
    at_floor = (shelf.healthscore <= params.HS_FLOOR + 1e-6).sum()
    total = len(shelf)
    pct = at_floor / total
    passed = pct >= 0.98
    return Result(
        "T1a shelfware lands at floor",
        "T1",
        passed,
        f"{at_floor}/{total} ({pct:.1%}) post-ramp shelfware accounts at HS ≤ {params.HS_FLOOR}",
    )


def check_overage(df: pd.DataFrame) -> Result:
    post = df[_post_ramp_mask(df)]
    ov = post[post.archetype == "overage"]
    if len(ov) == 0:
        return Result("T1b overage lands in [1.00, 1.30]", "T1", False, "no post-ramp overage accounts")
    in_band = ((ov.healthscore >= 1.00) & (ov.healthscore <= params.HS_CAP)).sum()
    total = len(ov)
    pct = in_band / total
    passed = pct >= 0.90
    return Result(
        "T1b overage lands in [1.00, 1.30]",
        "T1",
        passed,
        f"{in_band}/{total} ({pct:.1%}) post-ramp overage accounts in expected band; median HS={ov.healthscore.median():.3f}",
    )


def check_spike_drop(df: pd.DataFrame) -> Result:
    post = df[_post_ramp_mask(df)]
    sd = post[post.archetype == "spike_drop"]
    if len(sd) == 0:
        return Result("T1c spike_drop detected as band", "T1", False, "no post-ramp spike_drop accounts")
    # Post-ramp spike_drop should be either 'spike_drop' or 'at_risk_shelfware' band
    detected = sd[sd.band.isin(["spike_drop", "at_risk_shelfware"])]
    pct = len(detected) / len(sd)
    passed = pct >= 0.80
    return Result(
        "T1c spike_drop detected as band",
        "T1",
        passed,
        f"{len(detected)}/{len(sd)} ({pct:.1%}) spike_drop accounts classified as spike_drop/at_risk; mean HS={sd.healthscore.mean():.3f}",
    )


def check_normal(df: pd.DataFrame) -> Result:
    # "normal" archetype in data_generation/config.py spans U∈[0.50, 0.95].
    # U=0.50 → base(U) = 0.70 under spec 03 §2.1; U=0.95 → base(U) = 1.00.
    # So a correctly-implemented metric should place ≥95% of normal accounts
    # in [0.60, HS_CAP] — anything outside means either the base(U) curve
    # or the generator drifted. Median is the more informative single number.
    post = df[_post_ramp_mask(df)]
    n = post[post.archetype == "normal"]
    if len(n) == 0:
        return Result("T1d normal lands in healthy band", "T1", False, "no post-ramp normal accounts")
    in_band = n[n.healthscore.between(0.60, params.HS_CAP)]
    pct = len(in_band) / len(n)
    passed = pct >= 0.95 and 0.80 <= n.healthscore.median() <= 1.05
    return Result(
        "T1d normal lands in healthy band",
        "T1",
        passed,
        f"{len(in_band)}/{len(n)} ({pct:.1%}) normal accounts in [0.60, {params.HS_CAP}]; median HS={n.healthscore.median():.3f}",
    )


# ---------------------------------------------------------------------------
# T2 — construct validity (invariants)
# ---------------------------------------------------------------------------

def check_bounds(df: pd.DataFrame) -> Result:
    violations_steady = df[~df.healthscore_steady.between(params.HS_FLOOR, params.HS_CAP)]
    # Blended HS can be in [HS_FLOOR, 1.30]; pre-ramp it's 1.00.
    violations_blend = df[~df.healthscore.between(params.HS_FLOOR, params.HS_CAP + 1e-9)]
    passed = len(violations_steady) == 0 and len(violations_blend) == 0
    return Result(
        "T2a HealthScore bounds honored",
        "T2",
        passed,
        f"steady-state out of [{params.HS_FLOOR}, {params.HS_CAP}]: {len(violations_steady)}; blended out of bounds: {len(violations_blend)}",
    )


def check_ramp_monotonicity(df: pd.DataFrame) -> Result:
    """ramp_w is bounded [0, 1] and behaves monotonically with contract_age per segment."""
    bad_w = df[~df.ramp_w.between(0.0, 1.0)]
    # Per segment, older contracts should have w ≥ younger on average.
    ent = df[df.segment == "Enterprise"].sort_values("contract_age_days")
    mm = df[df.segment == "Mid-Market"].sort_values("contract_age_days")
    # Monotonic (non-decreasing) check via Spearman correlation proxy:
    ent_ok = ent.ramp_w.diff().dropna().ge(-1e-9).all() if len(ent) > 1 else True
    mm_ok = mm.ramp_w.diff().dropna().ge(-1e-9).all() if len(mm) > 1 else True
    passed = len(bad_w) == 0 and ent_ok and mm_ok
    return Result(
        "T2b ramp weight bounded + monotonic",
        "T2",
        passed,
        f"ramp_w out of [0,1]: {len(bad_w)}; ENT monotonic: {ent_ok}; MM monotonic: {mm_ok}",
    )


def check_carr_equals_formula(df: pd.DataFrame) -> Result:
    """cARR must equal Committed_ARR × HealthScore to 6 decimals (D01)."""
    recomputed = df.committed_arr * df.healthscore
    diff = (df.carr - recomputed).abs().max()
    passed = diff < 1e-6
    return Result(
        "T2c cARR = Committed_ARR × HealthScore (D01)",
        "T2",
        passed,
        f"max |cARR - committed*HS| = {diff:.2e}",
    )


# ---------------------------------------------------------------------------
# T3 — decision utility
# ---------------------------------------------------------------------------

def check_shelfware_visible(df: pd.DataFrame) -> Result:
    """Post-ramp shelfware accounts must flip into an at_risk band — the whole point of cARR."""
    post = df[_post_ramp_mask(df)]
    shelf = post[post.archetype == "shelfware"]
    if len(shelf) == 0:
        return Result("T3a shelfware visibly at-risk post-ramp", "T3", False, "no shelfware to check")
    visible = (shelf.band == "at_risk_shelfware").sum()
    pct = visible / len(shelf)
    passed = pct >= 0.98
    return Result(
        "T3a shelfware visibly at-risk post-ramp",
        "T3",
        passed,
        f"{visible}/{len(shelf)} ({pct:.1%}) of shelfware archetypes show band='at_risk_shelfware'",
    )


def check_rep_dispersion(_df: pd.DataFrame) -> Result:
    """Rep-level weighted HealthScore should disperse meaningfully — otherwise the metric is useless for comp."""
    rep = pd.read_parquet(DATA_DIR / "mart_carr_by_rep.parquet")
    rep = rep.dropna(subset=["weighted_healthscore"])
    spread = rep.weighted_healthscore.max() - rep.weighted_healthscore.min()
    stdev = rep.weighted_healthscore.std()
    passed = spread >= 0.15 and stdev >= 0.03
    return Result(
        "T3b rep-level weighted HS disperses",
        "T3",
        passed,
        f"spread={spread:.3f} (need ≥0.15); stdev={stdev:.3f} (need ≥0.03); across {len(rep)} reps",
    )


# ---------------------------------------------------------------------------
# T4 — comp safety
# ---------------------------------------------------------------------------

def check_no_unbounded_multiplier(df: pd.DataFrame) -> Result:
    """A rep's cARR per account cannot exceed Committed_ARR × HS_CAP."""
    ratio = df.carr / df.committed_arr
    over = (ratio > params.HS_CAP + 1e-9).sum()
    passed = over == 0
    return Result(
        "T4a no account's cARR/Commit ratio exceeds HS_CAP",
        "T4",
        passed,
        f"{over} accounts with cARR/Committed > {params.HS_CAP}; max ratio observed = {ratio.max():.4f}",
    )


def check_new_logo_protection(df: pd.DataFrame) -> Result:
    """Per D12: new logos (age ≤ ramp_full) must have HealthScore == 1.00 exactly."""
    ent_full = params.RAMP_PARAMS["Enterprise"]["ramp_full"]
    mm_full = params.RAMP_PARAMS["Mid-Market"]["ramp_full"]
    new_logos = df[
        ((df.segment == "Enterprise") & (df.contract_age_days <= ent_full))
        | ((df.segment == "Mid-Market") & (df.contract_age_days <= mm_full))
    ]
    if len(new_logos) == 0:
        return Result("T4b new-logo protection (ramp floor)", "T4", True, "no new-logo accounts in this snapshot — vacuously true")
    violators = new_logos[~new_logos.healthscore.between(1.00 - 1e-6, 1.00 + 1e-6)]
    passed = len(violators) == 0
    return Result(
        "T4b new-logo protection (ramp floor)",
        "T4",
        passed,
        f"{len(violators)}/{len(new_logos)} new-logo accounts with HS ≠ 1.00 (D12 violation)",
    )


def check_orphan_exclusion(df: pd.DataFrame) -> Result:
    """D05: orphan usage must not influence cARR. Verify by comparing total credits
    in int_usage_rolled to int_orphan_usage 'valid' class."""
    orphan = pd.read_parquet(DATA_DIR / "int_orphan_usage.parquet")
    rolled = pd.read_parquet(DATA_DIR / "int_usage_rolled.parquet")
    valid_total = orphan.loc[orphan.usage_class == "valid", "credits_consumed"].sum()
    orphan_total = orphan.loc[orphan.usage_class != "valid", "credits_consumed"].sum()
    rolled_total = rolled["credits_90d"].sum()
    # The rolled total is a subset of valid_total (90d window), must not exceed it.
    passed = rolled_total <= valid_total + 1e-6
    return Result(
        "T4c orphan credits excluded from metric (D05)",
        "T4",
        passed,
        f"valid_total={valid_total:,.0f}  rolled_90d={rolled_total:,.0f}  orphan_excluded={orphan_total:,.0f}",
    )


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

CHECKS = [
    check_shelfware,
    check_overage,
    check_spike_drop,
    check_normal,
    check_bounds,
    check_ramp_monotonicity,
    check_carr_equals_formula,
    check_shelfware_visible,
    check_rep_dispersion,
    check_no_unbounded_multiplier,
    check_new_logo_protection,
    check_orphan_exclusion,
]


def main() -> int:
    df = _joined()
    print(f"[evals] loaded {len(df)} accounts from mart_carr_current")
    print(f"[evals] archetype counts: {df.archetype.value_counts().to_dict()}")
    print()

    results = [check(df) for check in CHECKS]
    for r in results:
        print(r.line())
    print()

    t1_t4_fails = [r for r in results if not r.passed and r.tier in ("T1", "T4")]
    t2_t3_fails = [r for r in results if not r.passed and r.tier in ("T2", "T3")]
    print(f"[evals] total={len(results)}  pass={sum(1 for r in results if r.passed)}  fail={sum(1 for r in results if not r.passed)}")
    if t1_t4_fails:
        print(f"[evals] STOP-THE-LINE: {len(t1_t4_fails)} T1/T4 failures")
        return 1
    if t2_t3_fails:
        print(f"[evals] warn: {len(t2_t3_fails)} T2/T3 failures (non-blocking)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
