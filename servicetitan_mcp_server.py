"""
ServiceTitan MCP Server for American Leak Detection.

Exposes ServiceTitan business data to Claude Desktop via the Model Context Protocol.
All data returned is aggregated and PII-free — no customer names, addresses, or
contact details are ever sent to Claude.

Tools exposed:
  list_technicians        — list active technicians by name
  get_technician_jobs     — job counts for a technician over a date range
  get_technician_revenue  — revenue earned by a technician over a date range
  get_jobs_summary        — overall job counts across all technicians
  get_revenue_summary     — total business revenue over a date range
  get_no_charge_jobs      — count of no-charge/warranty jobs over a date range
  compare_technicians     — side-by-side jobs, revenue, and $/job for all techs

Run this script directly (stdio transport for Claude Desktop):
  python servicetitan_mcp_server.py

Or test the auth connection:
  python servicetitan_mcp_server.py --check
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

# Load .env from the project directory regardless of where Claude Desktop
# sets the working directory when it launches this process.
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import structlog
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from config import get_settings
from logging_config import configure_logging
from query_validator import DateRangeQuery, TechnicianJobQuery, TechnicianNameQuery
from servicetitan_client import (
    ServiceTitanAPIError,
    ServiceTitanAuthError,
    ServiceTitanClient,
    ServiceTitanRateLimitError,
)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

_settings = get_settings()
# Resolve log file path relative to THIS script's directory, not cwd.
# Claude Desktop may launch this process from any working directory.
_log_file = str(Path(__file__).parent / _settings.log_file)
configure_logging(_settings.log_level, _log_file)
log = structlog.get_logger(__name__)

mcp = FastMCP(
    "ServiceTitan",
    instructions=(
        "Access ServiceTitan job management data for American Leak Detection. "
        "All responses show aggregated business metrics only — no customer PII. "
        "Use these tools to answer questions about technician jobs, revenue, and business performance."
    ),
)

# ---------------------------------------------------------------------------
# PII scrubbing — applied to every raw API record before anything is returned
# ---------------------------------------------------------------------------

_PII_JOB_FIELDS = frozenset(
    {
        "summary",          # Contains customer names and job descriptions
        "customerId",
        "locationId",
        "customerPo",
        "leadCallId",
        "partnerLeadCallId",
        "bookingId",
        "soldById",
        "externalData",
        "jobGeneratedLeadSource",
    }
)

_SAFE_JOB_FIELDS = frozenset(
    {
        "id",
        "jobNumber",
        "jobStatus",
        "completedOn",
        "businessUnitId",
        "jobTypeId",
        "technicianId",     # Internal numeric ID — not PII; used for tech grouping
        "total",
        "createdOn",
        "appointmentCount",
        "noCharge",
    }
)

_PII_TECH_FIELDS = frozenset(
    {
        "email",
        "phoneNumber",
        "mobilePhone",
        "outboundCallerId",
        "loginName",
        "home",
        "location",
        "bio",
        "memo",
        "payrollId",
        "payrollProfileId",
        "hourlyRate",
        "burdenRate",
        "commissionRate",
        "soldByRate",
        "aadUserId",
        "userId",
        "accountLocked",
        "permissions",
    }
)


def _scrub_job(raw: dict) -> dict:
    """Return a job record with all PII fields removed."""
    return {k: v for k, v in raw.items() if k in _SAFE_JOB_FIELDS}


def _scrub_technician(raw: dict) -> dict:
    """Return a technician record keeping only safe fields."""
    return {k: v for k, v in raw.items() if k not in _PII_TECH_FIELDS}


# ---------------------------------------------------------------------------
# Shared API helpers
# ---------------------------------------------------------------------------


async def _fetch_all_pages(
    client: ServiceTitanClient,
    module: str,
    path: str,
    params: dict,
    max_records: int = 1000,
) -> list[dict]:
    """
    Paginate through a ServiceTitan list endpoint, collecting all records.

    Stops at max_records to prevent runaway API usage.
    """
    results: list[dict] = []
    page = 1
    page_size = min(params.get("pageSize", 100), 200)

    while True:
        batch_params = {**params, "page": page, "pageSize": page_size}
        response = await client.get(module, path, params=batch_params)
        data = response.get("data", [])
        results.extend(data)

        if not response.get("hasMore") or len(results) >= max_records:
            break
        page += 1

    return results[:max_records]


async def _find_technician(
    client: ServiceTitanClient,
    name_fragment: str,
) -> list[dict]:
    """
    Return technicians whose name contains name_fragment (case-insensitive).

    Returns safe (PII-scrubbed) records.
    """
    all_techs = await _fetch_all_pages(
        client,
        module="settings",
        path="/technicians",
        params={"active": "true"},
        max_records=500,
    )
    needle = name_fragment.lower()
    matches = [
        _scrub_technician(t)
        for t in all_techs
        if needle in t.get("name", "").lower()
    ]
    return matches


def _format_date_range(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%B %-d, %Y") if sys.platform != "win32" else start.strftime("%B %d, %Y").lstrip("0")
    return f"{start.strftime('%b %d').lstrip('0')} – {end.strftime('%b %d, %Y').lstrip('0')}"


def _count_jobs_by_status(jobs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        status = job.get("jobStatus", "Unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _sum_revenue(jobs: list[dict]) -> float:
    """Sum the total field across all jobs. Treats None/missing as zero."""
    return sum(job.get("total") or 0.0 for job in jobs)


def _count_no_charge(jobs: list[dict]) -> int:
    """Count jobs where noCharge is True."""
    return sum(1 for job in jobs if job.get("noCharge"))


def _fmt_currency(amount: float) -> str:
    """Format a float as a dollar amount with commas."""
    return f"${amount:,.2f}"


def _user_friendly_error(exc: Exception) -> str:
    """Convert internal exceptions to helpful, non-leaking user messages."""
    if isinstance(exc, ServiceTitanRateLimitError):
        retry = f" Try again in {exc.retry_after} seconds." if exc.retry_after else ""
        return f"ServiceTitan rate limit reached.{retry}"
    if isinstance(exc, ServiceTitanAuthError):
        return "Unable to connect to ServiceTitan — authentication issue. Check credentials."
    if isinstance(exc, ServiceTitanAPIError):
        return f"ServiceTitan API error (HTTP {exc.status_code}). Please try again."
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        return f"Invalid input: {first['msg']}"
    if isinstance(exc, ValueError):
        return str(exc)
    return "An unexpected error occurred. Please try again."


def _fetch_jobs_params(start: date, end: date, tech_id: int | None = None) -> dict:
    """Build the standard params dict for a jpm/jobs API call."""
    params: dict = {
        "completedOnOrAfter": f"{start.isoformat()}T00:00:00Z",
        "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
    }
    if tech_id is not None:
        params["technicianId"] = tech_id
    return params


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_technicians(name_filter: str = "") -> str:
    """
    List active technicians at American Leak Detection.

    Args:
        name_filter: Optional partial name to search for (e.g. "Danny").
                     Leave blank to list all active technicians.

    Returns a formatted list of technician names.
    """
    log.info("tool.list_technicians", name_filter=name_filter)

    try:
        if name_filter:
            TechnicianNameQuery(name_fragment=name_filter)
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            matches = await _find_technician(client, name_filter)
    except Exception as exc:
        log.error("tool.list_technicians.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"

    if not matches:
        if name_filter:
            return f'No active technicians found matching "{name_filter}".'
        return "No active technicians found."

    lines = [f"Active technicians ({len(matches)} found):"]
    for t in sorted(matches, key=lambda x: x.get("name", "")):
        lines.append(f"  • {t.get('name', 'Unknown')}")

    return "\n".join(lines)


@mcp.tool()
async def get_technician_jobs(
    technician_name: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Get job counts for a specific technician over a date range.

    Args:
        technician_name: Full or partial technician name (e.g. "Danny", "Danny R").
        start_date: Start of date range in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End of date range in YYYY-MM-DD format. Defaults to last Sunday.

    Returns a summary of job counts broken down by status.
    No customer names or personal information is included.
    """
    log.info(
        "tool.get_technician_jobs",
        technician_name=technician_name,
        start_date=start_date,
        end_date=end_date,
    )

    try:
        query = TechnicianJobQuery(
            technician_name=technician_name,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            matches = await _find_technician(client, query.technician_name)

            if not matches:
                all_techs = await _find_technician(client, "")
                names = [t.get("name", "") for t in all_techs[:10]]
                suggestion = "\n  ".join(names)
                return (
                    f'No technician found matching "{technician_name}".\n'
                    f"Active technicians include:\n  {suggestion}"
                )

            if len(matches) > 1:
                names = ", ".join(t.get("name", "") for t in matches)
                return (
                    f'"{technician_name}" matches multiple technicians: {names}.\n'
                    f"Please be more specific."
                )

            tech = matches[0]
            tech_id = tech["id"]
            tech_name = tech.get("name", technician_name)

            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=_fetch_jobs_params(start, end, tech_id),
                max_records=1000,
            )

        status_counts = _count_jobs_by_status(jobs)
        total = sum(status_counts.values())
        date_label = _format_date_range(start, end)

        lines = [
            f"Jobs for {tech_name}  |  {date_label}",
            f"{'─' * 45}",
            f"Total jobs:  {total}",
        ]

        if status_counts:
            lines.append("")
            for status, count in status_counts.items():
                lines.append(f"  {status:<20} {count}")

        if total == 0:
            lines.append("\nNo completed jobs found in this date range.")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_jobs.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def get_technician_revenue(
    technician_name: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Get total revenue earned by a specific technician over a date range.

    Args:
        technician_name: Full or partial technician name (e.g. "Freddy", "Freddy G").
        start_date: Start of date range in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End of date range in YYYY-MM-DD format. Defaults to last Sunday.

    Returns revenue totals and job counts. No customer information is included.
    """
    log.info(
        "tool.get_technician_revenue",
        technician_name=technician_name,
        start_date=start_date,
        end_date=end_date,
    )

    try:
        query = TechnicianJobQuery(
            technician_name=technician_name,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            matches = await _find_technician(client, query.technician_name)

            if not matches:
                all_techs = await _find_technician(client, "")
                names = [t.get("name", "") for t in all_techs[:10]]
                suggestion = "\n  ".join(names)
                return (
                    f'No technician found matching "{technician_name}".\n'
                    f"Active technicians include:\n  {suggestion}"
                )

            if len(matches) > 1:
                names = ", ".join(t.get("name", "") for t in matches)
                return (
                    f'"{technician_name}" matches multiple technicians: {names}.\n'
                    f"Please be more specific."
                )

            tech = matches[0]
            tech_id = tech["id"]
            tech_name = tech.get("name", technician_name)

            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=_fetch_jobs_params(start, end, tech_id),
                max_records=1000,
            )

        total_jobs = len(jobs)
        no_charge = _count_no_charge(jobs)
        billed_jobs = total_jobs - no_charge
        revenue = _sum_revenue(jobs)
        rev_per_job = revenue / billed_jobs if billed_jobs > 0 else 0.0
        date_label = _format_date_range(start, end)

        lines = [
            f"Revenue for {tech_name}  |  {date_label}",
            f"{'─' * 45}",
            f"Total revenue:    {_fmt_currency(revenue)}",
            f"Total jobs:       {total_jobs}",
            f"  Billed:         {billed_jobs}   ({_fmt_currency(revenue)})",
            f"  No-charge:      {no_charge}",
        ]

        if billed_jobs > 0:
            lines.append(f"Revenue per job:  {_fmt_currency(rev_per_job)}")

        if total_jobs == 0:
            lines.append("\nNo completed jobs found in this date range.")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_revenue.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def get_jobs_summary(
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Get an overall jobs summary for the business over a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End date in YYYY-MM-DD format. Defaults to last Sunday.

    Returns total job counts broken down by status across all technicians.
    """
    log.info("tool.get_jobs_summary", start_date=start_date, end_date=end_date)

    try:
        query = DateRangeQuery(
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=_fetch_jobs_params(start, end),
                max_records=1000,
            )

        status_counts = _count_jobs_by_status(jobs)
        total = sum(status_counts.values())
        date_label = _format_date_range(start, end)

        lines = [
            f"Business Job Summary  |  {date_label}",
            f"{'─' * 45}",
            f"Total jobs:  {total}",
        ]

        if status_counts:
            lines.append("")
            for status, count in status_counts.items():
                lines.append(f"  {status:<20} {count}")

        if total == 0:
            lines.append("\nNo completed jobs found in this date range.")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_jobs_summary.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def get_revenue_summary(
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Get total business revenue over a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End date in YYYY-MM-DD format. Defaults to last Sunday.

    Returns total revenue, job counts, and no-charge breakdown.
    No customer information is included.
    """
    log.info("tool.get_revenue_summary", start_date=start_date, end_date=end_date)

    try:
        query = DateRangeQuery(
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=_fetch_jobs_params(start, end),
                max_records=1000,
            )

        total_jobs = len(jobs)
        no_charge = _count_no_charge(jobs)
        billed_jobs = total_jobs - no_charge
        revenue = _sum_revenue(jobs)
        date_label = _format_date_range(start, end)

        lines = [
            f"Business Revenue Summary  |  {date_label}",
            f"{'─' * 45}",
            f"Total revenue:   {_fmt_currency(revenue)}",
            f"Total jobs:      {total_jobs}",
            f"  Billed:        {billed_jobs}",
            f"  No-charge:     {no_charge}",
        ]

        if total_jobs == 0:
            lines.append("\nNo completed jobs found in this date range.")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_revenue_summary.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def get_no_charge_jobs(
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Get a count of no-charge (warranty, goodwill, or waived-fee) jobs over a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End date in YYYY-MM-DD format. Defaults to last Sunday.

    Returns the number and percentage of no-charge jobs.
    No customer information is included.
    """
    log.info("tool.get_no_charge_jobs", start_date=start_date, end_date=end_date)

    try:
        query = DateRangeQuery(
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=_fetch_jobs_params(start, end),
                max_records=1000,
            )

        total_jobs = len(jobs)
        no_charge = _count_no_charge(jobs)
        pct = (no_charge / total_jobs * 100) if total_jobs > 0 else 0.0
        date_label = _format_date_range(start, end)

        lines = [
            f"No-Charge Jobs  |  {date_label}",
            f"{'─' * 45}",
        ]

        if total_jobs == 0:
            lines.append("No completed jobs found in this date range.")
        else:
            lines.append(f"No-charge jobs:  {no_charge} of {total_jobs}  ({pct:.1f}%)")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_no_charge_jobs.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def compare_technicians(
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Compare all technicians side-by-side: jobs completed, revenue, and revenue per job.

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End date in YYYY-MM-DD format. Defaults to last Sunday.

    Shows who is working the most, who brings in the most revenue, and who
    earns the most per job. Only technicians with jobs in the period are shown.
    No customer information is included.
    """
    log.info("tool.compare_technicians", start_date=start_date, end_date=end_date)

    try:
        query = DateRangeQuery(
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            # Two API calls: all techs for name lookup, all jobs for metrics
            all_techs = await _fetch_all_pages(
                client,
                module="settings",
                path="/technicians",
                params={"active": "true"},
                max_records=500,
            )
            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=_fetch_jobs_params(start, end),
                max_records=1000,
            )

        # Build id → name lookup from technician records
        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}")
            for t in all_techs
            if "id" in t
        }

        # Group jobs by technicianId
        tech_stats: dict[int, dict] = {}
        unassigned_count = 0

        for job in jobs:
            tid = job.get("technicianId")
            if tid is None:
                unassigned_count += 1
                continue
            if tid not in tech_stats:
                tech_stats[tid] = {"jobs": 0, "revenue": 0.0, "no_charge": 0}
            tech_stats[tid]["jobs"] += 1
            tech_stats[tid]["revenue"] += job.get("total") or 0.0
            if job.get("noCharge"):
                tech_stats[tid]["no_charge"] += 1

        date_label = _format_date_range(start, end)

        if not tech_stats:
            return (
                f"Technician Comparison  |  {date_label}\n"
                f"{'─' * 55}\n"
                "No jobs with assigned technicians found in this date range."
            )

        # Sort by revenue descending
        rows = sorted(tech_stats.items(), key=lambda x: x[1]["revenue"], reverse=True)

        # Column widths
        name_w = max(len(tech_names.get(tid, f"Tech {tid}")) for tid, _ in rows)
        name_w = max(name_w, 10)

        header = f"{'Technician':<{name_w}}  {'Jobs':>5}  {'Revenue':>12}  {'$/Job':>10}  {'No-charge':>9}"
        sep = "─" * len(header)

        lines = [
            f"Technician Comparison  |  {date_label}",
            sep,
            header,
            sep,
        ]

        total_jobs = 0
        total_revenue = 0.0
        total_no_charge = 0

        for tid, stats in rows:
            name = tech_names.get(tid, f"Tech {tid}")
            j = stats["jobs"]
            rev = stats["revenue"]
            nc = stats["no_charge"]
            billed = j - nc
            rev_per_job = rev / billed if billed > 0 else 0.0

            lines.append(
                f"{name:<{name_w}}  {j:>5}  {_fmt_currency(rev):>12}  {_fmt_currency(rev_per_job):>10}  {nc:>9}"
            )

            total_jobs += j
            total_revenue += rev
            total_no_charge += nc

        total_billed = total_jobs - total_no_charge
        total_rev_per_job = total_revenue / total_billed if total_billed > 0 else 0.0

        lines.append(sep)
        lines.append(
            f"{'TOTAL':<{name_w}}  {total_jobs:>5}  {_fmt_currency(total_revenue):>12}  {_fmt_currency(total_rev_per_job):>10}  {total_no_charge:>9}"
        )

        if unassigned_count:
            lines.append(f"\n({unassigned_count} jobs had no assigned technician and are excluded)")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.compare_technicians.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        # Quick connectivity check — useful before adding to Claude Desktop
        async def _check() -> None:
            log.info("startup.checking_connection")
            async with ServiceTitanClient(_settings) as client:
                await client.ensure_authenticated()
            print("Connection OK — ServiceTitan authentication successful.")
            print("You can now add this server to Claude Desktop.")

        asyncio.run(_check())
    else:
        log.info("startup.starting_mcp_server")
        mcp.run(transport="stdio")
