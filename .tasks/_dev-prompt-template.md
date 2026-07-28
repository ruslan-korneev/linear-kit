# Dev-prompt — template

Emitted by the `dev-prompt` skill once both gates exit 0 and the operator approved the plan. Fill every
`<…>` from `.tasks/<id>/PLAN.md` + `VALIDATION.md`. The result must stand alone — a fresh background
session gets no prior conversation.

```
Implement <id> (<name>). Plan: .tasks/<id>/PLAN.md. Rules: AGENTS.md. Check kit: .tasks/_STACK.md.
Profile: <superlight|light|standard|deep>.

BRANCH: <id>-<slug>   (worktree: yes)

STEP -1 (workspace, BEFORE touching any source file — in this order):
  git worktree add ../<repo>-<id> -b <id>-<slug>
  mv .tasks/<id> ../<repo>-<id>/.tasks/<id>   # if grooming left the artifacts in the primary checkout
  cd ../<repo>-<id>
  bash scripts/ai/setup-worktree.sh        # links deps, copies local-only config, allocates ports/schema
  git add .tasks/<id> && git commit -m "docs(tasks): plan <id>"   # the plan is the FIRST commit
  git push -u origin HEAD
  gh pr create --draft --title "<id>: <name>" --body "WIP. Plan: .tasks/<id>/PLAN.md"
  bash scripts/ai/intake.sh writeback <REF> --status start   # ticket out of the backlog, by intent
  bash scripts/ai/gate.sh workspace <id>   # must exit 0 before you continue
  Source the env before running anything that binds a port: `set -a; . .tasks/_worktree.env; set +a`.
  Never run a package install through a symlinked dep dir.
  Doing this at the end instead makes the run invisible: nobody can watch the diff grow, and a crash
  takes everything unpushed with it.

STEP 0 (gate): re-read PLAN.md + OPEN_QUESTIONS.md, then:
  bash scripts/ai/gate.sh plan <id>
  Any NEW blocker (the plan missed something, a contradiction, a missing contract) → STOP: write it to
  OPEN_QUESTIONS.md as a `blocker` and ask the operator. Do NOT touch code while a blocker is open.

GOAL (verifiable acceptance): <one line>.

SCOPE IN:  <from PLAN tiers/deliverables>.
SCOPE OUT: <what we do NOT touch>.

STEP 1 — RED (tests first):
  Write the failing tests for the acceptance. You may NOT touch source paths in this step:
    bash scripts/ai/guard.sh test-author --head
  Then: bash scripts/ai/gate.sh red
  The suite MUST fail, and the failure must be the intended assertion — not an import or syntax error.
  Commit the RED state. No test command configured → say so, skip RED, rely on observation checks.
  Do not fake a TDD step.

COMMIT CADENCE (every step, not every tier):
  After each step: commit + push, then `bash scripts/ai/gate.sh committed` (fails while anything is
  uncommitted or unpushed). Small commits are reviewable; one blob at the end is not, and the draft PR
  is the operator's live view of the run. In a worktree, scope git calls: `git -C <worktree> ...` — the
  shell cwd can reset between tool calls and a commit then lands in the operator's checkout.

STEP 2 — GREEN (tier by tier):
  Implement the minimum that makes the tests pass and the acceptance true. You may NOT edit test files:
    bash scripts/ai/guard.sh builder --head
  A test you believe is wrong goes back with a reason — you do not bend it.
  Per tier: bash scripts/ai/gate.sh green
  CAP 3 fix attempts per failing gate; on the 4th, STOP and escalate with the raw error output.
  Deep self-review per tier: correctness, integration at REAL call sites, performance, architectural fit.
  Record deliberate deviations as "Decisions locked" in PLAN.md — never diverge silently.

STEP 3 — VALIDATE:
  Run EVERY check in .tasks/<id>/VALIDATION.md; evidence → .tasks/<id>/evidence/
  Confirm: bash scripts/ai/gate.sh evidence <id>
  SHARED/MANUAL RESOURCES (<name them: staging slot, device, paid API budget>): ask the operator, STOP
  and WAIT for their "go", then run your checks and report "done". Never seize or restart a shared
  resource yourself.

STEP 4 — READY FOR REVIEW (in parallel):
  1. Fill in the PR summary + how-to-verify citing the evidence, then `gh pr ready` (the PR has been
     a draft since STEP -1). The body MUST carry a "## Not verified" section listing every check that
     was NOT RUN and why, any acceptance line never observed, a degraded review diversity label, and any
     skipped gate. "Tests are green" without that is true and useless.
     Confirm: bash scripts/ai/gate.sh ready <id>   # fails while the PR is still a draft
     Post the link to the tracker:
     `bash scripts/ai/intake.sh writeback <REF> --comment "PR: <url>"` — the second and last tracker
     write of the run. Never close the ticket; that is the operator's.
  2. bash scripts/ai/review.sh 1 .tasks/<id>/VALIDATION.md --profile <profile>
     Lens reviewers in parallel + a wildcard + (deep) a judge. Findings are posted to the PR.
  3. harness-improver on the diff + .tasks/<id>/FRICTION.md → HARNESS_PROPOSALS.md (proposals only).
  4. APPROVED → done. CHANGES_REQUESTED → fix, re-validate, re-run with round+1. MAX 6 rounds, then
     STOP and escalate. Report if the review ran with DIVERSITY: DEGRADED.

GUARDRAILS (AGENTS.md):
  - Backend authority for money / permissions / progression / persistence; validate every
    client-originated request.
  - .tasks/ is committed. No force-push to the base branch. No secrets in code or logs.
  - No silent TODO / `any` / skipped test. Keep diffs reviewable.
  - Blocker → STOP + OPEN_QUESTIONS.md; never push a broken PR.

DoD: gate.sh green · gate.sh evidence <id> · every VALIDATION.md check green with evidence · acceptance
  met · PR opened. Merge is the operator's, after APPROVED.

Keep CHECKLIST.md + OPEN_QUESTIONS.md current. Log friction in FRICTION.md.
```
