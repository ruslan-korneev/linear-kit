"""Provision a team: the team itself, its workflow states, and its labels."""

from __future__ import annotations

from typing import Any

from linear_kit.client import LinearClient, LinearError, new_id
from linear_kit.models import Label, TeamPreset, TeamSpec, WorkflowState
from linear_kit.resources.plan import Plan
from linear_kit.resources.template import sync_templates

TEAM_CREATE = """
mutation ($input: TeamCreateInput!) {
  teamCreate(input: $input) { success team { id key name } }
}
"""

TEAM_UPDATE = """
mutation ($id: String!, $input: TeamUpdateInput!) {
  teamUpdate(id: $id, input: $input) { success team { id key name } }
}
"""

TEAMS_QUERY = """
query { teams { nodes { id key name } } }
"""

TEAM_DETAIL = """
query ($id: String!) {
  team(id: $id) {
    id key name
    states { nodes { id name type color position } }
    labels { nodes { id name isGroup parent { id name } } }
  }
}
"""

STATE_CREATE = """
mutation ($input: WorkflowStateCreateInput!) {
  workflowStateCreate(input: $input) { success workflowState { id name } }
}
"""

STATE_UPDATE = """
mutation ($id: String!, $input: WorkflowStateUpdateInput!) {
  workflowStateUpdate(id: $id, input: $input) { success workflowState { id name } }
}
"""

LABEL_CREATE = """
mutation ($input: IssueLabelCreateInput!) {
  issueLabelCreate(input: $input) { success issueLabel { id name } }
}
"""

#: Linear pins these and rejects workflowStateUpdate on them with
#: "unable to update reserved state". They are never repositioned or recolored.
RESERVED_STATE_TYPES = frozenset({"triage", "duplicate"})


def find_team(client: LinearClient, ref: str) -> dict[str, Any] | None:
    """Look a team up by key or name, case-insensitively."""
    teams = client.execute(TEAMS_QUERY)["teams"]["nodes"]
    needle = ref.casefold()
    for team in teams:
        if team["key"].casefold() == needle or team["name"].casefold() == needle:
            return team
    return None


def _team_input(spec: TeamSpec, name: str, key: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if key:
        payload["key"] = key
    if spec.description:
        payload["description"] = spec.description
    if spec.timezone:
        payload["timezone"] = spec.timezone
    if spec.icon:
        payload["icon"] = spec.icon
    if spec.color:
        payload["color"] = spec.color
    payload["private"] = spec.private

    # Cycle, estimation and triage details are sent even when the feature is
    # switched off. Linear keeps the settings either way, so carrying them
    # unconditionally means a preset still round-trips a team whose cycles are
    # currently disabled — the config is preserved for whenever it is enabled.
    cycles = spec.cycles
    payload.update(
        cyclesEnabled=cycles.enabled,
        cycleDuration=cycles.duration_weeks,
        cycleCooldownTime=cycles.cooldown_weeks,
        cycleStartDay=float(cycles.start_day),
        upcomingCycleCount=float(cycles.upcoming_count),
        cycleIssueAutoAssignStarted=cycles.auto_assign_started,
        cycleIssueAutoAssignCompleted=cycles.auto_assign_completed,
        cycleLockToActive=cycles.lock_to_active,
    )

    est = spec.estimation
    payload.update(
        issueEstimationType=est.type,
        defaultIssueEstimate=est.default,
        issueEstimationAllowZero=est.allow_zero,
        issueEstimationExtended=est.extended,
    )

    payload.update(
        triageEnabled=spec.triage.enabled,
        requirePriorityToLeaveTriage=spec.triage.require_priority,
    )
    return payload


def plan_team(
    client: LinearClient,
    preset: TeamPreset,
    *,
    name: str | None = None,
    key: str | None = None,
) -> Plan:
    spec = preset.team
    team_name = name or spec.name
    if not team_name:
        raise LinearError("No team name: pass --name or set team.name in the preset.")
    team_key = key or spec.key

    plan = Plan(title=f"team {team_name!r} from preset {preset.name!r}")
    existing = find_team(client, team_key or team_name)

    if existing:
        team_id = existing["id"]
        plan.notes.append(
            f"Team {existing['name']!r} ({existing['key']}) already exists — updating in place."
        )
        payload = _team_input(spec, team_name, None)  # key is immutable after create
        plan.add(
            f"teamUpdate     {existing['key']} — apply preset settings",
            lambda c, _id=team_id, _p=payload: _run_team_update(c, _id, _p),
        )
    else:
        team_id = new_id()
        payload = _team_input(spec, team_name, team_key) | {"id": team_id}
        plan.add(
            f"teamCreate     {team_name} ({team_key or 'auto-key'})",
            lambda c, _p=payload: _run_team_create(c, _p),
        )

    plan.context["team_id"] = team_id

    if preset.workflow_states:
        plan.add(
            f"workflowStates reconcile {len(preset.workflow_states)} states",
            lambda c, _id=team_id, _s=preset.workflow_states: _sync_states(c, _id, _s),
        )
    if preset.labels:
        total = sum(1 + len(lbl.children) for lbl in preset.labels)
        plan.add(
            f"issueLabels    reconcile {total} labels",
            lambda c, _id=team_id, _l=preset.labels: _sync_labels(c, _id, _l),
            tolerant=True,
        )
    if preset.templates:
        # Templates run last: they reference states and label groups by name, so
        # those have to exist before the resolver can look them up.
        plan.add(
            f"templates      reconcile {len(preset.templates)} templates",
            lambda c, _id=team_id, _t=preset.templates: sync_templates(c, _id, _t),
        )
    return plan


def _run_team_create(client: LinearClient, payload: dict[str, Any]) -> str:
    team = client.mutate(TEAM_CREATE, {"input": payload}, "teamCreate")["team"]
    return f"created {team['name']} ({team['key']})"


def _run_team_update(client: LinearClient, team_id: str, payload: dict[str, Any]) -> str:
    team = client.mutate(TEAM_UPDATE, {"id": team_id, "input": payload}, "teamUpdate")["team"]
    return f"updated {team['name']} ({team['key']})"


def _sync_states(client: LinearClient, team_id: str, wanted: list[WorkflowState]) -> str:
    """Match preset states to the team's states by name, then fix their order.

    Linear seeds every new team with default states, so creating blindly would
    duplicate them. Matching by name means a preset converges onto the defaults
    instead of fighting them. Extra states are left alone, never archived.

    Ordering needs a second pass: workflowStateCreate ignores `position` and
    appends instead, so positions are only settable via workflowStateUpdate
    once every state exists.
    """
    existing = client.execute(TEAM_DETAIL, {"id": team_id})["team"]["states"]["nodes"]
    by_name = {s["name"].casefold(): s for s in existing}

    created = 0
    for state in wanted:
        if state.name.casefold() in by_name:
            continue
        payload: dict[str, Any] = {
            "id": new_id(),
            "teamId": team_id,
            "name": state.name,
            "type": state.type,
            "color": state.color,
        }
        if state.description:
            payload["description"] = state.description
        client.mutate(STATE_CREATE, {"input": payload}, "workflowStateCreate")
        created += 1

    if created:
        existing = client.execute(TEAM_DETAIL, {"id": team_id})["team"]["states"]["nodes"]
        by_name = {s["name"].casefold(): s for s in existing}

    # Preset states first in preset order, then any unmanaged state after them,
    # keeping its current relative order. Reserved states are pinned by Linear.
    wanted_names = [s.name.casefold() for s in wanted]
    unmanaged = sorted(
        (
            s
            for s in existing
            if s["name"].casefold() not in wanted_names
            and s["type"] not in RESERVED_STATE_TYPES
        ),
        key=lambda s: s["position"],
    )
    ordered = [by_name[name] for name in wanted_names] + unmanaged
    desired_color = {s.name.casefold(): s for s in wanted}

    updated = 0
    for index, current in enumerate(ordered):
        if current["type"] in RESERVED_STATE_TYPES:
            continue
        changes: dict[str, Any] = {}
        if current["position"] != float(index):
            changes["position"] = float(index)

        state = desired_color.get(current["name"].casefold())
        if state:
            if current["color"].casefold() != state.color.casefold():
                changes["color"] = state.color
            if state.description:
                changes["description"] = state.description
        if changes:
            client.mutate(
                STATE_UPDATE, {"id": current["id"], "input": changes}, "workflowStateUpdate"
            )
            updated += 1

    unchanged = len(ordered) - created - updated
    return f"{created} created, {updated} updated, {max(unchanged, 0)} unchanged"


def _sync_labels(client: LinearClient, team_id: str, wanted: list[Label]) -> str:
    """Create missing team labels, including one level of label groups.

    A workspace-level label with the same name blocks a team label of that name,
    so collisions are reported rather than raised — the label already exists and
    is usable either way.
    """
    detail = client.execute(TEAM_DETAIL, {"id": team_id})["team"]
    by_name = {lbl["name"].casefold(): lbl for lbl in detail["labels"]["nodes"]}

    created, skipped, failed = 0, 0, []

    def create(label: Label, parent_id: str | None) -> str | None:
        current = by_name.get(label.name.casefold())
        if current is not None:
            nonlocal skipped
            skipped += 1
            return current["id"]

        payload: dict[str, Any] = {"id": new_id(), "teamId": team_id, "name": label.name}
        if label.color:
            payload["color"] = label.color
        if label.description:
            payload["description"] = label.description
        if label.is_group:
            payload["isGroup"] = True
        if parent_id:
            payload["parentId"] = parent_id
        try:
            result = client.mutate(LABEL_CREATE, {"input": payload}, "issueLabelCreate")
        except LinearError as exc:
            failed.append(f"{label.name}: {exc}")
            return None
        nonlocal created
        created += 1
        return result["issueLabel"]["id"]

    for label in wanted:
        parent_id = create(label, None)
        for child in label.children:
            if parent_id is None:
                failed.append(f"{child.name}: parent group {label.name!r} unavailable")
                continue
            create(child, parent_id)

    summary = f"{created} created, {skipped} existed"
    if failed:
        summary += f", {len(failed)} failed ({'; '.join(failed)})"
    return summary
