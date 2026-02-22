# Requirements — ServiceTitan MCP Server

Each requirement is a markdown file with YAML frontmatter in this directory.

## File naming

```
REQ-NNN-short-slug.md
```

IDs are sequential and never reused. Use a short lowercase slug describing the feature.

## Creating a requirement

1. Copy the template from the frontmatter below
2. Fill in all fields (use `null` for dates not yet known)
3. Write the Problem, Solution, Acceptance Criteria, and Technical Notes sections
4. Set `status: proposed` and `author:` to your name or `claude`

## Frontmatter template

```yaml
---
id: REQ-NNN
title: Short descriptive title
status: proposed
priority: medium
author: jimmy
requested_by: client
created: YYYY-MM-DD
approved: null
scheduled: null
implemented: null
verified: null
decision: null
tags: []
---
```

## Statuses

| Status | Meaning |
|--------|---------|
| `proposed` | Initial idea — needs Jimmy's review |
| `approved` | Accepted for implementation |
| `rejected` | Not doing this (reason in `decision` field) |
| `deferred` | Good idea but not now |
| `scheduled` | Assigned to a sprint or week |
| `in_progress` | Currently being built |
| `implemented` | Code complete, needs verification |
| `verified` | Tested and confirmed working |

## Workflow rules

- **Jimmy only:** approve/reject proposed items, set priority, verify implemented items
- **Claude can:** create proposed requirements, start scheduled work, mark work as implemented
- See `_workflow.yml` for the full transition map

## Cross-project report

```bash
python C:\Users\Tracy\Projects\claude-tracking\req_report.py
python C:\Users\Tracy\Projects\claude-tracking\req_report.py --project ALD-SERVICETITAN
python C:\Users\Tracy\Projects\claude-tracking\req_report.py --status proposed
```
