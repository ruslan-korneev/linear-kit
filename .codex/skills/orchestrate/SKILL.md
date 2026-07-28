---
name: orchestrate
description: Orchestration mode — the main session grooms slices and launches/monitors parallel background implementations. Tracks state on .tasks/_orchestration/BOARD.md, auto-retries transient failures (≤3) and escalates hard failures, and uses each slice's Touches/Depends-on to warn about conflicts and order a merge-train. Use when running several slices in parallel or managing in-flight background implementations.
---

# orchestrate — groom + launch + monitor parallel implementations

The main (orchestrator) session grooms slices and dispatches their implementations as background tasks,
then keeps them healthy. Every launch and every merge is **operator-gated** — the orchestrator manages
state and gives recommendations; it does not merge or override the operator.

## Loop
1. **Groom** a slice to the grooming gate (`task-explore` → `task-plan` + `slice-verify` + `groom-harden`;
   gate per `dev-prompt`).
2. **Conflict check at launch time** (not just at groom time — the repo and other in-flight slices move):
   read each in-flight/queued slice's `PLAN.md` `Touches:` + `Depends-on:`.
   - Overlapping `Touches` with a running slice → **cannot parallelize**; warn the operator, queue it.
   - Unmet `Depends-on` (a prerequisite slice not yet merged) → hold; don't launch.
3. **Launch** (operator-approved): emit the dev-prompt (`dev-prompt` skill) and start it as a **background
   task**, own branch `<id>-<slug>` (+ worktree; the implementer runs `scripts/ai/setup-worktree.sh`
   first — see `slice-implement`). Add a row to `BOARD.md`.
4. **Groom/launch more** independent slices in parallel.
5. **Monitor**: poll the background tasks; update `BOARD.md` states.
   - `failed` (transient — crash/timeout) → **auto-retry ≤3**, then escalate.
   - `blocked` (a `blocker` in the slice's `OPEN_QUESTIONS.md`) → **escalate to operator, do not retry**.
   - review not converged after 6 rounds → escalate.
   - **code-clean but runtime evidence blocked by a shared resource** (one staging slot, one device, one
     shared env) → don't let the review loop thrash on missing evidence. Serialize access, or defer that
     one piece of evidence to the merge-train and escalate — the operator's call.
6. **Merge-train** (operator merges): recommend a merge order that respects `Depends-on`; only one PR to
   the base branch at a time; after a merge, flag which in-flight branches must **rebase** and re-check
   their conflicts.

## State board: `.tasks/_orchestration/BOARD.md`
One row per active slice. States: `queued → grooming → ready → running → review → blocked → failed →
pr-open → merged`. Columns: id · state · branch · depends-on · touches (summary) · agent/task id ·
last-checked · PR · notes. This is the orchestrator's single source of truth for what's in flight; refresh
it every monitor pass.

## Parallel-safety rules
- Two slices may run in parallel **only** if their `Touches` do not overlap and neither `Depends-on` the other.
- Re-evaluate conflicts **at the moment of launch**, against currently-running slices — not stale
  groom-time data.
- When in doubt about overlap, **warn and ask** rather than launch.

## Escalate to the operator (stop autonomous handling) when
- A slice hits a real `blocker`.
- A reviewer loop doesn't converge in 6 rounds.
- Auto-retry (≤3) is exhausted.
- A conflict/merge ordering needs a human call.

## Do not
- Don't merge to the base branch or override the operator — recommend only.
- Don't launch conflicting or dependency-unmet slices in parallel.
- Don't let a failed/blocked slice loop silently — surface it.
