# Test Script — 4 New Analysis Tools

Restart Claude Desktop first, then paste each prompt into a new chat.
Check that the tool fires, returns data, and contains NO customer PII.

---

## Pre-flight: Confirm all 15 tools loaded

> List all the tools you have available from ServiceTitan.

**Expected:** 15 tools listed, including the 4 new ones at the bottom.

---

## Test 1: get_technician_job_mix

> What job types does Freddy G do? Break down his job mix for the last 90 days.

**Check:**
- Tool `get_technician_job_mix` fires (not a different tool)
- Shows job types with counts, revenue, avg $/job per type
- Shows % of jobs and % of revenue per type
- No customer names/addresses in output

**Follow-up (edge case — bad name):**

> Show job mix for "ZZZZNOTANAME" for the last 30 days.

**Expected:** Friendly error listing available technicians.

---

## Test 2: compare_technician_job_mix

> Compare all technicians by job type for the last 90 days.

**Check:**
- Tool `compare_technician_job_mix` fires
- Shows matrix: each job type with all techs underneath
- Company avg $/job shown per type
- Per-tech variance from avg (e.g., "+$50" or "-$30")
- No customer PII

**Follow-up (single type filter):**

> Compare all technicians on just RSLD jobs for the last 90 days.

**Expected:** Only RSLD type shown, all techs compared.

---

## Test 3: get_cancellations

> How many cancellations were there in the last 60 days? How many were late?

**Check:**
- Tool `get_cancellations` fires
- Shows total cancels, late cancels (within 24h of appointment)
- Per-tech breakdown with cancel counts
- Tags shown as cancel reason proxy
- "Hours before appt" timing shown per cancel
- No customer names/addresses/summaries

**Follow-up (late-only filter):**

> Show only the late cancellations from the last 60 days.

**Expected:** Only cancels where hours_before <= 24.

**Follow-up (tech filter):**

> Show cancellations for Freddy G in the last 60 days.

**Expected:** Only Freddy's cancels shown.

---

## Test 4: get_technician_discounts

> Show discount activity for the last 90 days.

**Check:**
- Tool `get_technician_discounts` fires
- Shows per-tech: discount count, total discount amount, common SKUs
- Company totals at bottom
- No customer names, addresses, or invoice descriptions in output

**Follow-up (tech filter):**

> Show discounts for Freddy G in the last 90 days.

**Expected:** Only Freddy's discount activity.

**Follow-up (minimum amount filter):**

> Show discounts over $100 for the last 90 days.

**Expected:** Only discounts where amount >= $100.

---

## Test 5: Regression — existing tools still work

> Compare all technicians for last week.

**Expected:** `compare_technicians` fires, leaderboard with jobs/revenue/$/job.

> Show revenue trend by job type for the last 90 days.

**Expected:** `get_revenue_trend` fires, monthly breakdown by job type.

> What does Freddy G's schedule look like this week?

**Expected:** `get_technician_schedule` fires, day-by-day appointments.

---

## Red flags to watch for

- Any customer name appearing in output
- Any street address or phone number
- Tool returning raw JSON instead of formatted text
- "Error: 401" or "Error: 403" (auth issue — re-run --check)
- "Error: 404" on a new endpoint (invoice or tag-type endpoint regression)
- Tool not found (module not imported — check servicetitan_mcp_server.py imports)
