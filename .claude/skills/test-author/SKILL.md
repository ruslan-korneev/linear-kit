---
name: test-author
description: Write the failing tests for a slice before any implementation exists — RED step of the loop. Run by an agent that may not touch source paths, so tests encode the acceptance rather than the implementation. Use after the plan is approved and before the builder starts.
---

# test-author — tests as the spec, written by someone who cannot cheat

If the implementer writes the tests, the tests describe the implementation and pass by construction. So
they are written first, by a separate identity, mechanically prevented from touching source
(`bash scripts/ai/guard.sh test-author`).

## Input

`PLAN.md` (acceptance, contracts, tier breakdown) and `VALIDATION.md` (acceptance → check mapping). Not
the grooming conversation, not the implementation ideas discussed there.

## What to write

- One test per acceptance line that is testable in code. `VALIDATION.md` already names them — keep the
  names traceable to the acceptance, so a failing test says *which promise broke*.
- Test the **contract**, not the internals: inputs → observable outputs and state transitions. A test that
  asserts on a private helper freezes the implementation and will be deleted at the first refactor.
- Cover the edge cases `PLAN.md` lists — boundary values, empty/null, ordering, idempotency, the unhappy
  path. Those are the cases the builder will otherwise quietly not handle.
- Reuse the project's existing test conventions: same runner, same fixtures, same naming, same helper
  layer. Find an analogous existing test first and match it.

## What NOT to write

- No tests for behavior the plan does not promise — that is scope creep with a green checkmark.
- No mock-only test standing in for a real integration the slice claims to make. A mocked boundary passes
  even when the real one is broken. If the promise is "it actually talks to X", that belongs in
  `VALIDATION.md` as an observation check, and you say so instead of faking it.
- No test that cannot fail. If you cannot make it fail before the code exists, it asserts nothing.

## The RED gate

Run `bash scripts/ai/gate.sh red` (or `red <path>` for one target). The suite **must** fail — and the
failure must be the **intended assertion**, not an import error, a syntax error, or a missing fixture.
Read the output and confirm the reason. Then commit the RED state; it is the proof the tests are real.

No test command configured in `.tasks/_STACK.md` → say so plainly, write nothing, and hand the acceptance
back as observation checks in `VALIDATION.md`. Do not fake a TDD step.

## Handing over

Report to the builder: which tests exist, what each one promises, which acceptance lines remain
**untestable in code** (visual, performance, live integration) and therefore stay as observation checks.

If the builder later claims a test is wrong, it comes back to you with the reason — the builder does not
edit tests. Wrong tests get fixed here, deliberately, and the change is recorded.

## Do not

- Don't touch source paths. The guard will fail the phase, and the point is lost anyway.
- Don't write the implementation "just to check the test works" — the RED gate is that check.
- Don't weaken an assertion to make a test pass later; that decision belongs to the operator, not to you.
