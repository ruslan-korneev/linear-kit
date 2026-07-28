---
name: slice-implement
description: The implementer playbook for an approved task — worktree, gate re-check, RED tests first, tier-by-tier GREEN implementation under mechanical guards, validation with evidence, PR, then review fan-out and the review loop. Use when running an implementation seeded by a dev-prompt, in a background task or a fresh session.
---

# slice-implement — from an approved plan to a reviewed PR

You implement one approved task. Your plan is `.tasks/<id>/PLAN.md`, your acceptance is
`.tasks/<id>/VALIDATION.md`, your commands come from `.tasks/_STACK.md`. Do not rely on prior chat context.

## 0 · Workspace first — before a single source file is touched

Order matters. Doing this at the end instead of the start is the difference between visible work and a
pile of changes nobody can see, review, or recover.

```bash
git worktree add ../<repo>-<id> -b <id>-<slug>      # never the operator's checkout, never the base branch
mv .tasks/<id> ../<repo>-<id>/.tasks/<id>            # only if grooming left it in the primary checkout
cd ../<repo>-<id>
bash scripts/ai/setup-worktree.sh                    # links deps, copies local-only config, allocates ports
git add .tasks/<id> && git commit -m "docs(tasks): plan <id>"   # the plan is the FIRST commit
git push -u origin HEAD
gh pr create --draft --title "<id>: <title>" --body "WIP. Plan: .tasks/<id>/PLAN.md"
bash scripts/ai/intake.sh writeback <REF> --status start   # ticket → in progress (no-op if writeback off)
bash scripts/ai/gate.sh workspace <id>               # must exit 0 before you continue
```

Why each part is non-negotiable:
- **Worktree** — the operator keeps working in their checkout while you run, and parallel slices stop
  colliding. `setup-worktree.sh` makes it cheap: dependencies are symlinked, not reinstalled.
- **Pushed branch** — a crash, a killed session, or a full disk otherwise takes the work with it.
- **Draft PR from the start** — the operator can watch the diff grow instead of receiving a wall of code
  at the end. Draft, not ready-for-review: it says "in progress", and it is opened before the code exists
  precisely so nobody has to ask what you are doing.
- **Plan committed first** — `.tasks/<id>/` is the first commit on the branch, before any code. It is
  committed, never gitignored: a reviewer reads the reasoning before the diff, and grooming survives a
  dead session. Artifacts follow the branch, so move them out of the operator's checkout into the worktree.
- **Ticket moved out of the backlog** — the tracker is where the rest of the team looks. A ticket in Todo
  while a branch and PR exist invites someone to start the same work. Move it by **intent**
  (`--status start`), never by a hardcoded state name.

Then re-read `PLAN.md` + `OPEN_QUESTIONS.md` and run `bash scripts/ai/gate.sh plan <id>`. A **new
blocker** (the plan missed something, a contradiction, a missing contract) → **STOP**: record it as a
`blocker`, escalate, touch no code. Never guess.

Source `.tasks/_worktree.env` before running anything that binds a port. Never run a package install
through a symlinked dependency dir.

## 1 · RED (see `test-author`)

Tests first, written by the test-author identity, verified by `bash scripts/ai/gate.sh red`. The suite must
fail for the intended reason. Commit the RED state. No test command configured → skip explicitly and say
so; the acceptance then rides on observation checks.

## 2 · GREEN, tier by tier

- You receive the plan, the tests, and the signatures. Implement the minimum that makes the tests pass and
  the acceptance true — no abstractions the plan does not call for.
- **You may not edit test files.** `bash scripts/ai/guard.sh builder` enforces it. A test you believe is
  wrong goes back to the test-author with the reason; you do not bend it.
- Reuse analogous existing code; match the surrounding style. Record deliberate deviations as
  `Decisions locked` in `PLAN.md` — never diverge silently.

**Commit and push after every step — not every tier, every step.**

```bash
bash scripts/ai/gate.sh committed   # fails while anything is uncommitted or unpushed
```

A step that is not committed does not exist: it cannot be reviewed on its own, cannot be reverted without
taking its neighbours with it, and is lost if the run dies. Ten small commits are reviewable; one blob at
the end is not, and that is what the operator has to read. Push each one — the draft PR is the live view
of what you are doing, and a PR that only updates at the end is a report, not a view.

In a worktree, scope every `git` call to it (`git -C <worktree> …`): the shell cwd can reset between tool
calls, and a commit then lands in the operator's checkout instead. Keep `CHECKLIST.md` current in the same
commit as the step it describes.
- Gate per tier: `bash scripts/ai/gate.sh green`. **Cap 3 fix attempts per failing gate** — on the 4th,
  stop and escalate with the raw error output. Ping-ponging against a gate burns budget and hides a real
  design problem.
- Deep self-review after each tier: correctness, integration at **real call sites** (not just the edited
  file), performance, architectural fit. Fix findings before moving on.

## 3 · Validate + evidence

- `bash scripts/ai/gate.sh green` clean (exit 0 — **not** exit 3, which means no check ran and nothing was
  verified), then run **every** check in `VALIDATION.md`, saving evidence to `.tasks/<id>/evidence/`.
  Confirm with `bash scripts/ai/gate.sh evidence <id>`.
- Shared or manual resources (one staging slot, one device, a paid budget) go **through the operator**:
  say what you need, stop, wait for their go. Never seize, restart, or repoint a shared resource.
- Do not open the PR with red or unrun checks.

## 4 · Friction

Log harness friction as you hit it to `.tasks/<id>/FRICTION.md`: stale guidance, missing commands, work you
had to do by hand twice. Raw material for `harness-improver`.

## 5 · Ready for review + review fan-out

- The PR already exists (opened as a draft in step 0). Now fill in the real summary + how-to-verify citing
  the evidence, then hand it over yourself — do not leave the draft mark for the operator to clear:

```bash
gh pr ready
bash scripts/ai/gate.sh ready <id>   # PR out of draft + body states what was not verified
```

**The PR body must state what was NOT verified.** A required section:

```markdown
## Not verified
- Check 4 (live payment observed end to end) — NOT RUN: needs the shared test merchant.
- Checks 7, 9 — NOT RUN: <reason>.
- Review ran DIVERSITY: CROSS-MODEL, not CROSS-ENGINE (one vendor available).
- RED/base check skipped for <path> (--no-base) because <reason>.
```

This is the single thing a solo agent cannot give you. "Tests are green" is true and nearly useless on its
own; what the operator needs is which parts of the green are load-bearing and which were never exercised.
Burying it in `.tasks/` does not count — they read the PR. If everything ran, write "Everything in
VALIDATION.md was run and passed" and mean it.
- Post the PR link to the tracker: `bash scripts/ai/intake.sh writeback <REF> --comment "PR: <url>"`.
  That is the **second and last** tracker write of the run — no progress narration in between, and never
  close the ticket: that is the operator's, like merging.
- Review goes **only** through `bash scripts/ai/review.sh <round> .tasks/<id>/VALIDATION.md --profile <p>`
  — lens reviewers in parallel, a wildcard for what they cannot see, a judge on `deep`. An ad-hoc agent
  review is not a substitute, including in a session that also did the grooming.
- In parallel, run `harness-improver` on the diff + `FRICTION.md`.

## 6 · Review loop (≤6 rounds)

`VERDICT: APPROVED` → done. `CHANGES_REQUESTED` → fix, re-validate, re-run with `<round+1>`. Not converged
after 6 → STOP and escalate. Watch for a degraded review (`DIVERSITY: DEGRADED`) and say so in your summary.

## 7 · Done

- Reconcile out-of-band changes (authored assets, dashboards, infra) into the repo or document them as
  externally owned.
- Remaining follow-ups → `OPEN_QUESTIONS.md`.
- **Merge is the operator's.** Do not merge yourself.

## Guardrails

Backend authority for money, permissions, progression, persistence; validate every client-originated
request. `.tasks/` is committed. No force-push to the base branch. No secrets in code or logs. No silent
TODO, `any`, or skipped test. Blocker → STOP.
