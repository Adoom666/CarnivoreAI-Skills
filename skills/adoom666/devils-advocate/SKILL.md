---
name: devils-advocate
description: Performs Devils Advocate Review (DAR) on plans and decisions. Triggers when user mentions "devil", "DAR", "challenge this", or wants critical review of a plan. Spawns sub-agents to challenge assumptions, find edge cases, validate from multiple perspectives (technical, UX, maintainability), and iterate until alignment before presenting refined plan. Guards against over-engineering by ensuring proposed solutions remain proportional to the original problem.
---

# Devils Advocate Review (DAR)

## Overview

This skill executes a structured adversarial review process on any plan, architecture, or decision. It forces rigorous validation through three phases: devil's advocacy, multi-perspective validation, and final presentation. Only after complete alignment across all validators does the refined plan get presented.

## Anti-Overcomplication Principle

**CRITICAL:** The purpose of DAR is to strengthen plans, NOT to expand their scope.

When reviewing and refining plans, guard against:
- Adding features/complexity that weren't in the original request
- Suggesting architectural changes beyond what's needed for the task
- Turning simple fixes into large refactors
- Proposing "nice-to-have" improvements as requirements
- Creating abstractions for one-time operations

**The devil's advocate should challenge BOTH:**
1. Weaknesses in the plan (missing edge cases, risks, etc.)
2. Unnecessary complexity (is this solution proportional to the problem?)

If the refined plan is significantly larger than the original, the devil should ask: "Is this complexity justified by the original requirements, or are we gold-plating?"

The goal is the SIMPLEST plan that fully addresses the user's actual request, not the most comprehensive plan possible.

## Execution Procedure

### STEP 1: Signal Activation

Output exactly this to confirm DAR is active:

```
👹 Devil in Play
```

### STEP 2: Phase 1 - Devil's Advocate Loop

For EACH distinct section/component in the current plan:

1. **Spawn a devil's advocate sub-agent** with this prompt pattern:
   ```
   You are a devil's advocate. Your job is to ATTACK this plan section:

   [PASTE PLAN SECTION]

   Challenge:
   - What assumptions are being made? Are they valid?
   - What edge cases could break this?
   - What are the risks? What could go wrong?
   - What's being overlooked or oversimplified?
   - What dependencies could fail?
   - Is the proposed solution proportional to the problem, or is it over-engineered?

   Be ruthless. Find the weaknesses.

   Report: List of specific concerns with severity (critical/major/minor).
   ```

2. **Process devil's feedback:**
   - For each CRITICAL or MAJOR concern: revise the plan to address it
   - For MINOR concerns: note them but proceed if trade-offs are acceptable

3. **Re-submit revised section to devil's advocate:**
   - Repeat until devil's advocate responds: "No critical concerns remain" or "Approach is sound"

4. **Move to next section.** Do not proceed to Phase 2 until ALL sections pass.

### STEP 3: Phase 2 - Multi-Perspective Validation

**Select 3 Relevant Perspectives:** Before spawning validators, analyze the plan and choose the 3 MOST RELEVANT perspectives from this catalog:

| Perspective | Use When Plan Involves |
|-------------|------------------------|
| Technical Correctness / Edge Cases | Logic, algorithms, data structures, API design |
| User Experience / UX Implications | UI changes, workflows, user-facing features |
| Security / Attack Vectors | Auth, data handling, external inputs, APIs |
| Performance / Scalability | Data volume, concurrent users, latency-sensitive ops |
| Maintainability / Future Implications | Architecture changes, new patterns, refactors |
| Cost / Resource Implications | Cloud infra, API calls, storage, compute |
| Business Logic / Domain Accuracy | Domain rules, calculations, process flows |
| Data Integrity / Consistency | Database ops, transactions, state management |
| Accessibility / Inclusivity | UI components, content, interaction patterns |
| Compliance / Regulatory | PII, GDPR, HIPAA, financial regulations |
| Integration / Compatibility | Third-party systems, migrations, backward compat |

**Example selections:**
- Auth system refactor → Security, Technical Correctness, Integration
- New checkout flow → UX, Business Logic, Data Integrity
- Database migration → Data Integrity, Performance, Maintainability
- Admin dashboard → UX, Accessibility, Security

Spawn THREE sub-agents IN PARALLEL using your selected perspectives:

**Validator Template (adapt for each perspective):**
```
Review this plan from the [PERSPECTIVE] lens:

[PASTE FULL REFINED PLAN]

Focus on:
- [2-4 specific questions relevant to this perspective]
- What could go wrong in this dimension?
- What's being overlooked?

Verdict: PASS (with any caveats) or FAIL (with specific blocking issues)
```

**Process results:**
- If ANY agent returns FAIL: address blocking issues, return to Phase 1 for those sections
- If all PASS with caveats: incorporate caveats into final plan
- Repeat Phase 2 until all three validators PASS

### STEP 4: Phase 3 - Present Refined Plan

Only after total alignment from Phase 2, present the final plan:

```
## 👹 DAR Complete - Refined Plan

### What Changed
[Bullet list of significant changes from original to final]

### Why It Changed
[Key insights from devil's advocacy and validation that drove changes]

### Final Plan
[The complete refined plan]

### Residual Risks
[Any known risks or caveats that remain, with mitigation notes]
```

## When to Skip DAR

DAR adds overhead. Skip it for:
- Simple bug fixes with obvious solutions
- Single-file changes with clear scope
- Direct, unambiguous user instructions
- Tasks where "getting it wrong" has minimal consequences
- Tasks where the solution is already appropriately scoped

Use DAR for:
- Architectural decisions
- Multi-system changes
- High-risk refactors
- Any task where mistakes are costly to undo
