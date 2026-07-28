---
name: task-intake
description: Turn an incoming request — a tracker ticket, an operator prompt, or a bug report — into a .tasks/<id>/ workspace with the goal, source reference, and intake type recorded. Works with any tracker through a command template, no MCP required. Use as the first step of any run.
---

# task-intake — the adapter at the front of the loop

The loop must start the same way regardless of where work comes from. This skill normalizes the entry and
records provenance, so nothing downstream needs to know whether the task came from a tracker, a CLI, or a
sentence the operator typed.

## The contract (all the core needs from any tracker)

| Field | Required | Use |
| --- | --- | --- |
| `id` | yes | `.tasks/<id>/`, branch name, PR title — lowercased key (`sm-12`, `gh-431`) |
| `title` | yes | one line |
| `body` | yes (may be empty) | → `extra_context/ticket.md` |
| `url` | no | backlink in `PLAN.md` and the PR |
| `status` | no | the human-facing state at intake |

Five fields. Epics, sprints, points, custom fields — not the core's business. A tracker that cannot
produce these five is not a tracker for this purpose; use manual intake.

## The tracker is declared, never inferred

`.tasks/_STACK.md` is the **only** statement of which tracker this project uses. Nothing else counts:

- **A tracker CLI installed on the machine is not evidence.** Your tools are global; projects are not.
- **Another repo's tracker is not evidence.** Habit from a previous session is exactly the failure mode
  this rule exists to stop.
- **A skill you know how to use is not evidence.** Knowing `some-tracker-cli` says nothing about whether
  *this* project files tickets there.
- **An issue-shaped key in the request (`ABC-12`) is not evidence** of which system it belongs to.

Empty `INTAKE_CMD` → **manual intake**. It does not mean "go find a tracker". Ask the operator.

Why the rule is strict: a misfiled ticket does not fail loudly. It succeeds, in the wrong workspace, and
stays wrong until a human reads a backlog that makes no sense. The same applies to writeback — moving a
ticket in someone else's project is worse than doing nothing.

If the operator names a tracker that `_STACK.md` does not mention, that is a **config change to propose**,
not an assumption to act on: show them the line to add, and offer manual intake for the current run.

## Three levels of support — pick the lowest one that works

**Level 0 · manual.** `INTAKE=manual` (or no `INTAKE_CMD`). The operator pastes the ticket; you normalize
it. Always available, zero configuration, works with a tracker that has no API at all.

**Level 1 · the command this project declares.** Whatever the project already uses is first-class — an
in-house CLI, `gh`, `jira`, `curl` against an API. It is a template in `.tasks/_STACK.md`, filled in by
the operator, never guessed:

```ini
INTAKE=<tracker-name>
INTAKE_CMD=<your-cli> issue show <ref> --json
INTAKE_SKILL=<skill that knows this CLI, if any>
INTAKE_STATUS_CMD=<your-cli> issue update <ref> --state "<value>"
INTAKE_COMMENT_CMD=<your-cli> issue comment <ref> --message "<value>"
```

Concrete shapes, for the operator to adapt when they set a project up:
`gh issue view <ref> --json number,title,body,url,state` · `jira issue view <ref> --raw` · any command
printing JSON with recognizable field names.

`bash scripts/ai/intake.sh fetch <ref>` substitutes `<ref>`, runs it, maps the usual JSON field names to
the contract, and writes the body to disk. Output it cannot map → it exits 4 and hands you the raw text;
load `INTAKE_SKILL` and normalize it yourself. **No MCP is required anywhere in this path** — and a new
tracker is one config line, not a code change.

**Level 2 · a script adapter.** `scripts/ai/intake/<name>.sh` printing normalized JSON. Only worth writing
when something non-interactive needs it: an orchestrator polling a queue, a batch import, CI writeback.
For everything else it is a bash wrapper around a command you could have named directly.

## Fetch failures

A failed fetch is a **stop**, not a prompt to improvise. Never invent a ticket body, never proceed from the
key alone assuming what it probably means. Report the command and its error, and offer manual intake.

## Writeback — read freely, write almost never

Default `INTAKE_WRITEBACK=false`. Agents that narrate progress into a tracker make it unreadable for the
humans who own it. With writeback enabled, the loop makes exactly two writes:

1. move the ticket to in-progress when implementation starts;
2. post the PR link when the PR opens.

Closing the ticket is a human decision, like merging. Commands come from `INTAKE_STATUS_CMD` /
`INTAKE_COMMENT_CMD`, so the core still knows no tracker:

```bash
bash scripts/ai/intake.sh writeback <ref> --status start      # intent, not a name
bash scripts/ai/intake.sh writeback <ref> --comment "PR: <url>"
```

**Move tickets by intent, never by a hardcoded name.** "In Progress" is true in one team and wrong in the
next; a status write that silently fails leaves the board lying to everyone reading it. `start` / `review`
/ `done` are resolved against the tracker's own workflow states (via `INTAKE_STATES_CMD`, reading each
state's `type`). Check how they resolve in this project with `bash scripts/ai/intake.sh states <ref>`.

`done` exists for completeness but the loop never sets it: closing a ticket is a human decision, like
merging.

## Ownership (do not duplicate state)

| Layer | Owns | Written by |
| --- | --- | --- |
| Tracker | **what** and **why**, priority, human-facing status | people |
| `.tasks/<id>/` | **how**: plan, questions, criteria, evidence | agents + operator |
| `_orchestration/BOARD.md` | **runtime**: what is in flight right now | orchestrator |

One fact, one home. The ticket body lives in `extra_context/ticket.md`; `PLAN.md` **links** it. Copying it
creates two sources of truth that silently diverge the first time someone edits the ticket.

## Ids

Lowercase the tracker key: `SM-12` → `sm-12`. UUID-shaped trackers (Notion, Trello) → first 8 characters
plus a slug (`a1b2c3d4-payment-retry`), because a folder name nobody can read defeats the point. Check for
an existing `.tasks/<id>/` before creating one. Manual intake → derive a short kebab-case slug from the
goal.

## Bug intake

A defect report takes the shorter path: **Report → Reproduce → Diagnose → Fix → Verify**. A bug run must
produce a **failing test that reproduces the defect** before any fix — that test is the RED gate. No
reproduction → reproducing it *is* the task, and "cannot reproduce" is a legitimate reportable outcome,
not a licence to change code speculatively.

## What this skill writes

`.tasks/<id>/PLAN.md`, § Overview only:

```markdown
# <id> — <title>

## Overview
- **Type:** feature | bug | tech-task | refactor | audit
- **Intake:** <INTAKE value from _STACK.md> · <ticket url> · status at intake: <status>
- **Goal (verbatim from the source):** …
- **Profile:** _(set by workflow-triage)_
- **Status:** grooming
```

Plus `extra_context/` for the ticket body and any pasted asset.

## Do not

- Don't start planning here — normalize the entry, then hand off to `workflow-triage`.
- Don't paraphrase in the Source field: paraphrase belongs in the crux, the original does not.
- Don't switch trackers by editing core files — it is one line in `.tasks/_STACK.md`. Existing task
  folders keep their own `url`; provenance is never rewritten retroactively.
