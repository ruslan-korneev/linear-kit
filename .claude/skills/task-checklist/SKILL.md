---
name: task-checklist
description: Create or update CHECKLIST.md in .tasks/<id>/ — a single-glance status dashboard tracking the dev loop phases (gate → context → scope → plan → implement → tier review → validate → done). Statuses only. Use when starting a larger task, finishing a step/tier, hitting a blocker, or refreshing context. Routed to from task-explore.
---

# task-checklist — `CHECKLIST.md`

## Goal

One glance = the full state of the task. Holds **statuses only** — never duplicate `PLAN.md` or
`OPEN_QUESTIONS.md` content. Critical for cross-session continuity: after compaction or in a fresh
session, read this to know what's done, in progress, blocked, or N/A. Use it for tasks big enough to span
tiers; trivial tasks don't need one.

File: `.tasks/<id>/CHECKLIST.md`

## Statuses

`[x]` done · `[ ]` not started · `[~]` in progress · `[!]` blocked (say what blocks) · `[-]` N/A (say why)

## Skeleton — dev loop phases

```markdown
# Checklist: <id> — Title

## 0. Gate (decision + critical problems)
- [ ] Relevant product canon read
- [ ] Ambiguous choices walked as a decision-tree; scope clear
- [ ] No unresolved blockers (else [!] → STOP, see OPEN_QUESTIONS.md)

## 1. Context & spec
- [ ] Canon + relevant src/docs read; analogous code identified
- [ ] Plan re-stated in own words (gate before code)
- [ ] PLAN.md written (overview + provenance + impl plan)
- [ ] VALIDATION.md written (acceptance → checks)

## 2. Scope
- [ ] Scope IN listed
- [ ] Scope OUT (what we will NOT touch) listed

## 3. Implementation (per tier/step from PLAN.md)
- [ ] Tier 1 implemented in small, reviewable commits
- [ ] Tier review: bugs / correctness / integration / performance (deep, at real call sites)
- [ ] Review findings fixed as follow-up steps
- [ ] (repeat per tier)

## 4. Validate / Definition of Done
- [ ] Static green (lint / typecheck / format — see .tasks/_STACK.md)
- [ ] Tests written for high-risk rules; suite green
- [ ] Manual/runtime observation of the slice (what was observed)
- [ ] Slice acceptance met — every VALIDATION.md check green with evidence

## 5. Done
- [ ] Out-of-band changes (authored assets, dashboards, infra) reconciled or documented as externally owned
- [ ] Follow-ups captured in OPEN_QUESTIONS.md / next task
- [ ] Committed (or PR opened) → reference
```

## Update rules
- On starting a phase/step → `[~]`; on finishing → `[x]`.
- On a blocker → `[!]` with the blocker on the same line; mirror it as a **blocker** in
  `OPEN_QUESTIONS.md` (STOP until resolved).
- Phase-3 sub-steps map to the tiers/steps in `PLAN.md`.

## Do not
- Don't duplicate `PLAN.md` / `OPEN_QUESTIONS.md` content — statuses only.
- Don't leave it stale — an outdated checklist is worse than none.
- Don't delete completed items — they are the audit trail of what shipped.
