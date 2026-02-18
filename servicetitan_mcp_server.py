"""
ServiceTitan MCP Server for American Leak Detection.

Exposes ServiceTitan business data to Claude Desktop via the Model Context Protocol.
All data returned is aggregated and PII-free — no customer names, addresses, or
contact details are ever sent to Claude.

Tools exposed:
  list_technicians        — list active technicians by name
  get_technician_jobs     — job counts for a technician over a date range
  get_jobs_summary        — overall job counts across all technicians

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
from query_validator import TechnicianJobQuery, TechnicianNameQuery
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
        "Use these tools to answer questions about technician jobs and business performance."
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

    # Validate and parse inputs
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
            # Step 1: Find the technician by name
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

            # Step 2: Fetch jobs for this technician in the date range
            # completedOnOrAfter / completedBefore for the completion date window
            jobs = await _fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params={
                    "technicianId": tech_id,
                    "completedOnOrAfter": f"{start.isoformat()}T00:00:00Z",
                    "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                },
                max_records=1000,
            )

        # Step 3: Aggregate — no raw job data leaves this function
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
        query = TechnicianJobQuery(
            technician_name="any",  # Not used here, but model requires it
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
                params={
                    "completedOnOrAfter": f"{start.isoformat()}T00:00:00Z",
                    "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                },
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
