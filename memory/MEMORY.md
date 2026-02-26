# Persistent Memory

> Curated long-term facts. Read at session start. Keep under ~200 lines.

## Identity
- Project: ServiceTitan MCP Server
- Project Code: ALD-SERVICETITAN
- Client: American Leak Detection Jupiter
- Developer: Jimmy
- Billing: Retainer

## Stack
- Language: Python 3
- Framework: MCP (Model Context Protocol) server
- APIs: ServiceTitan (OAuth 2.0 Client Credentials)
- Tools: analysis, jobs, recall, revenue, schedule modules

## Key Paths
- tools_*.py — MCP tool modules (analysis, jobs, recall, revenue, schedule)
- servicetitan_client.py — API client wrapper
- query_validator.py — Input validation for queries
- shared_helpers.py — Shared utility functions
- requirements/ — Requirements documents

## Learned Behaviors
- ServiceTitan credentials in .env only
- Validate all query inputs before API calls
- Rate limiting on ServiceTitan API
