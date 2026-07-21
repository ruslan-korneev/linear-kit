"""Resolve human-readable names in a preset to the UUIDs Linear wants.

Linear identifies everything by workspace-specific UUID. A preset that hardcoded
them would only ever apply to the workspace it was written against, which defeats
the point. So presets name things — `state: In Review`, `assignee: me` — and this
resolves those names against whichever workspace is being provisioned.

Lookups are cached per instance: a template referencing five labels should cost
one query, not five.
"""

from __future__ import annotations

from typing import Any

from linear_kit.client import LinearClient, LinearError

VIEWER = "query { viewer { id } }"
#: `app` filters out integration bot accounts, which are users to the API but
#: never a person you would assign an issue to.
USERS = "query { users { nodes { id name displayName email active app } } }"
TEAM_ENTITIES = """
query ($id: String!) {
  team(id: $id) {
    id
    states { nodes { id name } }
    labels { nodes { id name isGroup } }
  }
}
"""
PROJECTS = """
query { projects { nodes { id name projectMilestones { nodes { id name } } } } }
"""
TEAMS = "query { teams { nodes { id key name } } }"


#: Lookup tables are keyed by casefolded name but hold the original spelling, so
#: an error can echo names back the way the user would recognise them.
Index = dict[str, dict[str, str]]


class Resolver:
    def __init__(self, client: LinearClient, team_id: str) -> None:
        self._client = client
        self._team_id = team_id
        self._states: Index | None = None
        self._labels: Index | None = None
        self._groups: Index | None = None
        self._users: list[dict[str, Any]] | None = None
        self._projects: list[dict[str, Any]] | None = None
        self._teams: list[dict[str, Any]] | None = None

    def state_id(self, name: str) -> str:
        if self._states is None:
            self._load_team()
        assert self._states is not None
        return _pick(self._states, name, "workflow state")

    def label_id(self, name: str) -> str:
        if self._labels is None:
            self._load_team()
        assert self._labels is not None
        return _pick(self._labels, name, "label")

    def label_ids(self, names: list[str]) -> list[str]:
        return [self.label_id(name) for name in names]

    def label_group_id(self, name: str) -> str:
        if self._groups is None:
            self._load_team()
        assert self._groups is not None
        return _pick(self._groups, name, "label group")

    def user_id(self, ref: str) -> str:
        """Accept `me`, an email, a display name, or a full name."""
        if ref == "me":
            return str(self._client.execute(VIEWER)["viewer"]["id"])
        if self._users is None:
            self._users = [
                u for u in self._client.execute(USERS)["users"]["nodes"] if not u["app"]
            ]
        users = self._users

        needle = ref.casefold()
        for field in ("email", "displayName", "name"):
            for user in users:
                if (user.get(field) or "").casefold() == needle:
                    return str(user["id"])
        known = ", ".join(sorted(u["email"] for u in users if u["active"]))
        raise LinearError(f"No user matches {ref!r}. Try `me` or one of: {known}.")

    def team_id(self, ref: str) -> str:
        """Accept a team key (PAY) or a team name."""
        if self._teams is None:
            nodes: list[dict[str, Any]] = self._client.execute(TEAMS)["teams"]["nodes"]
            self._teams = nodes
        teams = self._teams
        needle = ref.casefold()
        for team in teams:
            if team["key"].casefold() == needle or team["name"].casefold() == needle:
                return str(team["id"])
        known = ", ".join(sorted(f"{t['key']} ({t['name']})" for t in teams)) or "none"
        raise LinearError(f"No team matches {ref!r}. Available: {known}.")

    def project_id(self, name: str) -> str:
        return str(self._project(name)["id"])

    def milestone_id(self, project_name: str, milestone_name: str) -> str:
        project = self._project(project_name)
        milestones: Index = {
            m["name"].casefold(): {"id": m["id"], "name": m["name"]}
            for m in project["projectMilestones"]["nodes"]
        }
        return _pick(milestones, milestone_name, f"milestone in project {project_name!r}")

    def _project(self, name: str) -> dict[str, Any]:
        if self._projects is None:
            self._projects = self._client.execute(PROJECTS)["projects"]["nodes"]
        projects = self._projects
        needle = name.casefold()
        for project in projects:
            if project["name"].casefold() == needle:
                return project
        known = ", ".join(sorted(p["name"] for p in projects)) or "none"
        raise LinearError(f"No project named {name!r}. Available: {known}.")

    def _load_team(self) -> None:
        team = self._client.execute(TEAM_ENTITIES, {"id": self._team_id})["team"]
        self._states = _index(team["states"]["nodes"])
        self._labels = _index(n for n in team["labels"]["nodes"] if not n["isGroup"])
        self._groups = _index(n for n in team["labels"]["nodes"] if n["isGroup"])


def _index(nodes: Any) -> Index:
    return {n["name"].casefold(): {"id": n["id"], "name": n["name"]} for n in nodes}


def _pick(mapping: Index, name: str, kind: str) -> str:
    """Look a name up case-insensitively, listing the options when it misses.

    A typo in a preset should say what the valid names are, rather than let
    Linear reject the mutation with something opaque later on.
    """
    found = mapping.get(name.casefold())
    if found is None:
        known = ", ".join(sorted(entry["name"] for entry in mapping.values())) or "none"
        raise LinearError(f"No {kind} named {name!r} in this team. Available: {known}.")
    return found["id"]
