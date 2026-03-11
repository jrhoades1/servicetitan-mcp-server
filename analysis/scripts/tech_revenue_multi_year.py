"""
Pull technician revenue from ServiceTitan for 2024-2025 and combine
with 2023 data from the Excel spreadsheet for multi-year comparison.

Uses the ServiceTitan MCP server's client library directly.
"""
from __future__ import annotations

import asyncio
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

# Add the MCP server project to the path so we can import its client
MCP_SERVER_DIR = Path("C:/Users/Tracy/Projects/servicetitan-mcp-server")
sys.path.insert(0, str(MCP_SERVER_DIR))

# Change to MCP server dir so .env is found
import os  # noqa: E402
os.chdir(MCP_SERVER_DIR)

from config import Settings  # noqa: E402
from servicetitan_client import ServiceTitanClient  # noqa: E402


# ── Name normalization ────────────────────────────────────────────────
# Map variant first names from ServiceTitan to canonical names matching
# the 2023 Excel data.  Add entries here if new aliases appear.
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

# Non-technician entries to exclude from reports (office, test, combo codes)
EXCLUDE_NAMES: set[str] = {"Office", "NC", "NC&AN"}


def normalize_name(first_name: str) -> str:
    """Return the canonical tech name, merging known aliases."""
    return NAME_ALIASES.get(first_name, first_name)


# ── 2023 data from Excel ─────────────────────────────────────────────
EXCEL_2023 = {
    "Jesse":  [83337.50, 83995.00, 92467.50, 71600.00],
    "Danny":  [79232.50, 77162.50, 68411.75, 97358.50],
    "Dan":    [87756.50, 94480.00, 94567.50, 96380.00],
    "Neill":  [83987.50, 72325.00, 78102.50, 91005.00],
    "Tom":    [80957.50, 87423.00, 93575.00, 84342.50],
    "Alan":   [84202.50, 83362.50, 97236.25, 96348.75],
    "Kris":   [77045.00, 56282.50, 78782.50, 80017.50],
}

QUARTERS = [
    ("Q1", (1, 1), (3, 31)),
    ("Q2", (4, 1), (6, 30)),
    ("Q3", (7, 1), (9, 30)),
    ("Q4", (10, 1), (12, 31)),
]


async def fetch_all_pages(
    client: ServiceTitanClient,
    module: str,
    path: str,
    params: dict,
    max_records: int = 5000,
) -> list[dict]:
    """Paginate through a ServiceTitan list endpoint."""
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


async def get_tech_quarterly_revenue(
    settings: Settings, year: int
) -> dict[str, list[float]]:
    """Pull quarterly revenue for all techs for a given year."""
    tech_data: dict[str, list[float]] = {}

    async with ServiceTitanClient(settings) as client:
        # Get all active techs
        all_techs = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "true"}, max_records=500
        )
        # Also get inactive techs (they may have had jobs in prior years)
        inactive_techs = await fetch_all_pages(
            client, "settings", "/technicians", {"active": "false"}, max_records=500
        )
        all_techs.extend(inactive_techs)

        print(f"  Found {len(all_techs)} technicians (active + inactive)")

        for tech in all_techs:
            tid = tech.get("id")
            tname = tech.get("name", f"Tech {tid}")
            raw_first = tname.split()[0] if tname else f"Tech{tid}"
            first_name = normalize_name(raw_first)

            quarterly = []
            for q_label, (sm, sd), (em, ed) in QUARTERS:
                start = date(year, sm, sd)
                end = date(year, em, ed)
                params = {
                    "completedOnOrAfter": f"{start.isoformat()}T00:00:00Z",
                    "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                    "technicianId": tid,
                }
                jobs = await fetch_all_pages(
                    client, "jpm", "/jobs", params, max_records=5000
                )
                revenue = sum(j.get("total") or 0.0 for j in jobs)
                quarterly.append(revenue)

            total = sum(quarterly)
            if total > 0:
                # Merge into existing entry if another tech mapped to same name
                if first_name in tech_data:
                    existing = tech_data[first_name]
                    tech_data[first_name] = [
                        existing[i] + quarterly[i] for i in range(4)
                    ]
                    merged_total = sum(tech_data[first_name])
                    if raw_first != first_name:
                        print(f"    {raw_first:<12} -> merged into {first_name} (${merged_total:>12,.2f} combined)")
                    else:
                        print(f"    {first_name:<12} += ${total:>12,.2f} (${merged_total:>12,.2f} combined)")
                else:
                    tech_data[first_name] = quarterly
                    alias_note = f" (from {raw_first})" if raw_first != first_name else ""
                    print(f"    {first_name:<12} ${total:>12,.2f}{alias_note}")

    return tech_data


def print_year_table(year: int, data: dict[str, list[float]], all_names: list[str]):
    """Print a single year's quarterly breakdown."""
    header = f"{'Tech':<12} {'Q1':>12} {'Q2':>12} {'Q3':>12} {'Q4':>12} {'ANNUAL':>14} {'Avg/Qtr':>12}"
    print(f"\n{'=' * 95}")
    print(f"{year} TECH REVENUE")
    print(f"{'=' * 95}")
    print(header)
    print("-" * 95)

    team_q = [0.0, 0.0, 0.0, 0.0]
    tech_count = 0

    for name in all_names:
        if name not in data:
            continue
        q = data[name]
        annual = sum(q)
        avg = annual / 4
        print(f"{name:<12} ${q[0]:>11,.2f} ${q[1]:>11,.2f} ${q[2]:>11,.2f} ${q[3]:>11,.2f} ${annual:>13,.2f} ${avg:>11,.2f}")
        for i in range(4):
            team_q[i] += q[i]
        tech_count += 1

    team_total = sum(team_q)
    print("-" * 95)
    print(f"{'TEAM':<12} ${team_q[0]:>11,.2f} ${team_q[1]:>11,.2f} ${team_q[2]:>11,.2f} ${team_q[3]:>11,.2f} ${team_total:>13,.2f} ${team_total/4:>11,.2f}")
    print(f"  {tech_count} techs | Avg per tech: ${team_total/max(tech_count,1):,.2f}")


def print_yoy_comparison(all_years: dict[int, dict[str, list[float]]], all_names: list[str]):
    """Print year-over-year annual totals comparison."""
    years = sorted(all_years.keys())

    print(f"\n\n{'=' * 80}")
    print("YEAR-OVER-YEAR ANNUAL COMPARISON")
    print(f"{'=' * 80}")

    # Header
    yr_cols = "  ".join(f"{y:>14}" for y in years)
    chg_cols = "  ".join(f"{'vs ' + str(y-1):>10}" for y in years[1:])
    print(f"{'Tech':<12} {yr_cols}  {chg_cols}")
    print("-" * 80)

    team_by_year = {y: 0.0 for y in years}

    for name in all_names:
        parts = [f"{name:<12}"]
        annuals = {}
        for y in years:
            if name in all_years[y]:
                annual = sum(all_years[y][name])
                annuals[y] = annual
                team_by_year[y] += annual
                parts.append(f"${annual:>13,.0f}")
            else:
                parts.append(f"{'—':>14}")

        # YoY changes
        for i, y in enumerate(years[1:], 1):
            prev_y = years[i - 1]
            if prev_y in annuals and y in annuals and annuals[prev_y] > 0:
                chg = (annuals[y] - annuals[prev_y]) / annuals[prev_y] * 100
                parts.append(f"{chg:>+9.1f}%")
            else:
                parts.append(f"{'—':>10}")

        print("  ".join(parts))

    # Team totals
    print("-" * 80)
    parts = [f"{'TEAM':<12}"]
    for y in years:
        parts.append(f"${team_by_year[y]:>13,.0f}")
    for i, y in enumerate(years[1:], 1):
        prev_y = years[i - 1]
        if team_by_year[prev_y] > 0:
            chg = (team_by_year[y] - team_by_year[prev_y]) / team_by_year[prev_y] * 100
            parts.append(f"{chg:>+9.1f}%")
        else:
            parts.append(f"{'—':>10}")
    print("  ".join(parts))


def print_ranking(all_years: dict[int, dict[str, list[float]]], all_names: list[str]):
    """Print annual ranking per year side by side."""
    years = sorted(all_years.keys())

    print(f"\n\n{'=' * 60}")
    print("ANNUAL RANKINGS BY YEAR")
    print(f"{'=' * 60}")

    for y in years:
        data = all_years[y]
        annuals = [(n, sum(data[n])) for n in all_names if n in data and sum(data[n]) > 0]
        annuals.sort(key=lambda x: x[1], reverse=True)
        team_total = sum(a for _, a in annuals)

        print(f"\n  {y}:")
        for rank, (name, annual) in enumerate(annuals, 1):
            pct = annual / team_total * 100 if team_total > 0 else 0
            print(f"    {rank}. {name:<12} ${annual:>12,.0f}  ({pct:.1f}%)")


def print_consistency(all_years: dict[int, dict[str, list[float]]], all_names: list[str]):
    """Print consistency analysis across all years."""
    years = sorted(all_years.keys())

    print(f"\n\n{'=' * 70}")
    print("CONSISTENCY ACROSS ALL YEARS (CV = Coefficient of Variation)")
    print(f"{'=' * 70}")

    # Collect all quarterly values per tech across all years
    consistency = []
    for name in all_names:
        all_quarters = []
        for y in years:
            if name in all_years[y]:
                all_quarters.extend(all_years[y][name])
        if len(all_quarters) >= 2:
            sd = statistics.stdev(all_quarters)
            mean = statistics.mean(all_quarters)
            cv = sd / mean * 100 if mean > 0 else 0
            consistency.append((name, cv, sd, mean, len(all_quarters)))

    consistency.sort(key=lambda x: x[1])
    for name, cv, sd, mean, n_quarters in consistency:
        print(f"  {name:<12} CV: {cv:>5.1f}%  (Avg ${mean:>10,.0f} | StdDev ${sd:>8,.0f} | {n_quarters} quarters)")


async def main():
    settings = Settings()
    all_years: dict[int, dict[str, list[float]]] = {}

    # 2023 from Excel
    all_years[2023] = EXCEL_2023
    print("2023: Loaded from Excel (7 techs)")

    # 2024 from API
    print("\n2024: Pulling from ServiceTitan API...")
    all_years[2024] = await get_tech_quarterly_revenue(settings, 2024)

    # 2025 from API (partial year — only completed quarters)
    today = date.today()
    if today >= date(2025, 3, 31):
        print("\n2025: Pulling from ServiceTitan API...")
        all_years[2025] = await get_tech_quarterly_revenue(settings, 2025)
    else:
        print("\n2025: Q1 not yet complete, pulling available data...")
        all_years[2025] = await get_tech_quarterly_revenue(settings, 2025)

    # Remove non-technician entries
    for y in all_years:
        for name in EXCLUDE_NAMES:
            all_years[y].pop(name, None)

    # Collect all tech names across all years
    all_names_set: set[str] = set()
    for year_data in all_years.values():
        all_names_set.update(year_data.keys())
    all_names = sorted(all_names_set)

    # Print per-year tables
    for y in sorted(all_years.keys()):
        print_year_table(y, all_years[y], all_names)

    # YoY comparison
    print_yoy_comparison(all_years, all_names)

    # Rankings
    print_ranking(all_years, all_names)

    # Consistency
    print_consistency(all_years, all_names)

    # Pay context
    print(f"\n\n{'=' * 50}")
    print("PAY CONTEXT (From Tracy)")
    print(f"{'=' * 50}")
    print("  Tech commission model: hours 'backed into' commission")
    print("  Alan recent example: $3,033 / 47 hrs = $64.53/hr effective")
    print("  Tracy recent example: $2,463 / 88 hrs = $27.99/hr effective")
    print("  Tracy works ~1.9x Alan's hours, earns 81% of his pay")


if __name__ == "__main__":
    asyncio.run(main())
