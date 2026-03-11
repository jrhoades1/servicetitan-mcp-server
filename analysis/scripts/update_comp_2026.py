"""
Pull 2026 YTD data from ServiceTitan to update Tracy's compensation case.
Extends the existing analysis (Jan 2024 - Dec 2025) with fresh numbers.

Outputs:
  1. Monthly avg ticket trend (Jan 2024 - present)
  2. 2026 YTD tech revenue + hours for updated comp comparison
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

MCP_SERVER_DIR = Path("C:/Users/Tracy/Projects/servicetitan-mcp-server")
sys.path.insert(0, str(MCP_SERVER_DIR))

import os  # noqa: E402
os.chdir(MCP_SERVER_DIR)

from config import Settings  # noqa: E402
from servicetitan_client import ServiceTitanClient  # noqa: E402

# ── Name normalization ────────────────────────────────────────────────
NAME_ALIASES: dict[str, str] = {
    "Daniel": "Dan", "Kristopher": "Kris", "Kristofer": "Kris",
    "Christopher": "Kris", "Allan": "Alan", "Allen": "Alan",
    "Thomas": "Tom", "Tommy": "Tom", "Neill": "Neill", "Neil": "Neill",
    "Danny": "Danny", "Jesse": "Jesse", "Kenneth": "Ken",
}
EXCLUDE_NAMES: set[str] = {"Office", "NC", "NC&AN"}
HOURLY_TECHS: set[str] = {"Freddy", "Jason"}


def normalize_name(first_name: str) -> str:
    return NAME_ALIASES.get(first_name, first_name)


# ── Compensation model ────────────────────────────────────────────────
COMP_MODEL: dict[str, dict] = {
    "__default__": {"rate": 0.21, "revenue_added_per_check": 0, "checks_per_year": 26},
    "Dan":    {"rate": 0.25, "revenue_added_per_check": 0, "checks_per_year": 26},
    "Neill":  {"rate": 0.21, "revenue_added_per_check": 3000, "checks_per_year": 26},
    "Danny":  {"rate": 0.23, "revenue_added_per_check": 2000, "checks_per_year": 26},
}
TECH_QUARTERLY_BONUS_RATE = 0.03

TRACY_COMP = {
    "base_salary": 89_000,
    "quarterly_bonus": 2_500,
    "bonuses_per_year": 4,
    "hours_biweekly": 88,
}


def get_comp(name: str, annual_revenue: float) -> dict:
    model = COMP_MODEL.get(name, COMP_MODEL["__default__"])
    rate = model["rate"]
    commission = annual_revenue * rate
    rev_added = model["revenue_added_per_check"]
    added_rev_bonus = rev_added * rate * model["checks_per_year"]
    quarterly_bonus = annual_revenue * TECH_QUARTERLY_BONUS_RATE if name not in HOURLY_TECHS else 0.0
    total = commission + added_rev_bonus + quarterly_bonus
    return {"commission": commission, "added_rev_bonus": added_rev_bonus,
            "quarterly_bonus": quarterly_bonus, "total": total, "rate": rate}


async def fetch_all_pages(client, module, path, params, max_records=5000):
    results = []
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


def appt_duration_hours(appt: dict) -> float:
    s, e = appt.get("start"), appt.get("end")
    if not s or not e:
        return 0.0
    try:
        dt_s = datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt_e = datetime.fromisoformat(e.replace("Z", "+00:00"))
        return max(0.0, (dt_e - dt_s).total_seconds() / 3600)
    except (ValueError, TypeError):
        return 0.0


async def main():
    settings = Settings()
    today = date.today()
    print(f"=== COMPENSATION UPDATE — Data through {today.isoformat()} ===\n")

    async with ServiceTitanClient(settings) as client:
        # Get all techs
        all_techs = await fetch_all_pages(client, "settings", "/technicians", {"active": "true"}, 500)
        inactive = await fetch_all_pages(client, "settings", "/technicians", {"active": "false"}, 500)
        all_techs.extend(inactive)

        tech_id_to_name = {}
        for t in all_techs:
            tid = t.get("id")
            raw = t.get("name", f"Tech {tid}").split()[0]
            name = normalize_name(raw)
            if name not in EXCLUDE_NAMES:
                tech_id_to_name[tid] = name

        print(f"Found {len(tech_id_to_name)} technicians\n")

        # ── 1. Monthly avg ticket trend (Jan 2024 → present) ─────────
        print("=" * 70)
        print("MONTHLY AVG TICKET TREND (Jan 2024 - Present)")
        print("=" * 70)
        print(f"{'Month':<12} {'Jobs':>6} {'Avg Ticket':>12} {'Tech $/Job':>12} {'vs Q1-2024':>12}")
        print("-" * 70)

        # Baseline: Q1 2024 average (from existing analysis)
        baseline_ticket = 536.0  # from existing doc

        month_start = date(2024, 1, 1)
        yearly_tickets = defaultdict(list)

        while month_start <= today:
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
            month_end = min(month_end, today)

            # Pull all completed jobs for this month (no tech filter = all jobs)
            # We need to go tech by tech since the API requires technicianId
            month_jobs = {}  # job_id -> total (dedup)
            for tid, tname in tech_id_to_name.items():
                params = {
                    "completedOnOrAfter": f"{month_start.isoformat()}T00:00:00Z",
                    "completedBefore": f"{(month_end + timedelta(days=1)).isoformat()}T00:00:00Z",
                    "technicianId": tid,
                }
                jobs = await fetch_all_pages(client, "jpm", "/jobs", params, 5000)
                for j in jobs:
                    if j.get("jobStatus") == "Completed":
                        jid = j.get("id")
                        total = j.get("total") or 0.0
                        if jid not in month_jobs:
                            month_jobs[jid] = total

            n_jobs = len(month_jobs)
            total_rev = sum(month_jobs.values())
            avg_ticket = total_rev / n_jobs if n_jobs > 0 else 0
            tech_per_job = avg_ticket * 0.24  # blended ~24% commission
            vs_baseline = ((avg_ticket - baseline_ticket) / baseline_ticket * 100) if baseline_ticket > 0 else 0

            label = month_start.strftime("%b %Y")
            yearly_tickets[month_start.year].append(avg_ticket)

            if n_jobs > 0:
                print(f"{label:<12} {n_jobs:>6} ${avg_ticket:>11,.0f} ${tech_per_job:>11,.0f} {vs_baseline:>+11.1f}%")

            # Next month
            if month_start.month == 12:
                month_start = date(month_start.year + 1, 1, 1)
            else:
                month_start = date(month_start.year, month_start.month + 1, 1)

        # Year averages
        print("-" * 70)
        for yr, tickets in sorted(yearly_tickets.items()):
            avg = sum(tickets) / len(tickets) if tickets else 0
            vs = ((avg - baseline_ticket) / baseline_ticket * 100) if baseline_ticket > 0 else 0
            print(f"  {yr} Avg: ${avg:,.0f}  ({vs:+.1f}% vs Q1 2024 baseline)")

        # ── 2. 2026 YTD tech revenue + hours ──────────────────────────
        print(f"\n\n{'=' * 100}")
        print(f"2026 YTD TECH COMPENSATION (Jan 1 - {today.isoformat()})")
        print(f"{'=' * 100}")

        ytd_start = date(2026, 1, 1)
        weeks_ytd = (today - ytd_start).days / 7

        # Revenue per tech (raw, for comp calc)
        tech_revenue: dict[str, float] = defaultdict(float)
        tech_jobs: dict[str, int] = defaultdict(int)

        for tid, tname in tech_id_to_name.items():
            params = {
                "completedOnOrAfter": f"{ytd_start.isoformat()}T00:00:00Z",
                "completedBefore": f"{(today + timedelta(days=1)).isoformat()}T00:00:00Z",
                "technicianId": tid,
            }
            jobs = await fetch_all_pages(client, "jpm", "/jobs", params, 5000)
            for j in jobs:
                if j.get("jobStatus") == "Completed":
                    total = j.get("total") or 0.0
                    tech_revenue[tname] += total
                    tech_jobs[tname] += 1

        # Hours per tech (2026 YTD)
        tech_hours: dict[str, float] = defaultdict(float)
        for tid, tname in tech_id_to_name.items():
            params = {
                "startsOnOrAfter": f"{ytd_start.isoformat()}T00:00:00Z",
                "startsBefore": f"{(today + timedelta(days=1)).isoformat()}T00:00:00Z",
                "technicianId": tid,
            }
            appts = await fetch_all_pages(client, "jpm", "/appointments", params, 2000)
            appts = [a for a in appts if a.get("status") != "Canceled"]
            tech_hours[tname] += sum(appt_duration_hours(a) for a in appts)

        # Annualize and display
        annualize_factor = 52 / weeks_ytd if weeks_ytd > 0 else 1

        print(f"\n  Data: {weeks_ytd:.1f} weeks | Annualized using {annualize_factor:.2f}x factor")
        print(f"\n  {'Name':<10} {'YTD Rev':>12} {'Ann. Rev':>12} {'Rate':>5} {'Ann. Comp':>12} {'Hrs/Wk':>8} {'$/Hr':>8}")
        print(f"  {'-' * 75}")

        tech_rows = []
        for name in sorted(set(list(tech_revenue.keys()) + list(tech_hours.keys()))):
            if name in EXCLUDE_NAMES or name in HOURLY_TECHS:
                continue
            rev = tech_revenue.get(name, 0)
            if rev == 0:
                continue
            ann_rev = rev * annualize_factor
            comp = get_comp(name, ann_rev)
            hrs = tech_hours.get(name, 0)
            hrs_wk = hrs / weeks_ytd if weeks_ytd > 0 else 0
            ann_hrs = hrs_wk * 52
            eff_hourly = comp["total"] / ann_hrs if ann_hrs > 0 else 0
            tech_rows.append((name, rev, ann_rev, comp["rate"], comp["total"], hrs_wk, eff_hourly))

        tech_rows.sort(key=lambda r: r[4], reverse=True)

        for name, rev, ann_rev, rate, total_comp, hrs_wk, eff_hourly in tech_rows:
            print(f"  {name:<10} ${rev:>11,.0f} ${ann_rev:>11,.0f} {rate:>4.0%} ${total_comp:>11,.0f} {hrs_wk:>7.1f} ${eff_hourly:>7.2f}")

        # Tracy
        tracy_total = TRACY_COMP["base_salary"] + (TRACY_COMP["quarterly_bonus"] * TRACY_COMP["bonuses_per_year"])
        tracy_hrs_wk = TRACY_COMP["hours_biweekly"] / 2
        tracy_hourly = tracy_total / (tracy_hrs_wk * 52)

        print(f"  {'-' * 75}")
        print(f"  {'Tracy':<10} {'(salary)':>12} {'':>12} {'':>5} ${tracy_total:>11,.0f} {tracy_hrs_wk:>7.1f} ${tracy_hourly:>7.2f}")

        # Averages
        if tech_rows:
            avg_comp = sum(r[4] for r in tech_rows) / len(tech_rows)
            avg_hrs = sum(r[5] for r in tech_rows) / len(tech_rows)
            avg_hourly = sum(r[6] for r in tech_rows) / len(tech_rows)

            print(f"\n  {'=' * 75}")
            print("  SUMMARY (2026 YTD, annualized)")
            print(f"  {'=' * 75}")
            print(f"  {'Metric':<35} {'Tracy':>14} {'Avg Tech':>14} {'Gap':>14}")
            print(f"  {'-' * 75}")
            print(f"  {'Annual compensation':<35} ${tracy_total:>13,.0f} ${avg_comp:>13,.0f} {'~equal' if abs(tracy_total - avg_comp) < 5000 else ''}")
            print(f"  {'Hours/week':<35} {tracy_hrs_wk:>13.1f} {avg_hrs:>13.1f} Tracy +{tracy_hrs_wk - avg_hrs:.0f}hrs")
            print(f"  {'Effective $/hour':<35} ${tracy_hourly:>13.2f} ${avg_hourly:>13.2f} Techs {avg_hourly/tracy_hourly:.1f}x more")

            # Months since last raise
            last_raise = date(2024, 8, 1)  # approximate — ~19 months as of Feb 2026
            months_since = (today.year - last_raise.year) * 12 + (today.month - last_raise.month)
            print(f"\n  Months since Tracy's last raise: ~{months_since}")
            print(f"  Estimated auto-raise per tech from pricing: ${(avg_comp * 0.048):,.0f}/yr")


if __name__ == "__main__":
    asyncio.run(main())
