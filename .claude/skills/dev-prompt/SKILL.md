---
name: dev-prompt
description: After a slice is groomed and approved, check the grooming gate and emit a self-contained implementation prompt (from .tasks/_dev-prompt-template.md), ask whether a separate worktree is needed, let the operator pick the implementer engine, and offer run modes (background task here, or a separate session). Use at the end of grooming, when the operator approves a slice for implementation.
---

# dev-prompt — hand a groomed slice off to implementation

The bridge from grooming → autonomous implementation. The groomer runs this once a slice is ready and the
operator approves it.

## Grooming gate (machine-checked, not judged)

```bash
bash scripts/ai/gate.sh plan  <id>   # PLAN.md + VALIDATION.md complete, acceptance mapped, no placeholders
bash scripts/ai/gate.sh groom <id>   # no open blocker + two consecutive quiet groom passes
```

Both must exit 0. Plus one thing no script can check: **the operator approved the plan** (gate G2).

If a gate is red → do **not** emit a dev-prompt. Report which gate failed and what it printed, then return
to grooming. "It looks complete to me" is not a gate.

## Before emitting

**Worktree: always.** Every run gets its own branch and worktree — parallel runs stop colliding and the
operator's tree stays clean. `setup-worktree.sh` links dependencies and allocates ports/schema, so the
cost is seconds.

**Engine:** `IMPLEMENT_ENGINE` in `.tasks/_STACK.md` is the default; the operator can override per run to
spread usage limits. A run started in another app's UI is **not** trackable from this session — say so
rather than pretending to monitor it.

**Run mode:**
- **Run here** — launch a background task from this session, seeded with the dev-prompt.
- **Separate session** — the operator pastes the prompt into a fresh session.
- **Orchestration** — the orchestrator launches it (see `orchestrate`).
- **Full autonomy** — `adw-run` drives every phase and stops only at G2 and G7.

## Emit

Fill `.tasks/_dev-prompt-template.md` from `PLAN.md` + `VALIDATION.md`:
- branch `<id>-<slug>`, in a worktree;
- the prompt is **self-contained** — it references `.tasks/<id>/PLAN.md` and `VALIDATION.md` by path and
  inlines the goal, profile, scope IN/OUT, and acceptance, so the implementer needs no prior conversation;
- it names the gates as commands (`gate.sh plan|red|green|evidence`, `guard.sh builder`), not as prose;
- it instructs the full flow: gate re-check → RED (test-author) → GREEN tier by tier under the builder
  guard → validation + evidence → PR → review fan-out + harness-improver → loop ≤6 → STOP on blocker;
- keep the template's **RUNTIME VALIDATION** block: how this project brings the app up, and who owns any
  shared/manual resource (the implementer asks the operator rather than seizing it).

## Do not
- Don't emit while the gate is red.
- Don't bake conversation-only context into the prompt — it must stand alone for a fresh background session.
- Don't start writing implementation code in the grooming session — the dev-prompt hands that to the
  implementer.
