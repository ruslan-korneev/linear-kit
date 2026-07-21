"""Provision custom views and their display preferences.

A view is two objects, not one. `customViewCreate` holds the name, scope and
filter; grouping, ordering and layout live in a separate `viewPreferences`
object keyed back by `customViewId`. Creating a view without preferences is
legal and yields Linear's defaults.

The two halves have opposite failure modes:

  * `filterData` is a typed `IssueFilter`, so a malformed filter is rejected by
    the API and the shape can be read straight off the schema.
  * `preferences` is `JSONObject` and validated by nothing — a bogus value is
    accepted, stored, and read back verbatim. So preferences are validated
    locally, against a vocabulary observed on real views (see models.py).
"""

from __future__ import annotations

from typing import Any

from linear_kit.client import LinearClient, LinearError, new_id
from linear_kit.models import (
    PRIORITY_VALUES,
    PROPERTY_FIELDS,
    DateFilter,
    EstimateFilter,
    ViewDisplay,
    ViewFilter,
    ViewSpec,
    ViewsPreset,
)
from linear_kit.resources.plan import Plan
from linear_kit.resources.resolve import Resolver
from linear_kit.resources.team import find_team

VIEWS_QUERY = """
query {
  customViews {
    nodes {
      id name modelName shared filterData
      team { id }
      organizationViewPreferences { id }
    }
  }
}
"""

VIEW_CREATE = """
mutation ($input: CustomViewCreateInput!) {
  customViewCreate(input: $input) { success customView { id name } }
}
"""

VIEW_UPDATE = """
mutation ($id: String!, $input: CustomViewUpdateInput!) {
  customViewUpdate(id: $id, input: $input) { success customView { id name } }
}
"""

PREFS_CREATE = """
mutation ($input: ViewPreferencesCreateInput!) {
  viewPreferencesCreate(input: $input) { success viewPreferences { id } }
}
"""

PREFS_UPDATE = """
mutation ($id: String!, $input: ViewPreferencesUpdateInput!) {
  viewPreferencesUpdate(id: $id, input: $input) { success viewPreferences { id } }
}
"""

#: `viewPreferencesUpdate` **replaces** the preferences object rather than merging
#: into it: writing `{fieldPreviewLinks: false}` alone was observed to wipe layout,
#: grouping and hiddenColumns off a configured view. So an update has to read the
#: stored object and overlay onto it, or every rerun would silently destroy any
#: setting someone made by hand that the preset does not itself name.
PREFS_READ = """
query ($id: String!) {
  customView(id: $id) {
    organizationViewPreferences {
      id
      preferences {
        layout viewOrdering viewOrderingDirection issueGrouping issueSubGrouping issueNesting
        showCompletedIssues showParents showSubIssues showSubTeamIssues showSupervisedIssues
        showTriageIssues showSnoozedItems showOnlySnoozedItems showArchivedItems
        closedIssuesOrderedByRecency
        showEmptyGroups showEmptyGroupsBoard showEmptyGroupsList
        showEmptySubGroups showEmptySubGroupsBoard showEmptySubGroupsList
        issueGroupingLabelGroupId issueSubGroupingLabelGroupId
        hiddenColumns hiddenRows hiddenGroupsList columnOrderBoard columnOrderList
        fieldId fieldStatus fieldPriority fieldAssignee fieldEstimate fieldLabels
        fieldProject fieldCycle fieldMilestone fieldDueDate fieldRelease
        fieldLinkCount fieldCustomerCount fieldCustomerRevenue fieldSla
        fieldTimeInCurrentStatus fieldDateCreated fieldDateUpdated fieldDateArchived
        fieldDateMyActivity fieldPullRequests fieldPreviewLinks fieldSentryIssues
      }
    }
  }
}
"""

#: Preferences attach at two levels: `user` (only the caller sees them) and
#: `organization` (the view's defaults for everyone). A preset describes how a
#: view should look for the team, which is the organization layer.
PREFS_TYPE = "organization"
PREFS_VIEW_TYPE = "customView"

#: YAML key -> the ViewPreferencesValues key it maps to, for the keys that mean
#: the same thing on every layout.
_DISPLAY_KEYS: dict[str, str] = {
    "layout": "layout",
    "group_by": "issueGrouping",
    "sub_group_by": "issueSubGrouping",
    "order_by": "viewOrdering",
    "order_completed_by_recency": "closedIssuesOrderedByRecency",
    "show_completed": "showCompletedIssues",
    "show_sub_issues": "showSubIssues",
    "nesting": "issueNesting",
    "show_triage": "showTriageIssues",
}

#: "Show empty groups" is not one key: Linear stores a separate one per layout,
#: and a view only reads the one matching its own layout. Writing the wrong one
#: is accepted and does nothing — the failure this whole module guards against.
#: Confirmed on live views: a list's toggle wrote `showEmptyGroupsList`, and a
#: board reads `showEmptyGroups` (its empty columns appeared with only that key
#: written, never `showEmptyGroupsBoard`). The board's rows toggle wrote
#: `showEmptySubGroupsBoard`.
_EMPTY_GROUP_KEYS: dict[str, str] = {"list": "showEmptyGroupsList", "board": "showEmptyGroups"}
_EMPTY_SUB_GROUP_KEYS: dict[str, str] = {
    "list": "showEmptySubGroupsList",
    "board": "showEmptySubGroupsBoard",
}


def build_filter_data(resolver: Resolver, spec: ViewFilter) -> dict[str, Any]:
    """Render a preset filter as an IssueFilter.

    Every clause is AND'd, mirroring how the UI stacks filter chips. Values
    inside one clause are OR'd via `in`, so `state: [Todo, In Progress]` means
    either state rather than both at once (which nothing could satisfy).
    """
    clauses: list[dict[str, Any]] = []

    if spec.state:
        clauses.append({"state": {"id": {"in": [resolver.state_id(n) for n in spec.state]}}})
    if spec.state_type:
        clauses.append({"state": {"type": {"in": list(spec.state_type)}}})
    if spec.assignee:
        clauses.append({"assignee": _user_clause(resolver, spec.assignee, nullable=True)})
    if spec.creator:
        clauses.append({"creator": _user_clause(resolver, spec.creator, nullable=False)})
    if spec.labels:
        # `some` = the issue carries at least one of these labels. `every` would
        # demand all of them on every issue, which is not what a chip list means.
        clauses.append({"labels": {"some": {"id": {"in": resolver.label_ids(spec.labels)}}}})
    if spec.priority:
        clauses.append({"priority": {"in": [PRIORITY_VALUES[p] for p in spec.priority]}})
    if spec.project:
        if spec.project.casefold() == "none":
            clauses.append({"project": {"null": True}})
        else:
            clauses.append({"project": {"id": {"eq": resolver.project_id(spec.project)}}})
    if spec.cycle:
        clauses.append({"cycle": _cycle_clause(spec.cycle)})
    if spec.team:
        clauses.append({"team": {"id": {"eq": resolver.team_id(spec.team)}}})
    if spec.due_date:
        clauses.append({"dueDate": _date_clause(spec.due_date)})
    if spec.estimate:
        clauses.append({"estimate": _estimate_clause(spec.estimate)})
    if spec.any_of:
        clauses.append({"or": [build_filter_data(resolver, alt) for alt in spec.any_of]})

    return {"and": clauses} if clauses else {}


def _user_clause(resolver: Resolver, ref: str, *, nullable: bool) -> dict[str, Any]:
    # Sentinels match casefolded, like names do — "None" must not become a
    # lookup for a user called None.
    if ref.casefold() == "none":
        if not nullable:
            raise LinearError("`creator: none` is meaningless — every issue has a creator.")
        return {"null": True}
    if ref.casefold() == "me":
        # isMe resolves at read time, so a shared view means "whoever is looking",
        # not "whoever ran linear-kit". Pinning an id here would be a different view.
        return {"isMe": {"eq": True}}
    return {"id": {"eq": resolver.user_id(ref)}}


def _cycle_clause(ref: str) -> dict[str, Any]:
    if ref == "none":
        return {"null": True}
    key = {"active": "isActive", "next": "isNext", "previous": "isPrevious"}[ref]
    return {key: {"eq": True}}


def _date_clause(spec: DateFilter) -> dict[str, Any]:
    clause: dict[str, Any] = {}
    if spec.none is not None:
        clause["null"] = spec.none
    if spec.after:
        clause["gte"] = spec.after
    if spec.before:
        clause["lte"] = spec.before
    if not clause:
        raise LinearError("`due_date` is empty — set before, after, or none.")
    return clause


def _estimate_clause(spec: EstimateFilter) -> dict[str, Any]:
    clause: dict[str, Any] = {}
    if spec.none is not None:
        clause["null"] = spec.none
    if spec.eq is not None:
        clause["eq"] = spec.eq
    if spec.gte is not None:
        clause["gte"] = spec.gte
    if spec.lte is not None:
        clause["lte"] = spec.lte
    if not clause:
        raise LinearError("`estimate` is empty — set eq, gte, lte, or none.")
    return clause


def build_preferences(resolver: Resolver, display: ViewDisplay) -> dict[str, Any]:
    """Render the display block as a preferences object, omitting unset keys.

    Unset means "leave Linear's default alone", so an unset key is left out
    rather than sent as null — null is a value, and writing it would pin the
    default in place. `_run_prefs` overlays the result onto what is stored.
    """
    prefs: dict[str, Any] = {}
    for key, target in _DISPLAY_KEYS.items():
        value = getattr(display, key)
        if value is not None:
            prefs[target] = value

    for value, keys in (
        (display.show_empty_groups, _EMPTY_GROUP_KEYS),
        (display.show_empty_sub_groups, _EMPTY_SUB_GROUP_KEYS),
    ):
        if value is None:
            continue
        if display.layout is None:
            raise LinearError(
                "`show_empty_groups` / `show_empty_sub_groups` need an explicit `layout`: "
                "Linear stores them per layout and reads only the key matching the view's own."
            )
        prefs[keys[display.layout]] = value

    if display.properties:
        # An exclusive list: naming a property shows it, omitting one hides it.
        # Only properties this preset models are touched — keys like SLA or pull
        # requests keep whatever the workspace has, since turning those off was
        # never asked for.
        wanted = {PROPERTY_FIELDS[p] for p in display.properties}
        for field in PROPERTY_FIELDS.values():
            prefs[field] = field in wanted

    if display.hide_states:
        if display.group_by != "workflowState":
            raise LinearError(
                "`hide_states` names board columns, which are only workflow states when "
                f"`group_by: workflowState`. This view groups by {display.group_by!r}."
            )
        prefs["hiddenColumns"] = [resolver.state_id(name) for name in display.hide_states]

    return prefs


def plan_views(client: LinearClient, preset: ViewsPreset, *, team: str) -> Plan:
    found = find_team(client, team)
    if not found:
        raise LinearError(f"No team matches {team!r} in this workspace.")
    team_id = found["id"]

    if not preset.views:
        raise LinearError(f"Preset {preset.name!r} declares no views.")

    resolver = Resolver(client, team_id)
    plan = Plan(title=f"views from preset {preset.name!r}")
    plan.notes.append(f"Team: {found['key']} ({found['name']})")

    existing = {
        v["name"].casefold(): v
        for v in client.execute(VIEWS_QUERY)["customViews"]["nodes"]
        if v.get("team") and v["team"]["id"] == team_id
    }

    for spec in preset.views:
        # Resolving here, while planning, is what lets a bad name fail before any
        # mutation runs rather than halfway through the list.
        filter_data = build_filter_data(resolver, spec.filter)
        preferences = build_preferences(resolver, spec.display)
        current = existing.get(spec.name.casefold())

        if current is None:
            view_id = new_id()
            payload = _view_input(spec, team_id) | {"id": view_id, "filterData": filter_data}
            plan.add(
                f"customViewCreate  {spec.name}",
                lambda c, _p=payload: _run_create(c, _p),
            )
        else:
            view_id = current["id"]
            plan.notes.append(f"View {spec.name!r} exists — updating in place.")
            payload = _view_input(spec, team_id) | {"filterData": filter_data}
            payload.pop("teamId", None)  # scope is fixed at creation
            plan.add(
                f"customViewUpdate  {spec.name}",
                lambda c, _id=view_id, _p=payload: _run_update(c, _id, _p),
            )

        if preferences:
            prefs_id = (current or {}).get("organizationViewPreferences") or {}
            plan.add(
                f"viewPreferences   {spec.name}: {_describe(preferences)}",
                lambda c, _v=view_id, _p=preferences, _e=prefs_id.get("id"): _run_prefs(c, _v, _p, _e),
            )

    return plan


def _view_input(spec: ViewSpec, team_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": spec.name, "teamId": team_id, "shared": spec.shared}
    if spec.description:
        payload["description"] = spec.description
    if spec.icon:
        payload["icon"] = spec.icon
    if spec.color:
        payload["color"] = spec.color
    return payload


def _describe(preferences: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in preferences.items())


def _stored_preferences(client: LinearClient, view_id: str) -> dict[str, Any]:
    """The organization layer's preferences as actually stored, minus unset keys.

    A null here means "never written", not "false" — the read is typed and returns
    every key, so nulls have to be dropped or they would be written back as real
    values and pin Linear's defaults in place.
    """
    view = client.execute(PREFS_READ, {"id": view_id}).get("customView") or {}
    prefs = (view.get("organizationViewPreferences") or {}).get("preferences") or {}
    return {key: value for key, value in prefs.items() if value is not None}


def _run_create(client: LinearClient, payload: dict[str, Any]) -> str:
    view = client.mutate(VIEW_CREATE, {"input": payload}, "customViewCreate")["customView"]
    return f"created {view['name']}"


def _run_update(client: LinearClient, view_id: str, payload: dict[str, Any]) -> str:
    view = client.mutate(
        VIEW_UPDATE, {"id": view_id, "input": payload}, "customViewUpdate"
    )["customView"]
    return f"updated {view['name']}"


def _run_prefs(
    client: LinearClient, view_id: str, preferences: dict[str, Any], existing_id: str | None
) -> str:
    if existing_id:
        # Overlay onto what is stored, because the mutation replaces rather than
        # merges. Sending only the preset's keys would strip everything else the
        # view had — a rerun is supposed to reconcile, not amputate.
        merged = _stored_preferences(client, view_id) | preferences
        client.mutate(
            PREFS_UPDATE, {"id": existing_id, "input": {"preferences": merged}}, "viewPreferencesUpdate"
        )
        kept = len(merged) - len(preferences)
        return f"updated ({kept} existing keys kept)" if kept > 0 else "updated"
    client.mutate(
        PREFS_CREATE,
        {
            "input": {
                "id": new_id(),
                "type": PREFS_TYPE,
                "viewType": PREFS_VIEW_TYPE,
                "customViewId": view_id,
                "preferences": preferences,
            }
        },
        "viewPreferencesCreate",
    )
    return "set"
