---
name: slice-verify
description: Define and run the .tasks/<id>/VALIDATION.md convention — acceptance → check → expected → evidence, split into automated and manual verification. Use when grooming a task (author it), self-checking before a PR, or verifying someone else's "it's done". Turns a completion claim into a reproducible observation.
---

# slice-verify — executable acceptance, driven by `VALIDATION.md`

Turns "DoD is met" into **"reproduce it."** The implementer and the reviewer run the same checks. There is
no monolithic verify script — the checks are per task, and the commands come from `.tasks/_STACK.md`.

## The artifact

Authored at **grooming** (via `task-plan`), before any code. Its path flows through the pipeline: groom →
dev-prompt → implementer → reviewer.

```markdown
# <id> — Validation plan

## Stage
- What to bring up before checking: services, fixtures/seed data, env vars, test account, which
  environment. Never production. In a worktree, source `.tasks/_worktree.env` first (ports/schema).

## Checks
| # | Acceptance (from the task) | Check | Expected | Kind | Evidence |
| - | -------------------------- | ----- | -------- | ---- | -------- |
| 1 | rule X computes Y for boundary input | `<TEST_ONE_CMD> path/to/x` | all green | auto | run output |
| 2 | types + lint clean | `bash scripts/ai/gate.sh static` | exit 0 | auto | log |
| 3 | server rejects a forged request | send crafted request per Stage | 4xx, no state change | auto | response + log |
| 4 | feature behaves right for a user | run the app, follow the Stage | matches acceptance | manual | text observation (+ screenshot) |
```

**Kind** matters: `auto` = a command with an exit code, runnable by anyone including the reviewer.
`manual` = a human or an agent observing behavior. Every task should push as much as possible into `auto`;
what remains `manual` is stated honestly rather than hidden behind an automated-sounding sentence.

Each row maps ONE acceptance line → a concrete check → an observable expectation → where evidence lands
(`.tasks/<id>/evidence/`).

## Rules for a good check

- **Derived from the task, not the implementation.** Write these before the code exists; a check invented
  after the fact tends to describe what the code happens to do.
- **Observable, not internal.** "Returns 403 and writes no row" beats "calls `assertPermission`".
- **Reproducible by someone else.** Any probe script, fixture, or query a check needs is saved as a file
  in `.tasks/<id>/extra_context/` and referenced by path — evidence capturing only the *output* forces the
  next runner to re-author the probe.
- **Expected result is concrete.** "Works correctly" is not an expectation; it is a wish.

## Roles

- **Groomer:** every acceptance/DoD line → ≥1 check. Gate: `bash scripts/ai/gate.sh plan <id>`.
- **Implementer:** bring up the Stage, run every check, save evidence. Gate:
  `bash scripts/ai/gate.sh evidence <id>`. No PR with red or unrun checks.
- **Reviewer:** independently re-run every `auto` check; for `manual` ones, judge whether the recorded
  evidence is reproducible. A check with no reproducible evidence is **not** passed.

Every check ends in one of three states, and the third is a legitimate outcome that must be **reported,
not hidden**: `PASS` · `FAIL` · `NOT RUN` (with the reason). A run with four passes and three NOT RUN is
useful information; the same run reported as "green" is a false claim. NOT RUN checks go into the PR body
under "Not verified", not only into `.tasks/` — the operator reads the PR.

## Guardrails

- Dev/staging only, never production data or environments.
- The reviewer stays read-only on shared state: no destructive commands, no deploys.
- A behavior that only fails in the real integration (mocks pass, reality breaks) **must** have a live
  observation check. Mock-only acceptance for "it actually talks to X" is not sufficient — say this
  explicitly in the row rather than letting a green unit test imply it.
