"""
Show how price increases automatically raise tech pay via commission
while Tracy's salary stays flat.

Pulls monthly completed job data from ServiceTitan, deduplicates by
job ID, and tracks average ticket over time. Every increase in avg
ticket = automatic raise for commission techs.

For Tracy's meeting with Ken.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

MCP_SERVER_DIR = Path("C:/Users/Tracy/Projects/servicetitan-mcp-server")
sys.path.insert(0, str(MCP_SERVER_DIR))

import os  # noqa: E402

os.chdir(MCP_SERVER_DIR)

from config import Settings  # noqa: E402
from servicetitan_client import ServiceTitanClient  # noqa: E402

TRACY_SALARY = 89_000  # Base salary only (no quarterly bonus — apples to apples)
COMMISSION_RATE = 0.21  # Most techs; Dan 25%, Danny 23% — 21% is conservative
QUARTERLY_BONUS_RATE = 0.03  # ~3% of quarterly revenue, all commission techs
EFFECTIVE_RATE = COMMISSION_RATE + QUARTERLY_BONUS_RATE  # 24% total


async def fetch_all_pages(
    client: ServiceTitanClient,
    module: str,
    path: str,
    params: dict,
    max_records: int = 50000,
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


def month_range(start_year: int, start_month: int, end_year: int, end_month: int):
    """Yield (year, month) tuples for a range of months."""
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def month_end(year: int, month: int) -> date:
    """Last day of a given month."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


async def main():
    settings = Settings()
    today = date.today()

    # Determine range: Jan 2024 through end of 2025 (or today if before)
    end_year = 2025
    end_month = 12
    if today < date(end_year, end_month, 1):
        end_year = today.year
        end_month = today.month

    print("Pulling monthly completed jobs from ServiceTitan (Jan 2024 - Dec 2025)...\n")

    monthly_data: list[dict] = []

    async with ServiceTitanClient(settings) as client:
        for year, month in month_range(2024, 1, end_year, end_month):
            m_start = date(year, month, 1)
            m_end = month_end(year, month)

            # Don't pull future months
            if m_start > today:
                break

            # Cap to today if month isn't complete
            if m_end > today:
                m_end = today

            params = {
                "completedOnOrAfter": f"{m_start.isoformat()}T00:00:00Z",
                "completedBefore": f"{(m_end + timedelta(days=1)).isoformat()}T00:00:00Z",
            }
            jobs = await fetch_all_pages(client, "jpm", "/jobs", params)

            # Filter: completed, not no-charge, deduplicate by job ID
            seen: set[int] = set()
            job_count = 0
            total_rev = 0.0

            for j in jobs:
                if j.get("jobStatus") != "Completed":
                    continue
                jid = j.get("id")
                if jid in seen:
                    continue
                seen.add(jid)
                amount = j.get("total") or 0.0
                if amount <= 0:
                    continue
                job_count += 1
                total_rev += amount

            avg_ticket = total_rev / job_count if job_count > 0 else 0
            label = f"{date(year, month, 1):%b %Y}"

            monthly_data.append({
                "year": year,
                "month": month,
                "label": label,
                "jobs": job_count,
                "revenue": total_rev,
                "avg_ticket": avg_ticket,
            })

            print(f"  {label:<10} {job_count:>4} jobs  avg ${avg_ticket:>,.0f}")

    if not monthly_data:
        print("No data found.")
        return

    # Baseline: average of Q1 2024 (Jan-Mar) for stability
    q1_2024 = [m for m in monthly_data if m["year"] == 2024 and m["month"] <= 3]
    if q1_2024:
        baseline_ticket = sum(m["avg_ticket"] for m in q1_2024) / len(q1_2024)
    else:
        baseline_ticket = monthly_data[0]["avg_ticket"]

    baseline_earnings = baseline_ticket * EFFECTIVE_RATE

    # Recent: average of last 3 complete months
    complete_months = [m for m in monthly_data if m["jobs"] >= 50]  # skip partial months
    recent = complete_months[-3:] if len(complete_months) >= 3 else complete_months
    recent_ticket = sum(m["avg_ticket"] for m in recent) / len(recent)
    recent_earnings = recent_ticket * EFFECTIVE_RATE

    ticket_change_pct = ((recent_ticket - baseline_ticket) / baseline_ticket) * 100

    # Print the report
    print(f"\n\n{'=' * 72}")
    print("PRICE INCREASE IMPACT ON COMPENSATION")
    print(f"{'=' * 72}")
    print("  Source: ServiceTitan completed jobs (verifiable)")
    print("  Jobs deduplicated by ID, $0 / no-charge excluded")
    print("  Baseline: Q1 2024 average (Jan-Mar 2024)")
    print(f"  Tech earnings rate: {COMMISSION_RATE:.0%} commission + {QUARTERLY_BONUS_RATE:.0%} quarterly bonus = {EFFECTIVE_RATE:.0%}")
    print("  (Conservative — some techs earn 23-25% commission)")
    print("  Tracy comparison: base salary only ($89K) — bonus excluded for apples-to-apples")

    print(f"\n  {'Period':<10} {'Jobs':>6} {'Avg Ticket':>12} {'Tech $/Job':>12} {'vs Baseline':>12}")
    print(f"  {'-' * 56}")

    for m in monthly_data:
        pct = ((m["avg_ticket"] - baseline_ticket) / baseline_ticket) * 100
        earn = m["avg_ticket"] * EFFECTIVE_RATE
        pct_str = "baseline" if m["year"] == 2024 and m["month"] <= 3 else f"{pct:+.1f}%"
        print(
            f"  {m['label']:<10} {m['jobs']:>6} "
            f"${m['avg_ticket']:>10,.0f} "
            f"${earn:>10,.0f} "
            f"{pct_str:>12}"
        )

    # Annual summary
    data_2024 = [m for m in monthly_data if m["year"] == 2024]
    data_2025 = [m for m in monthly_data if m["year"] == 2025]

    if data_2024 and data_2025:
        avg_2024 = sum(m["avg_ticket"] for m in data_2024) / len(data_2024)
        avg_2025 = sum(m["avg_ticket"] for m in data_2025) / len(data_2025)
        yoy_pct = ((avg_2025 - avg_2024) / avg_2024) * 100

        total_jobs_2024 = sum(m["jobs"] for m in data_2024)
        total_jobs_2025 = sum(m["jobs"] for m in data_2025)
        total_rev_2024 = sum(m["revenue"] for m in data_2024)
        total_rev_2025 = sum(m["revenue"] for m in data_2025)

        # Annualized tech comp impact
        # If a tech did the same # of jobs but at higher prices, their pay rises
        avg_annual_jobs_per_tech = total_jobs_2024 / 8  # ~8 commission techs
        implied_raise_per_tech = avg_annual_jobs_per_tech * (avg_2025 - avg_2024) * EFFECTIVE_RATE

        print(f"\n  {'=' * 56}")
        print("  YEAR-OVER-YEAR SUMMARY")
        print(f"  {'=' * 56}")
        print(f"  {'':>26} {'2024':>12} {'2025':>12} {'Change':>10}")
        print(f"  {'-' * 56}")
        print(f"  {'Avg ticket':<26} ${avg_2024:>10,.0f} ${avg_2025:>10,.0f} {yoy_pct:>+9.1f}%")
        print(f"  {'Tech earnings/job (24%)':<26} ${avg_2024*EFFECTIVE_RATE:>10,.0f} ${avg_2025*EFFECTIVE_RATE:>10,.0f} {yoy_pct:>+9.1f}%")
        print(f"  {'Total jobs':<26} {total_jobs_2024:>11,} {total_jobs_2025:>11,}")
        print(f"  {'Total revenue':<26} ${total_rev_2024:>10,.0f} ${total_rev_2025:>10,.0f}")

    # The bottom line
    print(f"\n  {'=' * 56}")
    print("  BOTTOM LINE")
    print(f"  {'=' * 56}")
    print(f"  Avg ticket (Q1 '24 baseline -> recent):   {ticket_change_pct:+.1f}%")
    print(f"    ${baseline_ticket:>,.0f} -> ${recent_ticket:>,.0f} per job")
    print("")
    print(f"  Tech earnings per job (automatic):        {ticket_change_pct:+.1f}%")
    print(f"    ${baseline_earnings:>,.0f} -> ${recent_earnings:>,.0f} per job")
    print("    (21% commission + 3% quarterly bonus = 24% of revenue)")

    if data_2024 and data_2025:
        print("")
        print(f"  Implied raise per tech from pricing:     ${implied_raise_per_tech:>+,.0f}/yr")
        print("    (Same workload, higher prices = more pay)")

    print("")
    print("  Tracy base salary increase:                0.0%")
    print(f"    ${TRACY_SALARY:>,.0f} -> ${TRACY_SALARY:>,.0f}")
    print("")
    print("  Every price increase is an automatic raise for commission techs.")
    print("  Tracy has received no adjustment in 19+ months.")


if __name__ == "__main__":
    asyncio.run(main())
