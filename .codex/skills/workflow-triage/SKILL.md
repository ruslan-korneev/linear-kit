---
name: workflow-triage
description: Decide how much workflow a task deserves — profile superlight / light / standard / deep — and record the choice with its reason in PLAN.md. Use at the start of every run, before planning, unless the operator named a profile themselves. Prevents a typo fix from costing twenty agent runs and a persistence migration from getting one shallow review.
---

# workflow-triage — right-size the loop

The full loop costs ~15–20 agent runs. Some tasks deserve it; most don't. Pick the profile **from the
blast radius of being wrong**, not from the size of the diff. State the choice in one line and move on —
do not ask the operator.

**The operator can name the profile** (`/adw-run deep SM-12`). When they have, do not run this skill to
second-guess them: record their choice in `PLAN.md` marked as theirs and start. Triage decides when
nobody decided.

## Profiles

| | `superlight` | `light` | `standard` | `deep` |
| --- | --- | --- | --- | --- |
| Scout | skip | skip (read the files directly) | yes | yes, multi-angle |
| Groom lenses | **none** | `contracts`, inline | `contracts` + `adversary` | every lens in `LENSES` |
| TDD | one test where a test command exists | optional | yes where a test command exists | yes, RED gate enforced |
| Review | 1 reviewer | 1 reviewer | 3 lenses + **wildcard** + judge | all lenses + wildcard + judge |
| Human gates | G7 only | G7 only | G2 + G7 | G2 + G7 |

Every profile keeps the worktree, the draft PR, `gate.sh green` and `gate.sh evidence`. What scales is
how much thinking happens *before* the code and how many angles look at it *after* — not whether the
work is tracked or verified.

**The wildcard reviewer and the judge stay on at `standard`.** Measured on a real run: every major finding
came from an adversarial angle — the grooming `adversary` lens, and the review pass that asked "what does
a person who already paid see?". Extra grooming passes past the lens set produced only minors. So weight
belongs on adversarial review of the **diff**, not on more ceremony before the code exists.

## Choosing

Go **deep** when *any* holds:
- data migration, or anything that can lose or corrupt persisted data
- a change that is hard to reverse once shipped (public interface, published asset, external side effect)
- concurrency, ordering, or retry semantics across systems
- a contract many consumers depend on

Money, permissions, authentication and progression **do not automatically mean `deep`**. They mean the
adversarial angle is mandatory — which `standard` already gives (the `adversary` groom lens plus the
wildcard reviewer). Sending every money-touching task to `deep` costs several times more and, on the
evidence, adds minors. Reach for `deep` when being wrong is *unrecoverable*, not merely expensive.

Go **light** when *all* hold:
- fully reversible in one revert, no state left behind
- no contract, no persisted data, no trust boundary
- the acceptance is observable in a single check
- an experienced engineer would review it in under two minutes

Go **superlight** when `light` holds *and* there is nothing for an adversarial reader to find: the
change is self-contained, its acceptance is one observation, and being wrong is noticed immediately
rather than discovered later. A copy change, a config value with a visible effect, a small fix in one
function nobody else calls. Grooming a change like that produces minors about the grooming.

Otherwise **standard**. When genuinely torn, take the heavier one: an unnecessary review pass costs
tokens, a missed contract bug costs a migration.

**Below `superlight` there is no profile, there is no run.** A typo, a version bump, a comment: do it
in the session, run `gate.sh green`, show the diff. Triage answers on blast radius, and a one-liner has
none — that is not a licence to spend a worktree and a PR on it. See the floor in `adw-run`.

## Escalation and de-escalation

The profile is not frozen. Escalate mid-run and say why:
- grooming surfaces an undefined contract or a trust boundary → `standard` → `deep`
- the diff grows past its planned scope → escalate one level
- a review round finds a blocker → next round runs `deep`
- a `superlight` task turns out to touch a second caller, or its acceptance needs more than one
  observation → `light` or `standard`, before writing code

An operator-named profile is escalated for the same reasons and no others — tell them at the moment you
do it, with the trigger. Silently upgrading their choice is how a "quick fix" becomes an afternoon.

De-escalate only before implementation starts, never to avoid a failing gate.

## Output

One line in `PLAN.md` § Overview:

```markdown
**Profile:** deep — touches the reward contract + a profile schema migration (irreversible on rollback).
```

When the operator named it, say so — the line records who decided, not just what:

```markdown
**Profile:** superlight — operator's choice.
```

Plus a `Profile changed:` line under `Decisions locked` if it moves mid-run.

## Do not

- Don't pick `deep` for everything "to be safe" — it trains the operator to skim, and a skimmed gate is no gate.
- Don't pick `light` because the deadline is tight; that is exactly when the blast radius argument matters.
- Don't ask the operator to choose; state your reasoning and let them override.
