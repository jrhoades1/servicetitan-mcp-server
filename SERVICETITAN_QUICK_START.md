# ServiceTitan MCP Server — Quick Start Guide

## How These Files Work Together

You now have a **complete, integrated framework** for building your ServiceTitan MCP server:

### The Framework Files (Copy These)

1. **FINAL_CLAUDE.md** → Rename to `CLAUDE.md`
   - **What:** Security rules, code quality standards, development philosophy
   - **When:** Auto-read by Claude at start of every session
   - **Contains:** Input validation, secrets management, OWASP alignment, zero-trust principles

2. **FINAL_BUILD_APP.md** → Rename to `BUILD_APP.md`
   - **What:** ATLAS+S workflow — your development methodology
   - **When:** Reference throughout development (you're following it now!)
   - **Contains:** 6-step secure development process (Architect → Trace → Link → Assemble → Stress-test → Secure → Monitor)

3. **FINAL_SETUP_GUIDE.md** → Rename to `SETUP_GUIDE.md`
   - **What:** Beginner-safe Claude Code setup
   - **When:** Setting up new environments or onboarding
   - **Contains:** Installation steps, security training, safe usage patterns

### Your Project Files (Already Created)

4. **SERVICETITAN_CLAUDE_PROJECT.md** → Copy to `CLAUDE.project.md`
   - **What:** Project-specific configuration for THIS ServiceTitan MCP server
   - **When:** Read by Claude alongside CLAUDE.md
   - **Contains:** Python stack, ServiceTitan API details, rate limits, secrets config, testing requirements

5. **SERVICETITAN_MCP_PROJECT_PLAN.md** → Keep as reference
   - **What:** Complete architecture created by following BUILD_APP.md ATLAS+S workflow
   - **When:** Reference during development
   - **Contains:** Full A→T→L→A→S→S→M breakdown with code examples

---

## How They Reference Each Other

```
CLAUDE.md (rules) ──────────┐
                            ├──> Every Claude session reads these
BUILD_APP.md (process) ─────┤
                            │
CLAUDE.project.md ──────────┘
(project config)

      │
      │ References
      ↓

SERVICETITAN_MCP_PROJECT_PLAN.md
(Created BY following BUILD_APP.md ATLAS+S)
      │
      │ Implementation guide
      ↓
   Your code
```

**The flow:**
1. **BUILD_APP.md** defines the ATLAS+S process
2. **SERVICETITAN_MCP_PROJECT_PLAN.md** is the output of following that process
3. **CLAUDE.project.md** tells Claude the project-specific details
4. **CLAUDE.md** enforces security rules throughout

---

## Step-by-Step Setup

### Step 1: Create Project Folder

```bash
mkdir servicetitan-mcp-server
cd servicetitan-mcp-server
```

### Step 2: Copy Framework Files

```bash
# Copy and rename the three framework files
cp /path/to/FINAL_CLAUDE.md ./CLAUDE.md
cp /path/to/FINAL_BUILD_APP.md ./BUILD_APP.md
cp /path/to/FINAL_SETUP_GUIDE.md ./SETUP_GUIDE.md

# Copy your project-specific files
cp /path/to/SERVICETITAN_CLAUDE_PROJECT.md ./CLAUDE.project.md
cp /path/to/SERVICETITAN_MCP_PROJECT_PLAN.md ./SERVICETITAN_MCP_PROJECT_PLAN.md
```

Your folder now looks like:
```
servicetitan-mcp-server/
├── CLAUDE.md                         ← Security rules (framework)
├── BUILD_APP.md                      ← ATLAS+S workflow (framework)
├── SETUP_GUIDE.md                    ← Setup guide (framework)
├── CLAUDE.project.md                 ← Project config (yours)
└── SERVICETITAN_MCP_PROJECT_PLAN.md  ← Architecture (yours)
```

### Step 3: Set Up Python Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install mcp httpx pydantic python-dotenv structlog pytest responses
```

### Step 4: Create Secrets File

```bash
# Copy the example
cp .env.example .env

# Edit with your credentials
nano .env  # or use your editor
```

Add your ServiceTitan credentials:
```bash
SERVICETITAN_CLIENT_ID=your_client_id_here
SERVICETITAN_CLIENT_SECRET=your_secret_here
SERVICETITAN_TENANT_ID=your_tenant_id
SERVICETITAN_API_BASE_URL=https://api.servicetitan.io/v2
```

### Step 5: Create .gitignore

```bash
cat > .gitignore << 'GITIGNORE'
# Secrets (CRITICAL)
.env
.env.*
credentials.json
token.json
*.key
*.pem

# Python
__pycache__/
*.pyc
venv/
.venv/
.pytest_cache/

# Logs
logs/
*.log

# IDE
.vscode/
.idea/
GITIGNORE
```

### Step 6: Initialize Git

```bash
git init
git add .
git commit -m "Initial commit: Framework files and project structure"
```

**Verify no secrets committed:**
```bash
git log --all -- .env
# Should return nothing
```

### Step 7: Start Building

**Tell Claude:**
```
I'm building a ServiceTitan MCP server. Please:

1. Read CLAUDE.md for security rules
2. Follow BUILD_APP.md ATLAS+S workflow
3. Read CLAUDE.project.md for project specifics
4. Reference SERVICETITAN_MCP_PROJECT_PLAN.md for the architecture

We're currently in the "A — Assemble" phase. Let's start by implementing 
the ServiceTitan API client with OAuth authentication.
```

---

## What Claude Will Do

When you say that, Claude will:

1. ✅ Read `CLAUDE.md` → Understand security rules
2. ✅ Read `BUILD_APP.md` → Know to follow ATLAS+S
3. ✅ Read `CLAUDE.project.md` → Get Python/MCP specifics
4. ✅ Read `SERVICETITAN_MCP_PROJECT_PLAN.md` → See the architecture

Then Claude will start implementing following:
- **CLAUDE.md** security rules (input validation, secrets management)
- **BUILD_APP.md** ATLAS+S Assemble phase guidance
- **CLAUDE.project.md** project-specific constraints
- **SERVICETITAN_MCP_PROJECT_PLAN.md** architecture and code examples

---

## File Reference Quick Guide

### "How do I...?"

**Q: How do I handle secrets?**
→ See `CLAUDE.md` section "No Hardcoded Secrets"
→ See `CLAUDE.project.md` section "Secrets Management"

**Q: What's the OAuth flow?**
→ See `SERVICETITAN_MCP_PROJECT_PLAN.md` section "L — Link"
→ See `CLAUDE.project.md` section "Authentication & Authorization"

**Q: How do I validate input?**
→ See `CLAUDE.md` section "Input Validation Is Mandatory"
→ See `SERVICETITAN_MCP_PROJECT_PLAN.md` code example in "A — Assemble"

**Q: What tools should the MCP server expose?**
→ See `SERVICETITAN_MCP_PROJECT_PLAN.md` section "MCP Tools to Implement"

**Q: How do I test this?**
→ See `BUILD_APP.md` section "S — Stress-test"
→ See `CLAUDE.project.md` section "Testing Requirements"

**Q: What security threats am I defending against?**
→ See `SERVICETITAN_MCP_PROJECT_PLAN.md` section "A — Architect" → Threat Model
→ See `BUILD_APP.md` section "T — Trace" → Security Attack Scenarios

**Q: How do I deploy this?**
→ See `SERVICETITAN_MCP_PROJECT_PLAN.md` section "Deployment Plan"
→ See `CLAUDE.project.md` section "Claude Desktop Integration"

---

## Why This Structure Works

### Without BUILD_APP.md Reference:
- ❌ No methodology (just ad-hoc coding)
- ❌ Security added as afterthought
- ❌ No testing strategy
- ❌ No deployment plan

### With Full Framework:
- ✅ **BUILD_APP.md** provides the ATLAS+S process
- ✅ **SERVICETITAN_MCP_PROJECT_PLAN.md** is the output of following that process
- ✅ **CLAUDE.md** enforces security at code level
- ✅ **CLAUDE.project.md** provides project specifics
- ✅ Everything references everything else coherently

---

## Your Current Status

**ATLAS+S Progress:**
- ✅ **A — Architect** (Problem defined, threat model complete)
- ✅ **T — Trace** (Architecture designed, security framework defined)
- ✅ **L — Link** (ServiceTitan OAuth documented, .env template ready)
- ⏳ **A — Assemble** ← **YOU ARE HERE** (Ready to write code)
- ⏳ **S — Stress-test** (Testing plan ready)
- ⏳ **S — Secure** (Security audit checklist ready)
- ⏳ **M — Monitor** (Logging strategy defined)

---

## Next Command

```bash
# You're ready. Tell Claude:
```

**Start the Assemble phase:**
```
Following BUILD_APP.md ATLAS+S workflow, we're now in the "A — Assemble" phase.

Please implement the ServiceTitan API client (servicetitan_client.py) with:
- OAuth 2.0 authentication
- Automatic token refresh
- Read-only enforcement
- Error handling per CLAUDE.md standards
- Rate limiting hooks

Reference the code example in SERVICETITAN_MCP_PROJECT_PLAN.md section 
"A — Assemble" → "API Client (servicetitan_client.py)"
```

---

**You now have a complete, integrated, production-ready framework. Let's build.** 🚀
