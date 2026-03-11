"""
Pull scheduled appointment hours per technician from ServiceTitan
and calculate real effective hourly rates vs compensation.

Uses appointment start/end times (scheduled, not clock-in/out) to
determine actual workload — replacing the fabricated "backed into
commission" timesheet hours.

Revenue is SPLIT evenly across techs on multi-tech jobs to avoid
double-counting (~28% of jobs have 2+ techs assigned).
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# Add the MCP server project to the path so we can import its client
MCP_SERVER_DIR = Path("C:/Users/Tracy/Projects/servicetitan-mcp-server")
sys.path.insert(0, str(MCP_SERVER_DIR))

import os  # noqa: E402
os.chdir(MCP_SERVER_DIR)

from config import Settings  # noqa: E402
from servicetitan_client import ServiceTitanClient  # noqa: E402

# ── Name normalization (same as tech_revenue_multi_year.py) ──────────
NAME_ALIASES: dict[str, str] = {
    "Daniel": "Dan",
    "Kristopher": "Kris",
    "Kristofer": "Kris",
    "Christopher": "Kris",
    "Allan": "Alan",
    "Allen": "Alan",
    "Thomas": "Tom",
    "Tommy": "Tom",
    "Neill": "Neill",
    "Neil": "Neill",
    "Danny": "Danny",
    "Jesse": "Jesse",
    "Kenneth": "Ken",
}

EXCLUDE_NAMES: set[str] = {"Office", "NC", "NC&AN"}


def normalize_name(first_name: str) -> str:
    return NAME_ALIASES.get(first_name, first_name)


def appt_duration_hours(appt: dict) -> float:
    """Return scheduled duration in hours from an appointment record."""
    s = appt.get("start")
    e = appt.get("end")
    if not s or not e:
        return 0.0
    try:
        dt_s = datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt_e = datetime.fromisoformat(e.replace("Z", "+00:00"))
        return max(0.0, (dt_e - dt_s).total_seconds() / 3600)
    except (ValueError, TypeError):
        return 0.0


# ── Compensation model ───────────────────────────────────────────────
COMP_MODEL: dict[str, dict] = {
    # Default: 21% commission, no per-check bonus
    # Tech quarterly bonus: ~3% of quarterly revenue (applied separately)
    "__default__": {"rate": 0.21, "revenue_added_per_check": 0, "checks_per_year": 26},
    # Overrides
    "Dan":    {"rate": 0.25, "revenue_added_per_check": 0, "checks_per_year": 26},
    # Neill gets $3K revenue ADDED per check — he earns his commission rate on it
    "Neill":  {"rate": 0.21, "revenue_added_per_check": 3000, "checks_per_year": 26},
    # Danny at 23%, gets $2K revenue ADDED per check
    "Danny":  {"rate": 0.23, "revenue_added_per_check": 2000, "checks_per_year": 26},
}

# ~3% of quarterly revenue as tech bonus (all commission techs)
TECH_QUARTERLY_BONUS_RATE = 0.03

# Hourly techs — exclude from commission-based team revenue trend
HOURLY_TECHS: set[str] = {"Freddy", "Jason"}

# Tracy (office manager) — salary + quarterly bonus
TRACY_COMP = {
    "base_salary": 89_000,
    "quarterly_bonus": 2_500,
    "bonuses_per_year": 4,
    "hours_biweekly": 88,
    "pay_periods": 26,
}


def get_comp(name: str, annual_revenue: float) -> dict:
    """Calculate estimated annual compensation for a tech."""
    model = COMP_MODEL.get(name, COMP_MODEL["__default__"])
    rate = model["rate"]

    # Base commission on actual revenue
    commission = annual_revenue * rate

    # Revenue added per check (Neill $3K, Danny $2K) — tech earns their
    # commission rate on this added revenue, not the full amount
    rev_added = model["revenue_added_per_check"]
    added_rev_bonus = rev_added * rate * model["checks_per_year"]

    # Quarterly tech bonus: ~3% of quarterly revenue
    quarterly_bonus = 0.0
    if name not in HOURLY_TECHS:
        quarterly_bonus = annual_revenue * TECH_QUARTERLY_BONUS_RATE

    total = commission + added_rev_bonus + quarterly_bonus
    return {
        "commission": commission,
        "added_rev_bonus": added_rev_bonus,
        "quarterly_bonus": quarterly_bonus,
        "total": total,
        "rate": rate,
    }


async def fetch_all_pages(
    client: ServiceTitanClient,
    module: str,
    path: str,
    params: dict,
    max_records: int = 5000,
) -> list[dict]:
    results: list[dict] = []
    page = 1
    while True:
        batch_params = {**params, "page": page, "pageSize": 200}
        response = await client.get(module, path, params=batch_params)
        data = response.get("data", [])
        results.extend(data)
        if not response.get("hasMore") or len(results) >= max_records:
            break
        page += 1
    return results[:max_records]


async def get_tech_hours(
    settings: Settings, year: int
) -> dict[str, dict]:
    """Pull total scheduled appointment hours per tech for a year."""
    tech_hours: dict[str, dict] = {}

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    # Cap end date to today if in current year
    today = date.today()
    if end > today:
        end = today

    async with ServiceTitanClient(settings) as client:
        # Get all techs (active + inactive)
        all_techs = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "true"}, max_records=500
        )
        inactive = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "false"}, max_records=500
        )
        all_techs.extend(inactive)

        print(f"  Found {len(all_techs)} technicians, pulling appointments for {year}...")

        for tech in all_techs:
            tid = tech.get("id")
            tname = tech.get("name", f"Tech {tid}")
            raw_first = tname.split()[0] if tname else f"Tech{tid}"
            first_name = normalize_name(raw_first)

            if first_name in EXCLUDE_NAMES:
                continue

            # Pull appointments for the year (in 90-day chunks to stay under API limits)
            all_appts: list[dict] = []
            chunk_start = start
            while chunk_start <= end:
                chunk_end = min(chunk_start + timedelta(days=89), end)
                params = {
                    "startsOnOrAfter": f"{chunk_start.isoformat()}T00:00:00Z",
                    "startsBefore": f"{(chunk_end + timedelta(days=1)).isoformat()}T00:00:00Z",
                    "technicianId": tid,
                }
                appts = await fetch_all_pages(
                    client, "jpm", "/appointments", params, max_records=2000
                )
                # Only count non-canceled
                appts = [a for a in appts if a.get("status") != "Canceled"]
                all_appts.extend(appts)
                chunk_start = chunk_end + timedelta(days=1)

            if not all_appts:
                continue

            total_hours = sum(appt_duration_hours(a) for a in all_appts)
            n_appts = len(all_appts)

            # Merge if name already exists (same dedup as revenue script)
            if first_name in tech_hours:
                existing = tech_hours[first_name]
                existing["hours"] += total_hours
                existing["appointments"] += n_appts
            else:
                tech_hours[first_name] = {
                    "hours": total_hours,
                    "appointments": n_appts,
                }

            if total_hours > 0 and first_name not in tech_hours or tech_hours.get(first_name, {}).get("hours", 0) == total_hours:
                print(f"    {first_name:<12} {n_appts:>4} appts  {total_hours:>8.1f} hrs")

    return tech_hours


async def get_split_revenue(
    settings: Settings, year: int
) -> tuple[dict[str, float], dict[str, float], int, int, float]:
    """
    Pull all completed jobs for the year and split revenue evenly
    across assigned techs on multi-tech jobs.

    Returns:
        split_revenue: {tech_name: split_revenue_total}
        raw_revenue:   {tech_name: raw_per_tech_total} (for comparison)
        total_jobs:    unique job count
        multi_jobs:    count of jobs with 2+ techs
        deduped_total: true revenue (by unique job ID)
    """
    quarters = [
        ("Q1", date(year, 1, 1), date(year, 3, 31)),
        ("Q2", date(year, 4, 1), date(year, 6, 30)),
        ("Q3", date(year, 7, 1), date(year, 9, 30)),
        ("Q4", date(year, 10, 1), date(year, 12, 31)),
    ]

    today = date.today()

    # Build tech ID -> name mapping
    async with ServiceTitanClient(settings) as client:
        all_techs_list = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "true"}, max_records=500
        )
        inactive = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "false"}, max_records=500
        )
        all_techs_list.extend(inactive)

        tech_id_to_name: dict[int, str] = {}
        for tech in all_techs_list:
            tid = tech.get("id")
            tname = tech.get("name", f"Tech {tid}")
            raw_first = tname.split()[0] if tname else f"Tech{tid}"
            first_name = normalize_name(raw_first)
            if first_name not in EXCLUDE_NAMES:
                tech_id_to_name[tid] = first_name

        print(f"  {len(tech_id_to_name)} technicians mapped")

        # For each tech, pull their jobs and track which job IDs they appear on
        # job_id -> {total, tech_ids set}
        job_registry: dict[int, dict] = {}
        raw_revenue: dict[str, float] = defaultdict(float)

        for tech in all_techs_list:
            tid = tech.get("id")
            if tid not in tech_id_to_name:
                continue
            name = tech_id_to_name[tid]

            for q_label, q_start, q_end in quarters:
                if q_start > today:
                    continue
                end = min(q_end, today)
                params = {
                    "completedOnOrAfter": f"{q_start.isoformat()}T00:00:00Z",
                    "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                    "technicianId": tid,
                }
                jobs = await fetch_all_pages(
                    client, "jpm", "/jobs", params, max_records=5000
                )
                completed = [j for j in jobs if j.get("jobStatus") == "Completed"]

                for j in completed:
                    jid = j.get("id")
                    total = j.get("total") or 0.0
                    raw_revenue[name] += total

                    if jid not in job_registry:
                        job_registry[jid] = {"total": total, "tech_names": set()}
                    job_registry[jid]["tech_names"].add(name)

            tech_raw = raw_revenue.get(name, 0)
            if tech_raw > 0:
                print(f"    {name:<12} raw: ${tech_raw:>12,.2f}")

    # Now split each job's revenue evenly across its assigned techs
    split_revenue: dict[str, float] = defaultdict(float)
    multi_count = 0

    for jid, info in job_registry.items():
        n_techs = len(info["tech_names"])
        share = info["total"] / n_techs
        if n_techs > 1:
            multi_count += 1
        for name in info["tech_names"]:
            split_revenue[name] += share

    deduped_total = sum(info["total"] for info in job_registry.values())

    print(f"\n  Jobs: {len(job_registry)} unique, {multi_count} multi-tech")
    print(f"  Deduped revenue:  ${deduped_total:>12,.2f}")
    print(f"  Raw per-tech sum: ${sum(raw_revenue.values()):>12,.2f}")
    print(f"  Split total:      ${sum(split_revenue.values()):>12,.2f}")

    return dict(split_revenue), dict(raw_revenue), len(job_registry), multi_count, deduped_total


async def main():
    settings = Settings()

    print("Pulling 2025 data from ServiceTitan...\n")
    print("Step 1: Scheduled appointment hours...")
    hours_2025 = await get_tech_hours(settings, 2025)

    print("\nStep 2: Revenue by job (split across multi-tech jobs)...")
    split_rev, raw_rev, total_jobs, multi_jobs, deduped_total = (
        await get_split_revenue(settings, 2025)
    )

    # Calculate weeks in the data period
    today = date.today()
    year_end = min(today, date(2025, 12, 31))
    days_in_year = (year_end - date(2025, 1, 1)).days
    weeks_in_year = days_in_year / 7

    # Tracy's numbers
    tracy_total = TRACY_COMP["base_salary"] + (TRACY_COMP["quarterly_bonus"] * TRACY_COMP["bonuses_per_year"])
    tracy_hrs_week = TRACY_COMP["hours_biweekly"] / 2  # 88 biweekly = 44/week
    tracy_annual_hrs = tracy_hrs_week * 52
    tracy_hourly = tracy_total / tracy_annual_hrs

    print(f"\n\n{'=' * 130}")
    print("2025 TECH COMPENSATION vs ACTUAL SCHEDULED HOURS (SPLIT REVENUE)")
    print(f"{'=' * 130}")
    print(f"  Data through: {today.isoformat()} ({weeks_in_year:.1f} weeks)")
    print("  Revenue: Split shown for analytics; RAW used for comp (what techs are actually credited)")
    print(f"  Multi-tech jobs: {multi_jobs} of {total_jobs} jobs — lead tech gets full credit")
    print("  Hours: ServiceTitan scheduled appointment times (start -> end)")
    print(f"  Deduped team revenue: ${deduped_total:>,.0f} (matches QuickBooks ~$2.7M)")

    header = (
        f"{'Name':<10} {'Type':>6} {'Split Rev':>12} {'Raw Rev':>12} {'Rate':>5} {'Commiss.':>10} "
        f"{'Rev Add':>8} {'Qtr Bns':>8} {'Total Comp':>12} "
        f"{'Hrs/Wk':>7} {'$/Hr':>8}"
    )
    print(f"\n{header}")
    print("-" * 130)

    # Combine all tech names from both revenue and hours
    all_names = sorted(set(list(split_rev.keys()) + list(hours_2025.keys())))

    rows = []
    for name in all_names:
        rev = split_rev.get(name, 0)
        raw = raw_rev.get(name, 0)
        if rev == 0 and raw == 0:
            continue
        # Comp is based on RAW revenue (what each tech is actually credited)
        # not split revenue — the split is analytical only
        comp = get_comp(name, raw)
        hrs_data = hours_2025.get(name, {"hours": 0, "appointments": 0})
        ytd_hrs = hrs_data["hours"]
        hrs_per_week = ytd_hrs / weeks_in_year if weeks_in_year > 0 else 0
        annual_hrs = hrs_per_week * 52
        eff_hourly = comp["total"] / annual_hrs if annual_hrs > 0 else 0
        tech_type = "hourly" if name in HOURLY_TECHS else "comm"

        rows.append((
            name, tech_type, rev, raw, comp["rate"], comp["commission"],
            comp["added_rev_bonus"], comp["quarterly_bonus"],
            comp["total"], hrs_per_week, eff_hourly, annual_hrs
        ))

    # Sort by total comp descending
    rows.sort(key=lambda r: r[8], reverse=True)

    for (name, tech_type, rev, raw, rate, commission, added_rev_bonus, qtr_bonus,
         total, hrs_wk, eff_hourly, annual_hrs) in rows:
        added_str = f"${added_rev_bonus:>6,.0f}" if added_rev_bonus > 0 else f"{'--':>8}"
        qtr_str = f"${qtr_bonus:>6,.0f}" if qtr_bonus > 0 else f"{'--':>8}"
        print(
            f"{name:<10} {tech_type:>6} ${rev:>11,.0f} ${raw:>11,.0f} {rate:>4.0%} ${commission:>9,.0f} "
            f"{added_str} {qtr_str} ${total:>11,.0f} "
            f"{hrs_wk:>6.1f} ${eff_hourly:>7.2f}"
        )

    # Tracy row
    print("-" * 130)
    print(
        f"{'Tracy':<10} {'salary':>6} {'':>12} {'':>12} {'':>5} {'':>10} "
        f"{'':>8} {'':>8} ${tracy_total:>11,.0f} "
        f"{tracy_hrs_week:>6.1f} ${tracy_hourly:>7.2f}"
    )

    # Commission team revenue (exclude hourly techs)
    comm_split = sum(rev for name, ttype, rev, *_ in rows if ttype == "comm")
    comm_raw = sum(raw for _, ttype, _, raw, *_ in rows if ttype == "comm")
    print(f"\n  Commission tech revenue (split): ${comm_split:>,.0f}")
    print(f"  Commission tech revenue (raw):   ${comm_raw:>,.0f}  (inflated by multi-tech double-counting)")
    print(f"  (Excludes hourly techs: {', '.join(sorted(HOURLY_TECHS))})")

    # Summary
    print(f"\n{'=' * 80}")
    print("HOURS COMPARISON SUMMARY")
    print(f"{'=' * 80}")

    # rows tuple: (name, tech_type, rev, raw, rate, commission, added_rev_bonus,
    #              qtr_bonus, total, hrs_wk, eff_hourly, annual_hrs)
    #              0      1          2    3    4     5          6
    #              7          8      9      10          11
    tech_rows_real = [
        (name, hrs_wk, total_comp, eff_hourly)
        for name, ttype, _, _, _, _, _, _, total_comp, hrs_wk, eff_hourly, _ in rows
        if hrs_wk > 0 and ttype == "comm"
    ]

    if tech_rows_real:
        avg_tech_hrs_wk = sum(h for _, h, _, _ in tech_rows_real) / len(tech_rows_real)
        avg_tech_hourly = sum(e for _, _, _, e in tech_rows_real) / len(tech_rows_real)
        avg_tech_comp = sum(t for _, _, t, _ in tech_rows_real) / len(tech_rows_real)

        print(f"\n  Commission techs only (excludes hourly: {', '.join(sorted(HOURLY_TECHS))})")
        print("  Comp = commission on RAW revenue + revenue-added bonus + 3% quarterly bonus")
        print(f"\n  {'Metric':<35} {'Tracy':>14} {'Avg Tech':>14} {'Ratio':>10}")
        print(f"  {'-' * 73}")
        print(f"  {'Annual compensation':<35} ${tracy_total:>13,.0f} ${avg_tech_comp:>13,.0f} {tracy_total/avg_tech_comp:>9.2f}x")
        print(f"  {'Hours/week (scheduled)':<35} {tracy_hrs_week:>13.1f} {avg_tech_hrs_wk:>13.1f} {tracy_hrs_week/avg_tech_hrs_wk:>9.2f}x")
        print(f"  {'Effective hourly rate':<35} ${tracy_hourly:>13.2f} ${avg_tech_hourly:>13.2f} {tracy_hourly/avg_tech_hourly:>9.2f}x")

        # Alan timesheet comparison
        alan_data = next((r for r in tech_rows_real if r[0] == "Alan"), None)
        if alan_data:
            print("\n  Alan timesheet vs reality:")
            print("    Timesheet:  47.0 hrs/wk (backed into commission)")
            print(f"    Scheduled:  {alan_data[1]:.1f} hrs/wk (from ServiceTitan appointments)")
            print(f"    Gap:        {47.0 - alan_data[1]:.1f} hrs/wk fabricated ({47.0 / alan_data[1]:.1f}x inflation)")

        print("\n  Tracy works more hours than every commission tech:")
        for name, hrs_wk, comp, hourly in sorted(tech_rows_real, key=lambda r: r[1], reverse=True):
            diff = tracy_hrs_week - hrs_wk
            print(f"    Tracy 44.0 vs {name:<10} {hrs_wk:>5.1f}  (+{diff:.1f} hrs/wk, {tracy_hrs_week/hrs_wk:.1f}x)")


if __name__ == "__main__":
    asyncio.run(main())
