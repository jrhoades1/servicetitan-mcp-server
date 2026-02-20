"""
Shared helpers for MCP tool modules.

Contains:
  - PII field definitions and scrub functions
  - Pagination helper (_fetch_all_pages)
  - Technician lookup (_find_technician)
  - Date/time formatting utilities
  - Revenue and job-count aggregation helpers
  - User-friendly error formatting

All tool modules import from here. No tool-specific logic belongs in this file.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import structlog
from pydantic import ValidationError

from server_config import settings
from servicetitan_client import (
    ServiceTitanAPIError,
    ServiceTitanAuthError,
    ServiceTitanClient,
    ServiceTitanRateLimitError,
)

log = structlog.get_logger(__name__)

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
        "recallForId",      # Internal numeric job ID — links GO BACKs to originals
        "invoiceId",        # Internal numeric invoice ID — for discount linkage
        "tagTypeIds",       # Tag IDs — used for cancel reason proxy
        "firstAppointmentId",  # Used for cancel timing calculation
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


def scrub_job(raw: dict) -> dict:
    """Return a job record with all PII fields removed."""
    return {k: v for k, v in raw.items() if k in _SAFE_JOB_FIELDS}


def scrub_technician(raw: dict) -> dict:
    """Return a technician record keeping only safe fields."""
    return {k: v for k, v in raw.items() if k not in _PII_TECH_FIELDS}


def scrub_appointment(raw: dict) -> dict:
    """Return an appointment record with PII fields removed."""
    return {k: v for k, v in raw.items() if k in _SAFE_APPT_FIELDS}


# ---------------------------------------------------------------------------
# Shared API helpers
# ---------------------------------------------------------------------------


async def fetch_all_pages(
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


async def find_technician(
    client: ServiceTitanClient,
    name_fragment: str,
) -> list[dict]:
    """
    Return technicians whose name contains name_fragment (case-insensitive).

    Returns safe (PII-scrubbed) records.
    """
    all_techs = await fetch_all_pages(
        client,
        module="settings",
        path="/technicians",
        params={"active": "true"},
        max_records=500,
    )
    needle = name_fragment.lower()
    matches = [
        scrub_technician(t)
        for t in all_techs
        if needle in t.get("name", "").lower()
    ]
    return matches


# ---------------------------------------------------------------------------
# Date / time formatting
# ---------------------------------------------------------------------------


def format_date_range(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%B %-d, %Y") if sys.platform != "win32" else start.strftime("%B %d, %Y").lstrip("0")
    return f"{start.strftime('%b %d').lstrip('0')} – {end.strftime('%b %d, %Y').lstrip('0')}"


def fmt_currency(amount: float) -> str:
    """Format a float as a dollar amount with commas."""
    return f"${amount:,.2f}"


def fmt_hours(h: float) -> str:
    """Format a float hours value as e.g. '7h 30m'."""
    total_min = round(h * 60)
    hrs = total_min // 60
    mins = total_min % 60
    if hrs == 0:
        return f"{mins}m"
    if mins == 0:
        return f"{hrs}h"
    return f"{hrs}h {mins}m"


def fmt_time_utc(iso_str: str | None) -> str:
    """Format a UTC ISO timestamp as a readable clock time (UTC)."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%I:%M %p").lstrip("0") + " UTC"
    except (ValueError, TypeError):
        return "—"


def fmt_dollar_short(amount: float) -> str:
    """Compact whole-dollar format for trend table columns."""
    return f"${amount:,.0f}"


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


# ---------------------------------------------------------------------------
# Revenue / job count aggregation
# ---------------------------------------------------------------------------


def count_jobs_by_status(jobs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        status = job.get("jobStatus", "Unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def sum_revenue(jobs: list[dict]) -> float:
    """Sum the total field across all jobs. Treats None/missing as zero."""
    return sum(job.get("total") or 0.0 for job in jobs)


def count_no_charge(jobs: list[dict]) -> int:
    """Count jobs where noCharge is True."""
    return sum(1 for job in jobs if job.get("noCharge"))


# ---------------------------------------------------------------------------
# Parameter builders
# ---------------------------------------------------------------------------


def fetch_jobs_params(start: date, end: date, tech_id: int | None = None) -> dict:
    """Build the standard params dict for a jpm/jobs API call."""
    params: dict = {
        "completedOnOrAfter": f"{start.isoformat()}T00:00:00Z",
        "completedBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
    }
    if tech_id is not None:
        params["technicianId"] = tech_id
    return params


def fetch_appt_params(start: date, end: date, tech_id: int | None = None) -> dict:
    """Build the standard params dict for a jpm/appointments API call."""
    params: dict = {
        "startsOnOrAfter": f"{start.isoformat()}T00:00:00Z",
        "startsBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
    }
    if tech_id is not None:
        params["technicianId"] = tech_id
    return params


# ---------------------------------------------------------------------------
# Revenue trend helpers
# ---------------------------------------------------------------------------


def get_month_buckets(start: date, end: date) -> list[tuple[int, int]]:
    """Return (year, month) tuples spanning start to end inclusive."""
    buckets: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        buckets.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return buckets


def month_label(year: int, month: int, cross_year: bool) -> str:
    """Short month label. Adds 2-digit year suffix when range crosses years."""
    label = date(year, month, 1).strftime("%b")
    return f"{label} {year % 100}" if cross_year else label


def job_month(job: dict) -> tuple[int, int] | None:
    """Extract (year, month) from a job's completedOn field."""
    raw = job.get("completedOn") or ""
    if len(raw) < 7:
        return None
    try:
        return int(raw[:4]), int(raw[5:7])
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


def user_friendly_error(exc: Exception) -> str:
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
