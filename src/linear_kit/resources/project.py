"""Provision a project and its milestones."""

from __future__ import annotations

from typing import Any

from linear_kit.client import LinearClient, LinearError, new_id
from linear_kit.models import ProjectPreset, ProjectSpec
from linear_kit.resources.plan import Plan
from linear_kit.resources.team import find_team

PROJECT_CREATE = """
mutation ($input: ProjectCreateInput!) {
  projectCreate(input: $input) { success project { id name url } }
}
"""

PROJECT_UPDATE = """
mutation ($id: String!, $input: ProjectUpdateInput!) {
  projectUpdate(id: $id, input: $input) { success project { id name url } }
}
"""

PROJECTS_QUERY = """
query { projects { nodes { id name } } }
"""

PROJECT_MILESTONES = """
query ($id: String!) {
  project(id: $id) { id projectMilestones { nodes { id name } } }
}
"""

MILESTONE_CREATE = """
mutation ($input: ProjectMilestoneCreateInput!) {
  projectMilestoneCreate(input: $input) { success projectMilestone { id name } }
}
"""


def _project_input(spec: ProjectSpec, name: str, team_ids: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "teamIds": team_ids}
    if spec.description:
        payload["description"] = spec.description
    if spec.content:
        payload["content"] = spec.content
    if spec.icon:
        payload["icon"] = spec.icon
    if spec.color:
        payload["color"] = spec.color
    if spec.priority is not None:
        payload["priority"] = spec.priority
    if spec.start_date:
        payload["startDate"] = spec.start_date
    if spec.target_date:
        payload["targetDate"] = spec.target_date
    return payload


def plan_project(
    client: LinearClient,
    preset: ProjectPreset,
    *,
    teams: list[str],
    name: str | None = None,
    description: str | None = None,
    target_date: str | None = None,
) -> Plan:
    spec = preset.project
    project_name = name or spec.name
    if not project_name:
        raise LinearError("No project name: pass --name or set project.name in the preset.")
    if not teams:
        raise LinearError("A project needs at least one team: pass --team KEY.")

    team_ids: list[str] = []
    for ref in teams:
        found = find_team(client, ref)
        if not found:
            raise LinearError(f"No team matches {ref!r} in this workspace.")
        team_ids.append(found["id"])

    if description:
        spec = spec.model_copy(update={"description": description})
    if target_date:
        spec = spec.model_copy(update={"target_date": target_date})

    plan = Plan(title=f"project {project_name!r} from preset {preset.name!r}")
    plan.notes.append(f"Teams: {', '.join(teams)}")

    existing = _find_project(client, project_name)
    if existing:
        project_id = existing["id"]
        plan.notes.append(f"Project {project_name!r} already exists — updating in place.")
        payload = _project_input(spec, project_name, team_ids)
        payload.pop("teamIds", None)  # not updatable via projectUpdate
        plan.add(
            f"projectUpdate  {project_name}",
            lambda c, _id=project_id, _p=payload: _run_update(c, _id, _p),
        )
    else:
        project_id = new_id()
        payload = _project_input(spec, project_name, team_ids) | {"id": project_id}
        plan.add(
            f"projectCreate  {project_name}",
            lambda c, _p=payload: _run_create(c, _p),
        )

    plan.context["project_id"] = project_id

    if spec.milestones:
        plan.add(
            f"milestones     reconcile {len(spec.milestones)} milestones",
            lambda c, _id=project_id, _m=spec.milestones: _sync_milestones(c, _id, _m),
        )
    return plan


def _find_project(client: LinearClient, name: str) -> dict[str, Any] | None:
    needle = name.casefold()
    for project in client.execute(PROJECTS_QUERY)["projects"]["nodes"]:
        if project["name"].casefold() == needle:
            return project
    return None


def _run_create(client: LinearClient, payload: dict[str, Any]) -> str:
    project = client.mutate(PROJECT_CREATE, {"input": payload}, "projectCreate")["project"]
    return f"created {project['name']} — {project['url']}"


def _run_update(client: LinearClient, project_id: str, payload: dict[str, Any]) -> str:
    project = client.mutate(
        PROJECT_UPDATE, {"id": project_id, "input": payload}, "projectUpdate"
    )["project"]
    return f"updated {project['name']} — {project['url']}"


def _sync_milestones(client: LinearClient, project_id: str, wanted: list[Any]) -> str:
    detail = client.execute(PROJECT_MILESTONES, {"id": project_id})["project"]
    existing = {m["name"].casefold() for m in detail["projectMilestones"]["nodes"]}

    created = 0
    for position, milestone in enumerate(wanted):
        if milestone.name.casefold() in existing:
            continue
        payload: dict[str, Any] = {
            "id": new_id(),
            "projectId": project_id,
            "name": milestone.name,
            "sortOrder": float(position),
        }
        if milestone.description:
            payload["description"] = milestone.description
        if milestone.target_date:
            payload["targetDate"] = milestone.target_date
        client.mutate(MILESTONE_CREATE, {"input": payload}, "projectMilestoneCreate")
        created += 1

    return f"{created} created, {len(wanted) - created} existed"
