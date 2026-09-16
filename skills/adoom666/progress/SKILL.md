---
name: progress
description: Produces a concise, read-only progress report of the CURRENT session — opening with a 1-2 sentence plain-English summary of the overall goal for a non-technical reader, followed by a markdown table of every distinct work item (Done / In Progress / Remaining) with per-item text progress bars, per-row "⚠️ Waiting on you" markers for items blocked on the user, a total aggregate bar, rough time-remaining estimates, and a "waiting on you" roadblocks list. Introspects the live conversation, `TODO.md` in the current working directory if one exists, and any dispatched background sub-agents/tasks via the TaskList tool. Use when the user says "/progress", "progress check", "progress report", "show progress", "where are we", "status update", "how's it going", "how far along are we", or asks for a session status summary. Does NOT write, create, or modify any file (not TODO.md, not a report file) — pure in-chat introspection and rendering. Skip for requests to actually plan, execute, or update TODO.md — this skill only reports on state that already exists.
---

# progress — Session Status Report

Renders a self-contained progress snapshot of the current session directly into the chat response. No file is read for the purpose of writing to it, and nothing is written anywhere — this is a read-only introspection skill. If the user wants TODO.md created or updated, that is a different task; do not do it here.

## What to do when this fires

### 1. Gather state from three sources

- **The live session itself.** Scan back through the conversation: what has the user asked for, what has actually been done (files edited, commands run, agents dispatched and returned), and what was said or implied to still be pending. This is the primary source — the report is about THIS session's real work, not a generic checklist.
- **`TODO.md` in the current working directory**, if one exists. Read it if present. Do not create it if it's absent — that would violate the read-only contract of this skill. If it exists, reconcile its checklist state against what you've actually observed happening in-session (a TODO.md line can be stale — trust direct evidence from the transcript over a checkbox that was never updated).
- **Live background work.** Call `ToolSearch` with a query like `select:TaskList` (or `"list background tasks"` if the exact name isn't known) to load the tool's schema, since it is deferred and not directly callable until its schema is fetched. Then call it to see any sub-agents or background workflows dispatched this session, and use their real current status (running / completed / failed) to correct your classification — a sub-agent you think is "in progress" may have already finished, or one you assumed finished may still be running. If `TaskList` is not available in this environment (ToolSearch returns no match), skip this source silently — do not block or error the report over a missing tool; just rely on the transcript and TODO.md.

### 2. Classify every distinct work item into exactly one bucket

Group related sub-steps into ONE item rather than listing every micro-action — the report must stay scannable at a glance (aim for single digits to ~10 rows even on a busy session). Each item gets exactly one status:

- ✅ **Done** — completed and confirmed in this session
- 🔄 **In progress** — actively being worked on right now (including a background sub-agent still running)
- ⬜ **Remaining** — discussed or implied as needed, but not started

Only report on items that are real — actually discussed, requested, or worked on this session. Never invent filler tasks to pad the table.

### 3. Render one markdown table

Columns: `Item | Status | Progress | Est. Remaining`

- **Item**: a few words, no restating of the full request.
- **Status**: emoji + word (`✅ Done`, `🔄 In Progress`, `⬜ Remaining`).
- **Progress**: a 10-character text bar using `█` for filled and `░` for empty, e.g. `██████░░░░`. Done = `██████████` (full). Remaining = `░░░░░░░░░░` (empty). In-progress = your best-judgment estimate of how far along that specific item is, rounded to the nearest block.
- **Est. Remaining**: a rough time bucket for what's LEFT on that item, always suffixed `(est.)`. Done items get `— (done)` instead of a time estimate. Use these T-shirt buckets as your judgment anchor (not measured data — Claude has no task-duration telemetry):
  - XS ≈ 5 min (est.)
  - S ≈ 15 min (est.)
  - M ≈ 45 min (est.)
  - L ≈ 2 hr (est.)
  - XL ≈ 4 hr+ (est.)

### 4. Render one aggregate bar below the table

One more 10-character `█`/`░` bar representing overall completion across all items. Weight items equally by default. If you deliberately weight unevenly (e.g. one item is clearly 80% of the actual effort), say so in one short clause right next to the bar — don't weight silently.

Below or beside the aggregate bar, give a **total estimated time remaining**: sum only the OPEN items (🔄 + ⬜) — never include done items in the sum. Label it `(est., rough)`.

### 5. Roadblocks section — only if something is actually blocked

If, and only if, one or more items are stalled pending a decision, input, credential, secret, or approval from the user, add a short section at the bottom:

```
⚠️ Waiting on you:
- <item>: needs <specific thing — a decision, a credential, an approval, a missing value>
```

One line per blocked item. If nothing is blocked, omit this section entirely — do not print an empty "no roadblocks" line, that's noise the user didn't ask for.

## Output discipline (the whole point of this skill)

- No preamble. No "Here's your progress report:", no restating the user's request, no closing summary paragraph. The table + bars + (optional) roadblocks section IS the entire response.
- Keep item names short. Collapse sprawling sub-steps under one item instead of a 20-row table.
- Never fabricate progress, completion percentages, or tasks that weren't actually part of this session.
- Every time figure carries `(est.)` so it visibly reads as a judgment call, not a measurement.

## Example output

```
| Item | Status | Progress | Est. Remaining |
|---|---|---|---|
| Lambda log triage script | ✅ Done | ██████████ | — (done) |
| CloudWatch alarm wiring | 🔄 In Progress | ██████░░░░ | S ≈ 15 min (est.) |
| Front-end error banner | 🔄 In Progress | ███░░░░░░░ | M ≈ 45 min (est.) |
| Rollback runbook doc | ⬜ Remaining | ░░░░░░░░░░ | M ≈ 45 min (est.) |
| Staging deploy | ⬜ Remaining | ░░░░░░░░░░ | S ≈ 15 min (est.) |

**Total: ████░░░░░░  (~40% complete, equal weighting) — 2 hr est. remaining (est., rough)**

⚠️ Waiting on you:
- Staging deploy: needs the staging AWS account ID confirmed before the CLI profile can be set
```
