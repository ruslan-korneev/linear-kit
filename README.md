# linear-kit

Provision Linear teams and projects from declarative YAML presets, across multiple workspaces —
and manage the issues inside them from the command line.

Every command is idempotent: reruns reconcile in place instead of duplicating. Nothing is ever
deleted or archived — only created and adjusted.

## Install

```bash
uv tool install --editable /path/to/linear-kit   # global `linear-kit`
# or, from inside the clone, without installing:
uv run linear-kit --help
```

## Auth

Create a personal API key in Linear: Settings → Security & Access → New API key. Team creation
needs an **Admin**-scoped key; project/label/state work needs only Write.

```bash
linear-kit auth add my-workspace     # prompts for the key on stdin, verifies it, stores it 0600
linear-kit auth list
linear-kit auth verify -w my-workspace
```

Keys live in `~/.config/linear-kit/config.toml`. `LINEAR_API_KEY_<WORKSPACE>` overrides the file
(e.g. `LINEAR_API_KEY_MY_WORKSPACE`) for CI.

**There is no default workspace.** Every command takes its target from `--workspace` or from the
repo's `.linear-kit.toml`, and refuses to run without one — see [Which workspace an issue lands
in](#which-workspace-an-issue-lands-in). A default is silent, and silence is the whole problem:
acting on the wrong workspace does not fail, it succeeds somewhere real. "The only workspace
configured" is not a default either — that would work right up until the day a second one is added.
A `default_workspace` line left in the config is rejected rather than ignored, since a config
stating a preference the tool does not honour is a lie about where work goes.

## Use

```bash
linear-kit preset list
linear-kit team create -w my-workspace -p team-standard --name "Payments" --key PAY --dry-run
linear-kit team create -w my-workspace -p team-standard --name "Payments" --key PAY

linear-kit project create -w my-workspace -t PAY -p project-standard \
    --name "Checkout v2" --target-date 2026-09-01 --dry-run

linear-kit view create -w my-workspace -t PAY -p views-board --dry-run
```

`--dry-run` prints the exact mutations without sending them. The same plan object is printed and
executed, so a dry run cannot drift from the real one.

`-p/--preset` accepts a bundled preset name or a path to any YAML file.

### Issues

Issues are not provisioned from a preset — they are day-to-day work, named on the command line.
What carries over is the planning discipline: names resolve and payloads build before anything is
sent, so `--dry-run` works the same way and a bad state name fails before a mutation runs.

```bash
linear-kit issue create --title "Fix auth timeout" \
    -d "Sessions drop after 30s." -s Todo --priority urgent -a me -l Bug --dry-run

linear-kit issue list -s Todo -a me
linear-kit issue list --all-teams --state-type started --json
linear-kit issue show PAY-12
linear-kit issue update PAY-12 --state "In Review" --add-label Feature
linear-kit issue comment PAY-12 -m "Deployed to staging."
linear-kit issue link PAY-12 --blocked-by PAY-9 --child PAY-14
```

`issue list` takes the same filter vocabulary a views preset does, rendered by the same code — so a
list and a custom view scoping the same way cannot disagree about what the filter means. Filters
stack with AND; repeating one ORs its values. `--state` and `--label` name per-team entities and so
need a team; `--state-type` works across the whole workspace.

#### Which workspace an issue lands in

**Every** command that talks to Linear resolves its workspace the same way, because every one of
them has a workspace to get wrong. `team create --name Payments --key PAY` names the team outright
but says nothing about *where* — a default would answer that question silently, and a mutation
against the wrong workspace does not fail, it lands in a real place and reports success.

So there is no default. Commands read `.linear-kit.toml`, searching from the working directory
upward, and **refuse to run without one** rather than guess:

```toml
workspace = "my-workspace"
team = "PAY"
project = "Checkout v2"   # optional — new issues join it unless --project none
```

Explicit `--workspace` / `--team` still win, since naming both says where you mean; the file is a
default for the repo, not a lock on it. But the files are read **even when the flags are
complete**, so a flag that contradicts them is reported rather than silently obeyed:

```
note: Bound by /repo/.linear-kit.toml
note: OVERRIDE: --team OPS beats 'PAY' from /repo/.linear-kit.toml
```

Reading them only when a flag was missing is what made an override invisible — no file read, no
sources, no note, no trace of having gone somewhere other than the repo says. The flags remain an
escape hatch; they just leave a mark. A typo'd key is rejected rather than ignored — a silently
misread binding is the failure this exists to prevent.

The files are committed, so the binding travels with the repo and shows up in a diff. A central
path → workspace map would be invisible from inside the repo and would rot on the first rename.

**Files cascade**, outermost first, each overriding only the keys it names. A monorepo binds the
workspace and team once at the root; a subdirectory adds a line for its own project:

```
repo/.linear-kit.toml                   workspace = "my-workspace"
                                        team = "PAY"
repo/services/billing/.linear-kit.toml  project = "Billing"
```

Ask where you are rather than read the files — in a cascade one file is a fragment, and the nearest
one is often the least informative:

```
$ linear-kit binding
  workspace  my-workspace
  team       PAY
  project    Billing
    from /repo/.linear-kit.toml
    from /repo/services/billing/.linear-kit.toml
```

Standing in `services/billing` then means `my-workspace` / `PAY` / `Billing`. Required keys are
checked against the merged result rather than per file, which is what lets the inner file be one
line — restating the workspace in every service is how the copies drift from the root. Absent means
inherit, so `project = ""` is how a subdirectory opts out of a project the root names.

Reads follow the same rule — `inspect`, `issue list`, `issue show` and `auth verify` all need a
target — so there is one thing to learn rather than two. `issue list` additionally scopes to the
bound team and the bound project; `--all-teams` drops the team scope while keeping the workspace,
`--all-projects` drops the project scope while keeping the team, and an explicit `--project` beats
the binding.

`issue update` is a partial patch: a field you do not name keeps its value. **`--label` is the
exception** — it states the complete label list, because Linear's `labelIds` replaces the label set
rather than merging into it. Use `--add-label` / `--remove-label` to work from what the issue
already carries; those read the current labels and fold your change into them.

There is no `issue delete`: the additive-only rule applies here too.

#### Linking issues

```bash
linear-kit issue link PAY-12 --blocks PAY-13          # PAY-12 holds PAY-13 up
linear-kit issue link PAY-12 --blocked-by PAY-9       # the same relation, other way round
linear-kit issue link PAY-12 --related PAY-40
linear-kit issue link PAY-12 --duplicate-of PAY-11
linear-kit issue link PAY-12 --parent PAY-3           # PAY-12 becomes a sub-issue
linear-kit issue link PAY-12 --child PAY-14 --child PAY-15
```

**The direction is in the flag name**, not in a `--type` option: Linear stores "A blocks B" and "B
blocks A" as the same relation type, told apart only by which side of the pair each issue sits on,
so naming the type alone would leave which end ambiguous — and a swapped link is created
successfully and reads as fact.

The same options work on `issue create` and `issue update`, which is how an issue is filed already
linked:

```bash
linear-kit issue create --title "Migrate the sessions table" --blocked-by PAY-9 --child PAY-14
```

Every issue named is looked up while the plan is built, so `--blocks PAY-999` fails before the new
issue is created rather than leaving it half-linked.

Linking is idempotent and additive, like everything else here. `issue link` reads the links the
issue already has and skips the ones that are there, saying so; nothing removes a link, so
unlinking is a job for the UI. Two directions worth knowing about:

- `--duplicate-of` **moves the issue to the Duplicate state** — Linear does that itself, not
  linear-kit. The plan says so before it runs.
- Linear accepts a mutual block (A blocks B *and* B blocks A). Asking for one when the opposite
  already exists is therefore not an error; the plan flags it, since it is usually a typo'd
  direction.

`issue show` prints the links in both directions, under `sub-issues` and `links`.

### Exporting an existing team

Turn a team someone configured by hand into a portable preset:

```bash
linear-kit team export -w my-workspace --team PAY --as pay-standard -o preset.yaml
linear-kit team create  -w other-workspace -p preset.yaml --name "New Team" --key NEW
```

The export drops the team's name and key — a preset describes how a team is configured, not which
team it is. Labels are excluded unless `--include-labels`, since they usually name products and
services specific to one workspace. Reserved states are skipped; Linear creates those itself.

Export is verified by round-trip: exporting a team, applying the result elsewhere, and exporting
again reproduces the original YAML byte for byte.

### Inspecting a workspace

```bash
linear-kit inspect teams|projects|labels|states|templates|views|members -w my-workspace
```

`inspect templates` and `inspect views` dump raw `templateData` / `filterData` — that is how you
recover those (undocumented) shapes: build one by hand in the UI, read it back, mirror it.

## Presets

`src/linear_kit/presets/*.yaml`, validated by pydantic before any mutation runs, so a typo fails
locally rather than halfway through provisioning.

A team preset covers team settings (cycles, estimation, triage, timezone, privacy), workflow
states, labels including one level of groups, and issue templates. Order in the `workflow_states`
list is the display order in Linear.

### Names, not ids

Linear identifies everything by workspace-specific UUID, so a preset holding raw ids would only
ever apply to the workspace it was written against. Presets therefore name things, and the names
are resolved against whichever workspace is being provisioned:

```yaml
templates:
- name: Issue
  issue:
    state: Todo             # resolved against this team's workflow states
    assignee: me            # "me", an email, or a display name
    labels: [api]           # team or workspace labels, by name
    project: Checkout v2    # optional; milestone requires it
  form_fields:
  - { type: title, label: Title }
  - { type: textarea, label: Description, default: "What is the problem?" }
  - { type: labelGroup, label: Service, group: Service }   # group named, id resolved
```

A name that does not exist fails before any mutation runs, listing what was available:

```
error: No workflow state named 'In Rewiew' in this team.
       Available: Backlog, Canceled, Done, In Progress, In Review, Pause, Testing, Todo.
```

Form field types: `title`, `textarea`, `dueDate`, `labelGroup` — the four confirmed to exist.
Field ids are derived from the team, template and field label, so a rerun is a no-op rather than
rewriting the form.

### Views

Two bundled presets, applied independently:

```bash
linear-kit view create -w my-workspace -t PAY -p views-board   # All Issues, Current cycle
linear-kit view create -w my-workspace -t PAY -p views-lists   # Backlog, Urgent
```

A view preset lists views, each with a `filter` and a `display` block:

```yaml
kind: views
name: views-board

views:
- name: All Issues
  shared: true               # personal unless set; shared views show up for everyone
  display:
    layout: board
    group_by: workflowState  # columns
    sub_group_by: project    # rows
    order_by: priority
    show_completed: week     # only what finished in the past week stays on the board
    show_empty_groups: true
    hide_states: [Done, Canceled, Duplicate]
    properties: [id, status, assignee, priority, project, labels, created]
```

`properties` is exclusive: naming a property shows it, omitting one hides it — so "everything
except links" is a list without `links`, and links ends up explicitly off rather than left at a
default. Available: `id`, `status`, `assignee`, `priority`, `project`, `milestone`, `labels`,
`due_date`, `estimate`, `cycle`, `links`, `time_in_status`, `created`, `updated`. Nothing outside
that list is touched — SLA badges, pull requests and Sentry issues keep whatever the workspace has,
since switching those off is not a view preset's call.

`hide_states` names board columns by workflow state, so it needs `group_by: workflowState`.

Filter fields AND together, mirroring how the UI stacks filter chips; a list within one field ORs
(`state_type: [unstarted, started]` means either). `any_of` nests alternatives under OR.

Available: `state` (by name), `state_type`, `assignee`, `creator`, `labels`, `priority`,
`project`, `cycle`, `team`, `due_date`, `estimate`, `any_of`. Priorities are named
(`urgent`/`high`/`medium`/`low`/`none`) rather than Linear's 0-4, and cycles are named
(`active`/`next`/`previous`) rather than given by id, so a view keeps working as cycles roll over.

Prefer state *types* over state names, and avoid labels, in a preset meant to travel: types are
fixed by Linear, whereas names and labels are whatever a workspace renamed them to. `views-lists`
breaks that rule deliberately — its `Urgent` view names Todo / Pause / In Progress, because
`unstarted + started` would also drag in In Review and Testing. The cost is that it fits teams
built from `team-extended` and fails on `team-standard`, which has no `Pause`. It fails through the
resolver, listing the states the team does have, rather than quietly returning nothing.

## Status

Implemented: teams, workflow states, labels, projects, milestones, issue templates, custom views,
team export, and issue create/update/list/show/comment/link.
Not implemented: project and document templates; exporting templates and views back to YAML;
declarative issue presets (seeding a backlog from YAML); removing a link once made.

Of Linear's four relation types, `blocks`, `related` and `duplicate` are exposed. `similar` is not:
it is in the enum, but nothing in the UI was found that produces one, so what it means is unverified
— and guessing undocumented Linear surface is how the bugs listed below got made.

Issue commands do not cover cycles: `--cycle` filters a list, but assigning an issue to a cycle is
absent, since no team with cycles enabled has been available to verify it against. Guessing that
one is how the rest of this file's warnings got written.

Custom views cover the filter fields the Linear UI itself offers. Display preferences are limited
to the vocabulary confirmed against live views — see the note on `preferences` below.

## Linear API notes

Findings verified against a live workspace, since the docs are thin here:

- Auth header is `Authorization: <key>` — no `Bearer` prefix.
- Rate limiting is reported as **HTTP 400 with code `RATELIMITED`**, not 429.
- Every create input accepts a client-supplied `id` (UUID v4) → retries are idempotent.
- `workflowStateCreate` silently **ignores `position`** and appends instead; ordering only applies
  via `workflowStateUpdate` once the state exists.
- The `Triage` and `Duplicate` states are reserved — updating them fails with
  `unable to update reserved state`.
- `issue(id:)` accepts the **human identifier** (`PAY-12`) as well as the UUID, and so does
  `issueUpdate(id:)` — no lookup query is needed to translate one into the other.
- An identifier matching nothing is a **GraphQL error**, not a null issue: `Could not find
  referenced Issue [INPUT_ERROR]`, which does not say which one. linear-kit puts the identifier
  back into the message, since a single command can name several issues (`--parent`).
- **`issueUpdate.labelIds` replaces the issue's labels, it does not merge.** An issue labelled
  `Bug`, updated with `labelIds: [Feature]`, came back labelled `Feature` alone. Every other field
  is a normal partial patch — updating `priority` alone left the labels untouched — so the danger
  is only in sending `labelIds` at all when the caller never mentioned a label. `--add-label` /
  `--remove-label` therefore read the current labels and send the folded-in result.
- Unassigning needs an **explicit `assigneeId: null`**; omitting the key means "keep the assignee".
- **A relation's direction lives in the input's two id fields, not in its type.** `IssueRelationType`
  holds `blocks`, `duplicate`, `related` and `similar`; `blocks` always reads *issueId blocks
  relatedIssueId*, so "blocked by" is that same type with the sides swapped. Which side an issue is
  on is readable only from `relations` (it is the `issue`) versus `inverseRelations` (it is the
  `relatedIssue`).
- **`issueRelationCreate` on a pair that already has that relation returns the existing one** rather
  than creating a second — the response carried the first relation's id, and a client-supplied `id`
  did not override it. So re-linking is safe; linear-kit still skips it, because a plan listing a
  mutation that changes nothing reads as though it did something.
- **`related` is symmetric and one-directional in storage.** Creating A→B `related` and then B→A
  `related` left *one* relation, its direction rewritten to B→A. So a link found on either side is
  the link, and checking only one side would flip it back and forth on every run.
- **`blocks` is not deduplicated across directions.** With A blocks B in place, B blocks A was
  accepted as a second relation — a mutual block is a state the API will let you build.
- **A `duplicate` relation moves the `issue` side to the Duplicate state.** A Backlog issue marked
  `duplicate` of another came back in state `Duplicate` with no state field ever being sent.
- `relatedIssueId` equal to `issueId` is refused: `relatedIssueId cannot have the same value as
  issueId [INVALID_INPUT]`.
- Sub-issues are not relations at all — `parentId` is a plain field on the child, so making B a
  sub-issue of A is an `issueUpdate` **on B**. A cycle is refused: `Cannot set parent because it
  would create a circular issue hierarchy [INPUT_ERROR]`.
- `customViewCreate.filterData` is a typed `IssueFilter`, not free-form JSON. Grouping, ordering
  and layout are not on the view at all — they live in `viewPreferencesCreate`.
- **`viewPreferences.preferences` is `JSONObject` and validated by nothing.** Writing
  `{"layout": "totally-bogus-layout"}` succeeds, stores, and reads back verbatim — leaving a view
  that silently renders wrong. Probing therefore cannot discover the vocabulary, since invalid and
  valid values are indistinguishable on read-back. linear-kit validates these locally instead, so
  a typo fails before the mutation. The confirmed values, read off live views:

  | key                  | confirmed values                      |
  | -------------------- | ------------------------------------- |
  | `layout`             | `list`, `board`                       |
  | `issueGrouping`      | `workflowState`, `priority`, `none`   |
  | `issueSubGrouping`   | `project`, `priority`, `none`         |
  | `viewOrdering`       | `priority`, `sortOrder`               |
  | `issueNesting`       | `showAll`, `none`                     |
  | `showCompletedIssues`| `all`, `week`                         |

  Absent from these lists means unobserved, not known-invalid. Extend them by configuring a view
  in the UI and reading it back with `inspect views`. `viewOrderingDirection` is not modelled at
  all: it read back `null` on every live view, so its vocabulary has never been seen.

  `issueGrouping` and `issueSubGrouping` are modelled as separate vocabularies even though the UI
  shows one dropdown for each: `project` has only ever been observed on the sub-grouping key and
  `workflowState` only on the grouping key. They very likely share one list, but "very likely" is
  exactly what fails silently here.
- **"Show empty groups" is one toggle over several keys.** Linear stores one per layout and a view
  reads only its own; writing the other is accepted and does nothing. A list writes
  `showEmptyGroupsList`, a board reads `showEmptyGroups` for its columns and
  `showEmptySubGroupsBoard` for its rows. So a preset setting these needs an explicit `layout`,
  and linear-kit refuses without one rather than picking a key at random.
- `hiddenColumns` holds **workflow state ids** when the board groups by state — confirmed by
  writing ids and watching those columns disappear, since the read-back proves nothing on its own.
- The UI's "Links" display chip is **`fieldPreviewLinks`**, not the similarly named
  `fieldLinkCount`. Confirmed the same way: writing `fieldPreviewLinks: false` turned the chip off,
  while switching the chip on never wrote `fieldLinkCount` (which defaults to false, so enabling it
  would have had to).
- Preferences attach at two levels, `user` and `organization`, and the effective values are the
  two merged. A preset describes how a view looks for the team, so it writes the `organization`
  layer; leaving a key unset leaves Linear's default alone rather than clearing it.
- **`viewPreferencesUpdate` replaces the preferences object, it does not merge into it.** Sending
  `{fieldPreviewLinks: false}` alone was observed to wipe layout, grouping and hiddenColumns off a
  configured view. linear-kit therefore reads the stored object and overlays the preset's keys
  onto it, so a rerun reconciles rather than amputating whatever someone set by hand.
- The UI writes a preference only when it *changes*. A key missing from a layer means "never
  touched", not "off" — so `viewPreferencesValues` (the merged read) cannot tell you what a click
  did. Read `organizationViewPreferences.preferences` for that.
- Reading `customView.viewPreferencesValues` returns the *merged* result and is typed, which is
  how the vocabulary above was recovered — the write side (`JSONObject`) reveals nothing.
- A cycle filter uses `isActive`/`isNext`/`isPrevious` booleans rather than a cycle id, so a view
  scoped to "the current cycle" survives the cycle rolling over.
- `assignee: {isMe: {eq: true}}` resolves per viewer at read time. A shared "My work" view means
  whoever is looking, not whoever created it.
- Errors put the useful text in `extensions.userPresentableMessage`; `message` is often a bare
  "Access denied" that hides the real cause (e.g. reaching the plan's team limit).
- State positions are per *type*, not global: Linear orders the board by state type first, then by
  position within that type.
- `templateCreate.templateData` is `JSON!` and undocumented. It accepts either a JSON object or a
  JSON string and always reads back as a **string**. The shape, recovered from a live template:

  ```json
  {"title":"","priority":4,"assigneeId":"…","labelIds":["…"],"stateId":"…",
   "projectId":"…","projectMilestoneId":"…","teamId":"…",
   "formFields":[{"id":"…","type":"title","required":true,"label":"Title","sortOrder":1000},
                 {"id":"…","type":"textarea","required":true,"label":"Description",
                  "descriptionData":{"type":"doc","content":[…]},"sortOrder":2000},
                 {"id":"…","type":"dueDate","required":true,"label":"Due date","sortOrder":5000},
                 {"id":"…","type":"labelGroup","required":true,"label":"…","sortOrder":6000,
                  "groupId":"…"}]}
  ```

  Field types seen: `title`, `textarea`, `dueDate`, `labelGroup`. `sortOrder` steps by 1000, and
  default body text is a ProseMirror doc in `descriptionData`.
- `User.app` marks integration bot accounts. They are users to the API but are never someone you
  would assign an issue to, so they are filtered out of assignee lookups.
