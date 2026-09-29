# How Claude Code loads and bills context (mechanics)

Verified on Claude Code 2.1.284. Re-check on your version; prove any claim below with the method noted.

## Measure first
- Every API call is logged in transcript JSONL under `<config dir>/projects/*/` (sub-agent threads in `subagents/`). Price each call from its usage block. Dedupe by message id plus request id (streamed messages repeat; keep the max of each counter).
- Split cost into: input, output, 5-minute cache write, 1-hour cache write, cache read. Break down by model, agent type, project and context bucket (<50K, 50-150K, 150-300K, 300K+). `scripts/scan_spend.py` does all of this.
- Context size x call count is the lever, not output length.
- A sub-agent's first-call context equals its fixed per-spawn overhead: system prompt, tools, the CLAUDE.md chain, the MEMORY.md index and the skill listing.

## What loads into every session and every sub-agent
- The global, project and local CLAUDE.md files and the MEMORY.md index. They are cache-read on every call. Rule of thumb: roughly 250 tokens per KB (bytes/4), paid x calls x spawns.
- `<config dir>/rules/*.md` also auto-loads everywhere. Never park main-session-only rules there.
- Main-session-only rules: advice for the user, who may keep them in a file OUTSIDE that directory and inject it with a SessionStart hook (matcher `startup|resume|clear|compact`, command `cat <file>`). Such a file should start with a line telling any worker that sees it to ignore it, since workers get the block too.
- The skill listing goes to every sub-agent (see levers L4).

## When edits take effect
- A running session caches CLAUDE.md and MEMORY.md at startup and hands that copy to every sub-agent it spawns. Edits reach only sessions started afterwards, or after a compaction.
- Compaction (automatic or `/compact`) re-reads both files. `/compact` is therefore the cheap way to pick up rule edits.
- `claude --resume` also reloads them, but the rule text sits at the front of the prompt, so the whole old conversation is re-cached at write price. Avoid it for a large session.
- Proof method: compare the first-call context size (scanner output) of a sub-agent spawned before and after, and for the model, extract only the model field, for example `grep -o '"model":"[^"]*"' <transcript> | sort | uniq -c`; never print or read message text.

## Compaction
- Autocompact threshold = min(floor((window - 20k) x pct/100), window - 33k) where pct comes from the autocompact override env var. A lower threshold means a smaller average context and cheaper turns, but more compactions and lost detail. It is a tradeoff, not a target.

## Model precedence for a sub-agent
Observed on Claude Code 2.1.284; re-check on yours. Only "the env var does not override `inherit`" is sourced from an explicit test.
1. The Agent tool's `model` parameter.
2. The agent definition's frontmatter `model` (`inherit` beats the env var below).
3. The sub-agent default-model env var (`CLAUDE_CODE_SUBAGENT_MODEL`).
4. The parent's model.

Built-in Explore and Plan are `inherit` and skip CLAUDE.md, so under an Opus main session they run on Opus unless the dispatch passes a model. A PreToolUse hook on the Agent tool can return `hookSpecificOutput.updatedInput` to fill in a missing model; on 2.1.284 no permissionDecision is needed. Proof method: read the spawned sub-agent transcript's `message.model` before and after.

## Cache behavior
- Changing effort mid-session invalidates the prompt cache. At 300K context on Opus that costs about $1.50 (computed at Opus 5.5 rates: 300K tokens x $5/MTok 5-minute cache-write price = $1.50). Change effort only at session start or right after `/clear`.
- The cache TTL is 1 hour on a subscription and 5 minutes on an API key or cloud provider (vendor blog); the 1-hour option on the latter writes at a higher price (see levers L7). The scanner's dollar figures are API list-price equivalents, so on a subscription read them as relative usage.
- Resuming a finished or turn-limited sub-agent (SendMessage) re-sends and re-caches its entire context. Start a fresh worker from a progress file instead.
- A sub-agent stopped by its turn limit returns partial output and asks the parent to resume it. Resuming resets the turn budget. Prevent it with bounded workers (levers L2).
