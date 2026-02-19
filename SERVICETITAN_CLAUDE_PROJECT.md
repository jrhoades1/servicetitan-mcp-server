# CLAUDE.project.md — ServiceTitan MCP Server

> **Important:** This project follows the **BUILD_APP.md ATLAS+S workflow**. The complete architecture plan is in `SERVICETITAN_MCP_PROJECT_PLAN.md`, which was created by following the ATLAS+S methodology step-by-step.

---

## Project Overview

- **Name:** ServiceTitan MCP Server for American Leak Detection
- **Type:** Model Context Protocol (MCP) server for Claude Desktop
- **Purpose:** Enable natural language queries of ServiceTitan business data
- **User:** Jimmy's wife (business owner, non-technical)
- **Deployment:** Local (Claude Desktop) or small VPS with VPN
- **Security Level:** Read-only, PII-minimized, production-grade

**Current Phase:** Following BUILD_APP.md ATLAS+S workflow
- ✅ **A — Architect** (complete)
- ✅ **T — Trace** (complete)
- ✅ **L — Link** (complete)
- ✅ **A — Assemble** (complete — server live and working in Claude Desktop)
- ⏳ **S — Stress-test** (upcoming)
- ⏳ **S — Secure** (upcoming)
- ⏳ **M — Monitor** (upcoming)

---

## Stack

### MCP Server
- **Protocol:** Model Context Protocol (Anthropic)
- **Language:** Python 3.11+
- **Framework:** `mcp` package (official SDK)
- **Package Manager:** pip + venv
- **Python Version:** 3.11 (see .python-version)

### Core Dependencies
- **mcp:** Anthropic's MCP SDK
- **httpx:** Async HTTP client (ServiceTitan API)
- **pydantic:** Data validation and settings
- **python-dotenv:** Environment variable management
- **structlog:** Structured JSON logging

### Optional Dependencies
- **redis:** Query result caching (5-minute TTL)
- **pytest:** Unit and integration testing
- **responses:** HTTP mocking for tests

### ServiceTitan Integration
- **API Version:** v2
- **Auth:** OAuth 2.0 (client credentials flow)
- **Token URL:** `https://auth.servicetitan.io/connect/token`
- **API Base URL:** `https://api.servicetitan.io`
- **URL Pattern:** `{api_base}/{module}/v2/tenant/{tenant_id}/{resource}`
- **Scope:** Read-only (GET endpoints only)
- **Rate Limit:** [Verify your tier — typically 1000 req/hour]

---

## Available CLI Tools

### Required for Development
- **python:** 3.11+
- **pip:** Package installation
- **git:** Version control

### NOT Available (No Media Processing)
- ImageMagick, FFmpeg, ExifTool not needed for this project

---

## Security Configuration

### Authentication & Authorization
```
OAuth 2.0 Client Credentials Flow:
  - Client ID: Stored in .env
  - Client Secret: Stored in .env
  - Tenant ID: Stored in .env
  - Token Refresh: Automatic (60 seconds before expiry)
  - Scope: Read-only (verified in ServiceTitan dashboard)
```

### Resource Limits

#### API Rate Limiting (ServiceTitan)
```
Rate Limit: Check your ServiceTitan tier
  - Typical: 1000 requests/hour
  - Burst: 100 requests/minute
  - On limit hit: Return cached data with warning
```

#### MCP Tool Rate Limiting (Our Server)
```
Per-tool limits:
  - get_technician_jobs: 10 queries/minute, 100/hour
  - list_technicians: 5 queries/minute (cached)
  - get_business_summary: 5 queries/minute, 20/hour

Enforcement: Token bucket algorithm
On limit hit: Return error with retry-after time
```

#### Query Constraints
```
Date ranges:
  - Max range: 90 days per query
  - Default: "last week" = Monday-Sunday

Technician names:
  - Max length: 100 characters
  - Allowed chars: Letters, spaces, hyphens only (regex: ^[A-Za-z\s\-]+$)
  - Fuzzy matching: Case-insensitive substring match

Result limits:
  - Jobs per query: Max 1000 (paginate if needed)
  - Technicians list: All active (typically <50)
```

#### Network & Timeouts
```
HTTP timeouts:
  - Connection: 5 seconds
  - Read: 10 seconds
  - Total: 30 seconds

Retry logic:
  - Max retries: 3
  - Backoff: Exponential (1s, 2s, 4s)
  - Retry on: Network errors, 5xx responses
  - No retry on: 4xx responses, auth failures
```

### Secrets Management

**Development (.env file):**
```bash
# .env (NEVER COMMIT)
ST_CLIENT_ID=your_client_id_here
ST_CLIENT_SECRET=your_client_secret_here
ST_APP_KEY=your_app_key_here
ST_TENANT_ID=your_numeric_tenant_id
ST_AUTH_URL=https://auth.servicetitan.io/connect/token
ST_API_BASE=https://api.servicetitan.io

# Logging
LOG_LEVEL=INFO  # DEBUG for development
LOG_FILE=logs/mcp_server.log
```

**Production (if deploying to server):**
- Use environment variables or AWS Secrets Manager
- Rotate credentials every 90 days
- Alert on failed authentication attempts

**Critical: What MUST be in .gitignore:**
```
.env
.env.*
credentials.json
token.json
*.key
*.pem
logs/*.log
__pycache__/
*.pyc
.pytest_cache/
venv/
.venv/
```

### Data Privacy & PII Minimization

**What we NEVER expose to Claude:**
```
❌ Customer names
❌ Customer addresses
❌ Customer phone numbers
❌ Customer email addresses
❌ Job descriptions (may contain PII)
❌ Raw ServiceTitan API responses
```

**What we DO expose (aggregated only):**
```
✅ Technician names (employees, not PII)
✅ Job counts
✅ Date ranges
✅ Job statuses (completed, cancelled, etc.)
✅ Revenue totals (aggregated)
✅ Business unit names
```

**Data Flow with PII Scrubbing:**
```
ServiceTitan API → Our server → Aggregate/anonymize → Claude
                                       ↓
                              [Customer data removed]
```

---

## Project Documentation

### Required Reading (Before Coding)

1. **BUILD_APP.md** — The ATLAS+S workflow (read this first!)
   - This is your roadmap for secure application development
   - Follow the A → T → L → A → S → S → M process

2. **SERVICETITAN_MCP_PROJECT_PLAN.md** — This project's complete architecture
   - Created by following BUILD_APP.md ATLAS+S workflow
   - Contains: Architecture, Security design, Implementation details, Testing strategy

3. **CLAUDE.md** — Security rules and coding standards
   - Input validation requirements
   - Secrets management rules
   - Error handling standards
   - OWASP alignment

### ServiceTitan API Documentation

- **API Docs:** https://developer.servicetitan.io/
- **OAuth Guide:** https://developer.servicetitan.io/docs/authentication
- **API Reference:** https://api.servicetitan.io/swagger/v2 (requires login)

### Code Organization

```
servicetitan-mcp-server/
├── CLAUDE.md                         # Security standards (from framework)
├── BUILD_APP.md                      # ATLAS+S workflow (from framework)
├── CLAUDE.project.md                 # This file (project-specific)
├── SERVICETITAN_MCP_PROJECT_PLAN.md  # Architecture (ATLAS+S output)
├── README.md                         # Setup and usage instructions
├── servicetitan_mcp_server.py        # Main MCP server (9 tools)
├── servicetitan_client.py            # ServiceTitan API wrapper
├── models.py                         # Pydantic models
├── query_validator.py                # Input validation + sanitization
├── cache.py                          # Redis caching (optional)
├── config.py                         # Load .env, validate settings
├── logging_config.py                 # Structured logging setup
├── tests/
│   ├── test_api_client.py
│   ├── test_query_validator.py
│   ├── test_mcp_tools.py
│   └── conftest.py                   # pytest fixtures
├── .env.example                      # Template (safe to commit)
├── .env                              # Real credentials (NEVER COMMIT)
├── .gitignore
├── requirements.txt                  # Production dependencies
├── requirements-dev.txt              # Development dependencies
└── logs/                             # Log files (gitignored)
```

---

## Development Workflow

### Before Writing Code (Critical!)

1. **Read BUILD_APP.md ATLAS+S workflow** (if you haven't already)
2. **Review SERVICETITAN_MCP_PROJECT_PLAN.md** (architecture plan)
3. **Review CLAUDE.md** (security rules)
4. **Check this file** (project-specific config)
5. **Verify ServiceTitan API access** (test OAuth flow)

### Before Every Commit

```bash
# Code quality
black .                    # Format code
ruff check .               # Linting

# Security
pip-audit                  # Check for vulnerabilities
python -m pytest tests/    # Run tests
grep -r "client_secret" . --exclude-dir=venv  # Check for leaked secrets

# All clear? Commit.
git add .
git commit -m "description"
```

### Pre-Commit Hooks (Recommended)

Install with:
```bash
pip install pre-commit
pre-commit install
```

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.1.1
    hooks:
      - id: black
  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: v0.1.13
    hooks:
      - id: ruff
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.1
    hooks:
      - id: gitleaks
```

---

## Testing Requirements

### Unit Tests (pytest)

**Required coverage:**
- `query_validator.py` — All validation logic
- `servicetitan_client.py` — OAuth flow, API calls (mocked)
- `cache.py` — Cache hit/miss logic

**Example test:**
```python
def test_technician_name_validation():
    # Valid names
    assert validate_name("Freddy Smith") == "Freddy Smith"
    assert validate_name("Mary-Anne") == "Mary-Anne"
    
    # Invalid names (should raise)
    with pytest.raises(ValueError):
        validate_name("Freddy; DROP TABLE users;")
    with pytest.raises(ValueError):
        validate_name("../../../etc/passwd")
```

### Integration Tests

**Required scenarios:**
- OAuth token acquisition and refresh
- API call with valid token
- API call with expired token (auto-refresh)
- Rate limit handling
- Network timeout handling

### Security Tests

**Required checks:**
- Prompt injection attempts blocked
- PII not in tool responses
- Secrets not in logs or errors
- Rate limiting enforced
- Invalid input rejected

**Example test:**
```python
def test_prompt_injection_blocked():
    malicious_query = "Freddy'; DROP TABLE technicians; --"
    with pytest.raises(ValueError, match="Invalid name format"):
        TechnicianJobQuery(technician_name=malicious_query)
```

---

## Claude Desktop Integration

### Configuration File

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows (IMPORTANT — UWP app path):**
Claude Desktop on Windows is a Windows Store (UWP/MSIX) app. The config file
is **not** at `%APPDATA%\Claude\` — it's at:
```
%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

Working config (server reads credentials from `.env` automatically):

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

All paths must be absolute. The server anchors all relative paths to the script's
own directory, so it runs correctly regardless of what working directory
Claude Desktop uses to launch the subprocess.

### Testing MCP Server in Claude

1. **Restart Claude Desktop** after updating config
2. **Open a new chat**
3. **Verify tools loaded:** Look for ⚡ (tools) indicator
4. **Test query:** "How many jobs did Freddy do last week?"
5. **Check logs:** `tail -f logs/mcp_server.log`

---

## Deployment

### Phase 1: Local Development (Current)
```bash
# Set up environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Configure secrets
cp .env.example .env
# Edit .env with real credentials

# Test OAuth
python -c "from servicetitan_client import ServiceTitanClient; import asyncio; asyncio.run(ServiceTitanClient().ensure_authenticated())"

# Run MCP server
python servicetitan_mcp_server.py

# In another terminal, configure Claude Desktop and test
```

### Phase 2: Production (Optional - VPS with VPN)

Only if you want remote access:
```bash
# Deploy to small VPS (DigitalOcean, AWS EC2, etc.)
# Use systemd service
# Restrict network access (VPN only)
# Store secrets in AWS Secrets Manager
# Set up monitoring and alerting
```

**For now, local-only is sufficient and more secure.**

---

## Common Commands

### Development
```bash
# Activate environment
source venv/bin/activate

# Run server (local testing)
python servicetitan_mcp_server.py

# Run tests
pytest tests/ -v

# Check for vulnerabilities
pip-audit

# Format code
black .
ruff check --fix .

# Type checking (optional, if using mypy)
mypy servicetitan_mcp_server.py
```

### ServiceTitan API Testing
```bash
# Test connection via the built-in check command
python servicetitan_mcp_server.py --check

# Manual OAuth test (requires jq)
curl -X POST https://auth.servicetitan.io/connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$ST_CLIENT_ID" \
  -d "client_secret=$ST_CLIENT_SECRET" | jq

# Manual API call (with token from above)
curl https://api.servicetitan.io/settings/v2/tenant/{ST_TENANT_ID}/technicians \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "ST-App-Key: $ST_APP_KEY" | jq
```

### Debugging
```bash
# Watch logs in real-time
tail -f logs/mcp_server.log

# Test individual components
python -c "from query_validator import TechnicianJobQuery; print(TechnicianJobQuery(technician_name='Freddy').get_date_range())"

# Check if Claude Desktop sees the server
# (No direct command - just test in Claude UI)
```

---

## Notes for Claude

### When Building This MCP Server

1. **Start with ATLAS+S:** Follow BUILD_APP.md step-by-step
   - We're currently in **A — Assemble** phase
   - Architecture is complete (see SERVICETITAN_MCP_PROJECT_PLAN.md)

2. **Security first:**
   - Input validation before ANY API call
   - PII minimization in ALL responses
   - Secrets NEVER in logs or errors
   - Read-only enforcement at API and code level

3. **Code structure:**
   - Keep modules focused (<200 lines per file)
   - Use Pydantic for all data validation
   - Use structlog for all logging (JSON format)
   - Async everywhere (httpx, MCP server)

4. **Testing strategy:**
   - Mock ServiceTitan API in tests (use `responses` library)
   - Test security edge cases (injection, PII leakage)
   - Test error handling (network failures, auth errors)

### When Adding Features

1. **Update SERVICETITAN_MCP_PROJECT_PLAN.md** first
2. **Add tool to MCP server** with input schema
3. **Add validation** in query_validator.py
4. **Add API method** in servicetitan_client.py
5. **Write tests** before implementing
6. **Aggregate data** (no raw PII)
7. **Add to README.md** for documentation

### Dark Software Principles (Level 2-3)

**Good defaults:**
- "last week" → Monday-Sunday of previous week
- No end_date → Use start_date as single day
- Ambiguous technician → List matches, ask user

**Helpful errors:**
- "No technician named 'Freddie' found. Did you mean 'Freddy Smith'?"
- "Date range too large. Please use a range of 90 days or less."
- "ServiceTitan API is temporarily unavailable. Showing cached data from 5 minutes ago."

**Proactive insights (Level 3, future):**
- "Freddy completed 12 jobs last week, which is 20% above his average."
- "Tuesday was Freddy's busiest day with 4 jobs."

### Never

- Expose raw ServiceTitan API responses
- Log OAuth tokens or API responses with PII
- Skip input validation ("trust" Claude to send valid data)
- Use string concatenation for any queries
- Hardcode credentials or tenant IDs
- Return more data than needed (PII minimization)
- Auto-execute without validation

---

## Changelog

### 2026-02-19 — Appointment Schedule Tools
- Added `get_technician_schedule` and `compare_technician_hours` tools
- Confirmed `jpm/appointments` endpoint with `technicianId`, `startsOnOrAfter`, `startsBefore` params
- Confirmed unavailable: `payroll/jobs`, `timetracking/timesheets`, `jpm/time-entries` (all 404)
- Schedule tools show scheduled hours only (no actual clock-in/out data available via API)

### 2026-02-19 — Revenue & Performance Tools
- Added 4 tools: `get_technician_revenue`, `get_revenue_summary`, `get_no_charge_jobs`, `compare_technicians`
- Refactored `query_validator.py` — `DateRangeQuery` base class, `TechnicianJobQuery` extends it
- Added `technicianId` to `_SAFE_JOB_FIELDS` (internal numeric ID, not PII)
- Server now has 9 tools total

### 2026-02-18 — Assemble Phase Complete
- Implemented all core modules: `config.py`, `logging_config.py`, `servicetitan_client.py`, `query_validator.py`, `servicetitan_mcp_server.py`
- Confirmed ServiceTitan API endpoints (`settings/technicians`, `jpm/jobs`)
- Fixed absolute path anchoring so Claude Desktop can launch server from any working directory
- Discovered and documented UWP config path for Claude Desktop on Windows
- Server confirmed live: all 3 tools tested against real production data

### 2026-02-18 — Project Initialization
- Created project structure per ATLAS+S workflow
- Defined security architecture (OAuth, PII minimization, rate limiting)
- Documented OAuth flow and API integration
- Established PII minimization requirements

---

## Success Criteria (from ATLAS+S Architect phase)

**Week 1 Goal:**
- Wife can ask "How many jobs did Freddy do last week?" and get accurate answer in <3 seconds

**Production Ready When:**
- ✅ Read-only enforcement verified (cannot POST/PUT/DELETE)
- ✅ No PII leakage possible (only aggregated data returned)
- ✅ Rate limiting prevents abuse (10/min, 100/hour enforced)
- ✅ Error handling prevents crashes (all exceptions caught)
- ✅ Wife uses it without developer help
- ✅ Response time acceptable (<10 seconds)
- ✅ No credentials ever exposed (scrubbed from logs/errors)

---

**This file is the project-specific configuration. Update it as the project evolves. Always refer back to BUILD_APP.md for the development methodology.**
