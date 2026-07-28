---
name: groom-harden
description: Adversarial completeness passes over a groomed task — one fresh-context pass per lens (contracts, failure modes, adversary, meta), each reading and appending to GROOM_LOG.md so passes advance instead of repeating. Loops until two consecutive quiet passes. Its converged state is a gate condition for implementation.
---

# groom-harden — passes that get further, not passes that repeat

The grooming skills produce the artifacts. This is the adversarial pass over them: fresh, skeptical eyes
that assume the groom is **incomplete** and try to prove it. Read-only on code; edits only `.tasks/<id>/`.

## Why fresh context each pass

A pass that inherits the grooming conversation inherits its blind spots — it already "knows" why every
choice was made and stops questioning it. So each pass runs as a **separate agent / cleared session**
whose entire input is: the artifacts, the repo, its assigned lens, and `GROOM_LOG.md`.

The ledger is what keeps passes moving forward instead of re-deriving the same three findings. Read it
**first**, every time.

## Lenses (one per pass, rotating)

From `LENSES` in `.tasks/_STACK.md` — the four core ones, plus any domain lenses the project added. The
profile decides how many run: `superlight` → none at all; `light` → `contracts`, run inline in the
session rather than by an agent; `standard` → `contracts` + `adversary`; `deep` → all.

1. **contracts** — every API/event/persisted contract the slice introduces or touches: source of truth,
   payload shape, writers/readers, validation, versioning, forbidden writes. Ownership ambiguity between
   two components is a finding, not a detail.
2. **failure-modes** — null/empty/boundary, ordering and concurrency, retries and idempotency, partial
   failure and rollback, clock/timezone, resource exhaustion, behavior at scale.
3. **adversary** — someone actively trying to break it: trust boundaries, client-supplied values taken on
   faith, authz gaps, rate/abuse surfaces, economic exploits, data exposure in logs.
4. **meta** — the pass that reads the other passes' findings and asks **what none of those lenses could
   see by construction**: product fit, operability, observability, migration/day-2, developer experience,
   the unhappy human path. This is where the non-obvious gaps live.

Domain lenses (economy, compliance, accessibility, multi-tenancy, …) are data in `_STACK.md`, not new code.

## One pass

1. Read `GROOM_LOG.md`: the **Closed** and **Rejected** tables are binding. Do not re-raise a settled item
   without evidence that did not exist before. Restating a concern more forcefully is not evidence.
2. Read `PLAN.md`, `OPEN_QUESTIONS.md`, `VALIDATION.md`, and the canon they cite.
3. Work your lens hard against the artifacts. For every candidate finding ask: *does this change scope,
   implementation, validation, or risk?* If not, it is noise — drop it.
4. Also check, every pass, regardless of lens: no open `blocker`; every load-bearing `clarify` is confirmed
   rather than asserted; every acceptance line maps to ≥1 runnable check; `Touches` / `Depends-on` accurate.
5. Fold findings into the artifacts — `OPEN_QUESTIONS.md` (blocker/clarify), `PLAN.md` (edge cases,
   contracts, decisions), `VALIDATION.md` (missing checks).
6. Append your row to `GROOM_LOG.md`, and add anything you examined-and-settled to **Closed**, anything you
   judged unreal to **Rejected**.

## Stop rule — coverage, not repetition

**One pass per lens.** The lens set is the coverage: when every lens has run once and closed clean, the
groom is done. A lens is repeated **only if it found a blocker or a major**, and then only that lens,
after its findings are folded in.

Counting "quiet passes" instead rewards asking the same questions again. Measured on a real run: passes
five and six produced three minors and zero majors — a third of the token budget for nothing. All three
majors came from distinct lenses, on their first pass.

**Minors are recorded, not chased.** They go in the ledger's Minors table and stop there; fold one into the
plan if it is cheap. A minor never justifies another pass.

Machine check: `bash scripts/ai/gate.sh groom <id>` — passes when every lens in `LENSES` has a row whose
last entry reports 0 blockers and 0 majors, and no blocker is open.

Final line of every pass, exactly one of:
- `VERDICT: QUIET` — nothing new at this lens; ledger updated; this lens is closed.
- `VERDICT: FINDINGS` — blockers/majors listed; they get folded in and **this lens re-runs**. Minors alone
  are not FINDINGS: record them and close the lens.

## Do not

- Don't pass with an open `blocker`.
- Don't manufacture findings to look thorough — a clean groom passes cleanly, and the ledger makes an
  inflated pass obvious in hindsight.
- Don't re-raise Closed or Rejected items; that is how a loop stops converging.
- Don't write implementation code or fix product code — this hardens the groom, not the build.
- Don't let findings live only in chat: unrecorded means it did not happen.
