# CLAUDE.md — ServiceTitan MCP Server

> Address the developer as **Jimmy**.

## Project

MCP server for **American Leak Detection** that enables natural language queries of ServiceTitan business data via Claude Desktop. Read-only, PII-minimized, production-grade.

See `CLAUDE.project.md` for API endpoints, MCP tools, env vars, Claude Desktop config, and full technical details.

## How to Operate

1. Read `CLAUDE.project.md` first — it has the complete API reference and tool inventory
2. Check `requirements/` for existing specs before building
3. Follow the CITADEL workflow in `BUILD_APP.md` for new features
4. For any new tool: add validation in `query_validator.py`, scrub PII, update all docs
5. Ask Jimmy if anything is unclear

## Rules (auto-loaded from `.claude/rules/`)

- **security-standards.md** — OWASP, input validation, merge checklist
- **guardrails.md** — Blocked commands, protected files
- **memory-protocol.md** — Session continuity via daily logs
- **billing-protocol.md** — Project code: `ALD-SERVICETITAN`
- **analysis-protocol.md** — 6-dimension completion check
- **session-start.md** — Briefing protocol at conversation start

## Project-Specific Security

- Never expose raw ServiceTitan API responses to users
- Never log OAuth tokens, secrets, or PII
- All tool inputs validated via Pydantic (treat as untrusted)
- Read-only: only GET requests allowed (enforced in `servicetitan_client.py`)
- PII scrubbed before any data reaches Claude (customer names, addresses, phones)
- Use structlog for all logging (JSON format)
- Format with Ruff before submitting
