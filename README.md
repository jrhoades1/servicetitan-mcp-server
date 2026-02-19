# ServiceTitan MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that connects Claude Desktop to your ServiceTitan account at American Leak Detection.

Ask Claude natural language questions about technician jobs and business performance — without exposing any customer personal information.

## What You Can Ask

```
"How many jobs did Freddy do last week?"
"How much revenue did Tom bring in last week?"
"What was total business revenue last week?"
"Compare all technicians for last week — who brought in the most?"
"How many no-charge jobs were there last week?"
"What does Freddy's schedule look like this week?"
"Who had the most scheduled hours last week? Who started earliest?"
"List all active technicians."
```

## How It Works

Claude Desktop → MCP Server → ServiceTitan API (read-only)

All data is aggregated before being returned to Claude. Customer names, addresses, and contact information are **never** sent to Claude — only job counts, statuses, revenue totals, and technician names.

---

## Prerequisites

- Python 3.11 or newer
- A ServiceTitan developer account with API credentials
- Claude Desktop installed on Windows

---

## Setup

### 1. Clone and create virtualenv

```bash
git clone <repo-url> servicetitan-mcp-server
cd servicetitan-mcp-server
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

Copy the example env file and fill in your ServiceTitan credentials:

```bash
copy .env.example .env
```

Edit `.env`:

```env
ST_CLIENT_ID=your_client_id_here
ST_CLIENT_SECRET=your_client_secret_here
ST_APP_KEY=your_app_key_here
ST_TENANT_ID=your_numeric_tenant_id
ST_AUTH_URL=https://auth.servicetitan.io/connect/token
ST_API_BASE=https://api.servicetitan.io
```

> **Where to find these:** ServiceTitan Developer Portal → Your App → Credentials.
> `ST_TENANT_ID` is the numeric ID visible in your ServiceTitan URL.

### 3. Test the connection

```bash
python servicetitan_mcp_server.py --check
```

Expected output:
```
Connection OK — ServiceTitan authentication successful.
You can now add this server to Claude Desktop.
```

If this fails, double-check your `.env` credentials.

---

## Claude Desktop Configuration

> **Windows note:** Claude Desktop is a Windows Store (UWP) app. The config file is
> **not** in the standard `%APPDATA%\Claude\` folder — it's in the MSIX package location.

### Config file location (Windows)

```
%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

Open that file in a text editor. Add the `mcpServers` block (update the paths to match your installation):

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

> Use the full absolute path — Claude Desktop can launch this server from any working directory.

### Apply the config

Fully quit and restart Claude Desktop after editing the config file.

In a new chat, you should see the tools indicator (⚡ or a hammer icon) confirming the server loaded.

---

## Available Tools (9 total)

### Job Tools

#### `list_technicians`
Lists all active technicians. Optionally filter by name.

**Example:** "List all technicians" or "Find technicians named Danny"

#### `get_technician_jobs`
Shows job counts for a specific technician over a date range, broken down by status.

**Parameters:** `technician_name`, `start_date`, `end_date`

#### `get_jobs_summary`
Shows job totals across all technicians for a date range.

**Parameters:** `start_date`, `end_date`

### Revenue Tools

#### `get_technician_revenue`
Revenue breakdown for a specific technician — total revenue, billed vs no-charge, and revenue per job.

**Parameters:** `technician_name`, `start_date`, `end_date`

#### `get_revenue_summary`
Business-wide revenue totals for a date range.

**Parameters:** `start_date`, `end_date`

#### `get_no_charge_jobs`
Count and percentage of no-charge jobs in a date range.

**Parameters:** `start_date`, `end_date`

#### `compare_technicians`
Leaderboard comparing all technicians: jobs, revenue, revenue per job, and no-charge count. Sorted by revenue descending.

**Parameters:** `start_date`, `end_date`

### Schedule Tools

#### `get_technician_schedule`
Day-by-day appointment schedule for a specific technician, showing start/end times and status.

**Parameters:** `technician_name`, `start_date`, `end_date`

#### `compare_technician_hours`
Compares all technicians by scheduled appointment hours and earliest start time. Sorted by hours descending.

**Parameters:** `start_date`, `end_date`

> **Note:** Schedule tools show *scheduled* appointment hours — not actual clock-in/out times (clock data is not available via the ServiceTitan API).

---

All date parameters default to last full Monday–Sunday week when omitted. Maximum date range is 90 days.

---

## Logs

The server writes structured JSON logs to `logs/mcp_server.log`. Useful for debugging:

```bash
# Watch logs in real time (Git Bash / PowerShell)
Get-Content logs\mcp_server.log -Wait -Tail 20
```

Logs never contain credentials, OAuth tokens, or customer personal information.

---

## Troubleshooting

### Server doesn't appear in Claude Desktop

1. Run `--check` to verify credentials work
2. Confirm the config file is in the correct UWP path (see above)
3. Fully quit Claude Desktop (check Task Manager — it may still be running in the background) and relaunch

### "No technician found matching..."

The name search is case-insensitive substring matching. Try a shorter fragment:
- "Danny R" → works
- "danny" → works
- "Danny Roe" → fails if actual name is "Danny R"

Run `list_technicians` to see exact names.

### Date range errors

- Dates must be in `YYYY-MM-DD` format
- Maximum range is 90 days
- Defaults automatically to last Monday–Sunday

### Authentication errors

Token expires every 15 minutes but refreshes automatically. If you see auth errors, check that your `ST_CLIENT_SECRET` in `.env` is current. Credentials may need rotation in the ServiceTitan developer portal.

---

## Adding New Tools

See `CLAUDE.project.md` → "Adding New Features" for the step-by-step process.

The general pattern:

1. Add a new `@mcp.tool()` function in `servicetitan_mcp_server.py`
2. Add input validation in `query_validator.py`
3. Add the API call (GET only) in `servicetitan_client.py`
4. Scrub PII before returning data
5. Update this README with the new tool

---

## Security

- **Read-only:** The server can only make GET requests. POST/PUT/DELETE raise an immediate error.
- **PII minimization:** Customer names, addresses, emails, and phone numbers are stripped from all API responses before processing.
- **Credential safety:** OAuth tokens and secrets are never written to logs or returned to users.
- **Input validation:** All tool inputs are validated with Pydantic before making any API call.

---

## Development

```bash
# Activate environment
venv\Scripts\activate

# Format code
black .
ruff check --fix .

# Security audit
pip-audit

# Run tests (once tests/ is built)
pytest tests/ -v
```
