"""
Recall and callback chain tracking tools.

Tools:
  get_recalls              — jobs where recallForId is not null (true ServiceTitan recalls)
  get_callback_chains      — recall chains grouped by original job; truck rolls + cost
  get_recall_summary       — recall rate by tech/BU/job_type with opportunity cost
  get_jobs_by_tag          — filter jobs by tag name(s)
  search_job_summaries     — text search across job summary field (PII-flagged)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import structlog
from pydantic import ValidationError

from server_config import mcp, settings
from servicetitan_client import ServiceTitanClient
from shared_helpers import (
    fetch_all_pages,
    fetch_jobs_params,
    fmt_currency,
    format_date_range,
    scrub_job,
    sum_revenue,
    user_friendly_error,
)
from query_validator import (
    CallbackChainQuery,
    JobsByTagQuery,
    RecallQuery,
    RecallSummaryQuery,
    SummarySearchQuery,
)

log = structlog.get_logger(__name__)

_SEP = "─" * 60


def _days_between(iso_a: str | None, iso_b: str | None) -> int | None:
    """Return integer days between two ISO timestamp strings, or None if unparseable."""
    if not iso_a or not iso_b:
        return None
    try:
        dt_a = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
        dt_b = datetime.fromisoformat(iso_b.replace("Z", "+00:00"))
        return abs(int((dt_b - dt_a).total_seconds() / 86400))
    except (ValueError, TypeError):
        return None


def _job_date(job: dict) -> str:
    """Return a short YYYY-MM-DD date from a job's completedOn field."""
    raw = job.get("completedOn") or ""
    return raw[:10] if raw else "—"


# ---------------------------------------------------------------------------
# Tool 1: get_recalls
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_recalls(
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
    business_unit: str = "",
) -> str:
    """
    Return jobs where recallForId is not null — these are true recalls booked
    through ServiceTitan's Job Actions → "Recall..." workflow.

    For each recall: shows the recall job details, the original job it links
    back to (if in the date range), days elapsed, technicians, tags, and the
    full job summary (with PII disclaimer).

    Parameters:
      start_date: YYYY-MM-DD (defaults to last Monday)
      end_date:   YYYY-MM-DD (defaults to last Sunday)
      technician_name: optional — filter by recall technician name
      business_unit:   optional — filter by business unit name
    """
    try:
        query = RecallQuery(
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
            business_unit=business_unit or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    date_label = format_date_range(start, end)
    log.info("get_recalls.start", start=str(start), end=str(end))

    try:
        async with ServiceTitanClient(settings) as client:
            all_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end),
                max_records=2000,
            )
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )
            raw_bus = await fetch_all_pages(
                client, "settings", "/business-units", {}, max_records=200,
            )
            raw_tags = await fetch_all_pages(
                client, "settings", "/tag-types", {}, max_records=500,
            )
    except Exception as exc:
        return f"Error: {user_friendly_error(exc)}"

    tech_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
    }
    type_names: dict[int, str] = {
        t["id"]: t.get("name", f"Type {t['id']}") for t in raw_types if "id" in t
    }
    bu_names: dict[int, str] = {
        b["id"]: b.get("name", f"BU {b['id']}") for b in raw_bus if "id" in b
    }
    tag_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tag {t['id']}") for t in raw_tags if "id" in t
    }

    # Index all jobs by ID for original-job lookup
    job_by_id: dict[int, dict] = {j["id"]: j for j in all_jobs if "id" in j}

    # Filter to recalls only
    recalls = [j for j in all_jobs if j.get("recallForId")]

    # Apply optional filters
    if query.technician_name:
        needle = query.technician_name.lower()
        target_ids = {tid for tid, name in tech_names.items() if needle in name.lower()}
        recalls = [r for r in recalls if r.get("technicianId") in target_ids]
        if not target_ids:
            return (
                f"No technician found matching '{query.technician_name}'. "
                f"Available: {', '.join(sorted(tech_names.values()))}"
            )

    if query.business_unit:
        needle = query.business_unit.lower()
        target_bu_ids = {bid for bid, name in bu_names.items() if needle in name.lower()}
        recalls = [r for r in recalls if r.get("businessUnitId") in target_bu_ids]

    recalls.sort(key=lambda j: j.get("completedOn") or "")

    lines = [
        f"Recall Jobs  |  {date_label}",
        _SEP,
    ]

    if query.technician_name:
        lines.append(f"Filter: Recall Tech = {query.technician_name}")
    if query.business_unit:
        lines.append(f"Filter: Business Unit = {query.business_unit}")
    if query.technician_name or query.business_unit:
        lines.append(_SEP)

    if not recalls:
        lines.append("No recall jobs found in this date range.")
        lines.append("")
        lines.append(
            "Note: Only jobs booked via Job Actions → 'Recall...' are counted here. "
            "GO BACK jobs without a recallForId are not true recalls."
        )
        return "\n".join(lines)

    for job in recalls:
        jnum = job.get("jobNumber") or job.get("id")
        jdate = _job_date(job)
        bu = bu_names.get(job.get("businessUnitId", 0), "—")
        tech = tech_names.get(job.get("technicianId", 0), "—")
        total = job.get("total") or 0.0
        no_charge = "  |  No-Charge" if job.get("noCharge") else ""
        tag_ids = job.get("tagTypeIds") or []
        tags = [tag_names.get(tid, f"Tag {tid}") for tid in tag_ids if tid in tag_names]

        lines.append(
            f"Recall #{jnum}  |  {jdate}  |  {bu}  |  {fmt_currency(total)}{no_charge}"
        )
        lines.append(f"  Recall Tech:  {tech}")
        if tags:
            lines.append(f"  Tags:         {', '.join(tags)}")

        # Original job lookup
        orig_id = job.get("recallForId")
        orig = job_by_id.get(orig_id) if orig_id else None
        if orig:
            orig_num = orig.get("jobNumber") or orig.get("id")
            orig_date = _job_date(orig)
            orig_type = type_names.get(orig.get("jobTypeId", 0), "—")
            orig_tech = tech_names.get(orig.get("technicianId", 0), "—")
            orig_total = orig.get("total") or 0.0
            days = _days_between(orig.get("completedOn"), job.get("completedOn"))
            days_str = f"  |  {days}d later" if days is not None else ""
            lines.append(
                f"  Original Job: #{orig_num}  |  {orig_date}  |  {orig_type}"
                f"  |  {fmt_currency(orig_total)}  |  {orig_tech}{days_str}"
            )
        else:
            lines.append(
                f"  Original Job: ID {orig_id}  (outside current date range — widen dates to see details)"
            )

        # Summary — raw field, never passed through scrub_job()
        summary = job.get("summary", "") or ""
        if summary.strip():
            lines.append(
                f"  \u26a0\ufe0f  Summary (may contain customer info): \"{summary.strip()}\""
            )

        lines.append("")

    # Summary block
    lines.append(_SEP)
    lines.append(f"Total recalls: {len(recalls)}  |  {date_label}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: get_callback_chains
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_callback_chains(
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
    min_chain_length: int = 2,
) -> str:
    """
    Group recall jobs into chains: original job → recall(s) linked by recallForId.

    Shows truck roll count, opportunity cost, and chain duration per chain.
    Only chains with recallForId linkage are included (reliable API data).

    Parameters:
      start_date:       YYYY-MM-DD (defaults to last Monday)
      end_date:         YYYY-MM-DD (defaults to last Sunday)
      technician_name:  optional — filter chains by ORIGINAL job's technician
      min_chain_length: minimum total visits to show (default 2, max 10)
    """
    try:
        query = CallbackChainQuery(
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
            min_chain_length=min_chain_length,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    date_label = format_date_range(start, end)
    log.info("get_callback_chains.start", start=str(start), end=str(end))

    try:
        async with ServiceTitanClient(settings) as client:
            all_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end),
                max_records=2000,
            )
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )
            raw_tags = await fetch_all_pages(
                client, "settings", "/tag-types", {}, max_records=500,
            )
    except Exception as exc:
        return f"Error: {user_friendly_error(exc)}"

    tech_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
    }
    type_names: dict[int, str] = {
        t["id"]: t.get("name", f"Type {t['id']}") for t in raw_types if "id" in t
    }
    tag_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tag {t['id']}") for t in raw_tags if "id" in t
    }
    job_by_id: dict[int, dict] = {j["id"]: j for j in all_jobs if "id" in j}

    # Calculate avg revenue for opportunity cost
    completed = [j for j in all_jobs if j.get("jobStatus") == "Completed"]
    total_rev = sum_revenue(completed)
    avg_rev = total_rev / len(completed) if completed else 0.0

    # Build chains: recallForId → list of recall jobs
    chains: dict[int, list[dict]] = defaultdict(list)
    for job in all_jobs:
        orig_id = job.get("recallForId")
        if orig_id:
            chains[int(orig_id)].append(scrub_job(job))

    # Apply technician filter on ORIGINAL job's tech
    if query.technician_name:
        needle = query.technician_name.lower()
        target_ids = {tid for tid, name in tech_names.items() if needle in name.lower()}
        if not target_ids:
            return (
                f"No technician found matching '{query.technician_name}'. "
                f"Available: {', '.join(sorted(tech_names.values()))}"
            )
        chains = {
            orig_id: recalls for orig_id, recalls in chains.items()
            if job_by_id.get(orig_id, {}).get("technicianId") in target_ids
        }

    # Filter by chain length (original + recalls >= min_chain_length)
    qualifying = {
        orig_id: recalls for orig_id, recalls in chains.items()
        if 1 + len(recalls) >= query.min_chain_length
    }

    lines = [
        f"Callback Chains  |  {date_label}  |  Min length: {query.min_chain_length}",
        _SEP,
    ]

    if not qualifying:
        lines.append(
            f"No callback chains with {query.min_chain_length}+ visits found in this date range."
        )
        return "\n".join(lines)

    # Sort chains: most truck rolls first
    sorted_chains = sorted(
        qualifying.items(), key=lambda kv: len(kv[1]), reverse=True
    )

    total_truck_rolls = 0
    total_opp_cost = 0.0

    for orig_id, recalls in sorted_chains:
        orig = job_by_id.get(orig_id)
        truck_rolls = 1 + len(recalls)
        total_truck_rolls += truck_rolls

        recall_opp_cost = len(recalls) * avg_rev
        total_opp_cost += recall_opp_cost

        # Chain duration: from original completedOn to last recall completedOn
        all_dates = []
        if orig:
            d = orig.get("completedOn")
            if d:
                all_dates.append(d)
        for r in recalls:
            d = r.get("completedOn")
            if d:
                all_dates.append(d)
        all_dates.sort()
        duration = _days_between(all_dates[0], all_dates[-1]) if len(all_dates) >= 2 else None
        dur_str = f"  |  {duration}d span" if duration is not None else ""

        lines.append(
            f"Chain: Original Job #{orig_id}  ({truck_rolls} truck rolls{dur_str})"
        )

        if orig:
            orig_date = _job_date(orig)
            orig_type = type_names.get(orig.get("jobTypeId", 0), "—")
            orig_tech = tech_names.get(orig.get("technicianId", 0), "—")
            orig_total = orig.get("total") or 0.0
            lines.append(
                f"  Original  |  {orig_date}  |  {orig_type}  |  {orig_tech}"
                f"  |  {fmt_currency(orig_total)}"
            )
        else:
            lines.append(f"  Original Job #{orig_id}  (outside date range)")

        recalls_sorted = sorted(recalls, key=lambda r: r.get("completedOn") or "")
        for i, recall in enumerate(recalls_sorted, 1):
            rnum = recall.get("jobNumber") or recall.get("id")
            rdate = _job_date(recall)
            rtype = type_names.get(recall.get("jobTypeId", 0), "—")
            rtech = tech_names.get(recall.get("technicianId", 0), "—")
            rtotal = recall.get("total") or 0.0
            tag_ids = recall.get("tagTypeIds") or []
            tags = [tag_names.get(tid, f"Tag {tid}") for tid in tag_ids if tid in tag_names]
            tag_str = f"  |  Tags: {', '.join(tags)}" if tags else ""
            no_charge_str = "  |  No-Charge" if recall.get("noCharge") else ""
            lines.append(
                f"  Recall {i}   |  {rdate}  |  {rtype}  |  {rtech}"
                f"  |  {fmt_currency(rtotal)}{no_charge_str}{tag_str}"
            )
            _ = rnum  # suppress unused warning — referenced above for clarity

        lines.append(
            f"  Opportunity Cost: ~{fmt_currency(recall_opp_cost)}"
            f"  ({len(recalls)} recall visit{'s' if len(recalls) > 1 else ''}"
            f" × {fmt_currency(avg_rev)} avg/job)"
        )
        lines.append("")

    lines.append(_SEP)
    lines.append(
        f"Total chains: {len(qualifying)}  |  "
        f"Total truck rolls: {total_truck_rolls}  |  "
        f"Total opportunity cost: ~{fmt_currency(total_opp_cost)}"
    )
    lines.append(
        "Note: Chains based on recallForId links only. "
        "GO BACK jobs without a recall link are not included."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3: get_recall_summary
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_recall_summary(
    start_date: str = "",
    end_date: str = "",
    group_by: str = "technician",
) -> str:
    """
    High-level recall metrics for management reporting.

    Recall rate is attributed to the ORIGINAL job's tech/BU/type — measuring
    who caused the rework, not who did it.

    Parameters:
      start_date: YYYY-MM-DD (defaults to last Monday)
      end_date:   YYYY-MM-DD (defaults to last Sunday)
      group_by:   "technician" | "business_unit" | "job_type" (default: technician)
    """
    try:
        query = RecallSummaryQuery(
            start_date=start_date or None,
            end_date=end_date or None,
            group_by=group_by or "technician",
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    date_label = format_date_range(start, end)
    log.info("get_recall_summary.start", start=str(start), end=str(end), group_by=query.group_by)

    try:
        async with ServiceTitanClient(settings) as client:
            all_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end),
                max_records=2000,
            )
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )
            raw_bus = await fetch_all_pages(
                client, "settings", "/business-units", {}, max_records=200,
            )
            raw_tags = await fetch_all_pages(
                client, "settings", "/tag-types", {}, max_records=500,
            )
    except Exception as exc:
        return f"Error: {user_friendly_error(exc)}"

    tech_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
    }
    type_names: dict[int, str] = {
        t["id"]: t.get("name", f"Type {t['id']}") for t in raw_types if "id" in t
    }
    bu_names: dict[int, str] = {
        b["id"]: b.get("name", f"BU {b['id']}") for b in raw_bus if "id" in b
    }
    tag_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tag {t['id']}") for t in raw_tags if "id" in t
    }
    job_by_id: dict[int, dict] = {j["id"]: j for j in all_jobs if "id" in j}

    completed = [j for j in all_jobs if j.get("jobStatus") == "Completed"]
    recalls = [j for j in all_jobs if j.get("recallForId")]
    total_rev = sum_revenue(completed)
    avg_rev = total_rev / len(completed) if completed else 0.0

    def _group_key(job: dict) -> str:
        if query.group_by == "technician":
            return tech_names.get(job.get("technicianId", 0), "Unknown")
        if query.group_by == "business_unit":
            return bu_names.get(job.get("businessUnitId", 0), "Unknown")
        return type_names.get(job.get("jobTypeId", 0), "Unknown")

    # Completed jobs grouped (denominator)
    completed_by_group: dict[str, int] = defaultdict(int)
    for j in completed:
        completed_by_group[_group_key(j)] += 1

    # Recalls — attributed to ORIGINAL job's group
    recall_counts: dict[str, int] = defaultdict(int)
    recall_days: dict[str, list[int]] = defaultdict(list)
    for recall in recalls:
        orig_id = recall.get("recallForId")
        orig = job_by_id.get(orig_id) if orig_id else None
        group = _group_key(orig) if orig else "Unknown"
        recall_counts[group] += 1
        days = _days_between(
            orig.get("completedOn") if orig else None,
            recall.get("completedOn"),
        )
        if days is not None:
            recall_days[group].append(days)

    all_groups = sorted(set(list(completed_by_group.keys()) + list(recall_counts.keys())))

    group_label = query.group_by.replace("_", " ").title()
    lines = [
        f"Recall Summary  |  {date_label}  |  by {group_label}",
        _SEP,
    ]

    if not recalls:
        lines.append("No recall jobs found in this date range.")
        lines.append("")
        total_go_backs = sum(
            1 for j in all_jobs
            if type_names.get(j.get("jobTypeId", 0), "").upper() == "GO BACK"
        )
        lines.append(f"Total GO BACK jobs: {total_go_backs}")
        lines.append("None have recallForId set (no true recalls via Recall action).")
        return "\n".join(lines)

    total_opp_cost = 0.0
    rows = []
    for group in all_groups:
        rc = recall_counts.get(group, 0)
        cc = completed_by_group.get(group, 0)
        rate = (rc / cc * 100) if cc > 0 else 0.0
        days_list = recall_days.get(group, [])
        avg_days = int(sum(days_list) / len(days_list)) if days_list else 0
        opp = rc * avg_rev
        total_opp_cost += opp
        if rc > 0 or cc > 0:
            rows.append((group, rc, cc, rate, avg_days, opp))

    rows.sort(key=lambda r: r[2], reverse=True)  # sort by completed jobs desc

    name_w = max((len(r[0]) for r in rows), default=10)
    for group, rc, cc, rate, avg_days, opp in rows:
        opp_str = f"  |  ~{fmt_currency(opp)} opp cost" if rc > 0 else ""
        avg_str = f"  |  Avg {avg_days}d to recall" if rc > 0 else ""
        lines.append(
            f"{group:<{name_w}}  |  {rc} recall{'s' if rc != 1 else ''} / {cc} jobs"
            f"  |  {rate:.1f}%{avg_str}{opp_str}"
        )

    lines.append("")
    lines.append(_SEP)

    # GO BACK classification block
    go_back_type_ids = {
        tid for tid, name in type_names.items() if "GO BACK" in name.upper()
    }
    set_test_tag_ids = {
        tid for tid, name in tag_names.items() if "SET TEST" in name.upper()
    }
    go_backs = [j for j in all_jobs if j.get("jobTypeId") in go_back_type_ids]
    true_recalls = [j for j in go_backs if j.get("recallForId")]
    set_tests = [
        j for j in go_backs
        if not j.get("recallForId")
        and any(tid in set_test_tag_ids for tid in (j.get("tagTypeIds") or []))
    ]
    other_go_backs = [
        j for j in go_backs if not j.get("recallForId") and j not in set_tests
    ]

    lines.append("GO BACK Classification (all GO BACK jobs in range):")
    total_completed_count = len(completed)
    recall_pct = (len(true_recalls) / total_completed_count * 100) if total_completed_count else 0.0
    lines.append(
        f"  True Recalls (recallForId set):       {len(true_recalls):>4}"
        f"  ({recall_pct:.1f}% of completed jobs)"
    )
    lines.append(f"  Set Test (tag-based):                 {len(set_tests):>4}")
    lines.append(f"  Other GO BACK / Unclassified:         {len(other_go_backs):>4}")
    lines.append(f"  Total GO BACK jobs:                   {len(go_backs):>4}")
    lines.append("")
    lines.append(
        f"Overall Recall Rate:    {recall_pct:.1f}%  "
        f"({len(true_recalls)} recalls / {total_completed_count} completed jobs)"
    )
    lines.append(f"Total Opportunity Cost: ~{fmt_currency(total_opp_cost)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 4: get_jobs_by_tag
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_jobs_by_tag(
    tag_names: str = "",
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
) -> str:
    """
    Return jobs that have one or more of the specified tags applied.

    Tag names are resolved to IDs server-side — use the exact display names
    shown in ServiceTitan (e.g. "Set Test", "CC on FILE").

    Parameters:
      tag_names:       comma-separated tag names (required)
      start_date:      YYYY-MM-DD (defaults to last Monday)
      end_date:        YYYY-MM-DD (defaults to last Sunday)
      technician_name: optional — filter by technician name
    """
    try:
        query = JobsByTagQuery(
            tag_names=tag_names or "",
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    date_label = format_date_range(start, end)
    log.info("get_jobs_by_tag.start", start=str(start), end=str(end))

    try:
        async with ServiceTitanClient(settings) as client:
            all_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end),
                max_records=2000,
            )
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )
            raw_tags_data = await fetch_all_pages(
                client, "settings", "/tag-types", {}, max_records=500,
            )
    except Exception as exc:
        return f"Error: {user_friendly_error(exc)}"

    tech_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
    }
    type_names: dict[int, str] = {
        t["id"]: t.get("name", f"Type {t['id']}") for t in raw_types if "id" in t
    }
    tag_id_to_name: dict[int, str] = {
        t["id"]: t.get("name", f"Tag {t['id']}") for t in raw_tags_data if "id" in t
    }
    tag_name_to_id: dict[str, int] = {
        v.lower(): k for k, v in tag_id_to_name.items()
    }

    # Resolve requested tag names to IDs
    requested = [t.strip() for t in query.tag_names.split(",") if t.strip()]
    resolved_ids: set[int] = set()
    unresolved: list[str] = []
    for name in requested:
        tid = tag_name_to_id.get(name.lower())
        if tid is not None:
            resolved_ids.add(tid)
        else:
            unresolved.append(name)

    if unresolved:
        available = sorted(tag_id_to_name.values())
        return (
            f"Unknown tag name(s): {', '.join(unresolved)}\n\n"
            f"Available tags: {', '.join(available)}"
        )

    # Filter jobs by technician if requested
    if query.technician_name:
        needle = query.technician_name.lower()
        target_ids = {tid for tid, name in tech_names.items() if needle in name.lower()}
        if not target_ids:
            return (
                f"No technician found matching '{query.technician_name}'. "
                f"Available: {', '.join(sorted(tech_names.values()))}"
            )
        all_jobs = [j for j in all_jobs if j.get("technicianId") in target_ids]

    # Filter jobs by tag match
    matching = [
        j for j in all_jobs
        if any(tid in resolved_ids for tid in (j.get("tagTypeIds") or []))
    ]
    matching.sort(key=lambda j: j.get("completedOn") or "")

    tag_display = ", ".join(
        f'"{tag_id_to_name[tid]}"' for tid in sorted(resolved_ids)
        if tid in tag_id_to_name
    )
    lines = [
        f"Jobs by Tag: {tag_display}  |  {date_label}",
        _SEP,
    ]
    if query.technician_name:
        lines.append(f"Filter: Technician = {query.technician_name}")
        lines.append(_SEP)

    if not matching:
        lines.append("No jobs found with the specified tag(s) in this date range.")
        return "\n".join(lines)

    for job in matching:
        jnum = job.get("jobNumber") or job.get("id")
        jdate = _job_date(job)
        jtype = type_names.get(job.get("jobTypeId", 0), "—")
        tech = tech_names.get(job.get("technicianId", 0), "—")
        total = job.get("total") or 0.0
        no_charge_str = "  No-Charge" if job.get("noCharge") else ""
        status = job.get("jobStatus", "—")

        # Show which of the requested tags matched
        job_tag_ids = job.get("tagTypeIds") or []
        matched_tags = [
            tag_id_to_name[tid] for tid in job_tag_ids
            if tid in resolved_ids and tid in tag_id_to_name
        ]
        other_tags = [
            tag_id_to_name[tid] for tid in job_tag_ids
            if tid not in resolved_ids and tid in tag_id_to_name
        ]
        tag_str = f"  [{', '.join(matched_tags)}]"
        if other_tags:
            tag_str += f"  +{', '.join(other_tags)}"

        is_recall = "  ← RECALL" if job.get("recallForId") else ""
        lines.append(
            f"Job #{jnum}  |  {jdate}  |  {jtype}  |  {tech}"
            f"  |  {fmt_currency(total)}{no_charge_str}  |  {status}{is_recall}"
        )
        lines.append(f"  Tags:{tag_str}")

    lines.append("")
    lines.append(_SEP)
    lines.append(
        f"Total: {len(matching)} job{'s' if len(matching) != 1 else ''} with tag(s) {tag_display}"
        f"  |  {date_label}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: search_job_summaries
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_job_summaries(
    search_text: str = "",
    start_date: str = "",
    end_date: str = "",
    technician_name: str = "",
    job_type: str = "",
) -> str:
    """
    Case-insensitive text search across job summary notes.

    Returns up to 50 matching jobs. Job summaries are free-text dispatcher
    notes and may contain customer names, phone numbers, or addresses.
    A PII warning is shown with every response.

    Parameters:
      search_text:     required — substring to search for (min 2 chars)
      start_date:      YYYY-MM-DD (defaults to last Monday)
      end_date:        YYYY-MM-DD (defaults to last Sunday)
      technician_name: optional — filter by technician name
      job_type:        optional — filter by job type name
    """
    try:
        query = SummarySearchQuery(
            search_text=search_text or "",
            start_date=start_date or None,
            end_date=end_date or None,
            technician_name=technician_name or None,
            job_type=job_type or None,
        )
        start, end = query.get_date_range()
    except (ValidationError, ValueError) as exc:
        return f"Error: {user_friendly_error(exc)}"

    date_label = format_date_range(start, end)
    log.info("search_job_summaries.start", start=str(start), end=str(end))

    try:
        async with ServiceTitanClient(settings) as client:
            # Fetch raw jobs — NOT scrubbed so summary field is accessible
            raw_jobs = await fetch_all_pages(
                client, "jpm", "/jobs",
                fetch_jobs_params(start, end),
                max_records=2000,
            )
            all_techs = await fetch_all_pages(
                client, "settings", "/technicians",
                {"active": "true"}, max_records=500,
            )
            raw_types = await fetch_all_pages(
                client, "jpm", "/job-types", {}, max_records=500,
            )
    except Exception as exc:
        return f"Error: {user_friendly_error(exc)}"

    tech_names: dict[int, str] = {
        t["id"]: t.get("name", f"Tech {t['id']}") for t in all_techs if "id" in t
    }
    type_names: dict[int, str] = {
        t["id"]: t.get("name", f"Type {t['id']}") for t in raw_types if "id" in t
    }

    # Apply optional pre-filters using scrubbed fields only
    if query.technician_name:
        needle = query.technician_name.lower()
        target_ids = {tid for tid, name in tech_names.items() if needle in name.lower()}
        if not target_ids:
            return (
                f"No technician found matching '{query.technician_name}'. "
                f"Available: {', '.join(sorted(tech_names.values()))}"
            )
        raw_jobs = [j for j in raw_jobs if j.get("technicianId") in target_ids]

    if query.job_type:
        needle = query.job_type.lower()
        target_type_ids = {
            tid for tid, name in type_names.items() if needle in name.lower()
        }
        raw_jobs = [j for j in raw_jobs if j.get("jobTypeId") in target_type_ids]

    # Search summary — accessed from RAW record, never from scrub_job()
    needle = query.search_text.lower()
    matches = [
        j for j in raw_jobs
        if needle in (j.get("summary") or "").lower()
    ]
    matches.sort(key=lambda j: j.get("completedOn") or "")

    lines = [
        f'Job Summary Search: "{query.search_text}"  |  {date_label}',
        "\u26a0\ufe0f  WARNING: Job summaries are free-text dispatcher notes and may contain",
        "    customer names, phone numbers, or addresses.",
        _SEP,
    ]

    if query.technician_name:
        lines.append(f"Filter: Technician = {query.technician_name}")
    if query.job_type:
        lines.append(f"Filter: Job Type = {query.job_type}")
    if query.technician_name or query.job_type:
        lines.append(_SEP)

    if not matches:
        lines.append(f'No jobs found with "{query.search_text}" in the summary.')
        return "\n".join(lines)

    shown = matches[:50]
    for job in shown:
        jnum = job.get("jobNumber") or job.get("id")
        jdate = _job_date(job)
        jtype = type_names.get(job.get("jobTypeId", 0), "—")
        tech = tech_names.get(job.get("technicianId", 0), "—")
        status = job.get("jobStatus", "—")
        is_recall = "  ← RECALL" if job.get("recallForId") else ""
        summary = (job.get("summary") or "").strip()

        lines.append(
            f"Job #{jnum}  |  {jdate}  |  {jtype}  |  {tech}  |  {status}{is_recall}"
        )
        lines.append(f"  Summary: \"{summary}\"")
        lines.append("")

    lines.append(_SEP)
    lines.append(
        f"Showing {len(shown)} of {len(matches)} match{'es' if len(matches) != 1 else ''}."
    )
    return "\n".join(lines)
