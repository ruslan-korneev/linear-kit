"""Read a live team and render it back as a preset.

This is the inverse of `plan_team`: it turns a workspace someone configured by
hand into a portable YAML file, so "set the new team up like that one" stops
being a manual transcription job.
"""

from __future__ import annotations

from typing import Any

import yaml

from linear_kit.client import LinearClient, LinearError
from linear_kit.models import Cycles, Estimation, Label, TeamPreset, TeamSpec, Triage, WorkflowState
from linear_kit.resources.team import RESERVED_STATE_TYPES, find_team

TEAM_EXPORT = """
query ($id: String!) {
  team(id: $id) {
    id key name description timezone icon color private
    cyclesEnabled cycleDuration cycleCooldownTime cycleStartDay upcomingCycleCount
    cycleIssueAutoAssignStarted cycleIssueAutoAssignCompleted cycleLockToActive
    issueEstimationType defaultIssueEstimate issueEstimationAllowZero issueEstimationExtended
    triageEnabled requirePriorityToLeaveTriage
    states { nodes { id name type color description position } }
    labels { nodes { id name color description isGroup parent { id name } } }
  }
}
"""

#: Linear groups the board by state type in this order, then by position within
#: each type. Sorting the export the same way makes the YAML read like the UI.
TYPE_ORDER = {"backlog": 0, "unstarted": 1, "started": 2, "completed": 3, "canceled": 4}


def export_team(
    client: LinearClient,
    team_ref: str,
    *,
    preset_name: str,
    include_labels: bool = False,
) -> str:
    """Return YAML for a preset that reproduces `team_ref`."""
    found = find_team(client, team_ref)
    if not found:
        raise LinearError(f"No team matches {team_ref!r} in this workspace.")
    team = client.execute(TEAM_EXPORT, {"id": found["id"]})["team"]

    preset = TeamPreset(
        name=preset_name,
        description=f"Exported from team {team['name']} ({team['key']}).",
        team=_team_spec(team),
        workflow_states=_states(team),
        labels=_labels(team) if include_labels else [],
    )

    # Team name and key are deliberately dropped: a preset describes how a team
    # is configured, not which team it is. `team create --name` supplies those.
    data = preset.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
    data["team"].pop("name", None)
    data["team"].pop("key", None)
    if not include_labels:
        data.pop("labels", None)

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def _team_spec(team: dict[str, Any]) -> TeamSpec:
    return TeamSpec(
        description=team.get("description"),
        private=bool(team["private"]),
        timezone=team.get("timezone"),
        icon=team.get("icon"),
        color=team.get("color"),
        cycles=Cycles(
            enabled=bool(team["cyclesEnabled"]),
            duration_weeks=int(team["cycleDuration"] or 2),
            cooldown_weeks=int(team["cycleCooldownTime"] or 0),
            start_day=int(team["cycleStartDay"] or 0),
            upcoming_count=int(team["upcomingCycleCount"] or 0),
            auto_assign_started=bool(team["cycleIssueAutoAssignStarted"]),
            auto_assign_completed=bool(team["cycleIssueAutoAssignCompleted"]),
            lock_to_active=bool(team["cycleLockToActive"]),
        ),
        estimation=Estimation(
            type=team["issueEstimationType"],
            default=float(team["defaultIssueEstimate"] or 0),
            allow_zero=bool(team["issueEstimationAllowZero"]),
            extended=bool(team["issueEstimationExtended"]),
        ),
        triage=Triage(
            enabled=bool(team["triageEnabled"]),
            require_priority=bool(team["requirePriorityToLeaveTriage"]),
        ),
    )


def _states(team: dict[str, Any]) -> list[WorkflowState]:
    """Reserved states are skipped — Linear creates and pins them itself."""
    states = [s for s in team["states"]["nodes"] if s["type"] not in RESERVED_STATE_TYPES]
    states.sort(key=lambda s: (TYPE_ORDER.get(s["type"], 99), s["position"]))
    return [
        WorkflowState(
            name=s["name"],
            type=s["type"],
            color=s["color"].lower(),
            description=s.get("description") or None,
        )
        for s in states
    ]


def _labels(team: dict[str, Any]) -> list[Label]:
    """Rebuild one level of label groups. Workspace-level labels are not team
    labels and are left out — they already exist everywhere in the org."""
    nodes = team["labels"]["nodes"]
    groups: dict[str, Label] = {}
    top: list[Label] = []

    for node in sorted(nodes, key=lambda n: (not n["isGroup"], n["name"].casefold())):
        label = Label(
            name=node["name"],
            color=(node["color"] or "").lower() or None,
            description=node.get("description") or None,
            is_group=bool(node["isGroup"]),
        )
        if node["isGroup"]:
            groups[node["id"]] = label
            top.append(label)
        elif node["parent"] and node["parent"]["id"] in groups:
            groups[node["parent"]["id"]].children.append(label)
        else:
            top.append(label)
    return top
