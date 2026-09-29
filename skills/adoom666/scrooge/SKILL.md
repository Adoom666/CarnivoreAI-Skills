---
name: scrooge
description: Use when you want to audit your Claude Code setup for wasted time, tokens and money. Measures real spend from your own transcripts, finds the biggest leaks (oversized context, wrong model tier, unbounded workers, bloated rule files), trims CLAUDE.md / AGENTS.md after a backup and your yes, prints paste-ready snippets for everything else, and estimates Time Saved % and Tokens Saved %. Invoke with /scrooge.
disable-model-invocation: true
---

# Scrooge: cut Claude Code time, tokens and money

**Warning.** This skill edits your CLAUDE.md / AGENTS.md files, only after backing them up and getting your yes. It never writes settings files, hooks or agent files; it prints those changes for you to apply.

Definitions: **orchestrator** = the main session that plans and dispatches sub-agents. **owner** = the person who owns the repo or setup being changed.

Set once, use in every command below: `SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/scrooge"` (use `<project>/.claude/skills/scrooge` if installed per project).

## Bundled files

- `scripts/scan_spend.py`: read-only spend scanner over your transcript JSONL (step 1 and the before/after compare).
- `scripts/prices.json`: vendor list prices the scanner uses; check it against the vendor pricing page before trusting dollars.
- `scripts/backup.sh`: copies files to a timestamped backup with a checksum manifest and restore notes; run it before any edit.
- `reference/levers.md`: the seven levers (L1-L7), each with apply, verify and revert notes, plus the paste-ready snippets you show the user.
- `reference/trim-playbook.md`: how to trim CLAUDE.md / AGENTS.md safely, with the mandatory rule-loss check.
- `reference/mechanics.md`: how Claude Code loads and bills context (caching, compaction, model precedence, when edits take effect).

## Part 1: The run

**Start here.** Measure first, then recommend only the levers that fit THIS setup, ranked by impact on your own data. Never lose output fidelity: same correctness, same security, same quality. A rule that saves money by shipping worse work is not a saving; skip it and say why. Mechanics below were observed on Claude Code 2.1.284: re-check on your version. Dollar figures are API list-price equivalents: on a subscription, read them as relative usage, not a bill.

**Write policy.** The only files you may edit are the user's CLAUDE.md and AGENTS.md, and only through the gate: (1) back up with `"$SKILL_DIR/scripts/backup.sh" <file>`, (2) show the diff, (3) apply only after the user says yes. Everything else (settings, hooks, agent files, permission lists, env vars, rules or memory files) is shown to the user as a snippet or advice. Say "Show this to the user; do not write it to any file." Never write those yourself.

**The one idea.** Cost is **context size x number of calls**, not output length. Most spend is cache reads of a large context repeated across many turns and many spawned workers. So the levers are: a smaller fixed context (rule files, memory index, skill list), fewer turns per worker (bounded workers), the right model tier, and not paying to rebuild a cache (resumes, mid-session effort changes). Waiting costs no tokens, but a gap longer than the cache TTL forces a full cache rewrite on the next call. Time and tokens are separate levers.

1. **Measure.** `python3 "$SKILL_DIR/scripts/scan_spend.py" --days 7` (add `--root <config dir>` per account; default `$CLAUDE_CONFIG_DIR` or `~/.claude`). Read-only: it reads only token-usage counts, model ids, timestamps, record types, message and request ids (for de-duplication), the names and ids of SendMessage tool calls, project folder names, and each sub-agent's type and short description from its .meta.json; it never prints message text, sends nothing off the machine, and writes nothing (stdout only). It prints aggregates plus project directory names and sub-agent short descriptions, never message content; redact the names and descriptions before sharing the output. Note the total, then the breakdowns by model, agent type, project and context bucket, the top threads, the median first-call context per agent type, compactions and SendMessage calls. That median is the fixed per-spawn overhead, but only for threads whose first call is inside the window (threads begun before `--since`, including resumed main sessions, are skipped). Check `scripts/prices.json` against the vendor pricing page first; models priced by family fallback are listed in a WARNING and unpriced models show "$ unknown".
2. **Diagnose.** Check leaks in this order; each maps to a lever in [reference/levers.md](reference/levers.md):
   - Opus share of spend, and which agent types carry it. Explicit `model: opus` on general-purpose build agents may carry more of the spend than the named judgment agent (the one agent type reserved for the strongest model). (L1)
   - Share of spend on calls with 300K+ context, and threads with hundreds of calls. (L2, L6)
   - Median first-call context per agent type well above the Explore/Plan baseline: rule files, memory index and skill list are paid on every call of every spawn. (L3, L4)
   - Explore/Plan running on the parent model. (L1)
   - SendMessage counts (resumes re-send and re-cache the whole context). (L5)
   - Flag 1-hour cache writes unless the gaps between calls are usually 5-60 minutes. (L7)
3. **Pick levers** by impact on this setup. Suggested starting order, as guidance only: model routing and bounded workers, then rule-file trims, then the skill-list cut (hiding unused skills from the list sent on every call). Rank your own levers with the scanner output; your ordering may differ.
4. **Apply, with the write policy above.**
   - CLAUDE.md / AGENTS.md trims: agent-applied through the gate (backup, diff, user's yes). Follow [reference/trim-playbook.md](reference/trim-playbook.md).
   - Everything else (agent tier files, the model-default hook, env vars, settings keys, skill hiding): print the matching snippet from [reference/levers.md](reference/levers.md) and let the user apply it. Check for name clashes first: if `builder`, `grunt`, `heavy` or `verifier` agents already exist, tell the user to rename the new ones.
   - Mechanics of what loads where: [reference/mechanics.md](reference/mechanics.md). Changes that alter review policy, security gates or release process need the owner's decision: ask, do not assume.
5. **Verify.** (a) Rule-loss check on any edited rule file (trim-playbook). (b) Model proof: for a newly spawned sub-agent, extract only the model field, for example `grep -o '"model":"[^"]*"' <transcript> | sort | uniq -c`; never print or read message text, to confirm the model it actually ran on; if the user set the sub-agent default-model env var, spawn one judgment/heavy agent and confirm the env var did not downgrade it. (c) Rerun the scanner over comparable windows: `scan_spend.py --compare A_since A_until B_since B_until`, judging USD per call and first-call context per agent type, not raw totals. Edits reach running sessions only after `/compact` or a new session; wait for post-change data.
6. **Estimate** (last section), and report a table: lever, status (FITS / ALREADY DONE / DOESN'T FIT + reason / NEEDS OWNER DECISION), what changed or which snippet was printed.

---

## Part 2: Time rules

Writing code takes minutes; waiting takes hours. Real time savings come from process, not model choice: model choice and context trims change speed very little, so expect little or no time saved from the token levers alone; measure it yourself. These rules are where time is won. Apply them with [reference/trim-playbook.md](reference/trim-playbook.md) section 6. Rules that thin out review or verification (marked REVIEW) only apply by the owner's explicit decision, and never for security-sensitive changes.

### Testing
1. **Full pipeline only before a release or version bump.** Full suite, integration gates, screenshot regeneration and sweeps run once per release; a dozen changes share one run. (REVIEW: deferral is the owner's call; security changes still get their proving test.)
2. **Per change, run only in-scope tests:** the test that proves the change plus existing tests of the code it touched (a name-filtered run). No package-wide or "affected" sweeps per change.
3. **Prove a test can fail only when cheap:** run the new test against the old code if that takes seconds. Never build a second environment just for that.
4. **Flakes: rerun only the failing test.** If it passes unchanged, log it (name plus machine load) and move on.
5. **Batch related fixes** into one change so they share one test pass.

### Test infrastructure (one-time investments; each applies only when the named cost is real)
6. If a DB-backed suite spends its time migrating: migrate once into a template and clone it per test or per test process, instead of migrating each time. Keep a switch to the old path.
7. If tests start many database or cache containers: share one per test binary with a logical DB each; give tests that touch server-wide state (pub/sub, flush, config) a dedicated one.
8. If UI verification means booting a full stack: keep one warm reusable stack, lock it while one change uses it, swap only the frontend in, verify, unlock.
9. If a large repo forces the full suite on every change: a dependency-aware "affected tests" selector for the pre-release run, falling back loudly to the full suite when build files change.
10. If tests are heavy: run them on a dedicated machine through one wrapper command, not on the laptop that is also editing.

### Process and merge (several sessions or workers on one repo)
11. **REVIEW: no PRs or issues for routine work**: rebase and push straight to trunk, retry on reject; PRs only for real features or bugs. Only by the owner's explicit decision, never for security-sensitive changes. Keep signed commits, linear history, no force-push.
12. Lock only what truly collides (a generated-bundle rebuild, an install refresh) with one short atomic `mkdir` lock; break it when stale (older than ~30 min or dead pid).
13. **Trivial edits skip workers**: copy, color, string or CSS changes in one or two files are done directly.
14. Hot-sync client-only static changes instead of restarting the service.
15. **Cap concurrent test-heavy workers** (start around 3) and back off above a load threshold with bounded retries.
16. **REVIEW: cut ceremony that never changed an outcome.** Ask how often a mandatory step actually stopped a bad change. Count it: if a mandatory step never blocked anything, it is ceremony. Only by the owner's explicit decision, never for security-sensitive changes.
17. **REVIEW:** validators run once per slice, not per edit, and are skipped when the worker's own automated check passed and was shown able to fail. Only by the owner's explicit decision, never for security-sensitive changes.
18. Run independent work in parallel and pre-stage what later steps need. Parallelism buys wall-clock time; it does not cut the work. Size fan-out by the deadline. (The vendor reports agent teams use about 7x the tokens of one session when teammates run in plan mode.)

### Keeping work alive (dead time)
19. **Never start a long job in the background and then wait on it**; the worker idles and dies unnoticed. Run in the foreground with a bounded timeout, looping past ~10 minutes.
20. **After a rate limit or restart, check real state first** (worktree, trunk log, locks) and continue from the worker's progress file with a FRESH worker. Do not SendMessage-resume a large finished worker: it re-sends and re-caches its whole context. Resume only when its context is small.
21. Workers started before a rule change must be told the new rule, or they finish the old way.
22. An interim reply (a plan, "waiting on X") is not a finished turn. Resend "continue from where you are"; after 2 resends treat it as failed and diagnose.
23. If several sessions share one checkout: refresh installs or builds from the main checkout after a fast-forward merge, not from a linked worktree, and never touch another session's uncommitted files.

### Context hygiene that also saves time
24. Keep the orchestrator thin: reads, searches, analysis and web research go to workers that return a status plus 1-2 lines, never code or log dumps.
25. Brief with file paths, not pasted content; pass state through files. Truncate every command output (`| head -50`), redirect noisy output to a file and grep it.
26. Complete briefs (the exact request, where code likely lives, file ownership, process, "do not spawn sub-agents") stop workers exploring on your dime.
27. Smallest change that solves it; reuse existing code; one bloat pass, then ship. When budget is tight, cut to the one test that proves the change.

---

## Part 3: Solo users (one session, no sub-agents)

Most of Parts 1-2 is about workers and does not apply. What does: (1) rule-file and memory trims (L3), since your whole session pays them every call; (2) the skill-list cut (L4); (3) effort discipline: set effort at session start or after `/clear`, never mid-session (L6); (4) `/compact` (or a new session) to shed a bloated context and to pick up rule edits; (5) the main session's own model choice: Sonnet for routine work, Opus for genuinely hard design or debugging. Skip the L1 routing hook, L2 bounded workers, L5 resumes, the agent-tier snippets and the multi-session time rules. Run the scanner, look at the context buckets and first-call context of your main sessions, and apply only those five.

---

## Part 4: Fidelity guardrails (never cut these to save time or money)

- Never strip validation, error handling, security checks or explicitly requested behavior to be faster or smaller.
- Every change still gets the one test that proves it works. Security fixes are tested through the real production path, never a hand-built one.
- The full suite still runs before every release. It is deferred, not deleted.
- Never downgrade a security review, an irreversible operation or a genuinely unspecified design to a cheaper model without a measured trial showing equal findings. Cheaper tiers do bounded builds; judgment stays on the top tier.
- A trim that moves a rule out of the always-loaded files must land it somewhere that still applies (trim-playbook rule-loss check). Dropped security rules are a defect, not a saving.
- Anything that weakens review or verification needs the owner's explicit decision and is never applied to security-sensitive changes.
- Fast AND correct. When they conflict, correct wins.

---

## Final step: the estimate

After the levers are applied or printed, compare a representative before sample with the same kinds of work under the new rules. Use the scanner's before/after numbers when post-change data exists; otherwise model it and state the assumptions. Give **Time Saved %** (from removed waits, rework loops and ceremony, not from model choice; "~0%" is a legitimate answer), **Tokens Saved %**, and **monthly dollars** from real billed usage by model at current verified rates (a representative week x 4.3 is fine). Fill in only measured or modeled values, and give ranges (for example "3-13%"). Anything unknown stays "?" (for example `$?/mo` when usage or rates cannot support a dollar figure, and say why). Label a modeled figure "modeled, not measured" and a dollar figure an API list-price equivalent, not cash. Name the sample, give a one-line basis per figure, and say which levers drive most of it.

**End the final response with the numbers**, using the sentence pattern "I saved you ?% time, ?% tokens, and $?/mo!" where each `?` is your range or a genuine unknown, never a placeholder number. Put nothing after it.
