"""
Analysis tools — get_technician_job_mix, compare_technician_job_mix,
get_cancellations, get_technician_discounts.

These tools provide deeper operational insights beyond basic job counts
and revenue totals. They answer questions about job type distribution,
cancellation patterns, and discount/credit behavior.
"""
from __future__ import annotations

from datetime import datetime

import structlog
from pydantic import ValidationError

from server_config import mcp, settings
from servicetitan_client import ServiceTitanClient
from query_validator import (
    TechnicianJobQuery,
    JobMixCompareQuery,
    CancellationQuery,
    DiscountQuery,
)
from shared_helpers import (
    fetch_all_pages,
    find_technician,
    format_date_range,
    count_no_charge,
    sum_revenue,
    fmt_currency,
    fetch_jobs_params,
    fetch_appt_params,
    user_friendly_error,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool 12: get_technician_job_mix
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_technician_job_mix(
    technician_name: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    Break down a technician's jobs by job type, showing count, revenue,
    and avg $/job for each type. Explains why some techs have lower $/job —
    is it their job mix or their pricing within a type?

    Args:
        technician_name: Full or partial technician name (e.g. "Freddy G").
        start_date: Start date YYYY-MM-DD. Defaults to last Monday.
        end_date: End date YYYY-MM-DD. Defaults to last Sunday.

    No customer information is included.
    """
    log.info(
        "tool.get_technician_job_mix",
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
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end, tech_id),
                max_records=1000,
            )

            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )

        type_names: dict[int, str] = {
            t["id"]: t.get("name", f"ID {t['id']}") for t in raw_types if "id" in t
        }

        # Group jobs by jobTypeId
        type_stats: dict[int, dict] = {}
        for job in jobs:
            jtid = job.get("jobTypeId")
            if jtid is None:
                continue
            if jtid not in type_stats:
                type_stats[jtid] = {"jobs": 0, "billed": 0, "no_charge": 0, "revenue": 0.0}
            s = type_stats[jtid]
            s["jobs"] += 1
            if job.get("noCharge"):
                s["no_charge"] += 1
            else:
                s["billed"] += 1
                s["revenue"] += job.get("total") or 0.0

        date_label = format_date_range(start, end)
        total_jobs = len(jobs)
        total_revenue = sum_revenue(jobs)

        if not type_stats:
            return (
                f"Job Mix for {tech_name}  |  {date_label}\n"
                f"{'─' * 50}\n"
                "No jobs found in this date range."
            )

        # Sort by total_jobs descending
        rows = sorted(type_stats.items(), key=lambda x: x[1]["jobs"], reverse=True)

        # Build table
        name_w = max(len(type_names.get(tid, f"ID {tid}")) for tid, _ in rows)
        name_w = max(name_w, 10)

        header = (
            f"{'Job Type':<{name_w}}  {'Jobs':>5}  {'Billed':>6}  {'No-Chg':>6}"
            f"  {'Revenue':>10}  {'Avg $/Job':>9}  {'% Jobs':>6}  {'% Rev':>6}"
        )
        sep = "─" * len(header)

        lines = [
            f"Job Mix for {tech_name}  |  {date_label}",
            sep,
            header,
            sep,
        ]

        for jtid, s in rows:
            name = type_names.get(jtid, f"ID {jtid}")
            avg = s["revenue"] / s["billed"] if s["billed"] > 0 else 0.0
            pct_jobs = (s["jobs"] / total_jobs * 100) if total_jobs > 0 else 0.0
            pct_rev = (s["revenue"] / total_revenue * 100) if total_revenue > 0 else 0.0

            lines.append(
                f"{name:<{name_w}}  {s['jobs']:>5}  {s['billed']:>6}  {s['no_charge']:>6}"
                f"  {fmt_currency(s['revenue']):>10}  {fmt_currency(avg):>9}  {pct_jobs:>5.1f}%  {pct_rev:>5.1f}%"
            )

        # Summary
        total_billed = total_jobs - count_no_charge(jobs)
        overall_avg = total_revenue / total_billed if total_billed > 0 else 0.0
        unique_types = len(type_stats)

        top_volume = max(rows, key=lambda x: x[1]["jobs"])
        top_rev = max(rows, key=lambda x: x[1]["revenue"])

        lines.append(sep)
        lines.append(f"Summary:")
        lines.append(f"  {total_jobs} total jobs  |  {total_billed} billed  |  {total_jobs - total_billed} no-charge")
        lines.append(f"  {fmt_currency(total_revenue)} total revenue  |  {fmt_currency(overall_avg)} avg/billed job")
        lines.append(f"  {unique_types} unique job types")
        lines.append(f"  Top by volume: {type_names.get(top_volume[0], '?')} ({top_volume[1]['jobs']})")
        lines.append(f"  Top by revenue: {type_names.get(top_rev[0], '?')} ({fmt_currency(top_rev[1]['revenue'])})")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_job_mix.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


# ---------------------------------------------------------------------------
# Tool 13: compare_technician_job_mix
# ---------------------------------------------------------------------------


@mcp.tool()
async def compare_technician_job_mix(
    start_date: str = "",
    end_date: str = "",
    job_type: str = "",
) -> str:
    """
    Compare all technicians' job type distribution side-by-side.

    Shows which techs handle which types of work and their relative revenue
    performance within each type. Reveals if high-value job types are
    concentrated on certain techs.

    Args:
        start_date: Start date YYYY-MM-DD. Defaults to last Monday.
        end_date: End date YYYY-MM-DD. Defaults to last Sunday.
        job_type: Optional — filter to compare all techs within a single job type.
                  Omit for the full matrix.

    No customer information is included.
    """
    log.info(
        "tool.compare_technician_job_mix",
        start_date=start_date,
        end_date=end_date,
        job_type=job_type,
    )

    try:
        query = JobMixCompareQuery(
            start_date=start_date or None,
            end_date=end_date or None,
            job_type=job_type or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end), max_records=2000,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )

        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
        }
        type_names: dict[int, str] = {
            t["id"]: t.get("name", f"ID {t['id']}") for t in raw_types if "id" in t
        }

        # If job_type filter specified, resolve to ID
        filter_type_id: int | None = None
        if query.job_type:
            name_to_id = {t.get("name", "").lower(): t["id"] for t in raw_types if "id" in t}
            filter_type_id = name_to_id.get(query.job_type.lower())
            if filter_type_id is None:
                sample = ", ".join(sorted(list(name_to_id.keys())[:20]))
                return (
                    f'Unknown job type: "{query.job_type}".\n'
                    f"Available job types (sample): {sample}"
                )

        # Build: {jobTypeId: {techId: {jobs, revenue, billed}}}
        matrix: dict[int, dict[int, dict]] = {}
        for job in jobs:
            jtid = job.get("jobTypeId")
            tid = job.get("technicianId")
            if jtid is None or tid is None:
                continue
            if filter_type_id is not None and jtid != filter_type_id:
                continue

            cell = matrix.setdefault(jtid, {}).setdefault(
                tid, {"jobs": 0, "revenue": 0.0, "billed": 0}
            )
            cell["jobs"] += 1
            if not job.get("noCharge"):
                cell["billed"] += 1
                cell["revenue"] += job.get("total") or 0.0

        date_label = format_date_range(start, end)

        if not matrix:
            return (
                f"Technician Job Mix Comparison  |  {date_label}\n"
                f"{'─' * 55}\n"
                "No jobs found in this date range."
            )

        # Find techs that appear in the data
        active_tech_ids = set()
        for type_data in matrix.values():
            active_tech_ids.update(type_data.keys())

        # Sort techs by total revenue descending
        tech_totals: dict[int, float] = {}
        for type_data in matrix.values():
            for tid, cell in type_data.items():
                tech_totals[tid] = tech_totals.get(tid, 0) + cell["revenue"]
        sorted_tech_ids = sorted(active_tech_ids, key=lambda t: tech_totals.get(t, 0), reverse=True)

        # Sort job types by total jobs descending
        type_totals: dict[int, int] = {}
        for jtid, type_data in matrix.items():
            type_totals[jtid] = sum(c["jobs"] for c in type_data.values())
        sorted_type_ids = sorted(matrix.keys(), key=lambda j: type_totals.get(j, 0), reverse=True)

        # Build output
        # Column format: "count/$avg" or "count" for no-charge types
        type_w = max(len(type_names.get(j, "?")) for j in sorted_type_ids)
        type_w = max(type_w, 10)
        tech_col_w = 14  # enough for "52/$478"

        # Header row
        tech_headers = [f"{tech_names.get(tid, '?')[:12]:>{tech_col_w}}" for tid in sorted_tech_ids]
        header = f"{'Job Type':<{type_w}}  {'Co. Avg':>{tech_col_w}}  " + "  ".join(tech_headers)
        sep = "─" * len(header)

        lines = [
            f"Technician Job Mix Comparison  |  {date_label}",
            sep,
            header,
            sep,
        ]

        for jtid in sorted_type_ids:
            type_data = matrix[jtid]
            tname = type_names.get(jtid, f"ID {jtid}")

            # Company average for this type
            co_jobs = sum(c["jobs"] for c in type_data.values())
            co_billed = sum(c["billed"] for c in type_data.values())
            co_rev = sum(c["revenue"] for c in type_data.values())
            co_avg = co_rev / co_billed if co_billed > 0 else 0.0

            if co_billed > 0:
                co_cell = f"{co_jobs}/${co_avg:,.0f}"
            else:
                co_cell = str(co_jobs)

            tech_cells = []
            for tid in sorted_tech_ids:
                cell = type_data.get(tid)
                if cell is None:
                    tech_cells.append(f"{'—':>{tech_col_w}}")
                elif cell["billed"] > 0:
                    t_avg = cell["revenue"] / cell["billed"]
                    # Show variance from company avg
                    if co_avg > 0:
                        var_pct = (t_avg - co_avg) / co_avg * 100
                        sign = "+" if var_pct >= 0 else ""
                        tech_cells.append(f"{cell['jobs']}/${t_avg:,.0f}({sign}{var_pct:.0f}%)".rjust(tech_col_w))
                    else:
                        tech_cells.append(f"{cell['jobs']}/${t_avg:,.0f}".rjust(tech_col_w))
                else:
                    tech_cells.append(f"{cell['jobs']:>{tech_col_w}}")

            line = f"{tname:<{type_w}}  {co_cell:>{tech_col_w}}  " + "  ".join(tech_cells)
            lines.append(line)

        lines.append(sep)

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.compare_technician_job_mix.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


# ---------------------------------------------------------------------------
# Tool 14: get_cancellations
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_cancellations(
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
    late_only: bool = False,
) -> str:
    """
    Show canceled jobs with timing, assigned technician, and tags.

    Tracks cancel rates, late cancels (within 24h of appointment), and
    patterns by technician. Cancellations represent lost revenue and
    wasted dispatch capacity.

    Args:
        start_date: Start date YYYY-MM-DD. Defaults to last Monday.
        end_date: End date YYYY-MM-DD. Defaults to last Sunday.
        technician_name: Optional filter by assigned tech.
        late_only: If true, only show cancellations within 24 hours of appointment.

    No customer information is included. Tags shown as cancel reason proxy.
    """
    log.info(
        "tool.get_cancellations",
        start_date=start_date,
        end_date=end_date,
        technician_name=technician_name,
        late_only=late_only,
    )

    try:
        query = CancellationQuery(
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
            late_only=late_only,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            # Fetch all jobs and appointments in range
            all_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end), max_records=2000,
            )
            all_appts = await fetch_all_pages(
                client, "jpm", "/appointments",
                fetch_appt_params(start, end), max_records=5000,
            )
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )
            # Tag types for cancel reason proxy
            raw_tags = await fetch_all_pages(
                client, "settings", "/tag-types", {}, max_records=500,
            )

        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
        }
        type_names: dict[int, str] = {
            t["id"]: t.get("name", f"ID {t['id']}") for t in raw_types if "id" in t
        }
        tag_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tag {t['id']}") for t in raw_tags if "id" in t
        }

        # Build jobId -> earliest appointment start
        job_appt_start: dict[int, str] = {}
        for a in all_appts:
            jid = a.get("jobId")
            appt_start = a.get("start")
            if jid is None or not appt_start:
                continue
            existing = job_appt_start.get(jid)
            if existing is None or appt_start < existing:
                job_appt_start[jid] = appt_start

        # Filter for canceled jobs
        canceled = [j for j in all_jobs if j.get("jobStatus") == "Canceled"]
        total_scheduled = len(all_jobs)

        # Optional tech filter
        tech_filter_id: int | None = None
        if query.technician_name:
            async with ServiceTitanClient(settings) as client:
                matches = await find_technician(client, query.technician_name)
            if not matches:
                return f'No technician found matching "{query.technician_name}".'
            if len(matches) > 1:
                names = ", ".join(t.get("name", "") for t in matches)
                return f'"{query.technician_name}" matches multiple technicians: {names}.\nPlease be more specific.'
            tech_filter_id = matches[0]["id"]
            canceled = [j for j in canceled if j.get("technicianId") == tech_filter_id]

        # Calculate hours before appointment for each canceled job
        enriched: list[dict] = []
        for job in canceled:
            jid = job.get("id")
            completed_on = job.get("completedOn") or ""
            appt_start = job_appt_start.get(jid, "")

            hours_before: float | None = None
            if completed_on and appt_start:
                try:
                    dt_cancel = datetime.fromisoformat(completed_on.replace("Z", "+00:00"))
                    dt_appt = datetime.fromisoformat(appt_start.replace("Z", "+00:00"))
                    hours_before = (dt_appt - dt_cancel).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass

            # Late cancel = within 24 hours of appointment
            is_late = hours_before is not None and hours_before <= 24

            if query.late_only and not is_late:
                continue

            # Tag names as cancel reason
            tag_ids = job.get("tagTypeIds") or []
            tags = [tag_names.get(tid, f"Tag {tid}") for tid in tag_ids if tid in tag_names]

            enriched.append({
                "job": job,
                "hours_before": hours_before,
                "is_late": is_late,
                "tags": tags,
                "appt_start": appt_start,
            })

        date_label = format_date_range(start, end)

        lines = [
            f"Cancellations  |  {date_label}",
            f"{'─' * 55}",
        ]

        if not enriched:
            qualifier = " late" if query.late_only else ""
            lines.append(f"No{qualifier} cancellations found in this date range.")
            return "\n".join(lines)

        # Sort by completedOn
        enriched.sort(key=lambda e: e["job"].get("completedOn") or "")

        for e in enriched:
            job = e["job"]
            jnum = job.get("jobNumber") or job.get("id")
            jtype = type_names.get(job.get("jobTypeId"), "—")
            tid = job.get("technicianId")
            tname = tech_names.get(tid, "Unassigned") if tid else "Unassigned"
            canceled_date = (job.get("completedOn") or "")[:10]
            appt_date = (e["appt_start"] or "")[:10]

            line = f"Job #{jnum}  |  {jtype}  |  Canceled: {canceled_date}"
            if appt_date:
                line += f"  |  Scheduled: {appt_date}"
            lines.append(line)
            lines.append(f"  Tech: {tname}")

            if e["hours_before"] is not None:
                h = e["hours_before"]
                if h < 0:
                    lines.append(f"  Notice: canceled after scheduled time")
                elif h < 1:
                    lines.append(f"  Notice: {h * 60:.0f} min before appointment (LATE)")
                elif h <= 24:
                    lines.append(f"  Notice: {h:.1f} hours before appointment (LATE)")
                else:
                    days = h / 24
                    lines.append(f"  Notice: {days:.1f} days before appointment")

            if e["tags"]:
                lines.append(f"  Tags: {', '.join(e['tags'])}")

            lines.append("")

        # Summary block
        total_cancels = len(enriched)
        late_count = sum(1 for e in enriched if e["is_late"])
        cancel_rate = (total_cancels / total_scheduled * 100) if total_scheduled > 0 else 0
        late_rate = (late_count / total_cancels * 100) if total_cancels > 0 else 0

        hours_list = [e["hours_before"] for e in enriched if e["hours_before"] is not None]
        avg_hours = sum(hours_list) / len(hours_list) if hours_list else 0

        # Per-tech breakdown
        tech_cancels: dict[str, dict] = {}
        for e in enriched:
            tid = e["job"].get("technicianId")
            tname = tech_names.get(tid, "Unassigned") if tid else "Unassigned"
            tc = tech_cancels.setdefault(tname, {"total": 0, "late": 0})
            tc["total"] += 1
            if e["is_late"]:
                tc["late"] += 1

        lines.append("Summary:")
        lines.append(f"  Total cancellations: {total_cancels} of {total_scheduled} jobs ({cancel_rate:.1f}%)")
        lines.append(f"  Late cancels (<24h): {late_count} ({late_rate:.1f}% of cancels)")
        if hours_list:
            lines.append(f"  Avg notice: {avg_hours:.1f} hours")

        if tech_cancels:
            lines.append("")
            lines.append("  By technician:")
            for tname, tc in sorted(tech_cancels.items(), key=lambda x: x[1]["total"], reverse=True):
                lines.append(f"    {tname}: {tc['total']} cancels ({tc['late']} late)")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_cancellations.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


# ---------------------------------------------------------------------------
# Tool 15: get_technician_discounts
# ---------------------------------------------------------------------------


def _extract_discounts(invoice: dict) -> list[dict]:
    """
    Extract discount information from an invoice.

    Discounts appear as either:
      - Non-zero discountTotal on the invoice itself
      - Negative-price line items in the items array

    Returns a list of discount records with safe fields only (no PII).
    """
    discounts = []
    items = invoice.get("items") or []

    for item in items:
        price = item.get("price") or 0.0
        total = item.get("total") or 0.0

        # Negative price/total = discount or credit
        if price < 0 or total < 0:
            discounts.append({
                "amount": abs(min(price, total)),
                "reason": item.get("skuName") or "Unknown",
                "type": item.get("type") or "Unknown",
            })

    return discounts


@mcp.tool()
async def get_technician_discounts(
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
    min_discount_amount: float = 0.0,
) -> str:
    """
    Track discount and credit activity per technician from invoices.

    Shows who is discounting, how often, and total revenue impact. Discounts
    appear as negative line items on ServiceTitan invoices.

    Args:
        start_date: Start date YYYY-MM-DD. Defaults to last Monday.
        end_date: End date YYYY-MM-DD. Defaults to last Sunday.
        technician_name: Optional filter by technician.
        min_discount_amount: Only show discounts above this dollar amount (default 0).

    No customer information is included.
    """
    log.info(
        "tool.get_technician_discounts",
        start_date=start_date,
        end_date=end_date,
        technician_name=technician_name,
        min_discount_amount=min_discount_amount,
    )

    try:
        query = DiscountQuery(
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
            min_discount_amount=min_discount_amount,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            # Fetch invoices (contains items with discount line items)
            invoices = await fetch_all_pages(
                client, "accounting", "/invoices",
                {
                    "modifiedOnOrAfter": f"{start.isoformat()}T00:00:00Z",
                    "pageSize": 100,
                },
                max_records=2000,
            )

            # Fetch jobs for technician linkage
            all_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end), max_records=2000,
            )

            # Technician lookup
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )

            # Job type lookup
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )

        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
        }
        type_names: dict[int, str] = {
            t["id"]: t.get("name", f"ID {t['id']}") for t in raw_types if "id" in t
        }

        # Build jobId -> technicianId + jobTypeId from jobs
        job_info: dict[int, dict] = {}
        for job in all_jobs:
            jid = job.get("id")
            if jid is not None:
                job_info[jid] = {
                    "technicianId": job.get("technicianId"),
                    "jobTypeId": job.get("jobTypeId"),
                }

        # Optional tech filter
        tech_filter_id: int | None = None
        if query.technician_name:
            async with ServiceTitanClient(settings) as client:
                matches = await find_technician(client, query.technician_name)
            if not matches:
                return f'No technician found matching "{query.technician_name}".'
            if len(matches) > 1:
                names = ", ".join(t.get("name", "") for t in matches)
                return f'"{query.technician_name}" matches multiple technicians: {names}.\nPlease be more specific.'
            tech_filter_id = matches[0]["id"]

        # Process invoices for discounts
        discounted_jobs: list[dict] = []
        total_invoices = 0

        for inv in invoices:
            # Extract safe fields only — NO customer/location/summary data
            job_data = inv.get("job") or {}
            job_id = job_data.get("id")
            job_num = job_data.get("number", "—")
            job_type_name = job_data.get("type", "—")

            # Look up tech from our jobs data
            ji = job_info.get(job_id, {})
            tid = ji.get("technicianId")
            jtid = ji.get("jobTypeId")

            # Apply tech filter
            if tech_filter_id is not None and tid != tech_filter_id:
                continue

            total_invoices += 1

            # Check for discount line items
            disc_items = _extract_discounts(inv)
            if not disc_items:
                continue

            total_discount = sum(d["amount"] for d in disc_items)

            # Apply min_discount_amount filter
            if total_discount < query.min_discount_amount:
                continue

            gross = inv.get("subTotal") or 0.0
            net = inv.get("total") or 0.0

            # Get business unit (only id and name — no PII)
            bu_data = inv.get("businessUnit") or {}
            bu_name = bu_data.get("name", "—")

            # Invoice date
            inv_date = (inv.get("invoiceDate") or "")[:10]

            # Use job type from our lookup if available
            if jtid and jtid in type_names:
                job_type_name = type_names[jtid]

            discounted_jobs.append({
                "job_num": job_num,
                "job_type": job_type_name,
                "date": inv_date,
                "tech_id": tid,
                "gross": gross,
                "discount": total_discount,
                "net": net,
                "disc_pct": (total_discount / gross * 100) if gross > 0 else 0,
                "reasons": [d["reason"] for d in disc_items],
                "bu": bu_name,
            })

        date_label = format_date_range(start, end)

        lines = [
            f"Discount Report  |  {date_label}",
            f"{'─' * 55}",
        ]

        if not discounted_jobs:
            lines.append("No discounted invoices found in this date range.")
            return "\n".join(lines)

        # Sort by date
        discounted_jobs.sort(key=lambda d: d["date"])

        for d in discounted_jobs:
            tname = tech_names.get(d["tech_id"], "Unassigned") if d["tech_id"] else "Unassigned"
            lines.append(f"Job #{d['job_num']}  |  {d['date']}  |  {d['job_type']}  |  {d['bu']}")
            lines.append(
                f"  Gross: {fmt_currency(d['gross'])}  |  "
                f"Discount: {fmt_currency(d['discount'])} ({d['disc_pct']:.1f}%)  |  "
                f"Net: {fmt_currency(d['net'])}"
            )
            lines.append(f"  Tech: {tname}")
            if d["reasons"]:
                reasons = ", ".join(set(d["reasons"]))
                lines.append(f"  Reason: {reasons}")
            lines.append("")

        # Summary
        total_disc_count = len(discounted_jobs)
        total_discount_dollars = sum(d["discount"] for d in discounted_jobs)
        total_gross = sum(d["gross"] for d in discounted_jobs)
        total_net = sum(d["net"] for d in discounted_jobs)
        disc_rate = (total_disc_count / total_invoices * 100) if total_invoices > 0 else 0
        rev_impact = (total_discount_dollars / total_gross * 100) if total_gross > 0 else 0
        avg_disc = total_discount_dollars / total_disc_count if total_disc_count > 0 else 0

        # Per-tech breakdown
        tech_disc: dict[str, dict] = {}
        for d in discounted_jobs:
            tname = tech_names.get(d["tech_id"], "Unassigned") if d["tech_id"] else "Unassigned"
            td = tech_disc.setdefault(tname, {"count": 0, "total_disc": 0.0})
            td["count"] += 1
            td["total_disc"] += d["discount"]

        lines.append("Summary:")
        lines.append(f"  {total_disc_count} of {total_invoices} invoices discounted ({disc_rate:.1f}%)")
        lines.append(f"  Total discounted: {fmt_currency(total_discount_dollars)}")
        lines.append(f"  Gross revenue: {fmt_currency(total_gross)}  |  Net revenue: {fmt_currency(total_net)}")
        lines.append(f"  Revenue impact: {rev_impact:.1f}%")
        lines.append(f"  Avg discount: {fmt_currency(avg_disc)} per discounted job")

        if tech_disc:
            lines.append("")
            lines.append("  By technician:")
            for tname, td in sorted(tech_disc.items(), key=lambda x: x[1]["total_disc"], reverse=True):
                lines.append(f"    {tname}: {td['count']} discounts, {fmt_currency(td['total_disc'])} total")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_discounts.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"
