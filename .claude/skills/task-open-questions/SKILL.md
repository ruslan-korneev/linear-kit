---
name: task-open-questions
description: Create or maintain OPEN_QUESTIONS.md in .tasks/<id>/ — a living doc of open questions, blockers, assumptions, and resolved decisions (with history). Categories — blocker (a STOP signal: work pauses until resolved), clarify (assumption in use), resolved (with the decision). Use when grooming surfaces an uncertainty, a blocker is hit, an assumption is made, or a question is answered. Routed to from task-explore.
---

# task-open-questions — `OPEN_QUESTIONS.md`

## Goal

A **living document** capturing every question, blocker, and assumption that lacks a clear answer from
the project's canon, the repo, or the user. Survives compaction: if conversational nuance is stripped,
the open items here persist.

File: `.tasks/<id>/OPEN_QUESTIONS.md`

## Categories (every entry is exactly one)

- **blocker** — a **STOP signal**. Work cannot proceed safely without an answer. When any blocker is
  open, **implementation pauses and you surface it to the user — do not guess.** Sources: canon
  contradicts itself or is missing for the slice; scope unclear enough that work would be wasted;
  ownership / source-of-truth undefined; an API, persistence, money, or permission contract is missing;
  a dependency, file, asset, credential, or tool access is unavailable; the user expressed unresolved
  hesitation. A "critical problem" simply IS a blocker — no separate artifact for it.
- **clarify** — an assumption is being used. Work can proceed, but confirm before locking design or shipping.
- **resolved** — historical entry now answered. Keep for audit; never delete.

## Skeleton

```markdown
# Open questions: <id>

## Blockers (STOP — pause work until cleared)
1. **<question / missing-context statement>**
   - Context: where it came up (artifact / discussion).
   - Source: canon / repo / user.
   - Why it blocks: what cannot be decided or built without this.
   - Possible resolutions: A) … B) …

## Clarify (proceed with stated assumption)
1. **<question>**
   - Assumption in use: …
   - Risk if wrong: …

## Resolved (audit trail — keep)
1. **<original question>** → resolved <YYYY-MM-DD>: chose X because Y (source).
```

## Update rules
- On surfacing a new uncertainty → add under the right category immediately.
- On hitting a blocker → add under Blockers, set the matching `CHECKLIST.md` item to `[!]`, and **STOP**:
  surface the blocker(s) to the user and pause until cleared.
- On getting an answer → move the entry to **Resolved** with date + rationale. Do not delete.
- On accepting an assumption explicitly → move from Blockers to Clarify.
- On the user declining to answer → mark Resolved with the explicit decision.

## Do not
- Don't leave it empty — if nothing is open, write "No open questions at current context level".
- Don't delete resolved entries — they are the audit trail.
- Don't proceed past an open **blocker** silently — STOP and ask first.
- Don't conflate blocker (work cannot proceed) with clarify (work proceeds on an assumption to confirm).
