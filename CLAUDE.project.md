# CLAUDE.project.md — ServiceTitan MCP Server

> **Important:** This project follows the **BUILD_APP.md ATLAS+S workflow**.
> Stack-specific rules, CLI tools, and confirmed API details are documented here.

---

## Project Overview

- **Name:** ServiceTitan MCP Server for American Leak Detection
- **Type:** Model Context Protocol (MCP) server for Claude Desktop
- **Purpose:** Enable natural language queries of ServiceTitan business data
- **End User:** Jimmy's wife (business owner, non-technical)
- **Deployment:** Local — Claude Desktop on Windows 11
- **Security Level:** Read-only, PII-minimized, production-grade

**Current ATLAS+S Phase:**
- ✅ **A — Architect** (complete)
- ✅ **T — Trace** (complete)
- ✅ **L — Link** (complete)
- ✅ **A — Assemble** (complete — server is live and working in Claude Desktop)
- ⏳ **S — Stress-test** (upcoming)
- ⏳ **S — Secure** (upcoming)
- ⏳ **M — Monitor** (upcoming)

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
| Resource     | Module     | Path              | Key Params                                      |
|--------------|------------|-------------------|-------------------------------------------------|
| Technicians  | `settings` | `/technicians`    | `active=true`                                   |
| Jobs         | `jpm`      | `/jobs`           | `technicianId`, `completedOnOrAfter`, `completedBefore` |

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
├── BUILD_APP.md                    # ATLAS+S workflow (framework)
├── CLAUDE.project.md               # This file — project-specific config
├── SERVICETITAN_CLAUDE_PROJECT.md  # Detailed architecture reference
├── SERVICETITAN_QUICK_START.md     # Visual guide to file relationships
├── README.md                       # Setup and usage instructions
├── servicetitan_mcp_server.py      # MCP server — 3 tools exposed
├── servicetitan_client.py          # ServiceTitan OAuth + API client
├── query_validator.py              # Pydantic input validation
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

**Planned but not yet built:**
- `tests/` — unit and integration tests
- `cache.py` — optional Redis caching

---

## MCP Tools (live)

| Tool | Description | Key Params |
|------|-------------|------------|
| `list_technicians` | List active technicians | `name_filter` (optional) |
| `get_technician_jobs` | Job counts for one tech over a date range | `technician_name`, `start_date`, `end_date` |
| `get_jobs_summary` | Overall job counts across all techs | `start_date`, `end_date` |

**Default date range:** Last full Monday–Sunday week (when no dates given).

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
- User-facing errors are sanitized (`_user_friendly_error`)
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

1. **Define the tool** in `servicetitan_mcp_server.py` with `@mcp.tool()`
2. **Add validation** in `query_validator.py`
3. **Add API method** in `servicetitan_client.py` (GET only)
4. **Scrub PII** before returning any data
5. **Update README.md** with the new tool
6. **Update this file** if new endpoints or env vars are needed
7. **Write tests** in `tests/`

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

---

## Changelog

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
- Created project structure per ATLAS+S workflow
- Defined security architecture (OAuth, PII minimization, rate limiting)

---

**Always refer back to BUILD_APP.md for development methodology. Update this file as the project evolves.**
