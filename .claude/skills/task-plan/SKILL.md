---
name: task-plan
description: Create or update PLAN.md in .tasks/<id>/ — the single planning artifact merging a 10-second overview, a provenance/entrypoints index, and a concrete tier/step implementation plan detailed enough that another engineer ships it without re-deriving the design. Use after task-explore sets up the workspace, or when scope or architecture materially changes. Routed to from task-explore.
---

# task-plan — `PLAN.md`

## Goal

One artifact a teammate (or a future session after compaction) reads to fully understand the task and
continue: **what/why** (10s), **where the context lives**, and **exactly how to build it**.

File: `.tasks/<id>/PLAN.md`

## Sections (in order)

### (a) Overview — 10-second what/why/scale
- **Type:** slice / feature / tech-task / bug / refactor / audit.
- **Intake:** where this came from (ticket URL, operator prompt, bug report) — set by `task-intake`.
- **Profile:** `superlight` / `light` / `standard` / `deep` + the one-line reason — set by `workflow-triage`,
  or by the operator, in which case say so (`operator's choice`).
- **Crux** (2–3 sentences): what we're doing and why.
- **Affected:** which layers/modules — be concrete for this codebase (API, domain, data/persistence,
  jobs, client/UI, infra, tooling).
- **Scale:** rough size — number of steps/tiers, new endpoints/contracts, schema/migration changes,
  manual/authored work.
- **Touches:** concrete files/modules this slice will modify. Feeds the orchestrator's conflict graph —
  slices with overlapping `Touches` cannot run in parallel.
- **Depends-on:** other slices/tasks that must land first. `none` if independent.
- **Status:** grooming / impl / review / done.

### (b) Provenance / entrypoints — index of context sources
Every load-bearing source, one line each. The navigation hub.
- **Product canon:** the specific pages/docs (absolute path if a sibling repo; URL if a tracker).
- **Repo (relative):** files/modules the work touches; analogous existing code to reuse.
- **Docs:** the `docs/` pages and policies that apply.
- **Open issues:** relevant open issues, especially known stopgaps this slice touches — link them. If
  this slice replaces or further entrenches a stopgap, say which under **Decisions locked**.
- **External:** official framework/library/API doc URLs actually consulted.
- **In-folder:** `extra_context/` assets.

### (c) Implementation plan — concrete, no guesswork
Plan at the level another engineer could implement directly: real paths, module/function names, API
contracts, data shapes, and the decisions behind them — not "add a field".

For larger work, split into **tiers** (independently reviewable milestones) and **steps** within each
tier. Each tier should leave the product in a reviewable/runnable state.

```markdown
## Affected files
| Layer   | Path                          | What changes                  |
| ------- | ----------------------------- | ----------------------------- |
| domain  | `src/domain/<x>`              | pure rule + types             |
| service | `src/services/<x>`            | orchestration / side effects  |
| api     | `src/api/<x>`                 | contract + input validation   |
| data    | `src/db/<x>`                  | schema + migration            |
| client  | `src/ui/<x>`                  | presentation / requests       |

## Tiers & steps
### Tier 1 — <name> (reviewable/runnable after)
1. <step> — what & why; key signatures / payload shape; analog in repo: `<path>`; acceptance.
2. ...
**Success criteria — automated:** the commands that prove this tier (exit codes, test names).
**Success criteria — manual:** what a human must observe, and how.
### Tier 2 — ...

## Edge cases & failure modes
## Trust boundaries & abuse surfaces (server authority, input validation, authz)
## Out of scope
## Decisions locked
- Chose X over Y because Z.
```

### (d) Validation plan → `.tasks/<id>/VALIDATION.md`
Author acceptance checks at groom time via the `slice-verify` skill: each acceptance/DoD line becomes ≥1
Check drawn from the project's check kit (`.tasks/_STACK.md`: lint / typecheck / tests / format / build /
manual observation), with where evidence lands. Derive checks from the slice, **not** from the
implementation. The implementer self-checks against it; the reviewer/verifier re-runs it. This file is
part of the **grooming gate** (see `dev-prompt`) — a slice is not ready to implement without it.

When `PLAN.md` / `OPEN_QUESTIONS.md` / `VALIDATION.md` read as complete, run **groom-harden** passes (one
fresh context per lens, ledger in `GROOM_LOG.md`) until two consecutive `QUIET` verdicts. Machine check:
`bash scripts/ai/gate.sh plan <id>` and `bash scripts/ai/gate.sh groom <id>` — both must exit 0 before a
dev-prompt is emitted.

**No unresolved questions in the plan.** A plan that says "either A or B" or "TBD" is not a plan; it hands
the decision to whoever implements it, at the worst possible moment. Resolve it, or record it as a
`blocker` and stop.

## Conventions to respect (guidance, not a cage)

- **Server/backend authority** for anything money-, permission-, or progression-shaped; treat client code
  as presentation/input/requests and validate every client-originated request.
- **Source of truth:** state it explicitly for anything with two possible owners (code vs authored asset,
  DB vs config, service A vs service B).
- **Persistence** goes through the project's data layer, not ad-hoc writes from feature code.
- **Architecture:** follow the repo's `AGENTS.md` / architecture docs — but architecture evolves; propose
  and record deviations as **Decisions locked** rather than silently diverging.

## Update rules
- Created during task-explore Phase B; updated on scope change, status transition, or a locked decision.
- Edit deltas — don't rewrite from scratch. New context source discovered → append to (b) immediately.

## Do not
- Don't write speculative draft code — write a plan, not an implementation.
- Don't skip "analogous code" — reuse what the repo already has.
- Don't generate this file while an unresolved **blocker** sits in `OPEN_QUESTIONS.md` — STOP first.
- Don't duplicate `CHECKLIST.md` statuses or restate `OPEN_QUESTIONS.md` here.
