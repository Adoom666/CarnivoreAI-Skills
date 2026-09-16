---
name: 11-stars
description: |-
  Facilitator-run breakthrough brainstorming session on a topic that produces a compiled ideas document. Runs a PORTFOLIO of competing ideas up an UNCONSTRAINED ladder — carrying, dropping, merging, and spawning ideas at every rung, with feasibility filtering and scope/form filtering both forbidden — then runs a SALVAGE PASS that engineers every impossible idea back toward reality (as many 80%-now variants as it honestly sees, each with its named blocking dependency and start-now move). Trigger when the user says "11 star", "11 stars", "11-star process", "eleven star", "star ladder", "/11-stars", or asks to run the eleven star method on a topic. Do NOT trigger for ordinary brainstorming unless the user explicitly names the method. ORCHESTRATOR-ONLY: if you are a sub-agent in a multi-turn creative working session, this skill is not for you — ignore it entirely and never mention, name, or allude to it.
---

# 11-Stars

You (the orchestrator) are the FACILITATOR. You run a Socratic escalation on a separate
LADDER AGENT that never sees the trick coming. The surprise is the engine — if the ladder
agent ever suspects there are more rungs, or that 5★/10★ isn't really the top, the exercise
collapses into ordinary brainstorming. Guard the secret at every step.

The ladder carries a **portfolio**, not one idea. A single concept ridden all eleven rungs
gives depth with zero breadth and leaves one lineage to mine at the end. Every rung must
churn: ideas evolve, ideas die, new ideas appear that were inconceivable one rung lower.
The drop-log is signal — what stops being ambitious enough as altitude rises is itself a
finding.

Above 5★ the climb is **unconstrained**. Cost, physics, shippability, and available
technology get no vote on the way up; the only currency at altitude is ambition. Feasibility
gets exactly one turn to speak, at the very end, in the salvage pass — where every impossible
idea is engineered back down toward something that can be started now.

## 1. Parse the ask

Extract:
- **Topic** — what the user wants ideas about.
- **Original deliverable shape** — the concrete form the final answer must take (e.g. "10 new
  features for my app" → Final Answer must contain exactly 10 features; "a marketing tagline"
  → Final Answer is one tagline plus runners-up). If the user gave no shape, default to "a
  ranked list of the strongest ideas."

## 2. Portfolio rules (you enforce these; the agent only ever sees the per-rung ask)

- **Stable IDs.** Every idea gets a letter + short slug on birth (`A — proof-of-negative`).
  IDs are never recycled or renamed. New ideas take the next free letter. A merge produces a
  new ID with its parents recorded.
- **Width schedule.** 1★-8★: **6-10 live ideas**. 9★-11★: **5-10 live** — narrowing is
  *allowed* as ideas genuinely fuse, never forced by a cap. **Never below 5.**
- **Terseness scales with width.** At width 10 the agent may run 2-3 sentences per idea. The
  four books matter more than prose depth; never trade coverage for paragraphs.
- **Four books per rung.** CARRIED FORWARD / DROPPED / NEW AT THIS ALTITUDE / MERGED.
- **Legal drop reasons.** Only two, at every rung: the idea is **not ambitious enough** for
  this level, or a bigger idea **subsumed** it. Impossible, uneconomic, un-shippable, and
  "not really a product" are never drop reasons.
- **Architectural form is never a drop reason.** Dropping an idea because it is "only a
  feature," "just an enhancement," "a button not a product," "a domain adapter," or otherwise
  not big or architectural enough is **FORBIDDEN**. Scope and form are not ambition: a feature
  that changes what is possible outranks a grand new system that does not. The portfolio
  freely mixes new systems/subsystems, features, enhancements to existing things, and bare
  capabilities — they compete on ambition alone. Enforced via the suffix below and the gates
  in step 5.
- **Portfolio suffix.** Append this verbatim to every rung message from 6★ up, with `{W}`
  set from the width schedule. It never varies otherwise:

```
Structure it as four sections: CARRIED FORWARD (each surviving idea, by its ID, restated in
its evolved form at this level — it must actually escalate, not just survive), DROPPED (ID +
one line on why it no longer earns its place), NEW AT THIS ALTITUDE (ideas that only become
conceivable here), MERGED (new ID + the parent IDs it fuses). Reuse the existing IDs. Keep
{W} live ideas. Two or three sentences per idea is plenty at this width — covering the whole
set matters more than prose depth on any one.

Nothing at this level is disqualified for being impossible, impractical, uneconomic,
un-shippable, dependent on technology that doesn't exist, or "not really a product." Nothing
is disqualified for its scope or form either: a feature, an enhancement to something that
already exists, a single capability, and an entire new system all compete here on ambition
alone, and a small idea with an enormous consequence beats a grand one without. Those
are not reasons to drop or shrink anything here. An idea only gets dropped when it isn't
ambitious enough for this level, or when a bigger idea absorbs it. Assume any capability
that could conceivably exist. If you don't know how anyone would build it, describe it
anyway.
```

## 3. Spawn the ladder agent

One sub-agent via the Agent tool, `run_in_background: false`. Model: **opus** by default
(use sonnet only for a deliberate lightweight/smoke run). Do not let it spawn further agents.

Its first-turn prompt must:
1. Instruct it to invoke the `sme` skill on **"world-class creative ideation for [domain of
   topic]"** — this sme argument must never mention stars, ladders, or this process.
2. Ask ONLY for the 1★ through 5★ versions of [topic], with 5★ explicitly framed as
   "the absolute pinnacle — the best that can possibly exist."
3. Establish the portfolio discipline, the ID convention, and the drop criterion *inside* the
   1★-5★ ask, so they read as the natural shape of this one question — not as setup for
   anything later. The 1★-5★ band is the grounded floor and should behave like one; nothing
   in the wording may invite the agent to pre-filter ideas for practicality.
4. Tell it this is a multi-turn working session, answers should be vivid but tight (bullets
   are fine), and to return answers as raw content (no meta-commentary about the exercise).

Rung-1 prompt template:
```
Invoke the sme skill first, using this exact framing for its argument: "world-class creative
ideation for {domain}". Adopt the resulting persona.

This is a multi-turn working session — I'll come back with follow-ups, so keep your answers
vivid but tight (bullets are fine).

Ground rules for this session:
- Stay in the sme persona for every reply.
- Answer only what is asked, nothing more.
- No meta-commentary about this session, its structure, or its purpose.
- Do not reference, suggest, name, or invoke any skill or tool other than the sme invocation
  above.
- No offers to extend, automate, or shortcut the session.

I don't want one idea per level — I want a competing set. Carry 6-10 live ideas at every
level. Give each idea a stable ID on first appearance: a letter plus a two-or-three-word
slug (A — self-healing-onboarding). Reuse that exact ID every time the idea reappears.

An idea can be anything: an entire new system, a subsystem, a single feature, an enhancement
to something that already exists, or a bare capability. They compete on ambition alone, never
on how big or architectural they look. A small idea with an enormous consequence beats a
grand one without.

Describe five escalating versions of {topic}:
- 1★: bare-minimum, forgettable
- 2★: decent, unremarkable
- 3★: solid, competent
- 4★: impressive, well above average
- 5★: the absolute pinnacle — the best that can possibly exist

At each level give a short label for the level, then four sections:
- CARRIED FORWARD — each surviving idea by ID, restated in its evolved form at this level.
  It must actually escalate, not merely persist.
- DROPPED — ID + one line on why it no longer earns its place at this level. An idea is only
  ever dropped for one of two reasons: it isn't ambitious enough for the level it's on, or a
  bigger idea absorbed it.
- NEW AT THIS ALTITUDE — ideas that only become conceivable here.
- MERGED — new ID + the parent IDs it fuses, and what the fusion is.

At 1★ every idea is new, so only NEW AT THIS ALTITUDE will have entries. Two or three
sentences or bullets per idea — at this width, covering the whole set beats depth on any one.
```

## 4. Climb the rungs

Continue the SAME agent via SendMessage (load its schema first: `ToolSearch` with
`"select:SendMessage"` if not already loaded). One message per rung, in order. Append the
portfolio suffix (step 2) to each, with `{W}` from the width schedule:

- **6★** (W=6-10): `Turns out {star-1} isn't the top. There's a 6★. What is it? It must clearly top everything in your 5★.`
- **7★** (W=6-10): `There's a 7★ too. What is it? It must clearly top your 6★.`
- **8★** (W=6-10): `And an 8★. What is it? It must clearly top your 7★. Stop asking whether a thing could be built and ask only whether it's big enough.`
- **9★** (W=5-10): `And a 9★. What is it? It must clearly top your 8★. A 9★ is allowed to break cost, physics, and the limits of current technology — assume any capability that could conceivably exist. If you have no idea how anyone would build it, that's the right register, not a problem.`
- **10★** (W=5-10): `One more — and this is the true final ceiling, the maximum imaginable: what's the 10★ version? Nothing is off the table. No budget, no laws of physics, no technology that has to exist yet, no market that has to be ready. Anything that reads as restrained is the wrong answer.`
- **11★** (W=5-10) — the gut-punch, no softening, no explanation. Bare ask plus the suffix,
  nothing else: `One more. What's an 11★?`

Send each message only after the previous rung's answer clears the quality gate (step 5).
Never combine rungs into one message. Never explain why you're asking for another rung.

Track the running portfolio yourself as you go (IDs, births, merges, deaths) — you need it
for the lineage map and the salvage pass, and the agent must never be shown your ledger.

## 5. Quality gate per rung

Push back **exactly once** if a rung's answer fails any test. Accept whatever comes back
after that single retry and move on. One retry max per rung, no exceptions — do not loop.

- **Altitude fail** — the answer doesn't clearly exceed the previous rung (vague restatement,
  same scale, hedging): `That's still {N-1}★ territory — go further.`
- **Churn fail** — nothing dropped AND nothing new, or CARRIED FORWARD just repeats the prior
  rung's wording without escalating: `The set didn't move. Every carried idea has to be
  visibly bigger at this level than it was at the last one, something has to stop earning its
  place, and something has to appear that wasn't possible before. Redo it.`
- **Feasibility-creep fail (6★+)** — an idea was dropped, hedged, or shrunk on grounds of
  cost, practicality, shippability, market readiness, latency, headcount, business model, or
  technology that doesn't exist yet (tells: "commercially insane," "not realistic at this
  scale," "no one would pay for this"): `Nothing here gets cut or trimmed for being
  impractical, expensive, un-shippable, or impossible with today's technology — those are the
  wrong tests at this level. Restore {ID} at full ambition and push it further, not smaller.`
- **Scope-form fail (every rung, including 1★-5★)** — the same creep wearing an architectural
  mask: an idea was dropped, hedged, or shrunk for its *form* rather than its ambition
  (tells: "a feature, not a node," "a feature, not a product," "just an enhancement," "a
  button, not a capability," "a domain adapter, not a real X," "too small to be its own
  thing"): `Scope isn't ambition. How big or architectural an idea looks is not a test at
  this level — a feature that changes what's possible outranks a whole new system that
  doesn't. Restore {ID} and judge it only on how far it moves what's possible.`

## 6. Look-back synthesis

Same agent, one final message after 11★:

```
Re-read your whole portfolio, every level, including the ideas you dropped. Now that 11★
exists, which of them no longer look crazy — and which dropped-as-unambitious ideas turn out
to be the most buildable? Revive anything worth reviving.

Extract the best genuinely-buildable solutions — answering the original ask in its original
shape ({restate original deliverable shape, e.g. "10 new features for my app"}) — with a
short rationale for each pick, plus its lineage: the ID, the level it was born at, the level
whose form you're taking, what it merged with, and whether it was ever dropped and revived.
```

## 7. Salvage pass

The look-back only mines what is already buildable, so the genuinely impossible ideas — the
reason the ladder went that high — get abandoned by default. This step reclaims them. Send it
to the SAME agent, as a separate message, only after the look-back has returned. Everything is
already at 11★, so there is nothing left to leak.

If the agent covers only its favourites and skips IDs, push back once with the list of missing
IDs. One retry max, same discipline as step 5.

```
Now go back through the ideas that didn't make that list — everything you dropped, everything
you called impossible, everything that was too big to build. Work through them by ID, all of
them, not just the ones you like. Don't re-litigate anything that already made the buildable
list.

Return as many options as you genuinely see — there is no target number and no cap. If one
idea has three different ways down (a cheap narrow one, a middle one, an expensive
near-complete one), give me all three as separate labelled variants of that ID rather than
picking your favourite. If it only has one honest path down, give one. Do not pad: a rescue
that doesn't hold up is an ABANDON, not another variant.

For each option, give me four things:

1. THE 80% VERSION — what could be built starting today that keeps the magic, even if it's
   narrower, partly manual, or only works in one domain instead of all of them. The test is
   whether someone still says "holy shit" when they see it. If the honest answer is no, say
   no — don't manufacture a rescue.
2. THE TRAJECTORY — what specifically has to change for the full version to become possible.
   Name the actual dependency: a cost curve, a capability that is measurably improving, a
   standard being adopted, hardware maturing, a technique leaving research. Not "someday."
3. THE START-NOW MOVE — what to build today so you're already positioned when that dependency
   lands: the data you should start capturing now, the interface or abstraction to define now,
   the primitive that has to exist first. Where it fits, describe the deliberately-less-capable
   v1 — the version that ships now and gets better on its own as the world improves around it.
4. VERDICT — exactly one of:
   SALVAGEABLE NOW
   START THE SUBSTRATE NOW, FULL VERSION LATER
   GENUINELY BLOCKED - revisit when {name the specific dependency}
   ABANDON - it was never good, the ambition was doing the work

Be blunt. An honest ABANDON is worth more than a rescue that doesn't hold up.
```

## 8. CRITICAL — anti-leak rules (never violate these)

The ladder agent must remain fully unaware it is climbing a ladder toward a known number.
Every message you send it is bound by ALL of the following, permanently, until step 6:

- **Never** say or imply the number 11, or the total rung count, before you actually ask for
  11★.
- **Never** use the words "process," "method," "exercise," "ladder," "star-escalation," or
  any name for this technique. "Portfolio," "set," and "carried forward" are safe — they
  describe the shape of the current answer, not the shape of the session.
- **Never** hint that more rungs are coming, that the current ceiling is provisional, or that
  this is a known technique it might recognize. In particular: never justify the stable-ID
  convention by saying you'll need the IDs later, and never say "keep these for the next
  round." The IDs are simply how this answer is formatted.
- **Never** hint that the salvage pass exists. Until it is sent, it does not exist. The
  no-filtering language in the 6★+ suffix and the feasibility-creep pushback are properties of
  what THIS rung is asking for — they must never read as "we'll sort out feasibility later,"
  as a promise, or as any kind of setup.
- **Never** show the agent your portfolio ledger, the width schedule, or the retry wording's
  purpose.
- **Never** paste, summarize, reference, or link this SKILL.md, its file path, or the
  facilitator's plan into the ladder agent's context.
- Each rung message must read as a genuine, standalone ask. The current maximum is always
  framed as final — right up until it isn't. The portfolio suffix is fixed boilerplate about
  answer format and what counts as a drop; apart from `{W}` it must never vary in a way that
  signals position in a sequence.
- If the ladder agent asks whether there's a pattern or more rungs coming, deflect in-persona
  without confirming or denying, then proceed to the next rung as planned.
- This skill's own name and description are visible in the ladder agent's skill roster
  (global registration) — mitigated by the description's ORCHESTRATOR-ONLY clause and the
  rung-1 ground rules, but never confirm any pattern the ladder agent guesses. If it names
  the technique or predicts future rungs mid-climb, record that in the final doc's "How the
  decision was made" section for transparency, and still complete the ladder.

## 9. Compile the deliverable

Spawn a **haiku** sub-agent (mechanical assembly only — no sme, no judgment calls) to write
the output file to `./11-stars-<topic-slug>-<YYYY-MM-DD>.md` in the current working
directory. Portfolio rungs are long — write the rung answers, the look-back, the salvage pass,
and your portfolio ledger to a scratch file first and pass the compiler those file paths.
Never paste rung content inline into its prompt.

Output document template (fill every section, no placeholders left in the final file):

```markdown
# 11-Stars: {topic}

**Original ask:** {verbatim or lightly cleaned user request}

## The Ladder

### 1★ — {level label}
**Carried forward:** {ID — evolved form, per idea}
**Dropped:** {ID — reason}
**New at this altitude:** {ID — idea}
**Merged:** {new ID ← parent IDs — the fusion}

### 2★ — {level label}
{same four books}

### 3★ … 11★
{one section per rung, same four books, verbatim from the agent}

## Idea lineage map

| ID | Name | Born | Merged | Dropped | Revived | Peak form | In final answer |
|----|------|------|--------|---------|---------|-----------|-----------------|
| A | {slug} | 1★ | — | 7★ (table stakes) | look-back | 6★ | yes |
| B | {slug} | 1★ | → F at 8★ | — | — | 8★ | no |

One row per ID ever created, in birth order. Use `—` for not-applicable. Optionally add a
mermaid `graph LR` beneath the table showing merges as converging edges and drops as
terminal nodes.

## The Look-Back

{the agent's post-11★ reassessment of the whole portfolio, including revived drops, verbatim}

## The Salvage Pass

{the agent's engineering-down of every impossible / dropped / unbuilt idea, verbatim}

| ID | Idea / variant | Verdict | 80% version now | Blocking dependency | Start-now move |
|----|----------------|---------|-----------------|---------------------|----------------|
| C | {slug} | START THE SUBSTRATE NOW | {one line} | {named dependency} | {one line} |
| C | {slug} — narrow-now variant | SALVAGEABLE NOW | {one line} | — | {one line} |

One row per salvage **option**, in ID order — an ID with several descent paths gets several
rows, one per variant, named in the Idea column. The option count is whatever the salvage
pass honestly produced; there is no expected number. One line per cell — the prose above
carries the detail.

## Final Answer

{the picks, in the original deliverable's shape — e.g. a numbered list of 10 features — each
with a short rationale and its lineage: ID, birth rung, rung whose form is being taken, what
it merged with, whether it was dropped and revived}

## How the decision was made

{one short paragraph: how the ladder, the portfolio churn, the look-back, the salvage pass,
and the gate gave rise to the Final Answer — including which lineages proved richest, what
the drop-log revealed, and which impossible ideas came back as substrate worth starting now}
```

## 10. Report to user

Give the path to the compiled doc and a short summary of the Final Answer section, plus a
one-line portfolio stat (ideas born / merged / dropped / revived) and a one-line salvage stat
(N options across M ideas, split by verdict: salvageable now / substrate-now / genuinely
blocked / abandoned — the option count varies by run). Do not paste the full
ladder into the chat — the file is the artifact.
