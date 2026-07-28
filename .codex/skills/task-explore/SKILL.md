---
name: task-explore
description: Initialize or refresh a committed .tasks/<id>/ workspace for a slice or task, then route to task-plan / task-checklist / task-open-questions. Use when starting substantial grooming, design, audit, or implementation work, when the user says "explore the task" / "groom this" / "refresh task context", or to rehydrate the persistent artifacts at the start of a fresh session or after compaction.
---

# task-explore — entrypoint for `.tasks/<id>/`

## Goal

Establish or refresh the committed workspace `.tasks/<id>/` so any session (or teammate) can pick the
task up in under a minute by reading `PLAN.md` + `CHECKLIST.md`. This skill is the **router**: it scans
repo state, reads the project's canon, then hands off to the artifact skills. It does not implement code.

`<id>` is a short kebab-case slug or ticket id.

## When to apply

- Starting substantial grooming, design, audit, or multi-step implementation work.
- User says "explore the task", "groom this", "refresh task context", "обнови контекст".
- Start of a new session, or after compaction — rehydrate from the on-disk artifacts.
- Already inside `.tasks/<id>/` and need to re-sync the snapshot against current repo + canon.

## Workspace layout (committed — it is the provenance record)

```
.tasks/<id>/                  ← committed (NOT gitignored)
├── PLAN.md                   ← task-plan: overview + provenance/entrypoints + impl plan (always)
├── CHECKLIST.md              ← task-checklist: loop-phase status dashboard (as needed)
├── OPEN_QUESTIONS.md         ← task-open-questions: blockers / clarify / resolved (as needed)
├── VALIDATION.md             ← slice-verify: acceptance → check → expected → evidence
└── extra_context/            ← optional: user-pasted assets (PRDs, screenshots, notes)
```

`PLAN.md` is the only always-on file. Create the others when the work is large enough to warrant
tracking. Don't manufacture files that carry no information.

## Context sources

- **Project rules:** `AGENTS.md` / `CLAUDE.md` at the repo root — the production bar and workflow this
  task must respect.
- **Stack profile:** `.tasks/_STACK.md` — the concrete check kit (lint / typecheck / test / format /
  build / run commands) and stack conventions. Every validation check must be expressible with it.
- **Product canon** — wherever *this* project keeps it, as recorded in `.tasks/_STACK.md` § Product canon
  (a wiki repo, `docs/product/`, a tracker, a PRD in `extra_context/`). Not recorded → ask; do not go
  hunting in tools this project never declared. If canon lives in a sibling repo, read it by **absolute
  path** — cross-repo `[[wikilinks]]` do not resolve. Record the path in `PLAN.md` provenance.
- **Implementation repo:** the modules the task touches, plus `docs/`, tests, and config. Note
  analogous existing code to reuse.
- **Open issues** (`gh issue list --state open`, or the project's tracker): known constraints, deferred
  work, and especially **accepted-but-temporary decisions** (label them `questionable-solutions`). An
  issue overlapping the task area is load-bearing context: the task may need to honor, work around, or
  finally **replace** it.

## Flow

### Phase A — collect
1. Determine `<id>` (from the user, or derive one from the work).
2. Read the relevant product canon for the systems in scope.
3. Scan the repo areas the task touches; note analogous existing code to reuse. **Verify the actual
   dependency set** (manifest + lockfile + installed tree) before claiming a library is absent or
   present — check the manifest, don't trust memory or stale docs.
4. Check open issues relevant to the task area. Surface any overlap in `OPEN_QUESTIONS.md` — if the task
   touches a known stopgap, decide whether this is the moment to replace it, and link the issue.
5. Copy any user-pasted context into `extra_context/` so the folder is self-contained.

### Phase B — synthesize (new workspace)
1. **task-open-questions** → log uncertainties as you read. A real unknown (missing canon,
   contradiction, undefined contract, missing prerequisite) is a **blocker** = a STOP signal: surface it
   and pause, don't guess.
2. **task-plan** → `PLAN.md`: overview, provenance/entrypoints index, and the implementation plan.
3. **slice-verify** → `VALIDATION.md`: every acceptance line → ≥1 runnable check.
4. **task-checklist** → `CHECKLIST.md`: skeleton tracking the loop phases (only for larger tasks).
5. **groom-harden** → once the artifacts read as complete, run the adversarial completeness pass
   (unresolved decision-tree branches, dangling/unasked questions, deep edge cases, contract/acceptance/
   scope coverage); fold findings back in and loop until `VERDICT: GROOM_COMPLETE`. Its clean verdict is
   part of the `dev-prompt` gate.

### Phase C — refresh (workspace exists)
1. Re-read canon and reconcile changes into `PLAN.md` (edit deltas; don't rewrite from scratch).
2. Re-inventory `extra_context/`.
3. `OPEN_QUESTIONS.md`: mark newly-resolved (keep history); add new ones.
4. `CHECKLIST.md`: advance statuses to reality.
5. Tell the user briefly: what was refreshed, what's open, what's blocked.

## Do not

- Don't generate `PLAN.md` while an unresolved **blocker** sits in `OPEN_QUESTIONS.md` — STOP and ask.
- Don't write implementation code here — this skill grooms and routes only.
- Don't gitignore `.tasks/` — it is committed provenance.
- Don't invent product canon; capture gaps in `OPEN_QUESTIONS.md`.
