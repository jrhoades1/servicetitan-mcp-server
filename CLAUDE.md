# CLAUDE.md — ServiceTitan MCP Server

> Address the developer as **Jimmy**.

## Project

MCP server for **American Leak Detection** that enables natural language queries of ServiceTitan business data via Claude Desktop. Read-only, PII-minimized, production-grade.

See `CLAUDE.project.md` for API endpoints, MCP tools, env vars, Claude Desktop config, and full technical details.

## Core Philosophy

> **DSF Motto:** Eliminate the human from the loop. Every process should trend toward full automation.

- **Autonomy first** — if a request adds human intervention, flag it and propose an automated alternative
- Security is not optional — if uncertain, fail closed
- If a decision trades convenience for security, choose security
- If complexity increases attack surface, simplify
- Think step-by-step before writing any code
- Ask Jimmy for clarification before writing large amounts of code if ambiguous
- Prefer smaller, focused functions (<150 lines) — easier to review for security flaws and comprehend at a glance. Composition over inheritance

## Planning (Before Writing Any Code)

1. Understand the task completely
2. Check `.claude/skills/` for an existing skill that matches the task
3. Check `requirements/` for existing specs
4. Review existing patterns in the codebase
5. For data handling, tools, or user input: perform quick security assessment
6. Ask Jimmy for clarification if anything is unclear

## How to Operate

1. Read `CLAUDE.project.md` first — it has the complete API reference and tool inventory
2. **Find the skill first** — Check `.claude/skills/` before starting any task. Don't improvise when a skill exists.
3. Check `requirements/` for existing specs before building
4. Follow the CITADEL workflow in `BUILD_APP.md` for new features
5. For any new tool: add validation in `query_validator.py`, scrub PII, update all docs
6. Ask Jimmy if anything is unclear

## Model Selection

- **Haiku** — Mechanical file operations, data formatting, deterministic tasks.
- **Sonnet** — Structured extraction, pattern matching, scoring, code generation, standard analysis. The workhorse.
- **Opus** — Persuasive writing, nuanced reasoning, creative positioning, strategic advice, complex multi-step analysis.

Don't default to Opus out of caution. Be honest about what each task actually requires.

## Session Start

Every new conversation begins with the session-start protocol (see `.claude/rules/session-start.md`). Run `python3 hooks/session_status.py`, read memory + logs, give Jimmy a quick briefing, ask what to work on.

During session: append notable events, decisions, and completed tasks to today's log.

## Rules (auto-loaded from `.claude/rules/`)

- **security-standards.md** — OWASP, input validation, merge checklist
- **guardrails.md** — Blocked commands, protected files
- **memory-protocol.md** — Session continuity via daily logs
- **billing-protocol.md** — Project code: `ALD-SERVICETITAN`
- **analysis-protocol.md** — 6-dimension completion check
- **session-start.md** — Briefing protocol at conversation start

## Guardrails & Security

See `.claude/rules/guardrails.md` for safety rules and `.claude/rules/security-standards.md` for the full security standards. Key principle: when uncertain about intent, ask rather than guess.

## Project-Specific Security

- Never expose raw ServiceTitan API responses to users
- Never log OAuth tokens, secrets, or PII
- All tool inputs validated via Pydantic (treat as untrusted)
- Read-only: only GET requests allowed (enforced in `servicetitan_client.py`)
- PII scrubbed before any data reaches Claude (customer names, addresses, phones)
- Use structlog for all logging (JSON format)
- Format with Ruff before submitting
