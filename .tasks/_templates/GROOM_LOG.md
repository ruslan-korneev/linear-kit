# Groom log — <id>

Append-only ledger of `groom-harden` passes. Each pass runs in a **fresh context** and reads this file
first, so it does not re-derive what earlier passes already settled.

**One pass per lens — the lens set is the coverage.** A lens is repeated only when it found a blocker or a
major, and then only that lens, after its findings are folded in. Re-running the whole rotation to see if
anything new turns up is how a groom burns a third of its budget on minors.

`scripts/ai/gate.sh groom <id>` parses the table below: it opens when **every lens in `LENSES`
(`.tasks/_STACK.md`) has a row whose last entry reports 0 blockers and 0 majors**, and no blocker is open
in `OPEN_QUESTIONS.md`. Keep the column order — the gate reads by position.

Outcome: `quiet` = nothing new worth acting on · `findings` = blocker or major raised (minors alone are
recorded, not chased).

| Pass | Lens | Outcome | New blockers | New majors | Folded into |
| ---- | ---- | ------- | ------------ | ---------- | ----------- |
| P1 | contracts | findings | 1 | 2 | PLAN.md §Contracts, OPEN_QUESTIONS.md#3 |
| P2 | contracts | quiet | 0 | 0 | — |

## Closed — do not re-raise without new evidence

Items earlier passes examined and settled. A later pass that wants to reopen one must cite evidence that
did not exist before, not merely restate the concern.

| # | Item | Pass | Resolution |
| - | ---- | ---- | ---------- |

## Rejected findings

Raised by a pass, judged not real. Off the table — the same finding must not reappear each round.

| # | Finding | Pass | Why rejected |
| - | ------- | ---- | ------------ |

## Minors (recorded, not chased)

Worth knowing, not worth another pass. Fold into the plan if cheap; otherwise they die here.

| # | Minor | Pass |
| - | ----- | ---- |
