"""
Job management tools — list_technicians, get_technician_jobs, get_jobs_summary,
get_jobs_by_type.
"""
from __future__ import annotations

import structlog
from pydantic import ValidationError

from server_config import mcp, settings
from servicetitan_client import ServiceTitanClient
from query_validator import DateRangeQuery, TechnicianJobQuery, TechnicianNameQuery, JobsByTypeQuery
from shared_helpers import (
    fetch_all_pages,
    find_technician,
    format_date_range,
    count_jobs_by_status,
    count_no_charge,
    fmt_currency,
    fetch_jobs_params,
    fetch_appt_params,
    user_friendly_error,
)

log = structlog.get_logger(__name__)


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
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            matches = await find_technician(client, name_filter)
    except Exception as exc:
        log.error("tool.list_technicians.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"

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
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            matches = await find_technician(client, query.technician_name)

            if not matches:
                all_techs = await find_technician(client, "")
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

            jobs = await fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=fetch_jobs_params(start, end, tech_id),
                max_records=1000,
            )

        status_counts = count_jobs_by_status(jobs)
        total = sum(status_counts.values())
        date_label = format_date_range(start, end)

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
        return f"Error: {user_friendly_error(exc)}"


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
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            jobs = await fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=fetch_jobs_params(start, end),
                max_records=1000,
            )

        status_counts = count_jobs_by_status(jobs)
        total = sum(status_counts.values())
        date_label = format_date_range(start, end)

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
        return f"Error: {user_friendly_error(exc)}"


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
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            # Fetch job-type lookup
            raw_types = await fetch_all_pages(client, "jpm", "/job-types", {}, max_records=500)
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
            jobs = await fetch_all_pages(
                client, "jpm", "/jobs", fetch_jobs_params(start, end), max_records=3000
            )

            appts = await fetch_all_pages(
                client, "jpm", "/appointments", fetch_appt_params(start, end), max_records=5000
            )

            # Technician lookup
            all_techs = await fetch_all_pages(client, "settings", "/technicians", {"active": "true"}, max_records=500)
            tech_names = {t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t}

            # Business unit lookup
            raw_bus = await fetch_all_pages(client, "settings", "/business-units", {}, max_records=200)
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
                lst = job_techs.setdefault(jid, [])
                if not any(x["id"] == tid and x["role"] == entry["role"] for x in lst):
                    lst.append(entry)

        # If technician_name filter provided, resolve and require match
        tech_filter_id: int | None = None
        if query.technician_name:
            async with ServiceTitanClient(settings) as client:
                matches = await find_technician(client, query.technician_name)
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

            if tech_filter_id is not None:
                assigned = job_techs.get(job.get("id"), [])
                assigned_ids = {a["id"] for a in assigned}
                primary = job.get("technicianId")
                if tech_filter_id != primary and tech_filter_id not in assigned_ids:
                    continue

            filtered.append(job)

        # Build output lines
        date_label = format_date_range(start, end)
        header_type_name = None
        for tid in wanted_ids:
            header_type_name = type_names.get(tid)
            if header_type_name:
                break
        header_type_name = header_type_name or ", ".join(query.job_type_list())

        lines: list[str] = [f"{header_type_name} Jobs  |  {date_label}", f"{'─' * 50}"]

        tech_counter: dict[str, int] = {}
        total_revenue = 0.0

        if not filtered:
            lines.append("No matching jobs found in this date range.")
            return "\n".join(lines)

        filtered.sort(key=lambda j: j.get("completedOn") or "")

        for job in filtered:
            jid = job.get("id")
            jobnum = job.get("jobNumber") or jid
            completed = (job.get("completedOn") or "")[:10] if job.get("completedOn") else "—"
            total = job.get("total") or 0.0
            total_revenue += total
            bu = bus_names.get(job.get("businessUnitId"), "—")

            lines.append(f"Job #{jobnum}  |  {completed}  |  {fmt_currency(total)}  |  {bu}")
            techs = []
            assigned = job_techs.get(jid, [])
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

            rid = job.get("recallForId") or (job.get("relatedJob") or {}).get("id")
            if rid:
                lines.append(f"  Related job: {rid}")

            lines.append("")

        # Summary block
        total_jobs = len(filtered)
        no_charge = count_no_charge(filtered)
        lines.append("Summary:")
        lines.append(f"  total_jobs: {total_jobs}")
        lines.append(f"  total_revenue: {fmt_currency(total_revenue)}")
        lines.append(f"  no_charge_count: {no_charge}")
        if tech_counter:
            summary = "  technician_summary: " + "  |  ".join(
                f"{name}: {count}" for name, count in sorted(tech_counter.items(), key=lambda x: x[1], reverse=True)
            )
            lines.append(summary)

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_jobs_by_type.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"
