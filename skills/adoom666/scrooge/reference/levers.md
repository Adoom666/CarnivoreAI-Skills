# Levers

Seven levers, L1 to L7, listed in a suggested starting order. Rank them for your own setup with the scanner output; the order here is guidance, not a measurement. Mechanics here were observed on Claude Code 2.1.284; re-check on your version. Every lever: know how to revert, and back up any CLAUDE.md / AGENTS.md with `scripts/backup.sh` before an agent-applied edit. Settings, hooks and agent files are never written by the agent: print the snippet in this file and let the user apply it. Mechanics referenced here are in [mechanics.md](mechanics.md).

## L1 Model tiering and routing
- **What:** default workers to Sonnet, Haiku for mechanical work with one right answer, Opus only for judgment. Opus is allowed for a numbered reason only: (1) design with no settled spec, (2) security or adversarial review of a finished diff, (3) unknown-root-cause debugging after a cheaper model failed, (4) executing an irreversible operation. Implementation from a spec goes to Sonnet, even for security code; Opus then reviews the diff.
- **Apply (user applies; snippets below):**
  - The four agent files (Snippet A). Frontmatter sets model, effort and maxTurns, so each dispatch sets both model and effort (a dispatch call cannot set effort, so agents otherwise inherit the session's; observed on Claude Code 2.1.284).
  - The sub-agent default-model env var (Snippet C) so an omitted model is not the expensive parent model.
  - Built-in general-purpose, Explore and Plan agents must always get an explicit model. The model-default hook (Snippet B) fills it in for Explore and Plan.
  - A rule in the orchestrator's instructions (CLAUDE.md / AGENTS.md, through the backup-diff-yes gate): every dispatch names its tier fresh, never copied from an earlier brief, and "any doubt goes up a tier" is not allowed (there is always doubt).
- **Audit first:** in the scanner output look at agent type x model. Explicit `model: opus` on general-purpose build agents is a common leak, distinct from the named judgment agent.
- **Optional hard lock (prose only, no script):** a PreToolUse hook on `Agent|Task` that rewrites or blocks `model: opus` for any agent other than the judgment agent. Tradeoff: a legitimate one-off Opus use must go through the judgment agent.
- **Risk:** quality drop on genuinely hard tasks; keep the four reasons honest and keep security review on the top tier. Extra turns on a cheaper model can cost time.
- **Verify:** spawn one agent per tier and extract only the model field, for example `grep -o '"model":"[^"]*"' <transcript> | sort | uniq -c`; never print or read message text; in particular spawn one judgment/heavy agent after setting the default-model env var and confirm it was not downgraded. Rescan and compare the model mix.
- **Revert:** the user deletes the agent files, unsets the env var, removes the hook entry.

## L2 Bounded workers
- **What:** one bounded task per worker, about 100 tool calls; at that point (or when context bloats) the worker writes progress and the next step to a progress file and returns a HANDOFF line (the worker writes its progress to a file and stops, so a fresh worker can continue). A fresh worker continues from the file. `maxTurns` about 150 in agent frontmatter is only the backstop, so the handoff can still be written before the hard stop.
- **Why:** cost per turn scales with context, and long-running threads reach 300K+ context where each call is the priciest.
- **Apply:** the bound and the return contract are in the agent snippets (Snippet A); also put them in the orchestrator's rules (CLAUDE.md / AGENTS.md, gated). Give every brief a progress-file path.
- **Risk:** more handoffs cost coordination; keep tasks sized so most finish inside the bound.
- **Verify:** scanner: threads with more than ~150 calls, and the share of spend in 300K+ context, should fall.
- **Revert:** raise maxTurns, drop the bound from the rules.

## L3 Rule-file and memory trims
- **What:** shrink what loads into every session and sub-agent: CLAUDE.md / AGENTS.md chain, MEMORY.md index, `rules/*.md`. Move rare procedures to on-demand skills and history/rationale to docs. Main-session-only rules can move to a file the user injects with a SessionStart hook (advice; the user sets that up).
- **Apply:** follow [trim-playbook.md](trim-playbook.md), including its mandatory rule-loss check. The agent edits only CLAUDE.md / AGENTS.md, behind the backup-diff-yes gate; trims to other files are shown as proposed diffs.
- **Sizing:** roughly 250 tokens per KB (bytes/4), paid on every call of every spawn; measure first-call context instead of guessing.
- **Risk:** silently dropping a rule (security rules can be dropped by accident). Never skip the loss check.
- **Verify:** rule-loss check; scanner median first-call context per agent type (after `/compact` or a new session).
- **Revert:** restore from the backup manifest.

## L4 Skill listing cut
- **What:** every sub-agent receives the skill listing.
- **Controls (the user applies them):** `disable-model-invocation: true` in a SKILL.md hides it from models but keeps `/name`; `skillOverrides` in settings can switch off claude.ai-synced skills (`anthropic-skills:*`); observed on 2.1.284: skillOverrides did not affect plugin skills, use `enabledPlugins` (set false) to drop a whole plugin; `disallowedTools: Skill` in an agent's frontmatter removes the list for that agent type (already in the grunt agent, Snippet A). The settings keys are in Snippet C.
- **Verify:** compare a new sub-agent's first-call context size (scanner output); never print or read message text.
- **Risk:** hiding a skill you actually want a model to invoke automatically. **Revert:** undo the settings/frontmatter change.

## L5 Stop resuming workers
- **What:** SendMessage to a finished or turn-limited sub-agent re-sends and re-caches its whole context.
- **Apply:** rule "never resume a large worker; start a fresh one from its progress file". Resume only small contexts. Goes into CLAUDE.md / AGENTS.md through the gate.
- **Verify:** scanner "SendMessage calls" count (includes ordinary messages, so read alongside cost). **Revert:** drop the rule.

## L6 Compaction and effort discipline
- **Autocompact override:** lowers average context; more compactions and lost detail. Choose from your own context-bucket data ([mechanics.md](mechanics.md) has the formula). Snippet C gives an example value only.
- **Effort:** change it only at session start or after `/clear` (mid-session change invalidates the cache, ~$1.50 at 300K on Opus; computed at Opus 5.5 rates: 300K tokens x $5/MTok 5-minute cache write = $1.50).
- **Verify:** scanner compactions count and 300K+ bucket share before/after. **Revert:** the user unsets the env var.

## L7 Cache TTL
- The 1-hour TTL bills cache writes at 2x the input price instead of 1.25x (1.6x the 5-minute write price; env var `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h` for sub-agents), and results depend on the setup. The default TTL is 1 hour on a subscription and 5 minutes on an API key or cloud provider, so this only matters on the latter. It pays only when gaps between calls are usually over 5 minutes but under 1 hour, and often.
- **Apply (advice for the user):** measure your own gaps between calls and the 5m vs 1h write split (scanner cost split) before switching. Default: leave it off.
- **Revert:** the user unsets the TTL env var.

---

## Paste-ready snippets

Show this to the user. Do not write it to any file; the user decides whether to apply it.

### Snippet A: agent tier files

Four files, each saved by the user as `.claude/agents/<name>.md` (project) or `${CLAUDE_CONFIG_DIR:-~/.claude}/agents/<name>.md` (global). If an agent with the same name exists, the user renames the new one and its `name:` field.

Show this to the user. Do not write it to any file; the user decides whether to apply it.

**builder.md**
```markdown
---
name: builder
description: DEFAULT worker for bounded real work: implementing from a clear spec, code in a known pattern, localized bug fixes, tests, docs, single-module refactors.
model: sonnet
effort: medium
maxTurns: 150
---

You are a build worker. Do the edits yourself; do not spawn sub-agents. Test only what the change touches.
Bounded: one task, about 100 tool calls. At about 100 calls, or if your context is bloated, write progress plus the next step to the progress file named in the brief (else a new file in the project scratch dir) and return `HANDOFF: <path>`. A fresh worker continues from it; do not expect to be resumed.
Return contract: exactly one of `DONE` + 1-2 lines, `FAILED: <one-line reason>`, `NEEDS_CLARIFICATION` (blocking question plus options), or `HANDOFF: <path>`. No code or log dumps. Anything else (a plan, an interim result) is not a finished turn.
Stop and ask instead of guessing when the instructions are ambiguous, information is missing, or success criteria are unclear.
```

**grunt.md**
```markdown
---
name: grunt
description: Mechanical, fully specified work with one right answer: file reads, grep and summarize, renames, formatting, deterministic transforms, compressing verbose tool output, one-shot API or CLI calls.
model: haiku
effort: low
maxTurns: 40
disallowedTools: Skill
---

You are a fast executor. Do exactly the specified task, nothing more. Do not spawn sub-agents.
Return contract: `DONE` or `FAILED: <one-line reason>`, then at most 2 lines. No code or log dumps unless asked.
```

**heavy.md**
```markdown
---
name: heavy
description: Judgment tier. The dispatch must cite one numbered reason: (1) design with no settled spec, (2) security or adversarial review of a finished diff, (3) unknown-root-cause debugging after a cheaper model failed, (4) executing an irreversible operation. Never for building from a spec.
model: opus
effort: high
maxTurns: 150
---

You are the senior engineer for high-stakes judgment. Do the work yourself; do not spawn sub-agents.
Allowed reasons: 1 design with no settled spec; 2 security or adversarial review of a finished diff; 3 unknown-root-cause debugging after a cheaper model failed; 4 executing an irreversible operation.
If the brief gives no numbered reason, or the task is implementation from a spec, stop and return `NEEDS_CLARIFICATION`: that is builder work.
At about 100 tool calls write progress to the progress file named in the brief and return `HANDOFF: <path>`.
Return contract: `DONE` + 1-2 lines, `FAILED: <reason>`, `NEEDS_CLARIFICATION`, or `HANDOFF: <path>`.
```

**verifier.md**
```markdown
---
name: verifier
description: Read-only checking: confirm or refute a specific claim against real code or live data, fact-check a document, validate results. Never edits.
model: sonnet
effort: high
maxTurns: 60
---

You are a read-only verifier. Prove or disprove the claim with file:line or command evidence. Do not edit files and do not spawn sub-agents.
Return contract: verdict `CONFIRMED`, `PARTLY`, or `NOT CONFIRMED`, plus at most 6 lines of evidence.
```

### Snippet B: model-default hook script

Fills in a model for Explore and Plan dispatches that omit one. It only takes effect if the user also registers it in settings (the `PreToolUse` entry in Snippet C). The user would save it as `${CLAUDE_CONFIG_DIR:-~/.claude}/hooks/agent-model-default.sh`.

Show this to the user. Do not write it to any file; the user decides whether to apply it.

```bash
#!/bin/bash
# PreToolUse hook, matcher "Agent|Task".
# Built-in Explore and Plan agents inherit the parent model, so under an Opus main session they run on Opus.
# When the dispatch gives no model for one of them, fill in "sonnet". Everything else passes through untouched.
# Fail-open: missing jq or malformed input exits 0 with no output. Emits no permissionDecision.
# (Verified on Claude Code 2.1.284: updatedInput alone is honored. Re-check on your version.)
command -v jq >/dev/null 2>&1 || exit 0
IN=$(cat) || exit 0
printf '%s' "$IN" | jq -ce '
  select((.tool_input.subagent_type == "Explore" or .tool_input.subagent_type == "Plan")
         and ((.tool_input.model // "") == ""))
  | {hookSpecificOutput: {hookEventName: "PreToolUse", updatedInput: (.tool_input + {model: "sonnet"})}}
' 2>/dev/null
exit 0
```

### Snippet C: settings keys

To be merged by the user into their own settings, not pasted over existing hooks or env.

Show this to the user. Do not write it to any file; the user decides whether to apply it.

```json
{
  "_comment": "MERGE these keys into $CLAUDE_CONFIG_DIR/settings.json (default ~/.claude/settings.json) (or a project's .claude/settings.local.json to trial). Do not paste over existing hooks/env. Remove every key starting with an underscore. Values shown are examples, not recommendations.",
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet",
    "_subagent_model_warning": "After setting this, spawn one judgment/heavy agent and extract only its model field to confirm the env var did not downgrade it. Precedence was observed on Claude Code 2.1.284 only: re-check on your version.",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "60",
    "_autocompact_note": "Percent of (window - 20k), capped at window - 33k. Lower = smaller average context (cheaper turns) but more frequent compaction and lost detail. Pick from your own scan_spend.py context-bucket data; there is no universal number. Unset to keep the default."
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent|Task",
        "hooks": [{ "type": "command", "command": "bash \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/agent-model-default.sh\"" }]
      }
    ]
  },
  "skillOverrides": {
    "_comment": "Switches off claude.ai-synced skills (names like anthropic-skills:*). Observed on 2.1.284: it did not affect plugin skills; use enabledPlugins for those.",
    "anthropic-skills:example-skill": "off"
  },
  "enabledPlugins": {
    "_comment": "false drops the whole plugin, and its skills, from every listing.",
    "example-plugin@example-marketplace": false
  }
}
```
