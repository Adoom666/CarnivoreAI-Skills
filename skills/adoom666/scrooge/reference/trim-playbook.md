# Rule-file trim playbook

Mechanics used here (SessionStart hooks, the `disable-model-invocation` skill flag, `disallowedTools`) were verified on Claude Code 2.1.284; re-check on your version.

Goal: shrink what loads into every session and sub-agent without losing a single rule (roughly 250 tokens per KB by bytes/4). Common trap: security rules dropped by accident.

**Write policy.** The agent edits only CLAUDE.md and AGENTS.md, and only through this gate: back up with `scripts/backup.sh`, show the user the diff, apply after the user says yes. Any other file (MEMORY.md and topic files, `rules/*.md`, settings, hooks, agent files) is never written by the agent: show the proposed change as a diff or snippet and let the user apply it.

## 1. Back up
Run `scripts/backup.sh` on every CLAUDE.md / AGENTS.md file you will touch. It writes a timestamped copy at the original absolute paths, a `MANIFEST.sha256` and `RESTORE.txt`. Never edit before this exists.

## 2. Sort each piece of text into one of four homes
| Home | What belongs | How it loads |
|---|---|---|
| Always-loaded | Only what every worker truly needs: hard safety rules, return contract, worker bounds | CLAUDE.md chain |
| Main-session-only | Orchestrator rules: dispatch tiers, merge coordination | Advice for the user: a file outside `rules/`, injected by a SessionStart hook the user sets up (first line: "workers ignore this block") |
| On-demand skills | Rare procedures, checklists | Skill (consider `disable-model-invocation: true`) |
| Docs | History, rationale, incident write-ups, status tables | Linked from the rules, read when needed |

Move text; do not delete rules. Tell the user which rules were moved or dropped and why, and give them the proposed skill, doc, decisions-file or MEMORY.md text to save themselves (MEMORY.md works best as one short line per memory, details in topic files). The agent writes only CLAUDE.md and AGENTS.md.

## 3. Rule-loss check (ALWAYS, after the trim)
Split every old rule file into rule units (bullets, sentences with must/never/always). For each unit, find where it lives now (new files plus their destinations) and classify:
- **HOMELESS**: gone.
- **WEAKENED**: partly kept (a condition, an exception or a "never" was lost).
- **DANGLING**: points at a file or heading that no longer exists.
- **GLOBAL-ONLY**: survives only in a file someone else controls (for example a user-level file this project cannot rely on).

Fix every HOMELESS, WEAKENED and DANGLING item, and decide GLOBAL-ONLY items explicitly. This check catches rules dropped by accident (for example a pre-commit diff-review rule or a stop-on-credentials rule). Fix forward, then rerun the check. Some setups refuse Write from sub-agents, so have the checker return its findings as text.

## 4. Verify size
After `/compact` or a new session, scan and compare the median first-call context per agent type (scripts/scan_spend.py --compare). Confirm the drop; roughly 250 tokens per KB (bytes/4). Only threads whose first call is inside the scan window count.

## 5. Git repos
If the rule files live in a git repo, the agent does not commit or push; it shows the diff, and the user commits it their way.

## 6. Time rules: when and how (SKILL.md Part 2)
- When: after the token levers, and only for rules whose cost is real in your data (slow tests, waits, rework loops, idle workers). Skip infrastructure rules (6-10) unless the named cost shows up.
- How: pick the few rules that fit, put worker rules in the always-loaded CLAUDE.md / AGENTS.md (through the gate above), suggest a main-session file for orchestrator rules as advice, and tell the user the choice. Rules marked REVIEW weaken review or verification: apply them only by the owner's explicit decision, never for security-sensitive changes.
- Verify by measuring wall-clock per task before and after; expect little or no time saved from the token levers alone; measure it yourself.

## 7. Solo users
One session, no sub-agents: do sections 1-4 for your CLAUDE.md / AGENTS.md (and propose MEMORY.md trims as diffs), then stop.
