---
name: adw-run
description: Drive the AI Developer Workflow for one task end to end — intake, triage, scout, plan, groom passes, worktree, RED/GREEN implementation, validation, review fan-out — at the depth the task earns, pausing only at the human gates it earns. Use when the operator says "run the workflow", "прогони воркфлоу", "take this task through the loop", or hands over a ticket id and expects the whole loop.
arguments: [profile, ref]
argument-hint: "[superlight|light|standard|deep] [ticket-ref]"
---

# adw-run — the orchestrator of one task through the loop

You drive the whole loop for a single task. You do not write production code yourself: you run phases,
enforce gates mechanically, and spawn specialist agents whose identities are defined by what they may not
touch. Everything project-specific comes from `.tasks/_STACK.md`; never hardcode a command.

## Arguments

`$profile` — `superlight` · `light` · `standard` · `deep`, when the operator names one. Empty means
they did not, and `workflow-triage` picks. A named profile is a decision, not a hint: record it and
run it. Escalate mid-run only for the reasons in `workflow-triage`, and say so when you do.

`$ref` — the ticket id or the request itself, handed straight to `task-intake`.

## Human gates (at most two — protect the ones the profile keeps)

- **G2 · plan approval.** After the plan and validation criteria exist and grooming converged, present a
  compact summary and **stop for the operator**. This is the highest-leverage review point: a bad plan
  line becomes hundreds of bad code lines. **`standard` and `deep` only** — below those the plan is a
  dozen lines the operator would rubber-stamp, and a gate that gets rubber-stamped trains them to skim
  the one that matters.
- **G7 · merge.** After the review, present the ranked findings and **stop**. Merging is theirs, at
  every profile.

Everywhere else you proceed autonomously — **except** on a `blocker`, which always stops the run.

## What each profile actually runs

The profile is not a label on a run that happens anyway; it *is* the phase list. Read this table before
phase 1 and run only the column you are in.

| Phase | `superlight` | `light` | `standard` / `deep` |
| --- | --- | --- | --- |
| 0 · triage | skip — profile is explicit | skip if explicit | `workflow-triage` |
| 1 · scout | skip, read the files yourself | skip, read the files yourself | `context-scout` agent |
| 2 · plan | `PLAN.md` ~12 lines + `VALIDATION.md`, 1 check | short but complete | full |
| 2 · `OPEN_QUESTIONS.md` / `CHECKLIST.md` | only if a blocker appears | yes | yes |
| 3 · groom | **skip** | one inline `contracts` pass, no agent | one agent per lens |
| 3 · `GROOM_LOG.md` | not created | created | created |
| 4 · **G2** | skip | skip | **stop** |
| 5 · workspace | worktree + branch + draft PR | same | same |
| 6 · RED | one test where `TEST_CMD` exists, else observation | optional | required |
| 7 · GREEN + `gate.sh green` | required | required | required |
| 8 · validate + `gate.sh evidence` | required | required | required |
| 9 · review | `review.sh --profile superlight` (1 reviewer) | 1 reviewer | fan-out + wildcard (+ judge) |
| 10 · **G7** | **stop** | **stop** | **stop** |

Two rows never move, whatever the profile. **The workspace** — worktree, branch, draft PR — is
script-driven and takes seconds, and it is what makes a run revertible in one command and visible while
it happens; cutting it saves nothing measurable and loses everything if the session dies. **One
reviewer** — without it a small run is a solo run that awards itself a green tick, and one agent is the
cheapest independent look at a diff there is.

`superlight` still writes `PLAN.md` and `VALIDATION.md` because the gates read them: `gate.sh plan`
wants the four headers (`Touches`, `Depends-on`, `Out of scope`, `Decisions locked`) and one numbered
check, `gate.sh evidence` wants one evidence file. On a task this size three of those headers are one
word long. Nothing in `gate.sh` is skipped or special-cased for it.

## When not to run this at all

The harness has a floor. A typo, a version bump, a comment fix, a one-line config change with an
observable result: do it in the session, run `bash scripts/ai/gate.sh green`, and let the operator read
the diff. `workflow-triage` will honestly answer `superlight` for a one-liner, because it reasons about
blast radius and a one-liner has none — that is not a recommendation to spend a worktree and a PR on it.

Below the floor the cost is not the tokens, it is the operator's attention: a PR that says nothing
teaches them to stop reading PRs.

## Phases

### 0 · Intake + triage
1. `task-intake` — turn the request (ticket / prompt / bug report) into `.tasks/<id>/` with the goal and a
   back-reference to its source.
2. `workflow-triage` — pick the profile and record it in `PLAN.md`. **Skip this when `$profile` was
   given**; write the operator's choice into `PLAN.md` instead, marked as theirs. Never ask them to
   choose when they did not: state your reasoning in one line and let them override.

### 1 · Scout (agent: `context-scout`) — `standard` / `deep`
Read-only recon → provenance index. It burns its own context on grep/read/trace and returns conclusions,
so your context stays clean and the plan is not anchored on the first file anyone opened.
Below `standard` you read the files yourself: the agent's whole value is protecting a context you are
not going to fill on a task this size.

### 2 · Plan (`task-plan` + `slice-verify`)
`PLAN.md` (incl. `Touches` / `Depends-on` / scope OUT / decisions locked) and `VALIDATION.md` (every
acceptance line → ≥1 runnable check, with where evidence lands). Uncertainties → `OPEN_QUESTIONS.md`.

On `superlight` this is a dozen lines: the four headers `gate.sh plan` requires, three of them one word
long, and one numbered check. Short is the point — but the headers are not optional, because a task with
no stated scope OUT is a task that grows silently.

### 3 · Groom passes (`groom-harden`, agent: `groom-hardener`) — `light` and up
**One fresh-context pass per lens** from `LENSES` in `_STACK.md` — the lens set is the coverage. Each pass
reads `GROOM_LOG.md` first and appends its row. A lens that reports blockers or majors re-runs **after its
findings are folded in**; minors are recorded and never trigger another pass.
Check mechanically: `bash scripts/ai/gate.sh groom <id>`.

`light` runs the first lens inline, in this session, without spawning `groom-hardener` — one lens does
not need a fresh context to stay honest, and the agent's cost is the context it rebuilds.
`superlight` skips grooming entirely; `gate.sh groom` requires no lens there and passes on the blocker
check alone.

### 4 · G2 — stop for the operator — `standard` / `deep`
Present: goal, scope IN/OUT, the 3–5 decisions locked, open `clarify` assumptions, the check list, the
profile, and the estimated tier count. Wait. Fold their corrections back into the artifacts.

Skipped below `standard`. Not because the plan matters less, but because a twelve-line plan is one the
operator approves without reading, and a gate that gets rubber-stamped devalues the one that must not.

### 5 · Workspace — before any code
Worktree, branch, empty start commit, push, **draft PR** — in that order, before a single source file is
touched. Then `bash scripts/ai/gate.sh workspace <id>` must exit 0.

Grooming happened in the operator's checkout, so `.tasks/<id>/` is sitting there untracked. Move it into
the worktree and make it the **first commit on the branch** — the plan lands before the code it explains.

```bash
git worktree add ../<repo>-<id> -b <id>-<slug>
mv .tasks/<id> ../<repo>-<id>/.tasks/<id>          # artifacts follow the branch, not the checkout
cd ../<repo>-<id> && bash scripts/ai/setup-worktree.sh
git add .tasks/<id> && git commit -m "docs(tasks): plan <id>"
git push -u origin HEAD
gh pr create --draft --title "<id>: <title>" --body "WIP. Plan: .tasks/<id>/PLAN.md"
bash scripts/ai/intake.sh writeback <REF> --status start   # move the ticket out of the backlog
bash scripts/ai/gate.sh workspace <id>
```

`.tasks/` is committed, never gitignored: it is the provenance record. A reviewer opening the PR reads the
plan first and the diff second; a session that dies after grooming leaves the work recoverable.

Doing this at the end instead makes the whole run invisible: the operator cannot watch the diff grow, a
crash loses everything unpushed, parallel slices collide in one checkout, and a ticket still sitting in
Todo tells the rest of the team the work is unclaimed.

### 6 · RED (agent: `test-author`)
Tests first, written by an agent that may not touch source (`guard.sh test-author`). Gate:
`bash scripts/ai/gate.sh red` — the suite **must** fail, and the failure must be the intended assertion,
not an import error. No test command configured → say so plainly, skip RED, and rely on observation
checks; do not pretend TDD happened.

On `superlight` and `light` the test-author agent is overhead: write the one failing test yourself, then
run the same gate. The guard exists so an implementer cannot bend a test to fit; when you are about to
write both, the honest substitute is writing the test first and not touching it afterwards.

### 7 · GREEN (agent: `builder`)
Builder receives the plan, the tests, and the signatures — not the grooming history. It may not touch test
paths (`guard.sh builder`). Gate: `bash scripts/ai/gate.sh green`. **Cap 3 fix attempts per failing gate**;
on the 4th, stop and escalate with the raw error output rather than looping.

**Exit 3 is not a pass.** It means the gate ran no check at all — nothing about the diff was verified.
Do not treat it as green and do not "fix" it by moving on: record it in `FRICTION.md`, carry it to G7,
and put it in the PR's `## Not verified` section. A partial (`green: PARTIAL — …`) exits 0 and travels
the same way; the run continues, the claim shrinks.

**Commit and push after every step**, then `bash scripts/ai/gate.sh committed`. The draft PR is the live
view of the run — an uncommitted step is invisible to the operator and lost if the run dies.

### 8 · Validate (agent: `validator`)
Run every `VALIDATION.md` check, save evidence to `.tasks/<id>/evidence/`.
Gate: `bash scripts/ai/gate.sh evidence <id>`. Do not open a PR with red or unrun checks.

### 9 · Review
Fill in the PR summary + how-to-verify (including the "Not verified" section), `gh pr ready`, and confirm
with `bash scripts/ai/gate.sh ready <id>` — the run marks its own PR ready, not the operator. Then
`bash scripts/ai/review.sh <round> .tasks/<id>/VALIDATION.md --profile <profile>` — pass the profile you
actually ran, so the fan-out matches it: one reviewer below `standard`, lens reviewers in parallel above,
plus a wildcard hunting what those lenses cannot see and a judge that dedupes and adversarially verifies.
In parallel, run `harness-improver` on the diff + `FRICTION.md`.

### 10 · G7 — stop for the operator
Present the ranked, verified findings, the diversity label, **and what was never verified** — NOT RUN
checks, acceptance lines never observed, gates skipped and why. That list is the part a solo run cannot
produce; without it "green" says nothing about which parts of the green are load-bearing.
`CHANGES_REQUESTED` → fix, re-validate, re-run the round (**max 6**). Merge is the operator's.

## Rules

- **A `blocker` stops the run.** Write it to `OPEN_QUESTIONS.md`, surface it, wait. Never guess past it.
- **Gates are scripts, not opinions.** Never declare a phase done without the gate's exit code. Three
  codes, not two: `0` passed · `1` failed · `3` DEGRADED, nothing ran. Collapsing 3 into 0 is the exact
  failure the code distinguishes — a project with an empty `_STACK.md` would otherwise finish green
  having verified nothing.
- **Log friction as you go** to `.tasks/<id>/FRICTION.md` — it feeds the harness-improver.
- Keep `CHECKLIST.md` current; it is how a fresh session resumes this run after compaction.
- Report degradation honestly: a skipped RED gate, a `DIVERSITY: DEGRADED` review, an unreproducible
  check — say it in the summary rather than letting a green-looking run hide it.
- Before the first review of a project, check `bash scripts/ai/engines.sh list`. If it warns that `ENGINES`
  is unset, run `probe --write` once — reviews routed to an unauthenticated CLI return nothing, and
  nothing looks like approval.
