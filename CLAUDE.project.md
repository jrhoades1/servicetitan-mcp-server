> \*\*Important:\*\* This project follows the \*\*BUILD\_APP.md ATLAS+S workflow\*\*. 

> The complete architecture plan is in `SERVICETITAN\_MCP\_PROJECT\_PLAN.md`, 

> which was created by following the ATLAS+S methodology step-by-step.

```



\*\*It includes:\*\*

\- Current ATLAS+S phase tracking (you're in "A — Assemble")

\- Python/MCP stack details

\- ServiceTitan API configuration

\- Security requirements (OAuth, PII minimization, rate limiting)

\- Testing requirements

\- Claude Desktop integration

\- \*\*References to BUILD\_APP.md throughout\*\*



\### \*\*2. SERVICETITAN\_QUICK\_START.md\*\*

A visual guide showing \*\*how all 5 files work together\*\*:

```

CLAUDE.md (rules) ──────────┐

&nbsp;                           ├──> Claude reads these

BUILD\_APP.md (process) ─────┤

CLAUDE.project.md ──────────┘

&nbsp;        ↓ references

SERVICETITAN\_MCP\_PROJECT\_PLAN.md (output of following BUILD\_APP.md)

&nbsp;        ↓ guides

&nbsp;   Your code

