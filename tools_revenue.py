"""
Revenue tools — get_technician_revenue, get_revenue_summary, get_no_charge_jobs,
compare_technicians, get_revenue_trend.
"""
from __future__ import annotations


import structlog
from pydantic import ValidationError

from server_config import mcp, settings
from servicetitan_client import ServiceTitanClient
from query_validator import DateRangeQuery, TechnicianJobQuery
from shared_helpers import (
    fetch_all_pages,
    find_technician,
    format_date_range,
    count_no_charge,
    sum_revenue,
    fmt_currency,
    fmt_dollar_short,
    fetch_jobs_params,
    get_month_buckets,
    month_label,
    job_month,
    user_friendly_error,
)

log = structlog.get_logger(__name__)


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

        total_jobs = len(jobs)
        no_charge = count_no_charge(jobs)
        billed_jobs = total_jobs - no_charge
        revenue = sum_revenue(jobs)
        rev_per_job = revenue / billed_jobs if billed_jobs > 0 else 0.0
        date_label = format_date_range(start, end)

        lines = [
            f"Revenue for {tech_name}  |  {date_label}",
            f"{'─' * 45}",
            f"Total revenue:    {fmt_currency(revenue)}",
            f"Total jobs:       {total_jobs}",
            f"  Billed:         {billed_jobs}   ({fmt_currency(revenue)})",
            f"  No-charge:      {no_charge}",
        ]

        if billed_jobs > 0:
            lines.append(f"Revenue per job:  {fmt_currency(rev_per_job)}")

        if total_jobs == 0:
            lines.append("\nNo completed jobs found in this date range.")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_revenue.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


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

        total_jobs = len(jobs)
        no_charge = count_no_charge(jobs)
        billed_jobs = total_jobs - no_charge
        revenue = sum_revenue(jobs)
        date_label = format_date_range(start, end)

        lines = [
            f"Business Revenue Summary  |  {date_label}",
            f"{'─' * 45}",
            f"Total revenue:   {fmt_currency(revenue)}",
            f"Total jobs:      {total_jobs}",
            f"  Billed:        {billed_jobs}",
            f"  No-charge:     {no_charge}",
        ]

        if total_jobs == 0:
            lines.append("\nNo completed jobs found in this date range.")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_revenue_summary.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


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

        total_jobs = len(jobs)
        no_charge = count_no_charge(jobs)
        pct = (no_charge / total_jobs * 100) if total_jobs > 0 else 0.0
        date_label = format_date_range(start, end)

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
        return f"Error: {user_friendly_error(exc)}"


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
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            all_techs = await fetch_all_pages(
                client,
                module="settings",
                path="/technicians",
                params={"active": "true"},
                max_records=500,
            )
            jobs = await fetch_all_pages(
                client,
                module="jpm",
                path="/jobs",
                params=fetch_jobs_params(start, end),
                max_records=1000,
            )

        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}")
            for t in all_techs
            if "id" in t
        }

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

        date_label = format_date_range(start, end)

        if not tech_stats:
            return (
                f"Technician Comparison  |  {date_label}\n"
                f"{'─' * 55}\n"
                "No jobs with assigned technicians found in this date range."
            )

        rows = sorted(tech_stats.items(), key=lambda x: x[1]["revenue"], reverse=True)

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
                f"{name:<{name_w}}  {j:>5}  {fmt_currency(rev):>12}  {fmt_currency(rev_per_job):>10}  {nc:>9}"
            )

            total_jobs += j
            total_revenue += rev
            total_no_charge += nc

        total_billed = total_jobs - total_no_charge
        total_rev_per_job = total_revenue / total_billed if total_billed > 0 else 0.0

        lines.append(sep)
        lines.append(
            f"{'TOTAL':<{name_w}}  {total_jobs:>5}  {fmt_currency(total_revenue):>12}  {fmt_currency(total_rev_per_job):>10}  {total_no_charge:>9}"
        )

        if unassigned_count:
            lines.append(f"\n({unassigned_count} jobs had no assigned technician and are excluded)")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.compare_technicians.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


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
        return f"Error: {user_friendly_error(exc)}"

    cat_label = "Job Type" if group_by == "job_type" else "Business Unit"

    try:
        async with ServiceTitanClient(settings) as client:
            if group_by == "job_type":
                raw_cats = await fetch_all_pages(
                    client, "jpm", "/job-types", {}, max_records=200,
                )
            else:
                raw_cats = await fetch_all_pages(
                    client, "settings", "/business-units", {}, max_records=100,
                )

            jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end),
                max_records=2000,
            )

        cat_names: dict[int, str] = {
            c["id"]: c.get("name", f"ID {c['id']}")
            for c in raw_cats if "id" in c
        }

        cat_field = "jobTypeId" if group_by == "job_type" else "businessUnitId"
        months = get_month_buckets(start, end)
        cross_year = len(months) > 1 and months[0][0] != months[-1][0]

        cat_months: dict[int, dict[tuple[int, int], dict]] = {}
        for job in jobs:
            cid = job.get(cat_field)
            if cid is None:
                continue
            m = job_month(job)
            if m is None or m not in months:
                continue
            bucket = cat_months.setdefault(cid, {}).setdefault(
                m, {"revenue": 0.0, "billed": 0, "total": 0},
            )
            bucket["total"] += 1
            if not job.get("noCharge"):
                bucket["revenue"] += job.get("total") or 0.0
                bucket["billed"] += 1

        date_label = format_date_range(start, end)

        if not cat_months:
            return (
                f"Revenue Trend by {cat_label}  |  {date_label}\n"
                f"{'─' * 50}\n"
                "No jobs found in this date range."
            )

        rows: list[tuple] = []
        for cid, mdata in cat_months.items():
            name = cat_names.get(cid, f"ID {cid}")
            t_jobs = sum(md["total"] for md in mdata.values())
            t_billed = sum(md["billed"] for md in mdata.values())
            t_rev = sum(md["revenue"] for md in mdata.values())
            avg = t_rev / t_billed if t_billed > 0 else 0.0

            mavgs: list[float | None] = []
            for mo in months:
                md = mdata.get(mo)
                if md and md["billed"] > 0:
                    mavgs.append(md["revenue"] / md["billed"])
                else:
                    mavgs.append(None)

            first_val = next((v for v in mavgs if v is not None), None)
            last_val = next((v for v in reversed(mavgs) if v is not None), None)
            change = (
                (last_val - first_val) / first_val * 100
                if first_val and last_val and first_val > 0
                else None
            )
            rows.append((name, t_jobs, t_rev, avg, mavgs, change))

        rows.sort(key=lambda r: r[2], reverse=True)

        grand_mavgs: list[float | None] = []
        for mo in months:
            rev = sum(
                cat_months[cid].get(mo, {}).get("revenue", 0)
                for cid in cat_months
            )
            billed = sum(
                cat_months[cid].get(mo, {}).get("billed", 0)
                for cid in cat_months
            )
            grand_mavgs.append(rev / billed if billed > 0 else None)

        grand_jobs = sum(r[1] for r in rows)
        grand_rev = sum(r[2] for r in rows)
        grand_billed = sum(
            sum(md["billed"] for md in mdata.values())
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

        month_labels = [month_label(y, m, cross_year) for y, m in months]
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
                    f"{fmt_dollar_short(v):>{mcol_w}}" if v is not None
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
                f"{name:<{name_w}}  {t_jobs:>5}  {fmt_currency(avg):>10}"
                f"  {mstr}  {cstr:>8}"
            )

        mcells = []
        for v in grand_mavgs:
            mcells.append(
                f"{fmt_dollar_short(v):>{mcol_w}}" if v is not None
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
            f"{'TOTAL':<{name_w}}  {grand_jobs:>5}  {fmt_currency(grand_avg):>10}"
            f"  {mstr}  {gcstr:>8}"
        )

        if len(months) < 2:
            lines.append(
                "\n(Only 1 month in range — use 60-90 days for meaningful trends)"
            )

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_revenue_trend.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"
