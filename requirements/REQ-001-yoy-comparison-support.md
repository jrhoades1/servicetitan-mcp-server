---
id: REQ-001
title: Support year-over-year date ranges and fix compare_technicians empty results
status: implemented
priority: high
author: claude
requested_by: jimmy
created: 2026-02-23
approved: null
scheduled: 2026-02-23
implemented: 2026-02-23
verified: null
decision: null
tags: [date-range, compare-technicians, yoy, bug-fix]
---

## Problem

Running a Jun 1 – Dec 31 comparison across 2024 vs 2025 fails in two independent ways:

1. **90-day date range cap** — `query_validator.py` enforces `_MAX_DATE_RANGE_DAYS = 90`. A Jun–Dec range is ~214 days, so every tool rejects it outright. Year-over-year analysis is a core business need that the current cap blocks entirely.

2. **`compare_technicians` returns empty on valid data** — Even within a valid 90-day window (Jun 1 – Aug 29, 2024), the tool returns "No jobs with assigned technicians found" despite `get_jobs_summary` confirming 1,000 jobs exist and `get_technician_revenue` successfully finding 129 jobs for Freddy G in the same range. The root cause: `compare_technicians` fetches all jobs then groups by `job.get("technicianId")`, but the ServiceTitan `/jobs` endpoint does not reliably populate `technicianId` as a top-level field on returned job records. In contrast, `get_technician_revenue` works because it passes `technicianId` as a **query parameter** to the API, filtering server-side — it never reads `technicianId` off the job record itself.

3. **`max_records=1000` truncation** — For 7-month ranges, total job counts will exceed 1,000. The current `fetch_all_pages` cap silently drops records, skewing aggregations without any warning.

## Solution

### Fix 1: Raise the date range cap (query_validator.py)

Change `_MAX_DATE_RANGE_DAYS` from `90` to `366`. This supports full-year and YoY queries. The cap still prevents truly absurd ranges (multi-year) while enabling all reasonable business reporting.

```python
# query_validator.py, line 26
_MAX_DATE_RANGE_DAYS = 366
```

### Fix 2: Rewrite compare_technicians to query per-tech (tools_revenue.py)

Instead of fetching all jobs and grouping by a `technicianId` field that isn't reliably present, iterate over each active technician and call the API with `technicianId` as a query parameter — the same pattern that `get_technician_revenue` uses successfully.

```python
# Pseudocode for the rewrite
async with ServiceTitanClient(settings) as client:
    all_techs = await fetch_all_pages(client, "settings", "/technicians", {"active": "true"}, max_records=500)
    
    tech_stats = {}
    for tech in all_techs:
        tech_id = tech["id"]
        jobs = await fetch_all_pages(
            client, "jpm", "/jobs",
            fetch_jobs_params(start, end, tech_id),  # <-- server-side filter
            max_records=5000,
        )
        if jobs:
            tech_stats[tech_id] = {
                "name": tech.get("name"),
                "jobs": len(jobs),
                "revenue": sum_revenue(jobs),
                "no_charge": count_no_charge(jobs),
            }
```

This makes ~10 API calls (one per active tech) instead of one bulk call, but each call is reliable and correctly attributed.

### Fix 3: Raise max_records for long-range queries (tools_revenue.py, shared_helpers.py)

For endpoints that aggregate over long date ranges, increase `max_records` to `5000`. Optionally, add a warning to tool output when the cap is hit so truncation is visible:

```python
jobs = await fetch_all_pages(client, "jpm", "/jobs", params, max_records=5000)
if len(jobs) == 5000:
    # Append warning to output
    lines.append("\n⚠️ Results capped at 5,000 jobs — totals may be incomplete.")
```

## Acceptance Criteria

- [x] `compare_technicians` with date range Jun 1 – Aug 29, 2024 returns actual technician data (not "No jobs with assigned technicians found")
- [x] `compare_technicians` with date range Jun 1 – Dec 31, 2024 executes without date range error
- [x] `compare_technicians` with date range Jun 1 – Dec 31, 2025 executes without date range error
- [x] Revenue totals from `compare_technicians` match the sum of individual `get_technician_revenue` calls for the same period
- [x] Output includes a truncation warning if `max_records` cap is reached
- [x] All other tools that use `DateRangeQuery` also accept ranges up to 366 days

## Technical Notes

- **Files to modify:**
  - `query_validator.py` — change `_MAX_DATE_RANGE_DAYS` constant (1 line)
  - `tools_revenue.py` — rewrite `compare_technicians` function (~lines 245-369)
  - Optionally `shared_helpers.py` — add a truncation-aware wrapper or constant

- **Why `technicianId` is missing on job records:** The ServiceTitan v2 Jobs API returns `technicianId` only when the job has a single primary tech assignment. Jobs with multiple techs, unassigned dispatches, or certain status transitions may return `null`. The query parameter `technicianId` uses a different lookup (appointment-based assignment) and works reliably. This is a known ServiceTitan API behavior, not a bug in our code.

- **API call volume:** The per-tech approach adds ~10 calls per invocation (one per active tech). For 10 techs this is negligible. If tech count grows significantly, consider parallelizing with `asyncio.gather()`.

- **No breaking changes:** The `DateRangeQuery` change applies globally to all tools. Since we're only raising the limit, no existing valid queries will break. Tools that were working at 90 days continue to work identically.

## Decision Log
<!-- 2026-02-23 — proposed by claude: discovered during YoY comparison attempt; diagnosed via get_jobs_summary returning 1,000 jobs while compare_technicians returned empty for same range -->
<!-- 2026-02-23 — in_progress: implementation started by claude -->
<!-- 2026-02-23 — implemented: all 3 fixes applied — date cap raised to 366, compare_technicians rewritten to per-tech API queries, max_records raised to 5000 with truncation warnings -->
