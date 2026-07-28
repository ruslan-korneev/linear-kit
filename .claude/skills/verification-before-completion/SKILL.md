---
name: verification-before-completion
description: Before declaring anything done, fixed, or working — prove it by observing the actual behavior, not by reading the code you just wrote. Use at the end of any change, before saying "done", before opening a PR, and whenever you are about to report a fix.
---

# verification-before-completion

The most expensive failure mode of a coding agent is a confident "done" that was never observed. Reading
your own diff and concluding it works is not verification — it is the same reasoning that produced the bug.

## The rule

**Every completion claim names the observation that backs it.** If you cannot say *what you ran and what
you saw*, you are not done — you are hopeful.

| Claim | Not verification | Verification |
| --- | --- | --- |
| "Tests pass" | the tests exist | the run output, with counts |
| "Bug fixed" | the code path looks right | the reproduction now behaves differently than before |
| "Types are clean" | the file looks typed | the typecheck exit code |
| "Feature works" | it is implemented | the feature exercised end to end, and what was observed |
| "Nothing else broke" | the change is small | the suite run after the change |

## Procedure

1. Run the project's gates: `bash scripts/ai/gate.sh green` (static + tests, from `.tasks/_STACK.md`).
   Read the exit code, not the absence of red: `0` passed · `1` failed · **`3` nothing ran**. A `3` means
   this project has no checks configured, so "green" is a statement about nothing — report it as such.
2. Run every check in `VALIDATION.md`; save what you observed to `.tasks/<id>/evidence/`.
3. For a bug fix: confirm the **reproduction** now fails to reproduce. A fix without a before/after
   observation is a guess that happened to compile.
4. Re-read the original request — not the plan, the request. Does what you observed satisfy what was
   actually asked?
5. Report honestly, including what you could **not** verify and why. A run with two verified checks and one
   blocked check is a useful result; the same run reported as fully green is a lie with a green checkmark.

## Failure honesty

If a check fails, say so with the output. Do not:
- weaken an assertion so it passes,
- mark a check "N/A" because it is inconvenient,
- describe a partial implementation as finished and leave the remainder implied,
- attribute a failure to "flakiness" without evidence that it is flaky.

State exactly: what is done, what is not, what remains before the task can be considered complete.

## Do not

- Don't skip this because the change is trivial — trivial changes are exactly where unverified claims slip
  through.
- Don't verify by asking another agent whether the code looks correct; that is a second opinion, not an
  observation.
