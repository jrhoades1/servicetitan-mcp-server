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

## Business Structure
- **Two divisions:** Pool and House (not interchangeable)
- **Pool techs:** Kaleb, Danny, Jason, Freddy
  - Pool leak detection: $395, Spa: $495, plus repairs (variable)
- **House techs:** Dan, Tom, Kris, Neill, Alan
  - Jesse departed March 2026
  - Avg house ticket likely $620-650+ (blended $570 includes pool)
- **Commission rates:** Dan 25%, Danny 23%, all others 21% + 3% quarterly bonus
- **Ken (owner):** Former tech, sensitive about pushing techs too hard
- **Neill:** Injured Q2 2025; when healthy does ~15 jobs/wk but discounts ($510 avg vs $553 house avg), turns away work, and goes home early. ~$170K/yr gap.
- **Alan:** Injured Q3-Q4 2025; when healthy was highest-volume house tech (17.9 jobs/wk)
- **Adam:** Left company, was doing houses (671 jobs, $296K)
- **Jesse:** Departing March 2026 (693 jobs, $392K) — combined with Adam = $688K house revenue lost
- **Kaleb:** NOT underperforming — $618 avg ticket is highest on pool team (does more repairs at ~$1K)
- **In training:** Collin (house), Robert (pool), Chris (pool)
- **Pool pricing:** Pool $395, Spa $495, Repairs ~$1K
- **House avg ticket:** $553 (from ServiceTitan data)
- **Pool avg ticket:** $454
- **Analysis files:** analysis/ directory (comp case, optimization, Ken briefs, pool vs house)

## Learned Behaviors
- ServiceTitan credentials in .env only
- Validate all query inputs before API calls
- Rate limiting on ServiceTitan API
