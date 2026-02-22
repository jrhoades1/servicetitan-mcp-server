# CLAUDE.md — AI Development Standards (Secure by Default)

> **Instruction Confirmation:** Always address the developer as **Jimmy** in conversation, commit messages, and PR descriptions. This confirms you are reading and following these instructions.

---

## Related Workflow Documents

- **`BUILD_APP.md`** — The CITADEL v4.0 project methodology. Read this at the start of any new project or feature build before writing code. It includes: Zero-Trust architecture, Enterprise secrets management, API security hardening, Performance vs security trade-offs, full Look (monitor) step, and Incident Response playbook.
- **`CLAUDE.project.md`** *(per-repo)* — Project-specific overrides: tech stack, CLI tools, doc references, package manager. Always check for this file in the project root.
- **`SETUP_GUIDE.md`** — For onboarding new team members or setting up new development environments. Contains beginner-safe instructions for Claude Code setup.

---

## Project Context

This is a TypeScript-based project. All code must prioritize:

- Security
- Predictability
- Maintainability
- Minimal dependency surface
- Safe handling of untrusted input

> **Stack-specific rules** (framework, CLI tools, package manager) live in `CLAUDE.project.md` in each repo root. Always check there first.

---

## Core Development Philosophy

- Prefer smaller, focused components and functions over large monolithic ones (ideally < 150 lines)
- Follow existing patterns and conventions in the codebase
- Prefer composition over inheritance
- Think step-by-step before writing any code
- Ask for clarification before writing large amounts of code if the task is ambiguous
- If a decision trades convenience for security, choose security
- If uncertain, fail closed
- If complexity increases attack surface, simplify
- **Security is not optional**

---

## Cost Tracking & Client Billing

Every Claude Code CLI session is automatically logged to
`C:\Users\Tracy\Projects\claude-tracking\sessions.csv` via a global Stop hook
in `~/.claude/settings.json`. Each project must have `.claude/project-code.txt`
for accurate attribution.

### Setup for a new billable project
1. Create `.claude/project-code.txt` in the project root with one line: the project code
2. Create `.claude/billing.json` for expense tracking (see schema below)
3. (Optional) Add a project-specific `ANTHROPIC_API_KEY` to `.env` for exact API cost tracking
4. Add the project code to the table below

### Active project codes
| Code | Project | Client | Billing method |
|------|---------|--------|----------------|
| ALD-SERVICETITAN | ServiceTitan MCP Server | American Leak Detection | Retainer |

### Rate card
Update with your actual rates before billing:
- **Retainer / internal projects:** Included in monthly fee — log tokens for internal allocation
- **Billable API work:** check Anthropic Console (filter by project API key) for exact USD
- **Billable subscription work:** session count × your internal hourly/session rate

### Per-project expense tracking
Create `.claude/billing.json` in the project root to track hosting, domains,
API costs, software licenses, and one-time purchases. These merge into the
monthly report alongside token usage automatically.

```json
{
  "version": 1,
  "expenses": [
    {
      "id": "unique-slug",
      "description": "Human-readable name",
      "category": "hosting|domain|api|software|license|one-time",
      "amount": 20.00,
      "type": "recurring",
      "frequency": "monthly|quarterly|yearly",
      "start_date": "YYYY-MM-DD",
      "end_date": null,
      "notes": ""
    }
  ]
}
```

For one-time expenses, use `"type": "one-time"` and `"date": "YYYY-MM-DD"`
instead of `frequency`/`start_date`/`end_date`.

**Month attribution:** Monthly = every month while active. Quarterly = every 3 months
from start_date. Yearly = anniversary month only. One-time = month of purchase only.

### Generating a monthly invoice line item
```bash
python C:\Users\Tracy\Projects\claude-tracking\report.py --month YYYY-MM
```
Output lists sessions, tokens, and expenses by project. For API-billed projects,
cross-reference the Anthropic Console filtered by the project's API key for exact USD cost.

---

## Requirements Management

Each project has a `requirements/` directory containing structured specs as markdown files
with YAML frontmatter. This is the spec pipeline — structured requirements that Claude
can read and implement autonomously.

### How it works
- **One file per requirement:** `requirements/REQ-NNN-short-slug.md`
- **YAML frontmatter:** machine-parseable metadata (status, priority, dates, author)
- **Markdown body:** Problem, Solution, Acceptance Criteria, Technical Notes, Decision Log
- **Per-project workflow:** `requirements/_workflow.yml` defines statuses and transitions

### Who creates requirements
- **Jimmy** writes requirements for features, changes, and bug fixes
- **Claude** can propose requirements (`status: proposed`, `author: claude`) when noticing
  gaps or improvements — but does NOT implement until Jimmy approves
- Nothing moves from `proposed` to `approved` without Jimmy's sign-off

### Using requirements
- Before starting work, check `requirements/` for existing specs
- To implement: "implement REQ-003" — Claude reads the spec, builds it, checks off criteria
- Claude updates status dates and Decision Log as work progresses
- See `FINAL_REQUIREMENTS_TEMPLATE.md` for the full file format and field reference

### Cross-project report
```bash
python C:\Users\Tracy\Projects\claude-tracking\req_report.py
python C:\Users\Tracy\Projects\claude-tracking\req_report.py --project ALD-SERVICETITAN
python C:\Users\Tracy\Projects\claude-tracking\req_report.py --status proposed --detail
```

---

## Documentation to Reference

Before starting work in any project, check for these files (paths may vary by repo):

- `requirements/` — structured requirements (check for specs before building)
- `docs/STORAGE_MANAGER.md` — how persistent data and user assets are handled
- `docs/ADDING_ASSETS.md` — adding new images, videos, fonts, etc.
- `docs/COMPONENT_PATTERNS.md` — standard component structures and naming
- `docs/STYLE_GUIDE.md` — CSS/styling conventions

---

## Planning (Do This Before Writing Any Code)

1. Understand the task completely
2. Check for a `CLAUDE.project.md` in the project root and read it
3. Read relevant documentation files listed above
4. Review existing similar components/files for patterns
5. Plan the file structure and component breakdown
6. For tasks involving data handling, external tools, or user input:
   - Perform a quick security assessment (injection risks, sensitive data exposure, dependency issues)
7. Ask Jimmy for clarification if anything is unclear

---

## Core Security Principles

### 1. No Hardcoded Secrets

- Never hardcode API keys, tokens, credentials, or private URLs
- Use environment variables or a secrets manager for all secrets
- Never log secrets or sensitive values — scrub them from error messages and stack traces
- Never expose secrets to the client bundle
- Use automated secret scanning in CI (e.g., `gitleaks`, GitHub secret scanning, `trufflehog`)

### 2. Input Validation Is Mandatory

Treat all external input as untrusted, including:

- File uploads, JSON payloads, form input
- URL parameters, HTTP headers, filenames
- Media metadata, remote URLs

Always:

- Validate type, size, and format
- Enforce strict schemas for JSON (use Zod or equivalent)
- Reject unexpected or extra fields
- Fail closed, not open

### 3. Logging Hygiene

- Never log PII, credentials, tokens, or sensitive identifiers
- Use structured logging with explicit field control
- Sanitize error messages before surfacing them to users or logs
- Do not log full request bodies unless necessary and scrubbed
- Detailed errors go to server-side logs only — never to users

---

## CLI Tool Safety Rules (Non-Negotiable)

> CLI tools available in a given project are defined in `CLAUDE.project.md`. These rules apply universally to all of them.

Tools like `magick`, `ffmpeg`, `jq`, and `exiftool` are high risk when used on untrusted input.

### Never:
- Interpolate user input directly into shell commands
- Use `sh -c` with user-controlled content
- Execute commands built from string concatenation
- Allow arbitrary file paths from user input
- Allow network-based inputs unless explicitly approved

### Always:
- Pass arguments as arrays (no shell parsing)
- Use `--` to terminate options before file arguments
- Read only from a controlled, validated upload directory
- Write only to a controlled output directory
- Enforce strict resource limits (see project file for values)
- Prefer running processing inside a sandbox or container

---

## Resource Limits (Required Where Applicable)

> Specific values (max file size, resolution caps, etc.) are defined in `CLAUDE.project.md`. The categories below are mandatory wherever these tools are in use.

### Images (e.g., ImageMagick)
- Maximum file size and pixel count
- Maximum frame count for animated formats
- Strip all metadata by default
- Harden tool configuration (disable dangerous coders, limit memory/time)

### Video (e.g., ffmpeg)
- Maximum duration and resolution
- Disable network protocols
- Use `-nostdin`; enforce CPU/memory/time limits

### JSON parsing
- Maximum file size and nesting depth
- Timeout on parsing
- Reject extremely large arrays or deeply nested objects

### API & Rate Limiting
- Enforce rate limits on all endpoints that accept external input or trigger processing
- Apply stricter limits to unauthenticated requests
- Return `429 Too Many Requests` with `Retry-After` headers

---

## Media Handling Requirements

- Strip EXIF metadata unless explicitly required
- Validate MIME type and file signature (magic bytes) — do not trust file extensions
- Never allow path traversal (`../` or encoded variants)
- Do not overwrite arbitrary files
- Never allow writes outside controlled directories
- Quarantine uploads before processing; move to permanent storage only after validation passes

---

## Web Application Security

### XSS Protection
- Never use raw HTML injection unless sanitized with an allowlist parser (e.g., DOMPurify)
- Escape all user-generated content before rendering
- Sanitize Markdown rendering
- Prefer safe templating over raw HTML

### SSRF Protection
If fetching remote URLs:
- Block private IP ranges (10.x, 172.16.x, 192.168.x, 127.x, 169.254.x)
- Block localhost and cloud metadata endpoints (e.g., `169.254.169.254`)
- Enforce protocol allowlist (https only)
- Set request timeouts and response size caps
- Cap redirects at 2–3 maximum
- Resolve DNS before connecting and re-validate after resolution

### Authentication & Sessions
- Use `Secure`, `HttpOnly`, and `SameSite=Strict` cookie attributes
- Rotate session tokens on privilege escalation and login
- Never store sensitive tokens in `localStorage` or `sessionStorage`
- Use short-lived tokens with refresh rotation
- Implement account lockout after repeated failed attempts

### CSRF
If using cookie-based auth:
- Require CSRF tokens for all state-changing actions (POST, PUT, PATCH, DELETE)
- Use `SameSite=Strict` as an additional layer

### Content Security Policy (CSP)
- Use a strict Content Security Policy
- Prefer nonces or hashes over allowlisted domains
- **Avoid `unsafe-inline` and `unsafe-eval`** — fix the underlying issue instead
- Do not relax CSP to "make things work"

### Security Headers
Always set:
- `Strict-Transport-Security` (HSTS)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY` (or CSP `frame-ancestors 'none'`)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` to restrict unneeded browser features

---

## Database Security

- Use parameterized queries everywhere — never string concatenation
- Enable Row Level Security (RLS) on all tables containing user data
- Apply principle of least privilege: app user cannot DROP, ALTER, or CREATE
- Use foreign key constraints with appropriate CASCADE rules
- Add CHECK constraints for data validation at the database level
- Require SSL/TLS for all database connections
- Never expose raw database errors to users

---

## AI / LLM Feature Security

If the project includes AI-powered features:

**Input:**
- Sanitize user input before including in prompts
- Validate input length (prevent prompt stuffing)
- Filter instruction-injection patterns (`ignore previous`, `system:`, etc.)
- Rate limit AI endpoints — they are expensive and abuse-prone

**Output:**
- Validate and sanitize AI responses before rendering (XSS prevention)
- Never auto-execute AI-generated code without review
- Set token limits to prevent runaway cost / DoS
- Log AI interactions for abuse detection

**Keys & Cost:**
- Use separate API keys for AI services (easy independent rotation)
- Enforce per-user and per-IP cost limits
- Monitor for abuse patterns

---

## Dependency & Supply Chain Security

- Do not add new dependencies casually — evaluate necessity first
- Prefer standard library or existing approved dependencies
- Pin exact versions via lockfile
- Avoid loose semver ranges (`^`, `~`) for security-sensitive packages
- Avoid unmaintained or abandoned libraries
- Review transitive dependencies for known vulnerabilities
- Verify new packages: maintainer reputation, recent activity, open CVEs, download stats, license

Run before every merge:

```bash
# JavaScript / pnpm (or npm/yarn equivalent)
pnpm lint
pnpm typecheck
pnpm audit

# Python
pip-audit
bandit -r .
```

Use automated scanning in CI:
- Dependabot or Renovate for dependency updates
- CodeQL or Semgrep for static analysis
- `gitleaks` or `trufflehog` for secret scanning
- Generate and store an SBOM for every release

---

## OWASP Alignment

All features must consider the OWASP Top 10 (2021):

- **A01** Broken Access Control
- **A02** Cryptographic Failures / Sensitive Data Exposure
- **A03** Injection (SQL, shell, HTML, prompt, etc.)
- **A04** Insecure Design
- **A05** Security Misconfiguration
- **A06** Vulnerable and Outdated Components
- **A07** Identification and Authentication Failures
- **A08** Software and Data Integrity Failures (supply chain, deserialization)
- **A09** Security Logging and Monitoring Failures
- **A10** Server-Side Request Forgery (SSRF)

Also reference **OWASP Top 10 for LLMs** if the project uses AI features.

If unsure whether something is safe, default to rejecting the input.

---

## Code Quality Standards

- Strict TypeScript — `strict: true` in `tsconfig.json`
- No `any` unless explicitly justified with a comment
- Defensive programming — handle edge cases explicitly
- Clear, explicit error handling with typed error classes
- No silent fallthrough or swallowed exceptions
- No insecure defaults
- Format with Prettier before submitting
- Follow framework-specific best practices defined in `CLAUDE.project.md`

---

## Feature Development Checklist

### Planning (before writing code)
- [ ] Task is fully understood
- [ ] `CLAUDE.project.md` reviewed
- [ ] Relevant docs reviewed
- [ ] Existing patterns reviewed
- [ ] Security assessment performed for any data handling, tool use, or user input

### Before Every Merge

| Area | Required Checks |
|---|---|
| File uploads | Input validation, size limits, MIME/magic byte check, path traversal prevention, quarantine |
| Media processing | Resource limits, sandboxing, argument arrays, no shell injection |
| External fetches | SSRF protections, timeouts, size caps, protocol allowlist |
| Authentication | Token rotation, secure cookies, account lockout, CSRF protection |
| JSON parsing | Size limits, depth limits, schema validation |
| Shell execution | Array arguments, `--` separator, no user input interpolation |
| Database queries | Parameterized only, RLS enabled, least privilege |
| AI features | Input sanitization, output validation, rate limiting, cost controls |
| Dependencies | Audit run, lockfile reviewed, no loose semver |

### Documentation Sync (MANDATORY — after every feature change)
When adding, removing, or modifying any feature, public API, tool, or endpoint:
1. Update **all** documentation that references the changed feature — README, project docs, inline doc comments, module docstrings
2. Check `CLAUDE.project.md` for a project-specific doc-update checklist and follow it exactly
3. Keep counts, tables, and file structure comments in sync with reality
4. Never commit code changes without the corresponding doc updates in the same commit

Documentation drift across sessions is the #1 source of confusion. Treat docs like code — if it's stale, it's a bug.

### Final Steps (always before presenting code)
1. Format code with Prettier
2. Run ESLint and fix all issues (or document why an issue is intentionally ignored)
3. Run TypeScript type-check: `tsc --noEmit`
4. If changes involve dependencies, user input, or asset processing:
   - Run `pnpm audit` (or equivalent) and note any high/critical vulnerabilities
   - Manually check for accidental sensitive data exposure
5. If the change affects UI/UX, briefly describe the visual or behavioral change
6. Present the diff or full files with clear explanations

---

## Default Philosophy

> If a decision trades convenience for security, choose security.
> If uncertain, fail closed.
> If complexity increases attack surface, simplify.
> Security is not optional.

---

## Changelog

### v2.0.0 — Production Hardening (February 2026)
- **Enhanced:** Cross-references to BUILD_APP v4.0 and SETUP_GUIDE v2.0
- **Clarified:** This file is production-ready and tested
- **Confirmed:** All security practices align with CITADEL v4.0 workflow
- Original comprehensive security framework maintained

**This version works in production with BUILD_APP v4.0 and SETUP_GUIDE v2.0.**
