"""Create, update, read and comment on issues.

Unlike teams, projects and views, an issue is not provisioned from a preset —
it is day-to-day work, named on the command line. What carries over is the
planning discipline: every name is resolved and every payload built before a
mutation is sent, so `--dry-run` prints the same object that a real run
executes and a bad state name fails before anything is written.

`issueUpdate` is a partial patch — a field left out of the input keeps its
current value. The exception is `labelIds`, which **replaces** the issue's
label set rather than adding to it (confirmed live: an issue labelled `Bug`
updated with `labelIds: [Feature]` came back labelled `Feature` alone). So
`--label` is a complete statement of the labels, and `--add-label` /
`--remove-label` exist for the additive case, computed against the labels the
issue currently carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from linear_kit.client import LinearClient, LinearError, new_id
from linear_kit.models import PRIORITY_VALUES, ViewFilter
from linear_kit.resources.plan import Plan
from linear_kit.resources.resolve import Resolver
from linear_kit.resources.team import find_team
from linear_kit.resources.view import build_filter_data

#: Fields worth reading back off a mutated or listed issue.
ISSUE_FIELDS = """
  id identifier title priority estimate dueDate url
  state { name type }
  assignee { displayName email }
  labels { nodes { name } }
  project { name }
  projectMilestone { name }
  parent { identifier }
  team { id key name }
  createdAt updatedAt
"""

ISSUE_QUERY = "query ($id: String!) { issue(id: $id) { %s } }" % ISSUE_FIELDS

#: `issue(id:)` accepts the human identifier (PAY-11) as well as the UUID —
#: confirmed live, so a lookup query to translate one into the other is wasted.
ISSUE_DETAIL = """
query ($id: String!) {
  issue(id: $id) {
    %s
    description
    comments { nodes { id body createdAt user { displayName } } }
    children { nodes { identifier title state { name } } }
  }
}
""" % ISSUE_FIELDS

ISSUES_QUERY = """
query ($filter: IssueFilter, $first: Int!) {
  issues(filter: $filter, first: $first, orderBy: updatedAt) {
    nodes { %s }
  }
}
""" % ISSUE_FIELDS

ISSUE_CREATE = """
mutation ($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { identifier title url } }
}
"""

ISSUE_UPDATE = """
mutation ($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success issue { identifier title url } }
}
"""

COMMENT_CREATE = """
mutation ($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id url } }
}
"""


@dataclass
class IssueFields:
    """The mutable fields of an issue, as named on the command line.

    None means "not mentioned": on create that leaves Linear's default, on update
    it keeps the current value. That is why every field defaults to None rather
    than to an empty string or list — `--label` with no labels and no `--label`
    at all are different requests, and only one of them touches the issue.
    """

    title: str | None = None
    description: str | None = None
    state: str | None = None
    priority: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None
    add_labels: list[str] | None = None
    remove_labels: list[str] | None = None
    project: str | None = None
    milestone: str | None = None
    parent: str | None = None
    due_date: str | None = None
    estimate: int | None = None


def _fetch(client: LinearClient, query: str, identifier: str) -> dict[str, Any]:
    """Read one issue by identifier (PAY-12) or UUID.

    An identifier that matches nothing is a GraphQL error rather than a null
    issue, and Linear phrases it as "Could not find referenced Issue" without
    saying which one. Since a command can name several issues (`--parent`), the
    identifier has to go back into the message or the error cannot be acted on.
    """
    try:
        issue = client.execute(query, {"id": identifier}).get("issue")
    except LinearError as exc:
        # Only a lookup miss gets rephrased — an auth or transport failure is
        # not "no such issue", and headlining it as one sends the user checking
        # the identifier instead of the actual problem.
        if "could not find" in str(exc).casefold() or "not found" in str(exc).casefold():
            raise LinearError(f"No issue {identifier!r} in this workspace ({exc}).") from None
        raise
    if not issue:
        raise LinearError(f"No issue {identifier!r} in this workspace.")
    return dict(issue)


def _priority_value(name: str) -> int:
    try:
        return PRIORITY_VALUES[name.casefold()]
    except KeyError:
        known = ", ".join(PRIORITY_VALUES)
        raise LinearError(f"No priority named {name!r}. Available: {known}.") from None


def _resolve_parent(client: LinearClient, ref: str) -> str:
    return str(_fetch(client, ISSUE_QUERY, ref)["id"])


def _build_input(
    client: LinearClient,
    resolver: Resolver,
    fields: IssueFields,
    *,
    current_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Render the named fields as an Issue{Create,Update}Input.

    Called during planning, so a name that does not resolve raises here — before
    any mutation is sent — with the available names listed.
    """
    payload: dict[str, Any] = {}
    if fields.title is not None:
        payload["title"] = fields.title
    if fields.description is not None:
        payload["description"] = fields.description
    if fields.state is not None:
        payload["stateId"] = resolver.state_id(fields.state)
    if fields.priority is not None:
        payload["priority"] = _priority_value(fields.priority)
    if fields.assignee is not None:
        # "none" unassigns. Linear takes a null assigneeId for that, so it has to
        # be sent explicitly rather than left out — leaving it out means "keep".
        # Casefolded, like every other name here — `--assignee None` must not go
        # looking for a user named "None".
        payload["assigneeId"] = (
            None if fields.assignee.casefold() == "none" else resolver.user_id(fields.assignee)
        )
    if fields.due_date is not None:
        payload["dueDate"] = fields.due_date
    if fields.estimate is not None:
        payload["estimate"] = fields.estimate
    if fields.parent is not None:
        payload["parentId"] = _resolve_parent(client, fields.parent)

    if fields.project is not None:
        if fields.project.casefold() == "none":
            payload["projectId"] = None
        else:
            payload["projectId"] = resolver.project_id(fields.project)
    if fields.milestone is not None:
        # A milestone belongs to a project, so naming one without a project would
        # give the resolver nothing to look it up in.
        if not fields.project or fields.project.casefold() == "none":
            raise LinearError("`--milestone` needs `--project`: a milestone is scoped to a project.")
        payload["projectMilestoneId"] = resolver.milestone_id(fields.project, fields.milestone)

    label_ids = _label_ids(resolver, fields, current_labels)
    if label_ids is not None:
        payload["labelIds"] = label_ids

    return payload


def _label_ids(
    resolver: Resolver, fields: IssueFields, current_labels: list[str] | None
) -> list[str] | None:
    """Work out the complete label set, since `labelIds` replaces rather than adds.

    `--label` states the set outright. `--add-label` / `--remove-label` are
    folded into the labels the issue already has, which is why the caller passes
    them in: without that read, an add would silently drop every other label.
    """
    if fields.labels is None and not fields.add_labels and not fields.remove_labels:
        return None
    if fields.labels is not None and (fields.add_labels or fields.remove_labels):
        raise LinearError(
            "`--label` sets the complete label list, so it cannot be combined with "
            "`--add-label` / `--remove-label`."
        )

    if fields.labels is not None:
        return resolver.label_ids(fields.labels)

    for name in fields.remove_labels or []:
        # Resolved for the check alone — the id goes unused. A typo has to fail
        # here rather than remove nothing and report success.
        resolver.label_id(name)

    removed = {name.casefold() for name in fields.remove_labels or []}
    wanted = [name for name in current_labels or [] if name.casefold() not in removed]
    for name in fields.add_labels or []:
        if name.casefold() not in {w.casefold() for w in wanted}:
            wanted.append(name)
    return resolver.label_ids(wanted)


def plan_issue_create(client: LinearClient, *, team: str, fields: IssueFields) -> Plan:
    if not fields.title:
        raise LinearError("An issue needs a title: pass --title.")

    found = find_team(client, team)
    if not found:
        raise LinearError(f"No team matches {team!r} in this workspace.")
    team_id = found["id"]

    resolver = Resolver(client, team_id)
    payload = _build_input(client, resolver, fields) | {"id": new_id(), "teamId": team_id}

    plan = Plan(title=f"issue {fields.title!r}")
    plan.notes.append(f"Team: {found['key']} ({found['name']})")
    plan.add(
        f"issueCreate  {fields.title}{_describe(payload, fields)}",
        lambda c, _p=payload: _run_create(c, _p),
    )
    plan.context["issue_id"] = payload["id"]
    return plan


def plan_issue_update(client: LinearClient, identifier: str, *, fields: IssueFields) -> Plan:
    issue = _fetch(client, ISSUE_QUERY, identifier)
    resolver = Resolver(client, issue["team"]["id"])
    current_labels = [node["name"] for node in issue["labels"]["nodes"]]
    payload = _build_input(client, resolver, fields, current_labels=current_labels)
    if not payload:
        raise LinearError(f"Nothing to change on {identifier}: pass at least one field to update.")

    plan = Plan(title=f"issue {identifier}: {issue['title']}")
    plan.notes.append(f"Team: {issue['team']['key']} ({issue['team']['name']})")
    plan.add(
        f"issueUpdate  {identifier}{_describe(payload, fields)}",
        lambda c, _id=issue["id"], _p=payload: _run_update(c, _id, _p),
    )
    return plan


def plan_comment(client: LinearClient, identifier: str, *, body: str) -> Plan:
    # Checked before the fetch: an empty body needs no network call to reject.
    if not body.strip():
        raise LinearError("A comment needs a body: pass --message.")
    issue = _fetch(client, ISSUE_QUERY, identifier)

    plan = Plan(title=f"comment on {identifier}: {issue['title']}")
    payload = {"id": new_id(), "issueId": issue["id"], "body": body}
    first_line = body.strip().splitlines()[0]
    plan.add(
        f"commentCreate  {_truncate(first_line, 60)}",
        lambda c, _p=payload: _run_comment(c, _p),
    )
    return plan


def get_issue(client: LinearClient, identifier: str) -> dict[str, Any]:
    return _fetch(client, ISSUE_DETAIL, identifier)


def list_issues(client: LinearClient, *, spec: ViewFilter, limit: int = 50) -> list[dict[str, Any]]:
    """List issues matching a filter.

    The filter is the same `ViewFilter` a views preset uses, rendered by the same
    `build_filter_data` — so `issue list` and a custom view scoping the same way
    cannot disagree about what the filter means.
    """
    # State and label names are per-team, so resolving them needs a team. Without
    # one the filter can still run — it just cannot name a state or a label, and
    # the resolver says so rather than guessing which team was meant.
    team_id = ""
    if spec.team:
        found = find_team(client, spec.team)
        if not found:
            raise LinearError(f"No team matches {spec.team!r} in this workspace.")
        team_id = found["id"]
    elif spec.state or spec.labels:
        raise LinearError(
            "`--state` and `--label` name per-team entities, so they need `--team`. "
            "Filter the whole workspace with `--state-type` instead."
        )
    resolver = Resolver(client, team_id)
    filter_data = build_filter_data(resolver, spec)

    data = client.execute(ISSUES_QUERY, {"filter": filter_data or None, "first": limit})
    return list(data["issues"]["nodes"])


def _describe(payload: dict[str, Any], fields: IssueFields) -> str:
    """Name the fields being written, so --dry-run says more than the mutation name.

    Ids are useless to read, so this names what the user typed rather than what
    was resolved.
    """
    parts: list[str] = []
    for key, value in (
        ("state", fields.state),
        ("priority", fields.priority),
        ("assignee", fields.assignee),
        ("project", fields.project),
        ("milestone", fields.milestone),
        ("parent", fields.parent),
        ("due", fields.due_date),
    ):
        if value is not None:
            parts.append(f"{key}={value}")
    if fields.estimate is not None:
        parts.append(f"estimate={fields.estimate}")
    if "labelIds" in payload:
        parts.append(f"labels={len(payload['labelIds'])}")
    if fields.description is not None:
        parts.append("description")
    return f"  ({', '.join(parts)})" if parts else ""


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _run_create(client: LinearClient, payload: dict[str, Any]) -> str:
    issue = client.mutate(ISSUE_CREATE, {"input": payload}, "issueCreate")["issue"]
    return f"created {issue['identifier']} — {issue['url']}"


def _run_update(client: LinearClient, issue_id: str, payload: dict[str, Any]) -> str:
    issue = client.mutate(
        ISSUE_UPDATE, {"id": issue_id, "input": payload}, "issueUpdate"
    )["issue"]
    return f"updated {issue['identifier']} — {issue['url']}"


def _run_comment(client: LinearClient, payload: dict[str, Any]) -> str:
    comment = client.mutate(COMMENT_CREATE, {"input": payload}, "commentCreate")["comment"]
    return f"posted — {comment['url']}"
