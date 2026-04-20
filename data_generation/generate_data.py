"""
Synthetic B2B SaaS GTM dataset generator.

Produces four relational tables as CSV files under ./output/ :

  sales_reps         (~50)
  accounts           (~1,000)
  contracts          (~1,200 — 1 per account + expansions + renewals)
  daily_usage_logs   (~200,000)

Account archetypes (mutually exclusive, per config.ARCHETYPE_RATIOS):
  shelfware   — high commit, zero usage logs
  spike_drop  — ~90% of annual credits burned in month 1, near-zero after
  overage     — consistent 120%+ of monthly included credits
  normal      — healthy noisy usage in [50%, 95%] of included

Contract overlays:
  mid-year expansions — 2nd, larger overlapping contract mid-term
  renewals            — sequential contract starting ~at old one's end

Orphans (injected separately):
  bad-account logs    — account_id not in Accounts table
  out-of-window logs  — valid account_id, date outside any active contract

Run: python generate_data.py
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

import config as C

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

fake = Faker()
Faker.seed(C.SEED)
np.random.seed(C.SEED)
random.seed(C.SEED)


# ---------- helpers ----------

def _rep_id(i: int) -> str:
    return f"R{i:03d}"


def _acc_id(i: int) -> str:
    return f"ACC{i:06d}"


def _ct_id(i: int) -> str:
    return f"CT{i:06d}"


def _log_id(i: int) -> str:
    return f"UL{i:09d}"


def _sample_industry(segment: str) -> str:
    # Enterprise skews toward regulated verticals; mid-market skews SMB-friendly.
    if segment == "Enterprise":
        weights = [0.18, 0.22, 0.15, 0.05, 0.12, 0.12, 0.02, 0.04, 0.06, 0.04]
    else:
        weights = [0.28, 0.10, 0.08, 0.15, 0.08, 0.03, 0.08, 0.10, 0.05, 0.05]
    return random.choices(C.INDUSTRIES, weights=weights, k=1)[0]


def _sample_acv(segment: str) -> float:
    mu, sigma = (C.ENTERPRISE_ACV_LOGNORM if segment == "Enterprise"
                 else C.MIDMARKET_ACV_LOGNORM)
    raw = float(np.random.lognormal(mu, sigma))
    # Clamp to realistic ranges
    if segment == "Enterprise":
        return round(max(80_000, min(2_500_000, raw)), 2)
    return round(max(8_000, min(180_000, raw)), 2)


def _credits_from_acv(acv: float) -> int:
    # Included monthly credits ≈ ACV / (12 * price_per_credit) with some slack.
    base = acv / (12.0 * C.PRICE_PER_CREDIT)
    jitter = np.random.uniform(0.85, 1.15)
    return int(round(base * jitter))


def _quarter_end_biased_date(year: int) -> date:
    # Contracts in B2B cluster around quarter-ends — simulate that.
    q_ends = [date(year, 3, 28), date(year, 6, 28), date(year, 9, 28), date(year, 12, 20)]
    if random.random() < 0.55:
        anchor = random.choice(q_ends)
        offset = int(np.random.normal(0, 10))
        return anchor + timedelta(days=offset)
    # Otherwise uniform across year
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))


# ---------- table builders ----------

def build_sales_reps() -> pd.DataFrame:
    rows = []
    for i in range(1, C.N_REPS + 1):
        segment = "Enterprise" if i <= int(C.N_REPS * 0.45) else "Mid-Market"
        region = random.choices(C.REGIONS, weights=C.REGION_WEIGHTS, k=1)[0]
        rows.append({
            "rep_id": _rep_id(i),
            "name": fake.name(),
            "region": region,
            "segment": segment,
        })
    return pd.DataFrame(rows)


def build_accounts(reps: pd.DataFrame) -> pd.DataFrame:
    # Split accounts across segments per ENTERPRISE_FRACTION.
    n_ent = int(C.N_ACCOUNTS * C.ENTERPRISE_FRACTION)
    n_mm = C.N_ACCOUNTS - n_ent

    ent_reps = reps[reps.segment == "Enterprise"].rep_id.tolist()
    mm_reps = reps[reps.segment == "Mid-Market"].rep_id.tolist()

    rows = []
    for i in range(1, C.N_ACCOUNTS + 1):
        segment = "Enterprise" if i <= n_ent else "Mid-Market"
        rep_pool = ent_reps if segment == "Enterprise" else mm_reps
        rows.append({
            "account_id": _acc_id(i),
            "company_name": fake.company(),
            "industry": _sample_industry(segment),
            "rep_id": random.choice(rep_pool),
            # segment is not in the brief's schema but handy downstream;
            # we attach it via the rep join later so we keep the table clean.
            "_segment": segment,
        })
    df = pd.DataFrame(rows)
    return df


def _assign_archetypes(accounts: pd.DataFrame) -> dict[str, str]:
    ids = accounts.account_id.tolist()
    random.shuffle(ids)
    archetypes = {}
    cursor = 0
    for name, ratio in C.ARCHETYPE_RATIOS.items():
        n = int(round(len(ids) * ratio))
        for aid in ids[cursor:cursor + n]:
            archetypes[aid] = name
        cursor += n
    # Any rounding leftovers → normal
    for aid in ids[cursor:]:
        archetypes[aid] = "normal"
    return archetypes


def build_contracts(accounts: pd.DataFrame, archetypes: dict[str, str]) -> pd.DataFrame:
    rows = []
    ct_counter = 1

    # 1 base contract per account
    for _, acc in accounts.iterrows():
        segment = acc._segment
        acv = _sample_acv(segment)

        # Spike-drop accounts MUST start in-window, else their month-1 burst
        # happens before our data begins and the anomaly is invisible.
        if archetypes.get(acc.account_id) == "spike_drop":
            start_year = random.choice([2025, 2025, 2025])
        else:
            start_year = random.choices(
                [2024, 2025, 2026],
                weights=[0.18, 0.72, 0.10],
                k=1,
            )[0]
        start = _quarter_end_biased_date(start_year)
        if archetypes.get(acc.account_id) == "spike_drop":
            # Clamp: must start at least 45 days into the window so month-1 is observable.
            start = max(start, C.WINDOW_START + timedelta(days=5))
            start = min(start, C.WINDOW_END - timedelta(days=90))
        term_months = random.choices([12, 12, 12, 24, 36], weights=[0.6, 0.1, 0.1, 0.15, 0.05], k=1)[0]
        end = start + timedelta(days=term_months * 30)

        rows.append({
            "contract_id": _ct_id(ct_counter),
            "account_id": acc.account_id,
            "start_date": start,
            "end_date": end,
            "annual_commit_dollars": acv,
            "included_monthly_compute_credits": _credits_from_acv(acv),
        })
        ct_counter += 1

    base = pd.DataFrame(rows)

    # Mid-year expansions — pick existing contracts, add a 2nd larger overlapping one.
    exp_candidates = base.sample(n=min(C.N_MID_YEAR_EXPANSIONS, len(base)), random_state=C.SEED)
    expansions = []
    for _, ct in exp_candidates.iterrows():
        term_days = (ct.end_date - ct.start_date).days
        # Second contract starts mid-term, runs for another ~12 months (overlapping).
        second_start = ct.start_date + timedelta(days=int(term_days * 0.5))
        second_end = second_start + timedelta(days=365)
        second_acv = round(ct.annual_commit_dollars * np.random.uniform(1.3, 2.2), 2)
        expansions.append({
            "contract_id": _ct_id(ct_counter),
            "account_id": ct.account_id,
            "start_date": second_start,
            "end_date": second_end,
            "annual_commit_dollars": second_acv,
            "included_monthly_compute_credits": _credits_from_acv(second_acv),
        })
        ct_counter += 1

    # Renewals — sequential contracts on distinct accounts (not already expanded).
    expanded_ids = set(exp_candidates.account_id)
    renewal_pool = base[~base.account_id.isin(expanded_ids)]
    ren_candidates = renewal_pool.sample(n=min(C.N_RENEWALS, len(renewal_pool)), random_state=C.SEED + 1)
    renewals = []
    for _, ct in ren_candidates.iterrows():
        # Renewal kicks in around the end of the original contract, with mild price uplift.
        new_start = ct.end_date + timedelta(days=random.randint(-5, 10))
        new_end = new_start + timedelta(days=365)
        new_acv = round(ct.annual_commit_dollars * np.random.uniform(0.95, 1.15), 2)
        renewals.append({
            "contract_id": _ct_id(ct_counter),
            "account_id": ct.account_id,
            "start_date": new_start,
            "end_date": new_end,
            "annual_commit_dollars": new_acv,
            "included_monthly_compute_credits": _credits_from_acv(new_acv),
        })
        ct_counter += 1

    return pd.concat([base, pd.DataFrame(expansions), pd.DataFrame(renewals)], ignore_index=True)


# ---------- usage logs ----------

def _emit_log(logs: list, counter: list, account_id: str, d: date, credits: float):
    if credits <= 0:
        return
    # Hard invariant: every log date lives inside the observation window.
    if d < C.WINDOW_START or d > C.WINDOW_END:
        return
    counter[0] += 1
    logs.append({
        "log_id": _log_id(counter[0]),
        "account_id": account_id,
        "date": d,
        "compute_credits_consumed": round(float(credits), 2),
    })


def _active_days(contracts_for_account: pd.DataFrame) -> list[tuple[date, float, int]]:
    """
    Returns flat list of (date, monthly_included_credits, contract_index) for every
    day where at least one contract is active, clipped to the generation window.
    If multiple contracts overlap on a day, we pick the contract with the higher
    included_monthly_compute_credits (the "primary" commit for that day).
    """
    events: dict[date, tuple[float, int]] = {}
    for idx, ct in contracts_for_account.reset_index(drop=True).iterrows():
        start = max(ct.start_date, C.WINDOW_START)
        end = min(ct.end_date, C.WINDOW_END)
        d = start
        while d <= end:
            cur = events.get(d)
            if cur is None or ct.included_monthly_compute_credits > cur[0]:
                events[d] = (ct.included_monthly_compute_credits, idx)
            d += timedelta(days=1)
    return sorted([(d, m, i) for d, (m, i) in events.items()])


def _gen_normal(account_id, contracts_df, logs, counter):
    days = _active_days(contracts_df)
    if not days:
        return
    # Account-level "personality" so it's not perfectly uniform.
    util_target = np.random.uniform(0.50, 0.95)       # fraction of included consumed
    trend = np.random.choice([-0.0006, 0.0, 0.0, 0.0008, 0.0015], p=[0.15, 0.3, 0.3, 0.15, 0.1])
    for day_idx, (d, monthly_incl, _) in enumerate(days):
        # Baseline: spread included_monthly_credits over ~22 business days, scaled by utilization.
        per_day_mean = monthly_incl / 22.0 * util_target
        weekend = d.weekday() >= 5
        # Tuned so total daily_usage_logs lands near the brief's ~200K target
        # without flattening the weekday/weekend contrast that the spike-drop
        # M1-share calculation relies on.
        skip_prob = 0.18 if weekend else 0.03
        if random.random() < skip_prob:
            continue
        factor = 0.4 if weekend else 1.0
        noise = np.random.uniform(0.6, 1.25)
        credits = per_day_mean * factor * noise * (1 + trend * day_idx)
        _emit_log(logs, counter, account_id, d, credits)


def _gen_overage(account_id, contracts_df, logs, counter):
    days = _active_days(contracts_df)
    if not days:
        return
    util_target = np.random.uniform(1.20, 1.55)   # consistently over
    for d, monthly_incl, _ in days:
        per_day_mean = monthly_incl / 22.0 * util_target
        weekend = d.weekday() >= 5
        if weekend and random.random() < 0.25:
            continue
        factor = 0.5 if weekend else 1.0
        noise = np.random.uniform(0.85, 1.25)
        credits = per_day_mean * factor * noise
        _emit_log(logs, counter, account_id, d, credits)


def _gen_spike_drop(account_id, contracts_df, logs, counter):
    # "90% of annual credits in month 1" — apply per contract.
    for _, ct in contracts_df.iterrows():
        start = max(ct.start_date, C.WINDOW_START)
        end = min(ct.end_date, C.WINDOW_END)
        if start > end:
            continue
        annual_credits = ct.included_monthly_compute_credits * 12
        m1_end = min(start + timedelta(days=30), end)
        m1_target = annual_credits * np.random.uniform(0.85, 0.95)
        m1_days = (m1_end - start).days + 1
        per_day = m1_target / max(1, m1_days)
        d = start
        while d <= m1_end:
            credits = per_day * np.random.uniform(0.7, 1.3)
            _emit_log(logs, counter, account_id, d, credits)
            d += timedelta(days=1)
        # Remainder: sparse, tiny usage — a handful of logs.
        remaining_days = (end - m1_end).days
        if remaining_days > 0:
            n_trailing = max(1, remaining_days // 21)
            offsets = random.sample(range(1, remaining_days + 1), min(n_trailing, remaining_days))
            for off in offsets:
                credits = np.random.exponential(scale=max(5, ct.included_monthly_compute_credits * 0.002))
                _emit_log(logs, counter, account_id, m1_end + timedelta(days=off), credits)


def build_daily_usage_logs(accounts: pd.DataFrame, contracts: pd.DataFrame,
                           archetypes: dict[str, str]) -> pd.DataFrame:
    logs: list[dict] = []
    counter = [0]  # mutable box so helpers can increment

    by_account = contracts.groupby("account_id")

    for aid, arch in archetypes.items():
        if arch == "shelfware":
            continue  # intentionally produce no logs
        if aid not in by_account.groups:
            continue
        ct_df = by_account.get_group(aid)
        if arch == "normal":
            _gen_normal(aid, ct_df, logs, counter)
        elif arch == "overage":
            _gen_overage(aid, ct_df, logs, counter)
        elif arch == "spike_drop":
            _gen_spike_drop(aid, ct_df, logs, counter)

    # ---------- orphan/rogue usage ----------
    # (a) bad account_id — not present in Accounts at all
    for _ in range(C.N_ORPHAN_LOGS_BAD_ACCOUNT):
        fake_id = f"ACC{random.randint(900000, 999999):06d}"
        d = C.WINDOW_START + timedelta(days=random.randint(0, (C.WINDOW_END - C.WINDOW_START).days))
        credits = np.random.uniform(10, 500)
        _emit_log(logs, counter, fake_id, d, credits)

    # (b) valid account but date outside any active contract window.
    # Exclude shelfware so the "empty usage logs" invariant holds strictly.
    # Only sample accounts whose earliest contract starts with enough slack
    # for us to place a pre-contract date inside the observation window.
    eligible = []
    for aid in accounts.account_id.tolist():
        if archetypes.get(aid) == "shelfware":
            continue
        if aid not in by_account.groups:
            continue
        earliest = by_account.get_group(aid).start_date.min()
        slack_days = (earliest - C.WINDOW_START).days
        if slack_days >= 11:
            eligible.append((aid, earliest, slack_days))

    for _ in range(C.N_ORPHAN_LOGS_OUT_OF_WINDOW):
        if not eligible:
            break
        aid, earliest, slack = random.choice(eligible)
        back = random.randint(10, min(60, slack - 1))
        d = earliest - timedelta(days=back)
        # Defense in depth — must stay inside the window.
        if d < C.WINDOW_START or d > C.WINDOW_END:
            continue
        credits = np.random.uniform(5, 250)
        _emit_log(logs, counter, aid, d, credits)

    return pd.DataFrame(logs)


# ---------- orchestration ----------

def main():
    print(f"[window] {C.WINDOW_START}  →  {C.WINDOW_END}")
    print("[1/4] sales_reps ...")
    reps = build_sales_reps()

    print("[2/4] accounts ...")
    accounts = build_accounts(reps)

    # Archetypes assigned before contracts so spike_drop can bias start dates.
    archetypes = _assign_archetypes(accounts)

    print("[3/4] contracts ...")
    contracts = build_contracts(accounts, archetypes)

    print("[4/4] daily_usage_logs ... (slowest step)")
    usage = build_daily_usage_logs(accounts, contracts, archetypes)

    # Drop the helper column from accounts before write.
    accounts_out = accounts.drop(columns=["_segment"])

    # Write CSVs
    reps.to_csv(OUT_DIR / "sales_reps.csv", index=False)
    accounts_out.to_csv(OUT_DIR / "accounts.csv", index=False)
    contracts.to_csv(OUT_DIR / "contracts.csv", index=False)
    usage.to_csv(OUT_DIR / "daily_usage_logs.csv", index=False)

    # Write archetype labels (not for BQ — helps eval + spec writing)
    pd.DataFrame([{"account_id": k, "archetype": v} for k, v in archetypes.items()]) \
      .to_csv(OUT_DIR / "_account_archetypes.csv", index=False)

    # Summary
    print("\n=== Summary ===")
    print(f"sales_reps:        {len(reps):>8,}")
    print(f"accounts:          {len(accounts_out):>8,}")
    print(f"contracts:         {len(contracts):>8,}")
    print(f"daily_usage_logs:  {len(usage):>8,}")

    # Archetype sanity
    arch_counts = pd.Series(archetypes).value_counts()
    print("\nArchetype counts:")
    for k, v in arch_counts.items():
        print(f"  {k:<12} {v:>4}")

    # Edge-case presence
    orphans_bad = usage[~usage.account_id.isin(accounts_out.account_id)]
    print(f"\nOrphan logs (bad account_id):  {len(orphans_bad):,}")

    # Overlapping contracts
    overlaps = 0
    for aid, g in contracts.groupby("account_id"):
        g = g.sort_values("start_date").reset_index(drop=True)
        for i in range(len(g) - 1):
            if g.loc[i, "end_date"] > g.loc[i + 1, "start_date"]:
                overlaps += 1
                break
    print(f"Accounts with overlapping contracts: {overlaps}")

    print(f"\nWrote CSVs to: {OUT_DIR}")


if __name__ == "__main__":
    main()
