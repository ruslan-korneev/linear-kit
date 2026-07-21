"""Build and reconcile issue templates.

`templateData` is undocumented. Everything here mirrors the shape read back off
a template built by hand in the Linear UI:

    {"title": "", "priority": 4, "assigneeId": …, "labelIds": [...], "stateId": …,
     "projectId": …, "projectMilestoneId": …, "teamId": …,
     "formFields": [{"id": …, "type": "textarea", "required": true, "label": "…",
                     "descriptionData": {ProseMirror doc}, "sortOrder": 2000}]}

Linear accepts it as either a JSON object or a JSON string, and always reads it
back as a string.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from linear_kit.client import LinearClient
from linear_kit.models import FormField, Template
from linear_kit.resources.resolve import Resolver

TEMPLATES_QUERY = """
query { templates { id name type templateData team { id } } }
"""

TEMPLATE_CREATE = """
mutation ($input: TemplateCreateInput!) {
  templateCreate(input: $input) { success template { id name } }
}
"""

TEMPLATE_UPDATE = """
mutation ($id: String!, $input: TemplateUpdateInput!) {
  templateUpdate(id: $id, input: $input) { success template { id name } }
}
"""

#: Form fields need stable ids across reruns, otherwise every apply would
#: rewrite the whole form. Deriving them from (team, template, label) keeps a
#: rerun a no-op while still giving each field the UUID the API expects.
_FIELD_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

#: Linear spaces form fields 1000 apart, leaving room to insert between them.
_SORT_STEP = 1000


def build_template_data(
    resolver: Resolver, team_id: str, template: Template
) -> dict[str, Any]:
    issue = template.issue
    data: dict[str, Any] = {"title": issue.title, "teamId": team_id}

    if issue.priority is not None:
        data["priority"] = issue.priority
    if issue.assignee:
        data["assigneeId"] = resolver.user_id(issue.assignee)
    if issue.state:
        data["stateId"] = resolver.state_id(issue.state)
    if issue.labels:
        data["labelIds"] = resolver.label_ids(issue.labels)
    if issue.project:
        data["projectId"] = resolver.project_id(issue.project)
        if issue.milestone:
            data["projectMilestoneId"] = resolver.milestone_id(issue.project, issue.milestone)
    elif issue.milestone:
        raise ValueError(
            f"Template {template.name!r} sets a milestone but no project; "
            "a milestone only exists inside a project."
        )

    data["formFields"] = [
        _form_field(resolver, team_id, template, field, index)
        for index, field in enumerate(template.form_fields)
    ]
    return data


def _form_field(
    resolver: Resolver, team_id: str, template: Template, field: FormField, index: int
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid.uuid5(_FIELD_NAMESPACE, f"{team_id}:{template.name}:{field.label}")),
        "type": field.type,
        "required": field.required,
        "label": field.label,
        "sortOrder": (index + 1) * _SORT_STEP,
    }
    if field.default:
        payload["descriptionData"] = _prosemirror(field.default)
    if field.type == "labelGroup":
        if not field.group:
            raise ValueError(
                f"Form field {field.label!r} is a labelGroup but names no `group`."
            )
        payload["groupId"] = resolver.label_group_id(field.group)
    return payload


def _prosemirror(text: str) -> dict[str, Any]:
    """Wrap plain text as the ProseMirror doc Linear stores for default bodies.

    Blank lines separate paragraphs; an empty paragraph carries no content key.
    """
    paragraphs: list[dict[str, Any]] = []
    for line in text.split("\n"):
        if line.strip():
            paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
        else:
            paragraphs.append({"type": "paragraph"})
    return {"type": "doc", "content": paragraphs or [{"type": "paragraph"}]}


def sync_templates(client: LinearClient, team_id: str, wanted: list[Template]) -> str:
    """Create or update each template, matching by name within the team."""
    resolver = Resolver(client, team_id)
    existing = {
        t["name"].casefold(): t
        for t in client.execute(TEMPLATES_QUERY)["templates"]
        if t.get("team") and t["team"]["id"] == team_id
    }

    created, updated, unchanged = 0, 0, 0
    for template in wanted:
        data = build_template_data(resolver, team_id, template)
        current = existing.get(template.name.casefold())

        if current is None:
            payload: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "name": template.name,
                "type": template.type,
                "teamId": team_id,
                "templateData": data,
            }
            if template.description:
                payload["description"] = template.description
            if template.icon:
                payload["icon"] = template.icon
            if template.color:
                payload["color"] = template.color
            client.mutate(TEMPLATE_CREATE, {"input": payload}, "templateCreate")
            created += 1
            continue

        if _same(current["templateData"], data):
            unchanged += 1
            continue

        changes: dict[str, Any] = {"templateData": data}
        if template.description:
            changes["description"] = template.description
        if template.icon:
            changes["icon"] = template.icon
        if template.color:
            changes["color"] = template.color
        client.mutate(TEMPLATE_UPDATE, {"id": current["id"], "input": changes}, "templateUpdate")
        updated += 1

    return f"{created} created, {updated} updated, {unchanged} unchanged"


def _same(stored: str | dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Compare parsed structures, since Linear returns templateData as a string
    and its key order is not ours to rely on."""
    try:
        current = json.loads(stored) if isinstance(stored, str) else stored
    except json.JSONDecodeError:
        return False
    return current == wanted
