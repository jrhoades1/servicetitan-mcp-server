---
id: REQ-001
title: Add unit and integration tests
status: proposed
priority: high
author: claude
requested_by: jimmy
created: 2026-02-22
approved: null
scheduled: null
implemented: null
verified: null
decision: null
tags: [testing, quality, infrastructure]
---

## Problem
The server has 20 live MCP tools with no automated tests. Manual testing via Claude Desktop
is slow and doesn't catch regressions. The CITADEL Drill phase requires functional and
security tests before shipping.

## Solution
Create a `tests/` directory with pytest-based unit and integration tests covering:
- Input validation (Pydantic models in query_validator.py)
- PII scrubbing (shared_helpers.py)
- API client behavior (servicetitan_client.py — mock HTTP responses)
- Tool output format (each tools_*.py module)

## Acceptance Criteria
- [ ] pytest runs successfully with `pytest tests/ -v`
- [ ] Input validation tests cover all 13 Pydantic models
- [ ] PII scrubbing tests verify no customer data leaks
- [ ] API client tests mock HTTP and verify retry/error handling
- [ ] At least one integration test per tool module (mocked API)
- [ ] CI configuration (GitHub Actions) runs tests on push
- [ ] Coverage report generated

## Technical Notes
- Use `pytest` + `pytest-asyncio` for async tool functions
- Use `httpx` mocking (respx or pytest-httpx) for API calls
- conftest.py already exists with dummy credentials for CI
- requirements-dev.txt has pytest listed

## Decision Log
<!-- 2026-02-22 — proposed by claude: server has 20 tools with zero test coverage -->
