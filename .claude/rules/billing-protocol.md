# Billing Protocol

Cost tracking and session attribution.

## Session Tracking

Sessions logged to `claude-tracking/sessions.csv`. This project uses
`.claude/project-code.txt` for attribution and `.claude/billing.json` for expenses.

## Project Code

| Code | Project | Client |
|------|---------|--------|
| ALD-SERVICETITAN | ServiceTitan MCP Server | American Leak Detection |

## Requirements Management

Each project has `requirements/` with structured specs (YAML frontmatter + markdown).
- One file per requirement: `REQ-NNN-short-slug.md`
- Claude can propose (`status: proposed`) but NOT implement without Jimmy's approval
