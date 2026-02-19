"""
ServiceTitan MCP Server for American Leak Detection.

Exposes ServiceTitan business data to Claude Desktop via the Model Context Protocol.
All data returned is aggregated and PII-free — no customer names, addresses, or
contact details are ever sent to Claude.

Tools exposed:
  list_technicians          — list active technicians by name
  get_technician_jobs       — job counts for a technician over a date range
  get_technician_revenue    — revenue earned by a technician over a date range
  get_jobs_summary          — overall job counts across all technicians
  get_revenue_summary       — total business revenue over a date range
  get_no_charge_jobs        — count of no-charge/warranty jobs over a date range
  compare_technicians       — side-by-side jobs, revenue, and $/job for all techs
  get_technician_schedule   — appointments and scheduled hours for one technician
  compare_technician_hours  — scheduled hours and first start time for all techs
  get_revenue_trend         — avg $/job by job type or business unit, monthly trend

Run this script directly (stdio transport for Claude Desktop):
  python servicetitan_mcp_server.py

Or test the auth connection:
  python servicetitan_mcp_server.py --check
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
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
from query_validator import (
    DateRangeQuery,
    TechnicianJobQuery,
    TechnicianNameQuery,
    JobsByTypeQuery,
)
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


_SAFE_APPT_FIELDS = frozenset(
    {
        "id",
        "appointmentNumber",
        "start",              # Scheduled start time (UTC ISO string)
        "end",                # Scheduled end time (UTC ISO string)
        "arrivalWindowStart",
        "status",             # Done, Canceled, Scheduled, etc.
        "jobId",
        "active",
    }
)


def _scrub_appointment(raw: dict) -> dict:
    """Return an appointment record with PII fields removed."""
    return {k: v for k, v in raw.items() if k in _SAFE_APPT_FIELDS}


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


def _fetch_appt_params(start: date, end: date, tech_id: int | None = None) -> dict:
    """Build the standard params dict for a jpm/appointments API call."""
    params: dict = {
        "startsOnOrAfter": f"{start.isoformat()}T00:00:00Z",
        "startsBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
    }
    if tech_id is not None:
        params["technicianId"] = tech_id
    return params


def _appt_duration_hours(appt: dict) -> float:
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


def _fmt_time_utc(iso_str: str | None) -> str:
    """Format a UTC ISO timestamp as a readable clock time (UTC)."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%I:%M %p").lstrip("0") + " UTC"
    except (ValueError, TypeError):
        return "—"


def _fmt_hours(h: float) -> str:
    """Format a float hours value as e.g. '7h 30m'."""
    total_min = round(h * 60)
    hrs = total_min // 60
    mins = total_min % 60
    if hrs == 0:
        return f"{mins}m"
    if mins == 0:
        return f"{hrs}h"
    return f"{hrs}h {mins}m"


def _get_month_buckets(start: date, end: date) -> list[tuple[int, int]]:
    """Return (year, month) tuples spanning start to end inclusive."""
    buckets: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        buckets.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return buckets


def _month_label(year: int, month: int, cross_year: bool) -> str:
    """Short month label. Adds 2-digit year suffix when range crosses years."""
    label = date(year, month, 1).strftime("%b")
    return f"{label} {year % 100}" if cross_year else label


def _job_month(job: dict) -> tuple[int, int] | None:
    """Extract (year, month) from a job's completedOn field."""
    raw = job.get("completedOn") or ""
    if len(raw) < 7:
        return None
    try:
        return int(raw[:4]), int(raw[5:7])
    except (ValueError, IndexError):
        return None


def _fmt_dollar_short(amount: float) -> str:
    """Compact whole-dollar format for trend table columns."""
    return f"${amount:,.0f}"


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
async def get_jobs_by_type(
    job_types: str,
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
    status: str = "All",
) -> str:
    """
    Return individual job-level records filtered by job type, including all technicians assigned.

    Args follow the `JobsByTypeQuery` model. Returns a PII-free, human-readable list.
    """
    log.info(
        "tool.get_jobs_by_type",
        job_types=job_types,
        start_date=start_date,
        end_date=end_date,
        technician_name=technician_name,
        status=status,
    )

    try:
        query = JobsByTypeQuery(
            job_types=job_types,
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
            status=status or "All",
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(_settings) as client:
            # Fetch job-type lookup
            raw_types = await _fetch_all_pages(client, "jpm", "/job-types", {}, max_records=500)
            type_names: dict[int, str] = {t["id"]: t.get("name", f"ID {t['id']}") for t in raw_types if "id" in t}
            name_to_id = {t.get("name", "").lower(): t["id"] for t in raw_types if "id" in t}

            # Map requested names to ids
            wanted = query.job_type_list()
            wanted_ids: set[int] = set()
            missing: list[str] = []
            for wt in wanted:
                kid = name_to_id.get(wt.lower())
                if kid is None:
                    missing.append(wt)
                else:
                    wanted_ids.add(kid)

            if missing:
                sample = ", ".join(sorted(list(name_to_id.keys())[:20]))
                return (
                    f"Unknown job type(s): {', '.join(missing)}.\n"
                    f"Available job types (sample): {sample}"
                )

            # Fetch all jobs and appointments in the date range, then filter locally
            jobs = await _fetch_all_pages(
                client, "jpm", "/jobs", _fetch_jobs_params(start, end), max_records=3000
            )

            appts = await _fetch_all_pages(
                client, "jpm", "/appointments", _fetch_appt_params(start, end), max_records=5000
            )

            # Technician lookup
            all_techs = await _fetch_all_pages(client, "settings", "/technicians", {"active": "true"}, max_records=500)
            tech_names = {t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t}

            # Business unit lookup
            raw_bus = await _fetch_all_pages(client, "settings", "/business-units", {}, max_records=200)
            bus_names = {b["id"]: b.get("name", f"BU {b['id']}") for b in raw_bus if "id" in b}

        # Build jobId -> assigned technicians from appointments
        job_techs: dict[int, list[dict]] = {}
        for a in appts:
            jid = a.get("jobId")
            if jid is None:
                continue
            assigned = a.get("assignedTechnicians") or []
            for at in assigned:
                tid = at.get("technicianId")
                if tid is None:
                    continue
                entry = {
                    "id": tid,
                    "role": at.get("role") or ("Primary" if tid == a.get("technicianId") else "Added"),
                    "is_original": bool(at.get("isOriginal") or at.get("original", False)),
                }
                # avoid duplicates
                lst = job_techs.setdefault(jid, [])
                if not any(x["id"] == tid and x["role"] == entry["role"] for x in lst):
                    lst.append(entry)

        # If technician_name filter provided, resolve and require match
        tech_filter_id: int | None = None
        if query.technician_name:
            async with ServiceTitanClient(_settings) as client:
                matches = await _find_technician(client, query.technician_name)
            if not matches:
                return f'No technician found matching "{query.technician_name}".'
            if len(matches) > 1:
                names = ", ".join(t.get("name", "") for t in matches)
                return (
                    f'"{query.technician_name}" matches multiple technicians: {names}.\nPlease be more specific.'
                )
            tech_filter_id = matches[0]["id"]

        # Filter jobs by requested job types and status and technician filter
        filtered: list[dict] = []
        for job in jobs:
            if job.get("jobTypeId") not in wanted_ids:
                continue
            jstatus = job.get("jobStatus", "Unknown")
            if query.status != "All":
                if query.status == "Completed" and jstatus != "Completed":
                    continue
                if query.status == "Canceled" and jstatus != "Canceled":
                    continue

            # technician_name filter: include job if any assigned tech matches or job.technicianId matches
            if tech_filter_id is not None:
                assigned = job_techs.get(job.get("id"), [])
                assigned_ids = {a["id"] for a in assigned}
                primary = job.get("technicianId")
                if tech_filter_id != primary and tech_filter_id not in assigned_ids:
                    continue

            filtered.append(job)

        # Build output lines
        date_label = _format_date_range(start, end)
        # Use the first requested job type name (for header)
        header_type_name = None
        for tid in wanted_ids:
            header_type_name = type_names.get(tid)
            if header_type_name:
                break
        header_type_name = header_type_name or ", ".join(query.job_type_list())

        lines: list[str] = [f"{header_type_name} Jobs  |  {date_label}", f"{'─' * 50}"]

        # Technician summary counter
        tech_counter: dict[str, int] = {}
        total_revenue = 0.0

        if not filtered:
            lines.append("No matching jobs found in this date range.")
            return "\n".join(lines)

        # Sort by completedOn
        filtered.sort(key=lambda j: j.get("completedOn") or "")

        for job in filtered:
            jid = job.get("id")
            jobnum = job.get("jobNumber") or jid
            completed = (job.get("completedOn") or "")[:10] if job.get("completedOn") else "—"
            total = job.get("total") or 0.0
            total_revenue += total
            bu = bus_names.get(job.get("businessUnitId"), "—")
            jt_name = type_names.get(job.get("jobTypeId"), "—")

            lines.append(f"Job #{jobnum}  |  {completed}  |  {_fmt_currency(total)}  |  {bu}")
            techs = []
            assigned = job_techs.get(jid, [])
            # ensure primary is listed first
            primary_id = job.get("technicianId")
            if primary_id is not None and not any(a["id"] == primary_id for a in assigned):
                assigned.insert(0, {"id": primary_id, "role": "Primary", "is_original": False})

            for a in assigned:
                tid = a.get("id")
                name = tech_names.get(tid, f"Tech {tid}")
                role = a.get("role") or ("Primary" if tid == primary_id else "Added")
                is_orig = a.get("is_original", False)
                label = f"{name} ({role})"
                if is_orig:
                    label += " (Original)"
                techs.append(label)
                tech_counter[name] = tech_counter.get(name, 0) + 1

            if techs:
                lines.append(f"  Technicians: {', '.join(techs)}")
            else:
                lines.append("  Technicians: —")

            # related job id if present
            rid = job.get("relatedJobId") or (job.get("relatedJob") or {}).get("id")
            if rid:
                lines.append(f"  Related job: {rid}")

            lines.append("")

        # Summary block
        total_jobs = len(filtered)
        no_charge = _count_no_charge(filtered)
        lines.append("Summary:")
        lines.append(f"  total_jobs: {total_jobs}")
        lines.append(f"  total_revenue: {_fmt_currency(total_revenue)}")
        lines.append(f"  no_charge_count: {no_charge}")
        if tech_counter:
            summary = "  technician_summary: " + "  |  ".join(f"{name}: {count}" for name, count in sorted(tech_counter.items(), key=lambda x: x[1], reverse=True))
            lines.append(summary)

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_jobs_by_type.error", error_type=type(exc).__name__)
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


@mcp.tool()
async def get_technician_schedule(
    technician_name: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Get the appointment schedule for a specific technician over a date range.

    Shows each appointment's scheduled start time, duration, and daily totals.
    Useful for seeing when a tech starts work and how many hours they are scheduled.

    Args:
        technician_name: Full or partial technician name (e.g. "Freddy", "Freddy G").
        start_date: Start of date range in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End of date range in YYYY-MM-DD format. Defaults to last Sunday.

    Times are shown in UTC. No customer information is included.
    """
    log.info(
        "tool.get_technician_schedule",
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

            raw_appts = await _fetch_all_pages(
                client,
                module="jpm",
                path="/appointments",
                params=_fetch_appt_params(start, end, tech_id),
                max_records=500,
            )

        appts = [
            _scrub_appointment(a) for a in raw_appts
            if a.get("status") != "Canceled"
        ]
        appts.sort(key=lambda a: a.get("start") or "")

        date_label = _format_date_range(start, end)
        total_hours = sum(_appt_duration_hours(a) for a in appts)

        lines = [
            f"Schedule for {tech_name}  |  {date_label}",
            f"{'─' * 50}",
            f"Appointments:       {len(appts)}",
            f"Total scheduled:    {_fmt_hours(total_hours)}",
        ]

        if not appts:
            lines.append("\nNo appointments found in this date range.")
            return "\n".join(lines)

        # Group by day
        days: dict[str, list[dict]] = {}
        for a in appts:
            start_str = a.get("start", "")
            day_key = start_str[:10] if start_str else "Unknown"
            days.setdefault(day_key, []).append(a)

        lines.append("")
        for day_key in sorted(days):
            try:
                day_label = datetime.fromisoformat(day_key).strftime("%a %b %-d") \
                    if sys.platform != "win32" \
                    else datetime.fromisoformat(day_key).strftime("%a %b %d").replace(" 0", " ")
            except ValueError:
                day_label = day_key
            day_appts = days[day_key]
            day_hours = sum(_appt_duration_hours(a) for a in day_appts)
            lines.append(f"  {day_label}  ({_fmt_hours(day_hours)})")
            for a in day_appts:
                t_start = _fmt_time_utc(a.get("start"))
                t_end = _fmt_time_utc(a.get("end"))
                dur = _appt_duration_hours(a)
                lines.append(f"    {t_start} → {t_end}  ({_fmt_hours(dur)})")

        lines.append(f"\n(Times are UTC — scheduled, not actual clock-in/out)")
        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_schedule.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def compare_technician_hours(
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Compare scheduled hours and earliest start time across all technicians.

    Shows who is scheduled the most hours and who starts earliest.
    Makes one API call per active technician to fetch their appointments.

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to last Monday.
        end_date: End date in YYYY-MM-DD format. Defaults to last Sunday.

    Times are shown in UTC. No customer information is included.
    Note: These are scheduled appointment hours, not actual clock-in/out times.
    """
    log.info(
        "tool.compare_technician_hours",
        start_date=start_date,
        end_date=end_date,
    )

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
            # Fetch all active technicians
            all_techs_raw = await _fetch_all_pages(
                client,
                module="settings",
                path="/technicians",
                params={"active": "true"},
                max_records=500,
            )

            # For each tech, fetch their appointments in the date range
            tech_appts: dict[int, list[dict]] = {}
            for tech in all_techs_raw:
                tid = tech.get("id")
                if tid is None:
                    continue
                raw = await _fetch_all_pages(
                    client,
                    module="jpm",
                    path="/appointments",
                    params=_fetch_appt_params(start, end, tid),
                    max_records=500,
                )
                # Exclude canceled appointments
                done = [_scrub_appointment(a) for a in raw if a.get("status") != "Canceled"]
                if done:
                    tech_appts[tid] = done

        if not tech_appts:
            date_label = _format_date_range(start, end)
            return (
                f"Technician Hours Comparison  |  {date_label}\n"
                f"{'─' * 55}\n"
                "No appointments found in this date range."
            )

        # Build name lookup
        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}")
            for t in all_techs_raw
            if "id" in t
        }

        # Compute stats per tech
        rows = []
        for tid, appts in tech_appts.items():
            name = tech_names.get(tid, f"Tech {tid}")
            total_h = sum(_appt_duration_hours(a) for a in appts)
            appts_sorted = sorted(appts, key=lambda a: a.get("start") or "")
            first_start = appts_sorted[0].get("start") if appts_sorted else None
            last_end = appts_sorted[-1].get("end") if appts_sorted else None
            rows.append((name, total_h, first_start, last_end, len(appts)))

        # Sort by total scheduled hours descending
        rows.sort(key=lambda r: r[1], reverse=True)

        date_label = _format_date_range(start, end)
        name_w = max(len(r[0]) for r in rows)
        name_w = max(name_w, 12)

        header = f"{'Technician':<{name_w}}  {'Appts':>5}  {'Sched Hours':>11}  {'First Start (UTC)':>17}"
        sep = "─" * len(header)

        lines = [
            f"Technician Hours Comparison  |  {date_label}",
            sep,
            header,
            sep,
        ]

        total_appts = 0
        total_hours = 0.0

        for name, hours, first_start, last_end, n_appts in rows:
            first_fmt = _fmt_time_utc(first_start) if first_start else "—"
            lines.append(
                f"{name:<{name_w}}  {n_appts:>5}  {_fmt_hours(hours):>11}  {first_fmt:>17}"
            )
            total_appts += n_appts
            total_hours += hours

        lines.append(sep)
        lines.append(
            f"{'TOTAL':<{name_w}}  {total_appts:>5}  {_fmt_hours(total_hours):>11}"
        )
        lines.append(f"\n(Scheduled appointment hours — not actual clock-in/out)")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.compare_technician_hours.error", error_type=type(exc).__name__)
        return f"Error: {_user_friendly_error(exc)}"


@mcp.tool()
async def get_revenue_trend(
    group_by: str = "job_type",
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Show average revenue per job by category, broken down by month.

    Reveals which job types or business units are trending up or down
    in per-job revenue. Best with a wide date range (60-90 days).

    Args:
        group_by: "job_type" (e.g. CSLD, Slab Repair) or "business_unit"
                  (e.g. Slab, Pool). Defaults to "job_type".
        start_date: Start date YYYY-MM-DD. Defaults to last Monday.
        end_date: End date YYYY-MM-DD. Defaults to last Sunday.

    Monthly avg $/job is calculated from billed jobs only (no-charge excluded).
    No customer information is included.
    """
    log.info(
        "tool.get_revenue_trend",
        group_by=group_by,
        start_date=start_date,
        end_date=end_date,
    )

    if group_by not in ("job_type", "business_unit"):
        return 'Error: group_by must be "job_type" or "business_unit".'

    try:
        query = DateRangeQuery(
            start_date=start_date or None,
            end_date=end_date or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {_user_friendly_error(exc)}"

    cat_label = "Job Type" if group_by == "job_type" else "Business Unit"

    try:
        async with ServiceTitanClient(_settings) as client:
            # Fetch category lookup (only id + name used — PII fields ignored)
            if group_by == "job_type":
                raw_cats = await _fetch_all_pages(
                    client, "jpm", "/job-types", {}, max_records=200,
                )
            else:
                raw_cats = await _fetch_all_pages(
                    client, "settings", "/business-units", {}, max_records=100,
                )

            # Fetch all jobs in range
            jobs = await _fetch_all_pages(
                client, "jpm", "/jobs",
                _fetch_jobs_params(start, end),
                max_records=2000,
            )

        # Build id → name lookup (only uses id and name — no PII returned)
        cat_names: dict[int, str] = {
            c["id"]: c.get("name", f"ID {c['id']}")
            for c in raw_cats if "id" in c
        }

        cat_field = "jobTypeId" if group_by == "job_type" else "businessUnitId"
        months = _get_month_buckets(start, end)
        cross_year = len(months) > 1 and months[0][0] != months[-1][0]

        # Accumulate: {cat_id: {month: {revenue, billed, total}}}
        cat_months: dict[int, dict[tuple[int, int], dict]] = {}
        for job in jobs:
            cid = job.get(cat_field)
            if cid is None:
                continue
            month = _job_month(job)
            if month is None or month not in months:
                continue
            bucket = cat_months.setdefault(cid, {}).setdefault(
                month, {"revenue": 0.0, "billed": 0, "total": 0},
            )
            bucket["total"] += 1
            if not job.get("noCharge"):
                bucket["revenue"] += job.get("total") or 0.0
                bucket["billed"] += 1

        date_label = _format_date_range(start, end)

        if not cat_months:
            return (
                f"Revenue Trend by {cat_label}  |  {date_label}\n"
                f"{'─' * 50}\n"
                "No jobs found in this date range."
            )

        # Build rows sorted by total revenue descending
        rows: list[tuple] = []
        for cid, mdata in cat_months.items():
            name = cat_names.get(cid, f"ID {cid}")
            t_jobs = sum(m["total"] for m in mdata.values())
            t_billed = sum(m["billed"] for m in mdata.values())
            t_rev = sum(m["revenue"] for m in mdata.values())
            avg = t_rev / t_billed if t_billed > 0 else 0.0

            mavgs: list[float | None] = []
            for month in months:
                m = mdata.get(month)
                if m and m["billed"] > 0:
                    mavgs.append(m["revenue"] / m["billed"])
                else:
                    mavgs.append(None)

            # Trend: first non-None month vs last non-None month
            first_val = next((v for v in mavgs if v is not None), None)
            last_val = next((v for v in reversed(mavgs) if v is not None), None)
            change = (
                (last_val - first_val) / first_val * 100
                if first_val and last_val and first_val > 0
                else None
            )
            rows.append((name, t_jobs, t_rev, avg, mavgs, change))

        rows.sort(key=lambda r: r[2], reverse=True)

        # Grand totals per month
        grand_mavgs: list[float | None] = []
        for month in months:
            rev = sum(
                cat_months[cid].get(month, {}).get("revenue", 0)
                for cid in cat_months
            )
            billed = sum(
                cat_months[cid].get(month, {}).get("billed", 0)
                for cid in cat_months
            )
            grand_mavgs.append(rev / billed if billed > 0 else None)

        grand_jobs = sum(r[1] for r in rows)
        grand_rev = sum(r[2] for r in rows)
        grand_billed = sum(
            sum(m["billed"] for m in mdata.values())
            for mdata in cat_months.values()
        )
        grand_avg = grand_rev / grand_billed if grand_billed > 0 else 0.0
        g_first = next((v for v in grand_mavgs if v is not None), None)
        g_last = next((v for v in reversed(grand_mavgs) if v is not None), None)
        grand_change = (
            (g_last - g_first) / g_first * 100
            if g_first and g_last and g_first > 0
            else None
        )

        # Format output
        month_labels = [_month_label(y, m, cross_year) for y, m in months]
        name_w = max(len(r[0]) for r in rows)
        name_w = max(name_w, len(cat_label), 10)

        mcol_w = 8
        month_header = "  ".join(f"{ml:>{mcol_w}}" for ml in month_labels)
        header = (
            f"{cat_label:<{name_w}}  {'Jobs':>5}  {'Avg $/Job':>10}"
            f"  {month_header}  {'Change':>8}"
        )
        sep = "─" * len(header)

        lines = [
            f"Revenue per Job Trend by {cat_label}  |  {date_label}",
            sep,
            header,
            sep,
        ]

        for name, t_jobs, t_rev, avg, mavgs, change in rows:
            mcells = []
            for v in mavgs:
                mcells.append(
                    f"{_fmt_dollar_short(v):>{mcol_w}}" if v is not None
                    else f"{'—':>{mcol_w}}"
                )
            mstr = "  ".join(mcells)

            if change is not None:
                arrow = "↑" if change >= 0 else "↓"
                sign = "+" if change >= 0 else ""
                cstr = f"{arrow} {sign}{change:.0f}%"
            else:
                cstr = "—"

            lines.append(
                f"{name:<{name_w}}  {t_jobs:>5}  {_fmt_currency(avg):>10}"
                f"  {mstr}  {cstr:>8}"
            )

        # TOTAL row
        mcells = []
        for v in grand_mavgs:
            mcells.append(
                f"{_fmt_dollar_short(v):>{mcol_w}}" if v is not None
                else f"{'—':>{mcol_w}}"
            )
        mstr = "  ".join(mcells)

        if grand_change is not None:
            arrow = "↑" if grand_change >= 0 else "↓"
            sign = "+" if grand_change >= 0 else ""
            gcstr = f"{arrow} {sign}{grand_change:.0f}%"
        else:
            gcstr = "—"

        lines.append(sep)
        lines.append(
            f"{'TOTAL':<{name_w}}  {grand_jobs:>5}  {_fmt_currency(grand_avg):>10}"
            f"  {mstr}  {gcstr:>8}"
        )

        if len(months) < 2:
            lines.append(
                "\n(Only 1 month in range — use 60-90 days for meaningful trends)"
            )

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_revenue_trend.error", error_type=type(exc).__name__)
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
