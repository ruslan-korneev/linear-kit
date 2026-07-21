---
name: linear-setup
description: Provision Linear teams, projects and custom views from YAML presets via the linear-kit CLI. Use when the user asks to create/configure a Linear team, project, milestones, workflow states, labels, or views in any workspace, or to inspect an existing Linear workspace's config. For filing or updating individual issues, use linear-tasks instead.
---

# Linear setup

`linear-kit` provisions Linear from declarative YAML presets. Run it as bare `linear-kit` if
installed (`uv tool install --editable <repo>`), or `uv run --project <repo> linear-kit ...`.

This skill covers workspace configuration. Day-to-day issue work — filing tasks, changing status,
listing a backlog — is `linear-tasks`.

## Rules

1. **Always `--dry-run` first**, show the user the plan, and wait for approval before applying. These are real, shared workspaces.
2. **Never pass an API key on the command line.** Keys live in `~/.config/linear-kit/config.toml` (0600). To add one, tell the user to run `linear-kit auth add <name>` themselves — it reads the key from stdin.
3. **Every command needs a workspace** — from `-w <name>` or the repo's `.linear-kit.toml`. There is **no default**, and the CLI refuses rather than guess. `linear-kit auth list` shows the configured ones. Provisioning names the team but not the workspace, so `-w` is the only thing standing between `team create` and the wrong org.
4. Every command is **idempotent** — reruns update in place rather than duplicate. Rerunning after a partial failure is safe.

## Commands

```bash
linear-kit binding                         # which workspace/team a command run here targets
linear-kit auth list                       # configured workspaces
linear-kit auth verify -w <workspace>      # key still valid? admin?
linear-kit preset list                     # bundled presets
linear-kit preset show team-standard       # raw YAML

linear-kit team create -w <workspace> --preset team-standard --name "Payments" --key PAY --dry-run
linear-kit project create -w <workspace> --team PAY --preset project-standard \
    --name "Checkout v2" --description "..." --target-date 2026-09-01 --dry-run
linear-kit view create -w <workspace> --team PAY --preset views-board --dry-run   # or views-lists

# Copy an existing team's setup into a portable preset, then apply it elsewhere.
linear-kit team export -w <workspace> --team PAY --as pay-standard -o preset.yaml
linear-kit team create -w <other> -p preset.yaml --name "New Team" --key NEW

linear-kit inspect teams|projects|labels|states|templates|views|members -w <workspace>
```

When the user says "set it up like <team>", reach for `team export` rather than transcribing by
hand. Export drops the team's name/key and excludes labels unless `--include-labels`.

`--preset` takes a bundled name or a path to any YAML file, so a one-off setup can use a preset
written to the scratchpad instead of being committed.

## What a team preset controls

Team settings (cycles, estimation, triage, timezone, privacy), workflow states, labels including
one level of label groups, and issue templates. See `src/linear_kit/presets/`.

Presets reference things **by name**, never by UUID — a resolver translates names to ids against
the target workspace at apply time, which is what makes a preset portable:

```yaml
templates:
- name: Issue
  issue: { state: Todo, assignee: me, labels: [api], project: Checkout v2 }
  form_fields:
  - { type: title, label: Title }
  - { type: textarea, label: Description, default: "What is the problem?" }
  - { type: labelGroup, label: Service, group: Service }
```

Form field types are `title`, `textarea`, `dueDate`, `labelGroup` — only these four are confirmed
to exist, so do not invent others. A bad name fails before any mutation and lists what exists.

Reconciliation semantics worth knowing:
- States and labels match **by name, case-insensitively**. Linear seeds new teams with default
  states, so presets converge onto those rather than duplicating them.
- **Order in the preset list = display order in Linear.** Unmanaged states sort after the preset's.
- Extra states and labels are **never deleted or archived** — only added and adjusted.
- `Triage` and `Duplicate` are reserved by Linear and are left untouched.

## What a views preset controls

A view is scoped to a team (`-t`), and is personal unless `shared: true`. `-p` is required —
`views-board` and `views-lists` are peers, not a default and a variant.

- **views-board** — `All Issues` and `Current cycle`: statuses as columns, projects as rows,
  final states hidden, completed work kept for a week.
- **views-lists** — `Backlog` and `Urgent`: flat lists, sub-issues unnested, empty groups shown.

```yaml
kind: views
views:
- name: All Issues
  shared: true
  filter: {}                          # scoped to the team, so no filter = everything here
  display:
    layout: board
    group_by: workflowState           # columns
    sub_group_by: project             # rows
    order_by: priority
    show_completed: week
    show_empty_groups: true
    hide_states: [Done, Canceled, Duplicate]
    properties: [id, status, assignee, priority, labels]
```

Filter fields AND together; a list within one field ORs. `any_of` nests alternatives under OR.
Available: `state` (by name), `state_type`, `assignee`, `creator`, `labels`, `priority`,
`project`, `cycle`, `team`, `due_date`, `estimate`, `any_of`.

Prefer `state_type` (`triage`/`backlog`/`unstarted`/`started`/`completed`/`canceled`) over `state` names,
and avoid `labels`, in any preset meant to travel — types are fixed by Linear, names and labels
are per-workspace. `views-lists` breaks this deliberately (needs Todo/Pause/In Progress) and so
fits `team-extended` teams, not `team-standard` ones, which lack `Pause`.

`display` values are validated locally against a **confirmed-only** vocabulary, because Linear
validates `preferences` not at all (see API facts). Do not invent values to make a request fit:
- `layout`: `list`, `board`
- `group_by`: `workflowState`, `priority`, `none`
- `sub_group_by`: `project`, `priority`, `none` (a separate list — see API facts)
- `order_by`: `priority`, `sortOrder`
- `show_completed`: `all`, `week`
- `nesting`: `showAll`, `none`
- booleans: `show_sub_issues`, `show_triage`, `show_empty_groups`, `show_empty_sub_groups`,
  `order_completed_by_recency`
- `properties` (exclusive list — omitting one turns it off): `id`, `status`, `assignee`,
  `priority`, `project`, `milestone`, `labels`, `due_date`, `estimate`, `cycle`, `links`,
  `time_in_status`, `created`, `updated`. Nothing outside the list is touched (SLA, pull
  requests, Sentry keep whatever the workspace has). `links` is `fieldPreviewLinks`, **not**
  `fieldLinkCount`.
- `hide_states`: state names; needs `group_by: workflowState`

If the user wants something outside these lists, that value is *unobserved*, not impossible: have
them set it by hand in the UI, then run `inspect views` to read the real string back and extend
`models.py`. Guessing produces a silently broken view. Note `inspect views` shows the *merged*
values — to see what was actually written, read `organizationViewPreferences.preferences`.

## Not built yet

Project and document templates (only `type: issue` is supported, since their templateData shape
has never been observed), and exporting templates or views back into a preset.

## API facts (verified against a live workspace)

- Auth header is `Authorization: <key>` — **no** `Bearer` prefix.
- Rate limiting returns **HTTP 400 + code `RATELIMITED`**, not 429. The client retries it.
- `teamCreate` succeeds with an admin key; every create input accepts a client-supplied `id` (UUID v4).
- `workflowStateCreate` **ignores `position`** and appends; order is only settable via
  `workflowStateUpdate` after the state exists. Positions are per state *type*, not global.
- `projectCreate` requires `teamIds`; milestones are a separate `projectMilestoneCreate` per item.
- Free workspaces cap the number of teams (2 observed). `teamCreate` then fails with a bare
  "Access denied" whose real cause only appears in `extensions.userPresentableMessage`.
- A view is **two objects**: `customViewCreate` (name, scope, `filterData`) plus a separate
  `viewPreferencesCreate` keyed by `customViewId` for grouping/ordering/layout.
- `filterData` is a typed `IssueFilter` → a bad filter is rejected by the API. `preferences` is
  `JSONObject` and validated by **nothing** → `{"layout": "bogus"}` is stored and read back
  verbatim, silently breaking the view. This is why the vocabulary above is confirmed-only and
  enforced client-side; probing cannot distinguish valid from invalid.
- `customView.viewPreferencesValues` is typed on read and returns the merged org+user result —
  that read path is how the vocabulary gets recovered.
- Preferences exist at `user` and `organization` level; presets write `organization`. An unset key
  leaves Linear's default rather than clearing it. The UI writes only on *change*, so a key absent
  from a layer means "untouched", not "off" — which is why the merged view is misleading when
  recovering what a click did.
- **`viewPreferencesUpdate` REPLACES the preferences object rather than merging.** Writing one key
  wipes every other. linear-kit reads-then-overlays to survive this; anything else touching this
  mutation must do the same or it will silently destroy hand-made settings.
- "Show empty groups" is **one toggle over several keys**: a list writes `showEmptyGroupsList`, a
  board reads `showEmptyGroups` (columns) and `showEmptySubGroupsBoard` (rows). Writing the key
  for the wrong layout is accepted and does nothing, so `layout` must be explicit.
- `hiddenColumns` holds **workflow state ids** when grouping by state. Confirmed by writing ids
  and watching the columns vanish — read-back alone proves nothing, since nothing is validated.
- Cycle filters use `isActive`/`isNext`/`isPrevious` booleans, not ids → a "current cycle" view
  survives the cycle rolling over. `assignee: {isMe: {eq: true}}` resolves per viewer.
