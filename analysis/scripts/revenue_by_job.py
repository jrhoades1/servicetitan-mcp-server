"""
Pull 2025 revenue by unique job number (not per tech) to identify
double-counting from multi-tech jobs.

Compares:
  - Job-level total (deduplicated by job ID)
  - Per-tech sum (how our other scripts count it)
  - QuickBooks figure ($2.7M per Tracy)
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

MCP_SERVER_DIR = Path("C:/Users/Tracy/Projects/servicetitan-mcp-server")
sys.path.insert(0, str(MCP_SERVER_DIR))

import os  # noqa: E402
os.chdir(MCP_SERVER_DIR)

from config import Settings  # noqa: E402
from servicetitan_client import ServiceTitanClient  # noqa: E402


QB_REVENUE_2025 = 2_700_000  # Tracy's QuickBooks figure
PER_TECH_TOTAL = 3_623_902   # Our per-tech script total


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


async def main():
    settings = Settings()

    print("Pulling ALL 2025 completed jobs from ServiceTitan (by date, not by tech)...\n")

    # Pull in quarterly chunks to stay within any API limits
    quarters = [
        ("Q1", date(2025, 1, 1), date(2025, 3, 31)),
        ("Q2", date(2025, 4, 1), date(2025, 6, 30)),
        ("Q3", date(2025, 7, 1), date(2025, 9, 30)),
        ("Q4", date(2025, 10, 1), date(2025, 12, 31)),
    ]

    all_jobs: dict[int, dict] = {}  # Keyed by job ID to deduplicate
    multi_tech_jobs: dict[int, list[dict]] = defaultdict(list)  # Jobs seen more than once

    async with ServiceTitanClient(settings) as client:
        for q_label, q_start, q_end in quarters:
            today = date.today()
            if q_start > today:
                print(f"  {q_label}: Future quarter, skipping")
                continue

            end = min(q_end, today)

            # Pull jobs completed in this quarter (no tech filter)
            params = {
                "completedOnOrAfter": f"{q_start.isoformat()}T00:00:00Z",
                "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            }
            jobs = await fetch_all_pages(client, "jpm", "/jobs", params)

            completed = [j for j in jobs if j.get("jobStatus") == "Completed"]
            q_total = sum(j.get("total") or 0.0 for j in completed)

            # Deduplicate by job ID
            new_count = 0
            dup_count = 0
            for j in completed:
                jid = j.get("id")
                if jid in all_jobs:
                    dup_count += 1
                    multi_tech_jobs[jid].append(j)
                else:
                    all_jobs[jid] = j
                    new_count += 1
                    # Track first occurrence for multi-tech detection
                    multi_tech_jobs[jid].append(j)

            print(f"  {q_label}: {len(completed):>5} job records, "
                  f"{new_count} unique, {dup_count} duplicates, "
                  f"${q_total:>12,.2f} (raw sum)")

        # Now pull jobs PER TECH to see how multi-tech jobs inflate the total
        print("\n  Pulling per-tech jobs to detect multi-tech double-counting...")
        all_techs = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "true"}, max_records=500
        )
        inactive = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "false"}, max_records=500
        )
        all_techs.extend(inactive)

        per_tech_jobs: dict[int, list[dict]] = {}  # job_id -> list of tech records
        tech_names: dict[int, str] = {}
        per_tech_revenue_sum = 0.0

        for tech in all_techs:
            tid = tech.get("id")
            tname = tech.get("name", f"Tech {tid}")
            tech_names[tid] = tname

            # Pull all 2025 jobs for this tech
            tech_jobs_all: list[dict] = []
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
                tech_jobs_all.extend(completed)

            tech_total = sum(j.get("total") or 0.0 for j in tech_jobs_all)
            if tech_total > 0:
                per_tech_revenue_sum += tech_total
                for j in tech_jobs_all:
                    jid = j.get("id")
                    if jid not in per_tech_jobs:
                        per_tech_jobs[jid] = []
                    per_tech_jobs[jid].append({"tech_id": tid, "tech_name": tname, "total": j.get("total", 0)})

    # Analysis
    deduped_total = sum(j.get("total") or 0.0 for j in all_jobs.values())
    job_count = len(all_jobs)

    # Find jobs assigned to multiple techs
    multi_assigned = {jid: records for jid, records in per_tech_jobs.items() if len(records) > 1}
    double_counted_revenue = 0.0
    for jid, records in multi_assigned.items():
        job_total = all_jobs.get(jid, {}).get("total", 0)
        # Revenue is counted once per tech, so overcounting = (n_techs - 1) * job_total
        double_counted_revenue += job_total * (len(records) - 1)

    print(f"\n\n{'=' * 80}")
    print("2025 REVENUE RECONCILIATION")
    print(f"{'=' * 80}")

    print(f"\n  {'Method':<45} {'Revenue':>14} {'Jobs':>8}")
    print(f"  {'-' * 67}")
    print(f"  {'QuickBooks (Tracy)':<45} ${QB_REVENUE_2025:>13,.0f} {'':>8}")
    print(f"  {'ServiceTitan - by unique job ID':<45} ${deduped_total:>13,.0f} {job_count:>8}")
    print(f"  {'ServiceTitan - per-tech sum (our scripts)':<45} ${per_tech_revenue_sum:>13,.0f} {'':>8}")

    print(f"\n  {'Discrepancy Analysis':}")
    print(f"  {'-' * 67}")
    gap_tech_vs_job = per_tech_revenue_sum - deduped_total
    gap_job_vs_qb = deduped_total - QB_REVENUE_2025
    print(f"  {'Per-tech sum vs unique jobs (double-counting)':<45} ${gap_tech_vs_job:>+13,.0f}")
    print(f"  {'Unique jobs vs QuickBooks':<45} ${gap_job_vs_qb:>+13,.0f}")

    print("\n  Multi-tech job details:")
    print(f"  {'-' * 67}")
    print(f"  Jobs assigned to multiple techs:  {len(multi_assigned):>6}")
    print(f"  Estimated double-counted revenue:  ${double_counted_revenue:>12,.0f}")

    if multi_assigned:
        # Show top 20 biggest multi-tech jobs
        sorted_multi = sorted(
            multi_assigned.items(),
            key=lambda x: all_jobs.get(x[0], {}).get("total", 0),
            reverse=True,
        )
        print("\n  Top 20 multi-tech jobs (by revenue):")
        print(f"  {'Job ID':<12} {'Job #':<12} {'Total':>12} {'Techs':>6}  Tech Names")
        print(f"  {'-' * 75}")
        for jid, records in sorted_multi[:20]:
            job = all_jobs.get(jid, {})
            job_num = job.get("jobNumber", "?")
            total = job.get("total", 0)
            n_techs = len(records)
            names = ", ".join(r["tech_name"] for r in records)
            print(f"  {jid:<12} {job_num:<12} ${total:>11,.2f} {n_techs:>6}  {names}")

    # No-charge and status breakdown
    no_charge_count = sum(1 for j in all_jobs.values() if j.get("noCharge"))
    no_charge_total = sum(j.get("total") or 0 for j in all_jobs.values() if j.get("noCharge"))

    print("\n  Other factors:")
    print(f"  {'-' * 67}")
    print(f"  No-charge jobs:  {no_charge_count} jobs, ${no_charge_total:>,.0f} total")
    print("  (May still have a 'total' in ST but $0 invoiced in QB)")


if __name__ == "__main__":
    asyncio.run(main())
