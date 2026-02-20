"""
ServiceTitan MCP Server for American Leak Detection.

Exposes ServiceTitan business data to Claude Desktop via the Model Context Protocol.
All data returned is aggregated and PII-free — no customer names, addresses, or
contact details are ever sent to Claude.

Tools exposed (15 total):
  Job Tools:
    list_technicians          — list active technicians by name
    get_technician_jobs       — job counts for a technician over a date range
    get_jobs_summary          — overall job counts across all technicians
    get_jobs_by_type          — individual job records filtered by type, all techs shown

  Revenue Tools:
    get_technician_revenue    — revenue earned by a technician over a date range
    get_revenue_summary       — total business revenue over a date range
    get_no_charge_jobs        — count of no-charge/warranty jobs over a date range
    compare_technicians       — side-by-side jobs, revenue, and $/job for all techs
    get_revenue_trend         — avg $/job by job type or business unit, monthly trend

  Schedule Tools:
    get_technician_schedule   — appointments and scheduled hours for one technician
    compare_technician_hours  — scheduled hours and first start time for all techs

  Analysis Tools:
    get_technician_job_mix    — per-tech job breakdown by type with revenue
    compare_technician_job_mix — all techs × all job types comparison matrix
    get_cancellations         — canceled job records with timing and tags
    get_technician_discounts  — discount/credit tracking per technician from invoices

Run this script directly (stdio transport for Claude Desktop):
  python servicetitan_mcp_server.py

Or test the auth connection:
  python servicetitan_mcp_server.py --check
"""
from __future__ import annotations

import asyncio
import sys

from server_config import mcp, settings, log
from servicetitan_client import ServiceTitanClient

# Import tool modules — @mcp.tool() decorators register at import time
import tools_jobs  # noqa: F401
import tools_revenue  # noqa: F401
import tools_schedule  # noqa: F401
import tools_analysis  # noqa: F401


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        # Quick connectivity check — useful before adding to Claude Desktop
        async def _check() -> None:
            log.info("startup.checking_connection")
            async with ServiceTitanClient(settings) as client:
                await client.ensure_authenticated()
            print("Connection OK — ServiceTitan authentication successful.")
            print("You can now add this server to Claude Desktop.")

        asyncio.run(_check())
    else:
        log.info("startup.starting_mcp_server")
        mcp.run(transport="stdio")
