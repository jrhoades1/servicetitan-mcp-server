# CLAUDE.project.md — ServiceTitan MCP Server

> **Important:** This project follows the **BUILD_APP.md CITADEL workflow**.
> Stack-specific rules, CLI tools, and confirmed API details are documented here.

---

## Project Overview

- **Name:** ServiceTitan MCP Server for American Leak Detection
- **Type:** Model Context Protocol (MCP) server for Claude Desktop
- **Purpose:** Enable natural language queries of ServiceTitan business data
- **End User:** Jimmy's wife (business owner, non-technical)
- **Deployment:** Local — Claude Desktop on Windows 11
- **Security Level:** Read-only, PII-minimized, production-grade

**Current CITADEL Phase:**
- ✅ **C — Conceive** (complete)
- ✅ **I — Inventory** (complete)
- ✅ **T — Tie** (complete)
- ✅ **A — Assemble** (complete — server is live and working in Claude Desktop)
- ⏳ **D — Drill** (upcoming)
- ⏳ **E — Enforce** (upcoming)
- ⏳ **L — Look** (upcoming)

---

## Stack

### MCP Server
- **Protocol:** Model Context Protocol (Anthropic)
- **Language:** Python 3.11+
- **Framework:** `mcp` package v1.26.0 (`FastMCP`)
- **Package Manager:** pip + venv
- **Runtime:** `venv\Scripts\python.exe` (Windows)

### Core Dependencies (pinned)
```
mcp==1.26.0
httpx==0.28.1
pydantic==2.12.5
pydantic-settings==2.13.0
python-dotenv==1.2.1
structlog==25.5.0
```

---

## ServiceTitan API — Confirmed Details

### Authentication
- **Flow:** OAuth 2.0 Client Credentials
- **Token URL:** `https://auth.servicetitan.io/connect/token`
- **Token TTL:** 900 seconds (15 minutes)
- **Refresh strategy:** Token refreshed automatically before expiry (asyncio.Lock prevents thundering herd)

### API URL Structure
```
{ST_API_BASE}/{module}/v2/tenant/{ST_TENANT_ID}/{resource}
```
Example: `https://api.servicetitan.io/settings/v2/tenant/12345/technicians`

### Confirmed Endpoints
| Resource       | Module       | Path              | Key Params                                      |
|----------------|--------------|-------------------|-------------------------------------------------|
| Technicians    | `settings`   | `/technicians`    | `active=true`                                   |
| Jobs           | `jpm`        | `/jobs`           | `technicianId`, `completedOnOrAfter`, `completedBefore` |
| Appointments   | `jpm`        | `/appointments`   | `technicianId`, `startsOnOrAfter`, `startsBefore` |
| Job Types      | `jpm`        | `/job-types`      | (none — returns all, 31 records)                  |
| Business Units | `settings`   | `/business-units` | (none — returns all, 5 records)                 |
| Invoices       | `accounting` | `/invoices`       | `invoiceDateOnOrAfter`, `invoiceDateBefore`, `modifiedOnOrAfter` |
| Tag Types      | `settings`   | `/tag-types`      | (none — returns all, 100+ records)              |

> **Unavailable endpoints** (404): `payroll/jobs`, `timetracking/timesheets`, `jpm/time-entries`, `dispatch/timeclock`, `jpm/job-history`, `jpm/estimates`, `dispatch/appointment-history`, `accounting/invoice-items`, `settings/job-cancel-reasons`, `jpm/appointment-assignments`. No actual clock-in/out data or job audit trails are available via the API.

### Required Headers (every request)
```
Authorization: Bearer {access_token}
ST-App-Key: {ST_APP_KEY}
```

---

## Environment Variables

All stored in `.env` in the project root. Loaded by `config.py` using pydantic-settings.

| Variable       | Description                              | Example                                    |
|----------------|------------------------------------------|--------------------------------------------|
| `ST_CLIENT_ID` | OAuth client ID                          | `app-abc123`                               |
| `ST_CLIENT_SECRET` | OAuth client secret (SecretStr)      | `abc...`                                   |
| `ST_APP_KEY`   | ServiceTitan app key (header, SecretStr) | `key-xyz...`                               |
| `ST_TENANT_ID` | Numeric tenant ID                        | `12345678`                                 |
| `ST_AUTH_URL`  | OAuth token endpoint                     | `https://auth.servicetitan.io/connect/token` |
| `ST_API_BASE`  | API base URL (no trailing slash)         | `https://api.servicetitan.io`              |
| `LOG_LEVEL`    | Logging level (optional)                 | `INFO`                                     |
| `LOG_FILE`     | Log file path relative to project root   | `logs/mcp_server.log`                      |

---

## Project File Structure (actual)

```
servicetitan-mcp-server/
├── CLAUDE.md                       # Security standards (framework)
├── BUILD_APP.md                    # CITADEL workflow (framework)
├── CLAUDE.project.md               # This file — project-specific config
├── README.md                       # Setup and usage instructions
├── servicetitan_mcp_server.py      # Entry point — imports tool modules, runs MCP
├── server_config.py                # Shared MCP instance, settings, logging
├── shared_helpers.py               # PII scrubbing, API helpers, formatters
├── tools_jobs.py                   # 4 job tools (@mcp.tool registered at import)
├── tools_revenue.py                # 5 revenue tools
├── tools_schedule.py               # 2 schedule tools
├── tools_analysis.py               # 4 analysis tools
├── tools_recall.py                 # 5 recall tools
├── servicetitan_client.py          # ServiceTitan OAuth + API client
├── query_validator.py              # Pydantic input validation (13 models)
├── config.py                       # Settings loaded from .env
├── logging_config.py               # structlog JSON logging + PII scrub
├── requirements.txt                # Production dependencies (pinned)
├── requirements-dev.txt            # Dev/test dependencies
├── .env                            # Real credentials (NEVER COMMIT)
├── .env.example                    # Safe template (committed)
├── .gitignore
├── logs/
│   ├── .gitkeep
│   └── mcp_server.log              # gitignored
└── venv/                           # gitignored
```

**Module dependency chain (no circular imports):**
```
server_config.py → shared_helpers.py → tools_*.py → servicetitan_mcp_server.py
```

**Planned but not yet built:**
- `tests/` — unit and integration tests
- `cache.py` — optional Redis caching

---

## MCP Tools (20 live)

| Tool | Module | Description | Key Params |
|------|--------|-------------|------------|
| `list_technicians` | `tools_jobs` | List active technicians | `name_filter` (optional) |
| `get_technician_jobs` | `tools_jobs` | Job counts for one tech | `technician_name`, `start_date`, `end_date` |
| `get_jobs_summary` | `tools_jobs` | Overall job counts across all techs | `start_date`, `end_date` |
| `get_jobs_by_type` | `tools_jobs` | Job records filtered by type, with all assigned techs | `job_types`, `start_date`, `end_date`, `technician_name`, `status` |
| `get_technician_revenue` | `tools_revenue` | Revenue breakdown for one tech | `technician_name`, `start_date`, `end_date` |
| `get_revenue_summary` | `tools_revenue` | Business-wide revenue totals | `start_date`, `end_date` |
| `get_no_charge_jobs` | `tools_revenue` | Count and % of no-charge jobs | `start_date`, `end_date` |
| `compare_technicians` | `tools_revenue` | Leaderboard: jobs, revenue, $/job | `start_date`, `end_date` |
| `get_revenue_trend` | `tools_revenue` | Avg $/job by job type or BU, monthly trend | `group_by`, `start_date`, `end_date` |
| `get_technician_schedule` | `tools_schedule` | Day-by-day appointment schedule | `technician_name`, `start_date`, `end_date` |
| `compare_technician_hours` | `tools_schedule` | Scheduled hours + earliest start per tech | `start_date`, `end_date` |
| `get_technician_job_mix` | `tools_analysis` | Per-tech job breakdown by type with revenue | `technician_name`, `start_date`, `end_date` |
| `compare_technician_job_mix` | `tools_analysis` | All techs × all job types comparison matrix | `job_type`, `start_date`, `end_date` |
| `get_cancellations` | `tools_analysis` | Canceled jobs with timing and tags | `technician_name`, `late_only`, `start_date`, `end_date` |
| `get_technician_discounts` | `tools_analysis` | Discount/credit tracking per tech from invoices | `technician_name`, `min_discount_amount`, `start_date`, `end_date` |
| `get_recalls` | `tools_recall` | True recall jobs (recallForId set) with original job lookup | `technician_name`, `business_unit`, `start_date`, `end_date` |
| `get_callback_chains` | `tools_recall` | Recall chains grouped by original job; truck rolls + opportunity cost | `technician_name`, `min_chain_length`, `start_date`, `end_date` |
| `get_recall_summary` | `tools_recall` | Recall rate by tech/BU/job_type with opportunity cost | `group_by`, `start_date`, `end_date` |
| `get_jobs_by_tag` | `tools_recall` | Jobs filtered by tag name(s); names resolved to IDs | `tag_names`, `technician_name`, `start_date`, `end_date` |
| `search_job_summaries` | `tools_recall` | Text search across job summary field (PII-flagged) | `search_text`, `technician_name`, `job_type`, `start_date`, `end_date` |

**Default date range:** Last full Monday–Sunday week (when no dates given).
**Schedule tools note:** Show scheduled appointment hours, not actual clock-in/out (unavailable via API).

---

## Security Configuration

### Input Validation
- Technician names: `^[A-Za-z\s\-]+$`, max 100 chars
- Date ranges: YYYY-MM-DD, max 90-day span
- All validation via Pydantic models in `query_validator.py`

### PII Minimization
**Never sent to Claude:**
- Customer names, addresses, phones, emails
- Job summaries (contain customer info)
- Raw API responses

**Sent to Claude (aggregated only):**
- Technician names (employees, not PII)
- Job counts and statuses
- Date ranges
- Revenue totals (aggregated)

### Error Handling
- User-facing errors are sanitized (`user_friendly_error` in `shared_helpers.py`)
- Internal exception details go to server logs only
- No stack traces exposed to users

### Retry Logic
- Max retries: 3 with exponential backoff (1s, 2s, 4s)
- Retry on: network errors, 5xx responses
- No retry on: 4xx, auth failures

---

## Claude Desktop Integration (Windows)

### Config File Location — **IMPORTANT**

Claude Desktop on Windows is a UWP (MSIX) app. The config file is **not** in the
standard `%APPDATA%\Claude\` path. The actual location is:

```
%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

### Working Config
```json
{
  "mcpServers": {
    "servicetitan": {
      "command": "C:\\Users\\Tracy\\Projects\\servicetitan-mcp-server\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\Tracy\\Projects\\servicetitan-mcp-server\\servicetitan_mcp_server.py"
      ]
    }
  }
}
```

The server loads credentials from `.env` in the project directory automatically.
**All paths must be absolute** — Claude Desktop may launch the process from any working directory.

---

## Common Commands

```bash
# Activate venv (Windows)
venv\Scripts\activate

# Test OAuth connection before launching Claude Desktop
python servicetitan_mcp_server.py --check

# Watch server logs
tail -f logs/mcp_server.log

# Format and lint
black .
ruff check --fix .

# Security audit
pip-audit

# Run tests (once tests/ is built)
pytest tests/ -v
```

---

## Adding New Features

Follow the "Five Levels" principle (Simon Willison) — current server is Level 2.
Level 3 would add comparison context (e.g., "20% above average").

1. **Create or edit a tool module** (`tools_jobs.py`, `tools_revenue.py`, `tools_schedule.py`, `tools_analysis.py`, or `tools_recall.py`) — use `@mcp.tool()` decorator
2. **Add validation** in `query_validator.py`
3. **Add shared helpers** in `shared_helpers.py` if needed (PII scrubbing, formatters)
4. **Scrub PII** before returning any data
5. **Import the tool module** in `servicetitan_mcp_server.py` if it's a new file
6. **Update README.md** with the new tool
7. **Update this file** if new endpoints or env vars are needed
8. **Write tests** in `tests/`

---

## Notes for Claude

### Never
- Expose raw ServiceTitan API responses to users
- Log OAuth tokens, secrets, or responses containing PII
- Skip input validation (treat all tool inputs as untrusted)
- Use non-GET HTTP methods (enforced in `servicetitan_client.py`)
- Hardcode credentials or tenant IDs

### Always
- Keep modules focused (<200 lines per file)
- Use Pydantic for all data validation
- Use structlog for all logging (JSON format)
- Make paths absolute using `Path(__file__).parent` anchoring
- Test `--check` before modifying Claude Desktop config

### After adding, removing, or modifying any MCP tool (MANDATORY)
Update ALL of these before committing:
1. **Module docstring** in `servicetitan_mcp_server.py` — tool list at top of file
2. **MCP Tools table** in `CLAUDE.project.md` — tool count + row in the table
3. **Available Tools section** in `README.md` — tool count + entry under correct category
4. **File structure comment** in `CLAUDE.project.md` — tool count in `servicetitan_mcp_server.py` line
5. **Changelog** in `CLAUDE.project.md` — entry describing what was added/changed
6. **Confirmed Endpoints table** in `CLAUDE.project.md` — if a new API endpoint was used

This is non-negotiable. Documentation drift causes confusion across sessions.

---

## Changelog

### 2026-02-20 — Recall Tracking (5 New Tools, 15 → 20)
- **Added** `tools_recall.py` — new module with 5 recall and tag tools
- **Added** `get_recalls` — jobs where `recallForId` is not null; looks up original job by ID; shows days-to-recall and summary with PII warning
- **Added** `get_callback_chains` — groups recalls by original job; calculates truck rolls and opportunity cost (N recalls × avg $/job)
- **Added** `get_recall_summary` — recall rate by tech/BU/job_type; GO BACK classification block (true recalls vs Set Test vs unclassified); overall rate and opportunity cost
- **Added** `get_jobs_by_tag` — resolves tag names to IDs client-side; filters jobs by any matching tag; lists available tags on lookup failure
- **Added** `search_job_summaries` — case-insensitive substring search across `summary` field; max 50 results; always shows PII warning header
- **Added** 5 validators: `RecallQuery`, `CallbackChainQuery`, `RecallSummaryQuery`, `JobsByTagQuery`, `SummarySearchQuery`
- **Added** `warrantyId` to `_SAFE_JOB_FIELDS` (internal numeric ID, same class as `recallForId`)
- **Design decisions:** `summary` accessed from raw records (never via `scrub_job()`); recall rate attributed to original job's tech/BU (who caused the rework); chain matching via `recallForId` only (no locationId heuristic)
- Tool count: 15 → 20

### 2026-02-20 — Module Refactor + 4 New Analysis Tools
- **Refactored** monolithic `servicetitan_mcp_server.py` (1,600 lines) into focused modules:
  - `server_config.py` — shared MCP instance, settings, logging
  - `shared_helpers.py` — PII scrubbing, API helpers, formatters
  - `tools_jobs.py` — 4 job tools
  - `tools_revenue.py` — 5 revenue tools
  - `tools_schedule.py` — 2 schedule tools
  - `tools_analysis.py` — 4 new analysis tools
  - `servicetitan_mcp_server.py` — entry point only (~60 lines)
- **Added** `get_technician_job_mix` — per-tech job breakdown by type with revenue/avg stats
- **Added** `compare_technician_job_mix` — all techs x all job types matrix with company avg and variance
- **Added** `get_cancellations` — canceled jobs with timing, late-cancel detection, tag-based reason proxy
- **Added** `get_technician_discounts` — invoice discount tracking via negative line items, PII-safe
- **Added** 3 new validators: `JobMixCompareQuery`, `CancellationQuery`, `DiscountQuery`
- **Probed** and confirmed: `accounting/invoices`, `settings/tag-types`
- **Confirmed unavailable** (404): `jpm/job-history`, `jpm/estimates`, `dispatch/appointment-history`, `accounting/invoice-items`, `settings/job-cancel-reasons`, `jpm/appointment-assignments`
- **Expanded** `_SAFE_JOB_FIELDS` with: `recallForId`, `invoiceId`, `tagTypeIds`, `firstAppointmentId`
- Tool count: 11 → 15

### 2026-02-19 — Revenue Trend Tool
- Added `get_revenue_trend` — avg $/job by job type or business unit, monthly breakdown
- Probed and confirmed `jpm/job-types` (31 records) and `settings/business-units` (5 records)
- Only `id` and `name` used from lookup records — no PII from business unit records exposed

### 2026-02-19 — Appointment Schedule Tools
- Added `get_technician_schedule` — day-by-day appointment view per tech
- Added `compare_technician_hours` — scheduled hours and earliest start per tech
- Probed and confirmed `jpm/appointments` endpoint (supports `technicianId`, `startsOnOrAfter`, `startsBefore`)
- Confirmed unavailable: `payroll/jobs`, `timetracking/timesheets`, `jpm/time-entries` (404)
- Added `_SAFE_APPT_FIELDS`, `_scrub_appointment()`, duration/time helpers

### 2026-02-19 — Revenue & Performance Tools
- Added 4 tools: `get_technician_revenue`, `get_revenue_summary`, `get_no_charge_jobs`, `compare_technicians`
- Refactored `query_validator.py`: extracted `DateRangeQuery` base class from `TechnicianJobQuery`
- Added `technicianId` to `_SAFE_JOB_FIELDS` (internal numeric ID, not PII)
- Added helpers: `_sum_revenue`, `_count_no_charge`, `_fmt_currency`, `_fetch_jobs_params`

### 2026-02-18 — Assemble Phase Complete
- Implemented `config.py` (pydantic-settings, SecretStr)
- Implemented `logging_config.py` (structlog, PII scrubbing)
- Implemented `servicetitan_client.py` (OAuth2, read-only enforcement, retry logic)
- Implemented `query_validator.py` (Pydantic validation, 90-day limit)
- Implemented `servicetitan_mcp_server.py` (FastMCP, 3 tools, PII scrubbing)
- Confirmed ServiceTitan API endpoints: `settings/technicians`, `jpm/jobs`
- Fixed absolute path issue for Claude Desktop subprocess launch
- Server confirmed working: all 3 tools tested successfully in Claude Desktop
- Confirmed UWP config path: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\`

### 2026-02-18 — Project Initialization
- Created project structure per CITADEL workflow
- Defined security architecture (OAuth, PII minimization, rate limiting)

---

**Always refer back to BUILD_APP.md for development methodology. Update this file as the project evolves.**
