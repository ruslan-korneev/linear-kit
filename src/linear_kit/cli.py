"""linear-kit — provision Linear workspaces from declarative YAML presets."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from linear_kit import binding, config, models
from linear_kit.client import LinearClient, LinearError
from linear_kit.resources import (
    IssueFields,
    Plan,
    export_team,
    get_issue,
    list_issues,
    plan_comment,
    plan_issue_create,
    plan_issue_update,
    plan_project,
    plan_team,
    plan_views,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Provision Linear teams, projects, views and templates from YAML presets, "
    "and manage the issues inside them.",
)
auth_app = typer.Typer(no_args_is_help=True, help="Manage workspace API keys.")
team_app = typer.Typer(no_args_is_help=True, help="Create and configure teams.")
project_app = typer.Typer(no_args_is_help=True, help="Create and configure projects.")
view_app = typer.Typer(no_args_is_help=True, help="Create and configure custom views.")
issue_app = typer.Typer(no_args_is_help=True, help="Create, update and read issues.")
preset_app = typer.Typer(no_args_is_help=True, help="Inspect bundled presets.")
app.add_typer(auth_app, name="auth")
app.add_typer(team_app, name="team")
app.add_typer(project_app, name="project")
app.add_typer(view_app, name="view")
app.add_typer(issue_app, name="issue")
app.add_typer(preset_app, name="preset")

WorkspaceOpt = Annotated[
    str | None,
    typer.Option("--workspace", "-w", help="Workspace profile to act on.", show_default=False),
]
DryRunOpt = Annotated[
    bool, typer.Option("--dry-run", help="Print the mutations without sending them.")
]

VIEWER_QUERY = """
query {
  viewer { id name email admin }
  organization { id name urlKey userCount }
}
"""


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _client(workspace: str | None) -> tuple[str, LinearClient]:
    try:
        name, api_key = config.resolve(workspace)
    except config.ConfigError as exc:
        _fail(str(exc))
        raise AssertionError("unreachable")
    return name, LinearClient(api_key)


def _bound(workspace: str | None, team: str | None, *, need_team: bool = False) -> binding.Binding:
    """Settle which workspace (and team) a command acts on.

    Every command that talks to Linear goes through here, because every one of
    them has a workspace to get wrong. `--workspace` wins; otherwise the repo's
    `.linear-kit.toml` decides; failing both, this refuses rather than pick.
    """
    try:
        return binding.require(workspace, team, need_team=need_team)
    except binding.BindingError as exc:
        _fail(str(exc))
        raise AssertionError("unreachable")


def _note_binding(plan: Plan, bound: binding.Binding) -> None:
    """Say which files chose the target, so an unexpected one is visible up front.

    The whole cascade is listed, nearest last: with an inner file overriding the
    project, naming only one of them would hide where the rest came from. A flag
    that beat the files is listed too — the override is allowed, but it has to
    leave a trace, or `-w`/`-t` becomes a silent way around the binding.
    """
    for source in bound.sources:
        plan.notes.append(f"Bound by {source}")
    for override in bound.overrides:
        plan.notes.append(override)


def _execute(plan: Plan, workspace: str, client: LinearClient, *, dry_run: bool) -> None:
    typer.secho(f"\n{plan.title}", bold=True)
    typer.echo(f"workspace: {workspace}")
    for note in plan.notes:
        typer.secho(f"  note: {note}", fg=typer.colors.YELLOW)

    if not plan.steps:
        typer.echo("  nothing to do.")
        return

    typer.echo("")
    if dry_run:
        for step in plan.steps:
            typer.echo(f"  [dry-run] {step.label}")
        typer.secho("\nNothing sent. Drop --dry-run to apply.", fg=typer.colors.CYAN)
        return

    for step in plan.steps:
        typer.echo(f"  {step.label} ... ", nl=False)
        try:
            result = step.run(client)
        except LinearError as exc:
            if step.tolerant:
                typer.secho(f"skipped ({exc})", fg=typer.colors.YELLOW)
                continue
            typer.secho("failed", fg=typer.colors.RED)
            _fail(str(exc))
            return
        typer.secho(result, fg=typer.colors.GREEN)


@auth_app.command("add")
def auth_add(
    name: Annotated[str, typer.Argument(help="Profile name, e.g. my-workspace.")],
) -> None:
    """Store an API key, read from stdin so it never lands in shell history."""
    typer.echo(f"Paste the Linear API key for {name!r} (input hidden):", err=True)
    api_key = typer.prompt("key", hide_input=True).strip()
    if not api_key.startswith("lin_api_"):
        _fail("That does not look like a Linear personal API key (expected lin_api_ prefix).")

    with LinearClient(api_key) as client:
        try:
            data = client.execute(VIEWER_QUERY)
        except LinearError as exc:
            _fail(f"Key rejected by Linear: {exc}")
            return

    config.save_key(name, api_key)
    org, viewer = data["organization"], data["viewer"]
    typer.secho(
        f"saved {name!r} -> {org['name']} as {viewer['name']} (admin={viewer['admin']})",
        fg=typer.colors.GREEN,
    )


@auth_app.command("list")
def auth_list() -> None:
    """List configured workspace profiles."""
    names = config.list_workspaces()
    if not names:
        typer.echo("No workspaces configured. Run `linear-kit auth add <name>`.")
        return
    # No default marker: there is no default. Every command names its workspace
    # or takes it from the repo's .linear-kit.toml.
    for name in names:
        typer.echo(f"  {name}")


@auth_app.command("remove")
def auth_remove(name: str) -> None:
    """Forget a workspace profile."""
    try:
        config.remove_key(name)
    except config.ConfigError as exc:
        _fail(str(exc))
    typer.secho(f"removed {name!r}", fg=typer.colors.GREEN)


@auth_app.command("verify")
def auth_verify(workspace: WorkspaceOpt = None) -> None:
    """Check that a stored key still works and report its permissions."""
    name, client = _client(_bound(workspace, None).workspace)
    with client:
        try:
            data = client.execute(VIEWER_QUERY)
        except LinearError as exc:
            _fail(f"{name}: {exc}")
            return
    viewer, org = data["viewer"], data["organization"]
    typer.secho(f"{name}: ok", fg=typer.colors.GREEN)
    typer.echo(f"  org    {org['name']} ({org['urlKey']}), {org['userCount']} users")
    typer.echo(f"  user   {viewer['name']} <{viewer['email']}>  admin={viewer['admin']}")
    if not viewer["admin"]:
        typer.secho("  warning: not an admin — team creation may be rejected.", fg=typer.colors.YELLOW)


@team_app.command("create")
def team_create(
    preset: Annotated[str, typer.Option("--preset", "-p", help="Preset name or path to a YAML file.")] = "team-standard",
    name: Annotated[str | None, typer.Option("--name", help="Team name.")] = None,
    key: Annotated[str | None, typer.Option("--key", help="Team key, e.g. PAY.")] = None,
    workspace: WorkspaceOpt = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Create a team, then reconcile its workflow states and labels to the preset."""
    try:
        spec = models.load_team_preset(preset)
    except Exception as exc:
        _fail(f"preset {preset!r}: {exc}")
        return

    bound = _bound(workspace, None)
    ws_name, client = _client(bound.workspace)
    with client:
        try:
            plan = plan_team(client, spec, name=name, key=key)
        except LinearError as exc:
            _fail(str(exc))
            return
        _note_binding(plan, bound)
        _execute(plan, ws_name, client, dry_run=dry_run)


@team_app.command("export")
def team_export(
    team: Annotated[str, typer.Option("--team", "-t", help="Team key or name to export.")],
    preset_name: Annotated[str | None, typer.Option("--as", help="name: field of the preset.")] = None,
    include_labels: Annotated[
        bool, typer.Option("--include-labels", help="Also export the team's labels and groups.")
    ] = False,
    out: Annotated[str | None, typer.Option("--out", "-o", help="Write here instead of stdout.")] = None,
    workspace: WorkspaceOpt = None,
) -> None:
    """Render a live team back as a preset YAML.

    Team name and key are dropped — a preset says how a team is configured, not
    which team it is. Labels are excluded unless --include-labels, since they
    tend to name products and services specific to that one workspace.
    """
    _name, client = _client(_bound(workspace, None).workspace)
    with client:
        try:
            yaml_text = export_team(
                client, team,
                preset_name=preset_name or f"{team.lower()}-exported",
                include_labels=include_labels,
            )
        except LinearError as exc:
            _fail(str(exc))
            return

    if out:
        Path(out).write_text(yaml_text)
        typer.secho(f"wrote {out}", fg=typer.colors.GREEN)
    else:
        typer.echo(yaml_text)


@project_app.command("create")
def project_create(
    team: Annotated[list[str], typer.Option("--team", "-t", help="Team key or name. Repeatable.")],
    preset: Annotated[str, typer.Option("--preset", "-p", help="Preset name or path to a YAML file.")] = "project-standard",
    name: Annotated[str | None, typer.Option("--name", help="Project name.")] = None,
    description: Annotated[str | None, typer.Option("--description", help="Short summary.")] = None,
    target_date: Annotated[str | None, typer.Option("--target-date", help="YYYY-MM-DD.")] = None,
    workspace: WorkspaceOpt = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Create a project and its milestones."""
    try:
        spec = models.load_project_preset(preset)
    except Exception as exc:
        _fail(f"preset {preset!r}: {exc}")
        return

    bound = _bound(workspace, None)
    ws_name, client = _client(bound.workspace)
    with client:
        try:
            plan = plan_project(
                client, spec, teams=team, name=name,
                description=description, target_date=target_date,
            )
        except LinearError as exc:
            _fail(str(exc))
            return
        _note_binding(plan, bound)
        _execute(plan, ws_name, client, dry_run=dry_run)


@view_app.command("create")
def view_create(
    team: Annotated[str, typer.Option("--team", "-t", help="Team key or name to scope the views to.")],
    # No default: views-board and views-lists are peers, not a main one and a
    # variant, so picking either as the default would just be a coin toss.
    preset: Annotated[str, typer.Option("--preset", "-p", help="Preset name or path to a YAML file.")],
    workspace: WorkspaceOpt = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Create the preset's custom views and their display preferences."""
    try:
        spec = models.load_views_preset(preset)
    except Exception as exc:
        _fail(f"preset {preset!r}: {exc}")
        return

    bound = _bound(workspace, None)
    ws_name, client = _client(bound.workspace)
    with client:
        try:
            plan = plan_views(client, spec, team=team)
        except LinearError as exc:
            _fail(str(exc))
            return
        _note_binding(plan, bound)
        _execute(plan, ws_name, client, dry_run=dry_run)


BoundTeamOpt = Annotated[
    str | None,
    typer.Option("--team", "-t", help=f"Team key or name. Defaults to {binding.BINDING_FILE}."),
]
TitleOpt = Annotated[str | None, typer.Option("--title", help="Issue title.")]
DescOpt = Annotated[
    str | None, typer.Option("--description", "-d", help="Issue body, in markdown.")
]
StateOpt = Annotated[str | None, typer.Option("--state", "-s", help="Workflow state name.")]
PriorityOpt = Annotated[
    str | None, typer.Option("--priority", help="none, urgent, high, medium or low.")
]
AssigneeOpt = Annotated[
    str | None, typer.Option("--assignee", "-a", help="`me`, an email, a name, or `none`.")
]
LabelOpt = Annotated[
    list[str] | None,
    typer.Option("--label", "-l", help="Label name. Repeatable. States the complete list."),
]
AddLabelOpt = Annotated[
    list[str] | None, typer.Option("--add-label", help="Add a label, keeping the rest. Repeatable.")
]
RemoveLabelOpt = Annotated[
    list[str] | None, typer.Option("--remove-label", help="Remove a label. Repeatable.")
]
ProjectOpt = Annotated[
    str | None, typer.Option("--project", help="Project name, or `none` to detach.")
]
MilestoneOpt = Annotated[
    str | None, typer.Option("--milestone", help="Milestone name. Requires --project.")
]
ParentOpt = Annotated[
    str | None, typer.Option("--parent", help="Parent issue identifier, e.g. PAY-12.")
]
DueOpt = Annotated[str | None, typer.Option("--due-date", help="YYYY-MM-DD.")]
EstimateOpt = Annotated[int | None, typer.Option("--estimate", help="Estimate points.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit raw JSON instead of a table.")]


@issue_app.command("create")
def issue_create(
    title: TitleOpt = None,
    team: BoundTeamOpt = None,
    description: DescOpt = None,
    state: StateOpt = None,
    priority: PriorityOpt = None,
    assignee: AssigneeOpt = None,
    label: LabelOpt = None,
    project: ProjectOpt = None,
    milestone: MilestoneOpt = None,
    parent: ParentOpt = None,
    due_date: DueOpt = None,
    estimate: EstimateOpt = None,
    workspace: WorkspaceOpt = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Create an issue.

    The workspace and team come from `.linear-kit.toml` in the repo unless named
    explicitly — there is no fallback to the default workspace, since filing a
    task against the wrong one succeeds silently. If the binding names a project,
    the issue joins it; pass `--project none` to keep it out.
    """
    bound = _bound(workspace, team, need_team=True)
    if project is None and bound.project:
        project = bound.project

    fields = IssueFields(
        title=title, description=description, state=state, priority=priority,
        assignee=assignee, labels=list(label) if label else None, project=project,
        milestone=milestone, parent=parent, due_date=due_date, estimate=estimate,
    )
    ws_name, client = _client(bound.workspace)
    with client:
        try:
            plan = plan_issue_create(client, team=bound.team, fields=fields)
        except LinearError as exc:
            _fail(str(exc))
            return
        _note_binding(plan, bound)
        _execute(plan, ws_name, client, dry_run=dry_run)


@issue_app.command("update")
def issue_update(
    identifier: Annotated[str, typer.Argument(help="Issue identifier, e.g. PAY-12.")],
    title: TitleOpt = None,
    description: DescOpt = None,
    state: StateOpt = None,
    priority: PriorityOpt = None,
    assignee: AssigneeOpt = None,
    label: LabelOpt = None,
    add_label: AddLabelOpt = None,
    remove_label: RemoveLabelOpt = None,
    project: ProjectOpt = None,
    milestone: MilestoneOpt = None,
    parent: ParentOpt = None,
    due_date: DueOpt = None,
    estimate: EstimateOpt = None,
    workspace: WorkspaceOpt = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Change fields on an existing issue.

    Only what you name is touched — every other field keeps its value. The
    exception is `--label`, which replaces the issue's labels outright because
    Linear's `labelIds` replaces rather than merges; use `--add-label` /
    `--remove-label` to work from what the issue already has.
    """
    fields = IssueFields(
        title=title, description=description, state=state, priority=priority,
        assignee=assignee, labels=list(label) if label else None,
        add_labels=list(add_label) if add_label else None,
        remove_labels=list(remove_label) if remove_label else None,
        project=project, milestone=milestone, parent=parent,
        due_date=due_date, estimate=estimate,
    )
    bound = _bound(workspace, None, need_team=False)
    ws_name, client = _client(bound.workspace)
    with client:
        try:
            plan = plan_issue_update(client, identifier, fields=fields)
        except LinearError as exc:
            _fail(str(exc))
            return
        _note_binding(plan, bound)
        _execute(plan, ws_name, client, dry_run=dry_run)


@issue_app.command("comment")
def issue_comment(
    identifier: Annotated[str, typer.Argument(help="Issue identifier, e.g. PAY-12.")],
    message: Annotated[str, typer.Option("--message", "-m", help="Comment body, in markdown.")],
    workspace: WorkspaceOpt = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Post a comment on an issue."""
    bound = _bound(workspace, None, need_team=False)
    ws_name, client = _client(bound.workspace)
    with client:
        try:
            plan = plan_comment(client, identifier, body=message)
        except LinearError as exc:
            _fail(str(exc))
            return
        _note_binding(plan, bound)
        _execute(plan, ws_name, client, dry_run=dry_run)


@issue_app.command("list")
def issue_list(
    team: BoundTeamOpt = None,
    all_teams: Annotated[
        bool, typer.Option("--all-teams", help="Ignore the bound team and search the workspace.")
    ] = False,
    state: Annotated[
        list[str] | None, typer.Option("--state", "-s", help="State name. Repeatable, OR'd.")
    ] = None,
    state_type: Annotated[
        list[str] | None,
        typer.Option("--state-type", help="backlog, unstarted, started, completed, canceled, triage."),
    ] = None,
    assignee: AssigneeOpt = None,
    label: LabelOpt = None,
    priority: Annotated[
        list[str] | None, typer.Option("--priority", help="Priority name. Repeatable, OR'd.")
    ] = None,
    project: ProjectOpt = None,
    all_projects: Annotated[
        bool,
        typer.Option("--all-projects", help="Ignore the bound project and search the whole team."),
    ] = False,
    cycle: Annotated[
        str | None, typer.Option("--cycle", help="active, next, previous or none.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many to return.")] = 50,
    as_json: JsonOpt = False,
    workspace: WorkspaceOpt = None,
) -> None:
    """List issues matching a filter.

    Scoped to the team in `.linear-kit.toml` unless `--team` names another or
    `--all-teams` drops the scope; a bound project scopes the same way, dropped
    by `--all-projects`. Filters stack with AND, and repeating one OR's its
    values — the same semantics a views preset gets, since both render through
    the same code.
    """
    if team and all_teams:
        # Silently dropping the -t would answer a different question than asked.
        _fail("--team and --all-teams contradict each other: name a team or drop the scope, not both.")
        return
    bound = _bound(workspace, team)
    # The bound project scopes reads for the same reason it scopes creates: the
    # binding says which slice of the workspace this repo is about, and a list
    # that answers for the whole team is answering a different question.
    if project is None and not all_projects and bound.project:
        project = bound.project
    try:
        spec = models.ViewFilter.model_validate(
            {
                "team": None if all_teams else (bound.team or None),
                "state": list(state) if state else [],
                # Closed vocabularies are casefolded here so `--priority Urgent`
                # works like `--priority urgent` does on create; state names are
                # left alone — the resolver matches those case-insensitively.
                "state_type": [s.casefold() for s in state_type] if state_type else [],
                "assignee": assignee,
                "labels": list(label) if label else [],
                "priority": [p.casefold() for p in priority] if priority else [],
                "project": project,
                "cycle": cycle.casefold() if cycle else None,
            }
        )
    except Exception as exc:
        _fail(str(exc))
        return

    _name, client = _client(bound.workspace)
    with client:
        try:
            issues = list_issues(client, spec=spec, limit=limit)
        except LinearError as exc:
            _fail(str(exc))
            return

    if as_json:
        json.dump(issues, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    if not issues:
        typer.echo("No issues match.")
        return
    for issue in issues:
        typer.echo(_issue_row(issue))


@issue_app.command("show")
def issue_show(
    identifier: Annotated[str, typer.Argument(help="Issue identifier, e.g. PAY-12.")],
    as_json: JsonOpt = False,
    workspace: WorkspaceOpt = None,
) -> None:
    """Print an issue in full, with its description, sub-issues and comments."""
    bound = _bound(workspace, None)
    _name, client = _client(bound.workspace)
    with client:
        try:
            issue = get_issue(client, identifier)
        except LinearError as exc:
            _fail(str(exc))
            return

    if as_json:
        json.dump(issue, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    typer.secho(f"\n{issue['identifier']}  {issue['title']}", bold=True)
    typer.echo(f"  {issue['url']}")
    typer.echo(f"  state      {issue['state']['name']} ({issue['state']['type']})")
    typer.echo(f"  priority   {_priority_name(issue['priority'])}")
    typer.echo(f"  assignee   {_assignee_name(issue)}")
    if issue.get("labels", {}).get("nodes"):
        typer.echo(f"  labels     {', '.join(n['name'] for n in issue['labels']['nodes'])}")
    if issue.get("project"):
        milestone = issue.get("projectMilestone")
        suffix = f" / {milestone['name']}" if milestone else ""
        typer.echo(f"  project    {issue['project']['name']}{suffix}")
    if issue.get("parent"):
        typer.echo(f"  parent     {issue['parent']['identifier']}")
    if issue.get("dueDate"):
        typer.echo(f"  due        {issue['dueDate']}")
    if issue.get("estimate") is not None:
        typer.echo(f"  estimate   {issue['estimate']}")

    if issue.get("description"):
        typer.secho("\ndescription", bold=True)
        for line in issue["description"].splitlines():
            typer.echo(f"  {line}")

    children = issue.get("children", {}).get("nodes") or []
    if children:
        typer.secho("\nsub-issues", bold=True)
        for child in children:
            typer.echo(f"  {child['identifier']:<10} {child['state']['name']:<14} {child['title']}")

    comments = issue.get("comments", {}).get("nodes") or []
    if comments:
        typer.secho("\ncomments", bold=True)
        for comment in comments:
            who = (comment.get("user") or {}).get("displayName", "unknown")
            typer.echo(f"  {who} at {comment['createdAt']}")
            for line in comment["body"].splitlines():
                typer.echo(f"    {line}")


def _priority_name(value: int | None) -> str:
    return models.PRIORITY_NAMES.get(value or 0, str(value))


def _assignee_name(issue: dict[str, Any]) -> str:
    assignee = issue.get("assignee")
    return assignee["displayName"] if assignee else "unassigned"


def _issue_row(issue: dict[str, Any]) -> str:
    return (
        f"  {issue['identifier']:<10} {issue['state']['name']:<14} "
        f"{_priority_name(issue['priority']):<8} {_assignee_name(issue):<16} {issue['title']}"
    )


@preset_app.command("list")
def preset_list() -> None:
    """List bundled presets."""
    for name, kind, description in models.list_presets():
        typer.echo(f"  {name:<20} {kind:<8} {description}")


@preset_app.command("show")
def preset_show(name: str) -> None:
    """Print a preset's raw YAML."""
    try:
        typer.echo(models.preset_path(name).read_text())
    except FileNotFoundError as exc:
        _fail(str(exc))


INSPECT_QUERIES: dict[str, str] = {
    "teams": "query { teams { nodes { id key name private cyclesEnabled issueEstimationType triageEnabled } } }",
    "projects": "query { projects { nodes { id name state health startDate targetDate url } } }",
    "labels": "query { issueLabels { nodes { id name color isGroup parent { name } team { key } } } }",
    "states": "query { workflowStates { nodes { id name type color position team { key } } } }",
    "templates": "query { templates { id name type templateData } }",
    "views": "query { customViews { nodes { id name modelName shared icon color filterData } } }",
    "members": "query { users { nodes { id name email admin active } } }",
}


@app.command("binding")
def show_binding(
    workspace: WorkspaceOpt = None,
    team: BoundTeamOpt = None,
) -> None:
    """Print the workspace, team and project a command run here would target.

    Reading `.linear-kit.toml` yourself answers nothing: the files cascade, so
    one file is a fragment, and the nearest one is often the least informative.
    This resolves the whole chain the way every other command does, touches no
    network, and changes nothing — ask it rather than guess.
    """
    bound = _bound(workspace, team)
    typer.echo(f"  workspace  {bound.workspace}")
    typer.echo(f"  team       {bound.team or '(none — pass --team, or set one in a binding)'}")
    typer.echo(f"  project    {bound.project or '(none)'}")
    for source in bound.sources:
        typer.echo(f"    from {source}")
    if not bound.sources:
        typer.secho("    from flags only — no .linear-kit.toml applies here", fg=typer.colors.YELLOW)
    for override in bound.overrides:
        typer.secho(f"    {override}", fg=typer.colors.YELLOW)


@app.command("inspect")
def inspect(
    resource: Annotated[str, typer.Argument(help=f"One of: {', '.join(INSPECT_QUERIES)}.")],
    workspace: WorkspaceOpt = None,
) -> None:
    """Dump a resource as raw JSON.

    `inspect templates` and `inspect views` are how you recover the undocumented
    templateData / filterData shapes: build one by hand in the Linear UI, read it
    back here, then mirror it in a preset.
    """
    query = INSPECT_QUERIES.get(resource)
    if not query:
        _fail(f"Unknown resource {resource!r}. Try: {', '.join(INSPECT_QUERIES)}.")
        return

    _name, client = _client(_bound(workspace, None).workspace)
    with client:
        try:
            data: dict[str, Any] = client.execute(query)
        except LinearError as exc:
            _fail(str(exc))
            return
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    app()
