"""
Compare Pool Division vs House Division — jobs, revenue, avg ticket.

Pool techs: Kaleb, Danny, Jason, Freddy
House techs: Dan, Tom, Kris, Neill, Alan, Jesse
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

# Division assignments
POOL_TECHS = {"Kaleb", "Danny", "Jason", "Freddy", "Frederick"}
HOUSE_TECHS = {"Dan", "Daniel", "Tom", "Thomas", "Tommy", "Kris", "Kristopher",
               "Kristofer", "Christopher", "Neill", "Neil", "Alan", "Allan", "Allen",
               "Jesse"}

NAME_MAP = {
    "Daniel": "Dan", "Kristopher": "Kris", "Kristofer": "Kris",
    "Christopher": "Kris", "Allan": "Alan", "Allen": "Alan",
    "Thomas": "Tom", "Tommy": "Tom", "Neil": "Neill",
    "Frederick": "Freddy",
}


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


async def main():
    settings = Settings()

    quarters = [
        ("Q1", date(2025, 1, 1), date(2025, 3, 31)),
        ("Q2", date(2025, 4, 1), date(2025, 6, 30)),
        ("Q3", date(2025, 7, 1), date(2025, 9, 30)),
        ("Q4", date(2025, 10, 1), date(2025, 12, 31)),
    ]

    # Structure: {tech_name: {quarter: {"jobs": int, "revenue": float}}}
    tech_quarterly = {}

    async with ServiceTitanClient(settings) as client:
        # Get all techs
        all_techs = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "true"}, max_records=500
        )
        inactive = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "false"}, max_records=500
        )
        all_techs.extend(inactive)

        print(f"Found {len(all_techs)} technicians total\n")

        for tech in all_techs:
            tid = tech.get("id")
            tname = tech.get("name", f"Tech {tid}")
            raw_first = tname.split()[0] if tname else f"Tech{tid}"
            first_name = NAME_MAP.get(raw_first, raw_first)

            # Determine division
            if raw_first in POOL_TECHS or first_name in POOL_TECHS:
                division = "Pool"
            elif raw_first in HOUSE_TECHS or first_name in HOUSE_TECHS:
                division = "House"
            else:
                division = "Other"

            for q_label, q_start, q_end in quarters:
                today = date.today()
                if q_start > today:
                    continue
                end = min(q_end, today)

                params = {
                    "completedOnOrAfter": f"{q_start.isoformat()}T00:00:00Z",
                    "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                    "technicianId": tid,
                }
                jobs = await fetch_all_pages(client, "jpm", "/jobs", params)
                completed = [j for j in jobs if j.get("jobStatus") == "Completed"]
                revenue = sum(j.get("total") or 0.0 for j in completed)
                job_count = len(completed)

                if job_count > 0:
                    key = first_name
                    if key not in tech_quarterly:
                        tech_quarterly[key] = {"division": division, "quarters": {}}
                    if q_label not in tech_quarterly[key]["quarters"]:
                        tech_quarterly[key]["quarters"][q_label] = {"jobs": 0, "revenue": 0.0}
                    tech_quarterly[key]["quarters"][q_label]["jobs"] += job_count
                    tech_quarterly[key]["quarters"][q_label]["revenue"] += revenue

            # Print progress
            total_rev = sum(
                q["revenue"] for q in tech_quarterly.get(first_name, {}).get("quarters", {}).values()
            )
            total_jobs = sum(
                q["jobs"] for q in tech_quarterly.get(first_name, {}).get("quarters", {}).values()
            )
            if total_jobs > 0:
                div = tech_quarterly.get(first_name, {}).get("division", "?")
                print(f"  {first_name:<12} [{div:<5}] {total_jobs:>5} jobs  ${total_rev:>12,.2f}")

    # -- Results ------------------------------------------------------
    print(f"\n\n{'=' * 100}")
    print("POOL vs HOUSE DIVISION COMPARISON — 2025")
    print(f"{'=' * 100}")

    for division in ["House", "Pool", "Other"]:
        div_techs = {k: v for k, v in tech_quarterly.items() if v["division"] == division}
        if not div_techs:
            continue

        print(f"\n\n{'-' * 100}")
        print(f"  {division.upper()} DIVISION")
        print(f"{'-' * 100}")

        # Per-tech table
        header = f"  {'Tech':<12} {'Q1 Jobs':>8} {'Q1 Rev':>12} {'Q2 Jobs':>8} {'Q2 Rev':>12} {'Q3 Jobs':>8} {'Q3 Rev':>12} {'Q4 Jobs':>8} {'Q4 Rev':>12} {'Annual Jobs':>11} {'Annual Rev':>14} {'Avg Ticket':>11}"
        print(header)
        print(f"  {'-' * 96}")

        div_totals = {"jobs": 0, "revenue": 0.0}

        for name in sorted(div_techs.keys()):
            data = div_techs[name]
            parts = [f"  {name:<12}"]
            annual_jobs = 0
            annual_rev = 0.0

            for q in ["Q1", "Q2", "Q3", "Q4"]:
                qd = data["quarters"].get(q, {"jobs": 0, "revenue": 0.0})
                parts.append(f"{qd['jobs']:>8}")
                parts.append(f"${qd['revenue']:>11,.0f}")
                annual_jobs += qd["jobs"]
                annual_rev += qd["revenue"]

            avg_ticket = annual_rev / annual_jobs if annual_jobs > 0 else 0
            parts.append(f"{annual_jobs:>11}")
            parts.append(f"${annual_rev:>13,.0f}")
            parts.append(f"${avg_ticket:>10,.0f}")
            print(" ".join(parts))

            div_totals["jobs"] += annual_jobs
            div_totals["revenue"] += annual_rev

        div_avg_ticket = div_totals["revenue"] / div_totals["jobs"] if div_totals["jobs"] > 0 else 0
        print(f"  {'-' * 96}")
        print(f"  {'TOTAL':<12} {'':>8} {'':>12} {'':>8} {'':>12} {'':>8} {'':>12} {'':>8} {'':>12} {div_totals['jobs']:>11} ${div_totals['revenue']:>13,.0f} ${div_avg_ticket:>10,.0f}")

    # -- Side by side comparison --------------------------------------
    print(f"\n\n{'=' * 70}")
    print("SIDE-BY-SIDE SUMMARY")
    print(f"{'=' * 70}")

    pool_data = {k: v for k, v in tech_quarterly.items() if v["division"] == "Pool"}
    house_data = {k: v for k, v in tech_quarterly.items() if v["division"] == "House"}

    pool_jobs = sum(sum(q["jobs"] for q in v["quarters"].values()) for v in pool_data.values())
    pool_rev = sum(sum(q["revenue"] for q in v["quarters"].values()) for v in pool_data.values())
    house_jobs = sum(sum(q["jobs"] for q in v["quarters"].values()) for v in house_data.values())
    house_rev = sum(sum(q["revenue"] for q in v["quarters"].values()) for v in house_data.values())

    total_jobs = pool_jobs + house_jobs
    total_rev = pool_rev + house_rev

    pool_avg = pool_rev / pool_jobs if pool_jobs > 0 else 0
    house_avg = house_rev / house_jobs if house_jobs > 0 else 0
    overall_avg = total_rev / total_jobs if total_jobs > 0 else 0

    pool_techs_count = len(pool_data)
    house_techs_count = len(house_data)

    pool_per_tech_rev = pool_rev / pool_techs_count if pool_techs_count > 0 else 0
    house_per_tech_rev = house_rev / house_techs_count if house_techs_count > 0 else 0

    pool_jobs_per_week = pool_jobs / 52
    house_jobs_per_week = house_jobs / 52

    print(f"\n  {'Metric':<30} {'Pool':>14} {'House':>14} {'Total':>14}")
    print(f"  {'-' * 72}")
    print(f"  {'Techs':<30} {pool_techs_count:>14} {house_techs_count:>14} {pool_techs_count + house_techs_count:>14}")
    print(f"  {'Total Jobs':<30} {pool_jobs:>14,} {house_jobs:>14,} {total_jobs:>14,}")
    print(f"  {'Total Revenue':<30} ${pool_rev:>13,.0f} ${house_rev:>13,.0f} ${total_rev:>13,.0f}")
    print(f"  {'Avg Ticket':<30} ${pool_avg:>13,.0f} ${house_avg:>13,.0f} ${overall_avg:>13,.0f}")
    print(f"  {'Revenue/Tech':<30} ${pool_per_tech_rev:>13,.0f} ${house_per_tech_rev:>13,.0f} {'':>14}")
    print(f"  {'Jobs/Week (total)':<30} {pool_jobs_per_week:>14.1f} {house_jobs_per_week:>14.1f} {(pool_jobs_per_week + house_jobs_per_week):>14.1f}")
    print(f"  {'Jobs/Week/Tech':<30} {pool_jobs_per_week/max(pool_techs_count,1):>14.1f} {house_jobs_per_week/max(house_techs_count,1):>14.1f} {'':>14}")
    print(f"  {'Revenue Share':<30} {pool_rev/total_rev*100:>13.1f}% {house_rev/total_rev*100:>13.1f}% {'100.0%':>14}")

    # Quarterly comparison
    print(f"\n\n{'=' * 70}")
    print("QUARTERLY REVENUE — POOL vs HOUSE")
    print(f"{'=' * 70}")
    print(f"\n  {'Quarter':<10} {'Pool Rev':>14} {'Pool Jobs':>10} {'Pool Avg':>10} {'House Rev':>14} {'House Jobs':>11} {'House Avg':>10}")
    print(f"  {'-' * 79}")

    for q in ["Q1", "Q2", "Q3", "Q4"]:
        pj = sum(v["quarters"].get(q, {}).get("jobs", 0) for v in pool_data.values())
        pr = sum(v["quarters"].get(q, {}).get("revenue", 0) for v in pool_data.values())
        hj = sum(v["quarters"].get(q, {}).get("jobs", 0) for v in house_data.values())
        hr = sum(v["quarters"].get(q, {}).get("revenue", 0) for v in house_data.values())
        pa = pr / pj if pj > 0 else 0
        ha = hr / hj if hj > 0 else 0
        print(f"  {q:<10} ${pr:>13,.0f} {pj:>10} ${pa:>9,.0f} ${hr:>13,.0f} {hj:>11} ${ha:>9,.0f}")


if __name__ == "__main__":
    asyncio.run(main())
