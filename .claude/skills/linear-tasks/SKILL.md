---
name: linear-tasks
description: Create, update, list, link and comment on Linear issues via the linear-kit CLI. Use when the user asks to file/create a task or issue, change an issue's status/assignee/labels/priority, mark one issue as blocking/blocked by another or as a sub-issue of another, look at their backlog or what is in progress, or comment on an issue. For configuring a workspace itself — teams, workflow states, labels, projects, milestones, views — use linear-setup instead.
---

# Linear tasks

Day-to-day issue work through `linear-kit`. Run it as bare `linear-kit` if installed
(`uv tool install --editable <repo>`), or `uv run --project <repo> linear-kit ...`.

This skill covers issues. Provisioning the workspace they live in — teams, states, labels,
projects, views — is `linear-setup`.

## The binding decides where a task goes. Never guess it.

The danger here is not a command that fails; it is one that **succeeds in the wrong workspace**.
Filing "fix the auth timeout" from repo A into repo B's team works, reports success, and nobody
finds out until someone reads the wrong backlog. So the target is never inferred from context,
never taken from the default workspace, and never guessed from the repo's name.

### Ask the CLI where you are. Never read `.linear-kit.toml` to work it out.

```bash
linear-kit binding      # workspace / team / project + every file that decided them
```

Run this first, whenever the target matters. It touches no network and changes nothing.

Reading the file yourself gives the wrong answer, because the files **cascade**: the one in the
directory you are standing in is a fragment, and usually the least informative one. A `crm/`
holding only `project = "CRM"` is not "an incomplete binding that will be rejected" — it is a
complete binding whose workspace and team come from the repo root's `.linear-kit.toml` above it.
Concluding otherwise from the local file and then asking the user to fix it is the failure mode
this section exists to stop. `linear-kit binding` resolves the whole chain the way every real
command does; one `cat` does not.

### What the binding looks like

```toml
workspace = "my-workspace"
team = "PAY"
project = "Checkout v2"   # optional — new issues join it, `issue list` scopes to it
```

`linear-kit` reads it from the working directory upward and **refuses to create or change an issue
without one**, rather than falling back to a default. Every plan prints `note: Bound by <path>` for
each file that contributed, so the target is visible before anything is sent.

**Files cascade**, outermost first, each overriding only the keys it names. In a monorepo, bind the
workspace and team once at the root and give each service a one-line file for its own project:

```
repo/.linear-kit.toml                   workspace = "my-workspace"
                                        team = "PAY"
repo/services/billing/.linear-kit.toml  project = "Billing"
```

So when a repo already has a root binding and the user wants a subdirectory filed against a
different project or team, **add a file naming only that key** — do not copy the workspace down.
Every copy is a chance to drift from the root. Absent means inherit; `project = ""` opts a
subdirectory out of a project the root names.

What that means for you:

1. **`linear-kit binding` errors with "No .linear-kit.toml above this directory"** → *that* is what
   an absent binding looks like, and it is the only thing that counts as one. Do not work around it
   with `-w`/`-t`. Ask which workspace and team this repo belongs to (`linear-kit auth list` shows
   the workspaces, `linear-kit inspect teams -w <ws>` the teams), then offer to write the file. It
   is committed, so it is the user's call — show it and let them approve.
2. **Never pass `-w`/`-t` to override a binding that exists** unless the user explicitly named a
   different workspace or team in this conversation. The flags exist for people, not for you to
   route around a refusal. Doing it anyway is not silent — the plan prints
   `note: OVERRIDE: --team OPS beats 'PAY' from <file>` — but a note is a record, not permission.
3. **The user names a different project/team than the binding** → do it, but `--dry-run` first and
   show them the `OVERRIDE` line, so a slip is caught before the issue exists.
4. **Working outside any repo** (a scratch dir, `~`) → there is no binding and there is no default
   to fall back on. Ask which workspace and team, then pass `-w`/`-t` for that one command.

**There is no default workspace anywhere in linear-kit** — reads included. `issue list`,
`issue show` and `inspect` all need a target from `-w` or the binding, and refuse without one. So
running `linear-kit issue list` from `~` is an error, not a listing of some arbitrary workspace.
`issue list` also scopes to the bound team and the bound project: `--all-teams` drops the team
scope while keeping the workspace, `--all-projects` drops the project scope while keeping the
team. An explicit `--project` (including `--project none`, meaning issues in no project) beats
the binding.

## Rules

1. **`--dry-run` first** for anything touching an issue that already exists (`update`, `comment`),
   for any batch of more than one create, and for any create whose target you had to ask about.
   Show the plan, wait for approval. A single create in a bound repo can go straight through —
   the binding is the check.
2. **There is no `issue delete`.** A wrongly created issue has to be removed by hand in the UI.
   That asymmetry is why the target matters more than the content.
3. **Never pass an API key on the command line.** Keys live in `~/.config/linear-kit/config.toml`.
4. Reruns are safe: `update` is idempotent, `create` is not — rerunning it files a second issue.

## Commands

```bash
linear-kit binding                          # where would a command here go? ask before assuming

# In a repo with .linear-kit.toml, no -w/-t needed:
linear-kit issue create --title "Fix auth timeout" \
    -d "Sessions drop after 30s." -s Todo --priority urgent -a me -l Bug --dry-run

linear-kit issue list                       # the bound team, and the bound project if one is set
linear-kit issue list -s Todo -a me
linear-kit issue list --all-projects        # whole team, ignoring the bound project
linear-kit issue list --all-teams --state-type started
linear-kit issue list --json                # for parsing
linear-kit issue show PAY-12                # + description, sub-issues, links, comments
linear-kit issue update PAY-12 --state "In Review" --add-label Feature
linear-kit issue comment PAY-12 -m "Deployed to staging."
linear-kit issue link PAY-12 --blocked-by PAY-9 --child PAY-14

# Outside a bound repo, or when the user names the target explicitly:
linear-kit issue create -w my-workspace -t PAY --title "..." --dry-run
```

Fields on `create` / `update`: `--title`, `-d/--description` (markdown), `-s/--state`,
`--priority`, `-a/--assignee`, `-l/--label`, `--project`, `--milestone` (needs `--project`),
`--parent PAY-3` (makes it a sub-issue), `--due-date YYYY-MM-DD`, `--estimate`.

- `--priority`: `none`, `urgent`, `high`, `medium`, `low` — names, not numbers. Linear's scale is
  inverted (urgent = 1), so never pass a raw number.
- `--assignee`: `me`, an email, a display name, or `none` to unassign.
- `--state`: a workflow state **name** — team-specific. A wrong one fails before any mutation and
  lists what the team has.
- `--project none` detaches, and overrides a project named in the binding.

`update` is a partial patch: what you do not name keeps its value.

## Links: the direction is in the flag

`blocks` and `blocked by` are **one** Linear relation seen from opposite ends, so the flag names
which end the issue in the argument is on. Get it backwards and the link is created, reads as fact,
and nobody notices.

```bash
linear-kit issue link PAY-12 --blocks PAY-13      # PAY-12 holds PAY-13 up
linear-kit issue link PAY-12 --blocked-by PAY-9   # PAY-9 holds PAY-12 up
linear-kit issue link PAY-12 --related PAY-40
linear-kit issue link PAY-12 --duplicate-of PAY-11
linear-kit issue link PAY-12 --parent PAY-3       # PAY-12 becomes a sub-issue of PAY-3
linear-kit issue link PAY-12 --child PAY-14 --child PAY-15   # the other way round
```

Read the user's sentence literally: "PAY-12 is waiting on PAY-9" → `PAY-12 --blocked-by PAY-9`.
"nothing can start until PAY-12 is done" → `PAY-12 --blocks ...`. When the sentence is ambiguous,
`--dry-run` and show the plan line — it spells the direction out in words
(`issueRelationCreate  PAY-12 blocked by PAY-9`).

Every option above also works on `create` and `update`, which is how a task is filed already
linked: `issue create --title "..." --blocked-by PAY-9 --child PAY-14`. A wrong identifier fails
before the issue is created, not after.

- **Reruns are safe.** `link` reads what the issue already has and skips it with a note.
- **Nothing removes a link.** Unlinking is a UI job, same asymmetry as `issue delete`.
- **`--duplicate-of` moves the issue to the Duplicate state** — Linear does that itself. Do not use
  it as a soft "these two look alike"; that is `--related`.
- A mutual block (A blocks B *and* B blocks A) is accepted by Linear. If the plan notes that the
  opposite direction already exists, stop and check with the user — it is usually a flipped flag.

## Labels: --add-label, not --label

**`--label` replaces the issue's entire label set.** `linear-kit issue update PAY-12 -l Feature`
on an issue labelled `Bug` leaves it labelled `Feature` alone — `Bug` is gone, and the command
reports success. This mirrors Linear's `labelIds`, which replaces rather than merges.

So when the user says "add the bug label", use `--add-label Bug`. It reads the issue's current
labels and folds the change in. `--remove-label` likewise. Reach for `-l/--label` only when the
user is stating the complete list on purpose. The two cannot be combined; the CLI rejects it.

## Filters

`issue list` takes the same filter vocabulary a views preset does, rendered by the same code —
a list and a custom view scoping the same way cannot disagree.

Filters AND together; repeating one ORs its values (`-s Todo -s "In Progress"` = either).

- `-s/--state` (name), `--state-type` (`triage`/`backlog`/`unstarted`/`started`/`completed`/
  `canceled`), `-a/--assignee`, `-l/--label`, `--priority`, `--project`, `--cycle`
  (`active`/`next`/`previous`/`none`), `-n/--limit` (default 50), `--json`.
- `-s/--state` and `-l/--label` name per-team things, so they need a team — from the binding or
  `-t`. `--state-type` works across the workspace and is the portable choice.

"What am I working on" = `issue list -a me --state-type started`.
"My backlog" = `issue list -a me --state-type backlog`.

## Not built

Assigning an issue to a cycle (`--cycle` filters a list, but nothing sets one) — the shape was
never verified against a team with cycles enabled, and guessing undocumented Linear surface is
how this project's existing bugs were made. Also: no `issue delete`, no removing a link once made,
no declarative issue presets (seeding a backlog from YAML), and no `similar` relation — it is in
Linear's enum but nothing in the UI was found that produces one, so its meaning is unverified.

## API facts (verified against a live workspace)

- `issue(id:)` and `issueUpdate(id:)` accept the **human identifier** (`PAY-12`) as well as the
  UUID — no lookup needed.
- An identifier matching nothing is a **GraphQL error**, not a null issue, and Linear's message
  does not say which issue it meant. linear-kit puts the identifier back in.
- **`issueUpdate.labelIds` replaces, it does not merge** (confirmed: `Bug` + `labelIds:[Feature]`
  → `Feature` alone). Every other field is a normal partial patch — updating `priority` alone left
  labels untouched. See the labels section above.
- Unassigning needs an explicit `assigneeId: null`; omitting the key means "keep".
- **A relation's direction is in the two id fields, not in its type**: `blocks` reads *issueId
  blocks relatedIssueId*, so "blocked by" is the same type with the sides swapped. Re-creating a
  relation that exists returns the existing one rather than a duplicate.
- `related` is symmetric — created A→B then B→A, one relation remained with its direction
  rewritten. `blocks` is not: A blocks B and B blocks A can both exist.
- A `duplicate` relation moves the `issue` side to the **Duplicate state** on its own.
- A sub-issue is not a relation: `parentId` is a field on the **child**, so `--child` is an
  `issueUpdate` on the other issue. Linear refuses a parent cycle.
- Rate limiting is **HTTP 400 + `RATELIMITED`**, not 429. The client retries it.
- Errors put the real cause in `extensions.userPresentableMessage`; `message` is often a bare
  "Access denied".
