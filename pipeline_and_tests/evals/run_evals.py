"""
Evaluation harness for cARR.

Five tiers, mirroring specs/06_evaluation_framework.md:
  T1 Correctness          — each input archetype lands in its expected
                            HealthScore band
  T2 Construct validity   — bounds honored, cARR = Committed × HS identity
  T3 Decision utility     — shelfware visibility, rep ranking separation
  T4 Comp safety          — no unbounded multipliers, orphan exclusion
  T5 Transition fidelity  — does cARR actually surface the five failure
                            modes the seat→consumption pricing pivot
                            creates, in dollars the CFO can read?

The T5 framing: SaaS is moving from seat-based to consumption-based
pricing (AI is the forcing function). A seat-based book reports
Committed ARR as if every signed dollar is earned. A consumption book
has five places that assumption fails — shelfware, spike-drop, overage,
mid-term expansion, and orphaned usage. T5 tests, per failure mode,
that cARR's dollar answer diverges from seat-based in the expected
direction and magnitude. A T5 failure means the metric stopped doing
its business job, not that the code is wrong.

Each check returns (name, tier, passed, detail). A run prints a summary
and exits non-zero if any T1/T4/T5 check fails (stop-the-line events).
T2/T3 failures are warn-only here (bounds violations are physically
impossible given the CLAMP in metric_healthscore.sql, but we still
assert it so the check is audited).

v0.7: removed the ramp-blend from the HealthScore formula. Consequently
dropped `_post_ramp_mask`, `check_ramp_monotonicity`, and
`check_new_logo_protection` — there is no ramp weight any more and the
steady-state formula applies to every active-contract account.

v0.7.1: added T5 Transition fidelity (5 checks). Each check frames
one of the five pricing-pivot failure modes as a dollar delta between
what a seat-based accounting of the same book would report and what
cARR reports — so the eval output speaks to VPS/CFO, not only to the
build system.

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
# Archetype labels are generator provenance / eval ground truth — not a
# warehouse source table (the brief specifies 4 source tables and only
# those 4 sit in `gtm_analytics`). The pipeline snapshots the generator
# CSV into parquet on every run; we prefer that parquet, fall back to
# the CSV directly for bare-clone runs.
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
# T1 — archetype correctness
# ---------------------------------------------------------------------------

def check_shelfware(df: pd.DataFrame) -> Result:
    shelf = df[df.archetype == "shelfware"]
    if len(shelf) == 0:
        return Result("T1a shelfware lands at floor", "T1", False, "no shelfware accounts to test")
    at_floor = (shelf.healthscore <= params.HS_FLOOR + 1e-6).sum()
    total = len(shelf)
    pct = at_floor / total
    passed = pct >= 0.98
    return Result(
        "T1a shelfware lands at floor",
        "T1",
        passed,
        f"{at_floor}/{total} ({pct:.1%}) shelfware accounts at HS ≤ {params.HS_FLOOR}",
    )


def check_overage(df: pd.DataFrame) -> Result:
    ov = df[df.archetype == "overage"]
    if len(ov) == 0:
        return Result("T1b overage lands in [1.00, 1.30]", "T1", False, "no overage accounts")
    in_band = ((ov.healthscore >= 1.00) & (ov.healthscore <= params.HS_CAP)).sum()
    total = len(ov)
    pct = in_band / total
    passed = pct >= 0.90
    return Result(
        "T1b overage lands in [1.00, 1.30]",
        "T1",
        passed,
        f"{in_band}/{total} ({pct:.1%}) overage accounts in expected band; median HS={ov.healthscore.median():.3f}",
    )


def check_spike_drop(df: pd.DataFrame) -> Result:
    sd = df[df.archetype == "spike_drop"]
    if len(sd) == 0:
        return Result("T1c spike_drop detected as band", "T1", False, "no spike_drop accounts")
    # A spike_drop archetype should classify as 'spike_drop' (m1_share rule
    # tripped) or 'at_risk_shelfware' (HS depressed below 0.55 by the drop).
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
    # "normal" archetype in data_generation/config.py targets U∈[0.50, 0.95].
    # U=0.50 → base(U) = 0.72 under spec 03 §2.1; U=0.95 → base(U) = 1.08.
    # So a correctly-implemented metric should place ≥95% of normal accounts
    # in [0.60, HS_CAP] — provided the trailing 90-day window is fully
    # observable.
    #
    # Accounts with contract_age < 90d only have a partial history inside
    # the rolling window (the first few weeks' usage is the only evidence
    # available), so measured U is systematically lower than the generator's
    # target for young-but-normal accounts. v0.6 papered over this with a
    # segment-aware ramp blend; v0.7 drops the blend (see spec 03 §2.2), and
    # accordingly this eval restricts to `contract_age_days ≥ 90` where the
    # 90-day window is fully populated and the normal→healthy claim is
    # epistemically meaningful. Young accounts get their own fairness path
    # via the pre-signal trust branch (`U IS NULL → base = 1.00`) — they
    # just aren't what this check is about.
    n = df[df.archetype == "normal"]
    if len(n) == 0:
        return Result("T1d normal lands in healthy band", "T1", False, "no normal accounts")
    mature = n[n.contract_age_days >= 90]
    in_band = mature[mature.healthscore.between(0.60, params.HS_CAP)]
    pct = len(in_band) / len(mature) if len(mature) else 0.0
    passed = pct >= 0.95 and 0.80 <= mature.healthscore.median() <= 1.05
    return Result(
        "T1d normal (mature) lands in healthy band",
        "T1",
        passed,
        f"{len(in_band)}/{len(mature)} ({pct:.1%}) normal accounts with contract_age ≥ 90d in "
        f"[0.60, {params.HS_CAP}]; median HS={mature.healthscore.median():.3f}",
    )


# ---------------------------------------------------------------------------
# T2 — construct validity (invariants)
# ---------------------------------------------------------------------------

def check_bounds(df: pd.DataFrame) -> Result:
    violations = df[~df.healthscore.between(params.HS_FLOOR, params.HS_CAP + 1e-9)]
    passed = len(violations) == 0
    return Result(
        "T2a HealthScore bounds honored",
        "T2",
        passed,
        f"HS out of [{params.HS_FLOOR}, {params.HS_CAP}]: {len(violations)}",
    )


def check_base_modifier_identity(df: pd.DataFrame) -> Result:
    """HealthScore must equal clamp(base × modifier, FLOOR, CAP) — the steady-state formula."""
    recomputed = (df.base_score * df.modifier).clip(params.HS_FLOOR, params.HS_CAP)
    diff = (df.healthscore - recomputed).abs().max()
    passed = diff < 1e-6
    return Result(
        "T2b HealthScore = clamp(base × modifier, FLOOR, CAP)",
        "T2",
        passed,
        f"max |HS - clamp(base*mod)| = {diff:.2e}",
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
    """Shelfware accounts must flip into the at_risk_shelfware band — the whole point of cARR."""
    shelf = df[df.archetype == "shelfware"]
    if len(shelf) == 0:
        return Result("T3a shelfware visibly at-risk", "T3", False, "no shelfware to check")
    visible = (shelf.band == "at_risk_shelfware").sum()
    pct = visible / len(shelf)
    passed = pct >= 0.98
    return Result(
        "T3a shelfware visibly at-risk",
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
        "T4b orphan credits excluded from metric (D05)",
        "T4",
        passed,
        f"valid_total={valid_total:,.0f}  rolled_90d={rolled_total:,.0f}  orphan_excluded={orphan_total:,.0f}",
    )


# ---------------------------------------------------------------------------
# T5 — transition fidelity (seat→consumption pricing pivot)
#
# The pricing-pivot framing. A seat-based accounting reads every signed
# dollar as an earned dollar and stops there. Consumption pricing opens
# five places where that assumption breaks. Each T5 check measures the
# dollar gap between "what seat-based would have reported" and "what
# cARR reports" for one failure mode, and asserts the gap is in the
# expected direction and size. A T5 fail means a failure mode the
# metric was built to see has become invisible — stop-the-line.
# ---------------------------------------------------------------------------

# Generator list price for a single consumption credit
# (`data_generation/config.py::PRICE_PER_CREDIT`). Used only to
# dollarize the orphan-exclusion exposure in T5e so the CFO sees a
# dollar, not a credit count.
_CREDIT_LIST_PRICE_USD = 1.00


def check_pivot_shelfware(df: pd.DataFrame) -> Result:
    """T5a — cARR haircuts shelfware that seat-based would pay at full ACV."""
    shelf = df[df.archetype == "shelfware"]
    if len(shelf) == 0:
        return Result("T5a shelfware: cARR haircut vs seat-based", "T5", False, "no shelfware accounts")
    seat = shelf.committed_arr.sum()
    carr = shelf.carr.sum()
    haircut = (seat - carr) / seat if seat > 0 else 0.0
    passed = haircut >= 0.45
    return Result(
        "T5a shelfware: cARR haircut vs seat-based",
        "T5",
        passed,
        f"{len(shelf)} shelfware accounts  seat=${seat/1e6:.2f}M  cARR=${carr/1e6:.2f}M  "
        f"Δ=-${(seat-carr)/1e6:.2f}M (-{haircut:.1%}); seat-based would pay full ACV on all of them",
    )


def check_pivot_overage(df: pd.DataFrame) -> Result:
    """T5b — cARR surfaces consumption upside that seat-based has no price for."""
    ov = df[df.band == "overage"]
    if len(ov) == 0:
        return Result("T5b overage: cARR uplift vs seat-based", "T5", False, "no overage-band accounts")
    seat = ov.committed_arr.sum()
    carr = ov.carr.sum()
    uplift = (carr - seat) / seat if seat > 0 else 0.0
    passed = uplift >= 0.05
    return Result(
        "T5b overage: cARR uplift vs seat-based",
        "T5",
        passed,
        f"{len(ov)} accounts consuming beyond entitlement  seat=${seat/1e6:.2f}M  cARR=${carr/1e6:.2f}M  "
        f"Δ=+${(carr-seat)/1e6:.2f}M (+{uplift:.1%}); seat-based has no line item for overages",
    )


def check_pivot_spike_drop(df: pd.DataFrame) -> Result:
    """T5c — cARR catches the cliff; seat-based reports full ACV until contract ends."""
    sd = df[df.archetype == "spike_drop"]
    if len(sd) == 0:
        return Result("T5c spike_drop: cARR cliff vs seat-based", "T5", False, "no spike_drop accounts")
    caught = sd[sd.band.isin(["spike_drop", "at_risk_shelfware"])]
    seat = sd.committed_arr.sum()
    carr = sd.carr.sum()
    haircut = (seat - carr) / seat if seat > 0 else 0.0
    catch_rate = len(caught) / len(sd)
    passed = catch_rate >= 0.80 and haircut >= 0.20
    return Result(
        "T5c spike_drop: cARR cliff vs seat-based",
        "T5",
        passed,
        f"{len(caught)}/{len(sd)} ({catch_rate:.0%}) classified as spike_drop/at_risk  "
        f"seat=${seat/1e6:.2f}M  cARR=${carr/1e6:.2f}M  Δ=-${(seat-carr)/1e6:.2f}M (-{haircut:.1%}); "
        f"seat-based reports full ACV until the contract expires",
    )


def check_pivot_expansion(df: pd.DataFrame) -> Result:
    """T5d — cARR compounds overlapping contracts; seat-based prices each line separately."""
    ex = df[df.band == "expansion"]
    if len(ex) == 0:
        return Result("T5d expansion: cARR compounding vs seat-based", "T5", False, "no expansion-band accounts")
    seat = ex.committed_arr.sum()
    carr = ex.carr.sum()
    lift = (carr - seat) / seat if seat > 0 else 0.0
    passed = lift >= 0.05
    return Result(
        "T5d expansion: cARR compounding vs seat-based",
        "T5",
        passed,
        f"{len(ex)} mid-term expansion accounts (≥2 active contracts, U>1.0)  "
        f"seat=${seat/1e6:.2f}M  cARR=${carr/1e6:.2f}M  Δ=+${(carr-seat)/1e6:.2f}M (+{lift:.1%}); "
        f"seat-based prices each contract line independently",
    )


def check_pivot_orphans(_df: pd.DataFrame) -> Result:
    """T5e — cARR excludes rogue usage that seat-based has no entity to attach to."""
    orphan = pd.read_parquet(DATA_DIR / "int_orphan_usage.parquet")
    orphan_rows = orphan[orphan.usage_class != "valid"]
    valid_rows = orphan[orphan.usage_class == "valid"]
    n_orphan = len(orphan_rows)
    orphan_credits = orphan_rows.credits_consumed.sum()
    valid_credits = valid_rows.credits_consumed.sum()
    dollar_exposure = orphan_credits * _CREDIT_LIST_PRICE_USD
    # The rolled 90d usage (used by the metric) must be a subset of the
    # valid class — i.e. no orphan credit has slipped into cARR.
    rolled = pd.read_parquet(DATA_DIR / "int_usage_rolled.parquet")
    rolled_total = rolled.credits_90d.sum()
    excluded_cleanly = rolled_total <= valid_credits + 1e-6
    passed = n_orphan > 0 and excluded_cleanly
    return Result(
        "T5e orphans: cARR exclusion vs seat-based",
        "T5",
        passed,
        f"{n_orphan} rogue usage rows ({orphan_credits:,.0f} credits, ~${dollar_exposure/1e3:.1f}K list) "
        f"excluded from cARR under D05; seat-based accounting has no entity to attach this usage to",
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
    check_base_modifier_identity,
    check_carr_equals_formula,
    check_shelfware_visible,
    check_rep_dispersion,
    check_no_unbounded_multiplier,
    check_orphan_exclusion,
    check_pivot_shelfware,
    check_pivot_overage,
    check_pivot_spike_drop,
    check_pivot_expansion,
    check_pivot_orphans,
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

    # T1 (code correct), T4 (comp-safe), T5 (pivot fidelity) are stop-the-line.
    # T2 (bounds) / T3 (decision utility) warn-only — a T2 fail is physically
    # impossible under the CLAMP in SQL, a T3 fail is a design call.
    blocking_fails = [r for r in results if not r.passed and r.tier in ("T1", "T4", "T5")]
    advisory_fails = [r for r in results if not r.passed and r.tier in ("T2", "T3")]
    per_tier = {t: sum(1 for r in results if r.tier == t) for t in ("T1", "T2", "T3", "T4", "T5")}
    tier_breakdown = "  ".join(f"{t}={n}" for t, n in per_tier.items())
    print(f"[evals] tiers  {tier_breakdown}")
    print(f"[evals] total={len(results)}  pass={sum(1 for r in results if r.passed)}  fail={sum(1 for r in results if not r.passed)}")
    if blocking_fails:
        print(f"[evals] STOP-THE-LINE: {len(blocking_fails)} T1/T4/T5 failures")
        return 1
    if advisory_fails:
        print(f"[evals] warn: {len(advisory_fails)} T2/T3 failures (non-blocking)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
