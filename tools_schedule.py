"""
Schedule tools — get_technician_schedule, compare_technician_hours.
"""
from __future__ import annotations

import sys
from datetime import datetime

import structlog
from pydantic import ValidationError

from server_config import mcp, settings
from servicetitan_client import ServiceTitanClient
from query_validator import DateRangeQuery, TechnicianJobQuery
from shared_helpers import (
    fetch_all_pages,
    find_technician,
    format_date_range,
    fmt_hours,
    fmt_time_utc,
    appt_duration_hours,
    scrub_appointment,
    fetch_appt_params,
    user_friendly_error,
)

log = structlog.get_logger(__name__)


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

            raw_appts = await fetch_all_pages(
                client,
                module="jpm",
                path="/appointments",
                params=fetch_appt_params(start, end, tech_id),
                max_records=500,
            )

        appts = [
            scrub_appointment(a) for a in raw_appts
            if a.get("status") != "Canceled"
        ]
        appts.sort(key=lambda a: a.get("start") or "")

        date_label = format_date_range(start, end)
        total_hours = sum(appt_duration_hours(a) for a in appts)

        lines = [
            f"Schedule for {tech_name}  |  {date_label}",
            f"{'─' * 50}",
            f"Appointments:       {len(appts)}",
            f"Total scheduled:    {fmt_hours(total_hours)}",
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
            day_hours = sum(appt_duration_hours(a) for a in day_appts)
            lines.append(f"  {day_label}  ({fmt_hours(day_hours)})")
            for a in day_appts:
                t_start = fmt_time_utc(a.get("start"))
                t_end = fmt_time_utc(a.get("end"))
                dur = appt_duration_hours(a)
                lines.append(f"    {t_start} → {t_end}  ({fmt_hours(dur)})")

        lines.append(f"\n(Times are UTC — scheduled, not actual clock-in/out)")
        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.get_technician_schedule.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"


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
        return f"Error: {user_friendly_error(exc)}"

    try:
        async with ServiceTitanClient(settings) as client:
            all_techs_raw = await fetch_all_pages(
                client,
                module="settings",
                path="/technicians",
                params={"active": "true"},
                max_records=500,
            )

            tech_appts: dict[int, list[dict]] = {}
            for tech in all_techs_raw:
                tid = tech.get("id")
                if tid is None:
                    continue
                raw = await fetch_all_pages(
                    client,
                    module="jpm",
                    path="/appointments",
                    params=fetch_appt_params(start, end, tid),
                    max_records=500,
                )
                done = [scrub_appointment(a) for a in raw if a.get("status") != "Canceled"]
                if done:
                    tech_appts[tid] = done

        if not tech_appts:
            date_label = format_date_range(start, end)
            return (
                f"Technician Hours Comparison  |  {date_label}\n"
                f"{'─' * 55}\n"
                "No appointments found in this date range."
            )

        tech_names: dict[int, str] = {
            t["id"]: t.get("name", f"Tech {t['id']}")
            for t in all_techs_raw
            if "id" in t
        }

        rows = []
        for tid, appts in tech_appts.items():
            name = tech_names.get(tid, f"Tech {tid}")
            total_h = sum(appt_duration_hours(a) for a in appts)
            appts_sorted = sorted(appts, key=lambda a: a.get("start") or "")
            first_start = appts_sorted[0].get("start") if appts_sorted else None
            last_end = appts_sorted[-1].get("end") if appts_sorted else None
            rows.append((name, total_h, first_start, last_end, len(appts)))

        rows.sort(key=lambda r: r[1], reverse=True)

        date_label = format_date_range(start, end)
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
            first_fmt = fmt_time_utc(first_start) if first_start else "—"
            lines.append(
                f"{name:<{name_w}}  {n_appts:>5}  {fmt_hours(hours):>11}  {first_fmt:>17}"
            )
            total_appts += n_appts
            total_hours += hours

        lines.append(sep)
        lines.append(
            f"{'TOTAL':<{name_w}}  {total_appts:>5}  {fmt_hours(total_hours):>11}"
        )
        lines.append(f"\n(Scheduled appointment hours — not actual clock-in/out)")

        return "\n".join(lines)

    except Exception as exc:
        log.error("tool.compare_technician_hours.error", error_type=type(exc).__name__)
        return f"Error: {user_friendly_error(exc)}"
