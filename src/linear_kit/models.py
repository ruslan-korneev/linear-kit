"""Pydantic schema for YAML presets.

Presets are validated before any mutation runs, so a typo in a preset fails
locally instead of halfway through provisioning a workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

EstimationType = Literal["notUsed", "exponential", "fibonacci", "linear", "tShirt"]
StateType = Literal["backlog", "unstarted", "started", "completed", "canceled"]

PRESET_DIR = Path(__file__).parent / "presets"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Cycles(Strict):
    enabled: bool = False
    duration_weeks: int = 2
    cooldown_weeks: int = 0
    start_day: int = 1  # 0 = Sunday
    upcoming_count: int = 2
    auto_assign_started: bool = True
    auto_assign_completed: bool = True
    lock_to_active: bool = False


class Estimation(Strict):
    type: EstimationType = "notUsed"
    default: float = 1
    allow_zero: bool = False
    extended: bool = False


class Triage(Strict):
    enabled: bool = False
    require_priority: bool = False


class WorkflowState(Strict):
    """Order in the preset list is the order shown in Linear."""

    name: str
    type: StateType
    color: str
    description: str | None = None


class Label(Strict):
    name: str
    color: str | None = None
    description: str | None = None
    is_group: bool = False
    children: list["Label"] = Field(default_factory=list)


class TeamSpec(Strict):
    name: str | None = None
    key: str | None = None
    description: str | None = None
    private: bool = False
    timezone: str | None = None
    icon: str | None = None
    color: str | None = None
    cycles: Cycles = Field(default_factory=Cycles)
    estimation: Estimation = Field(default_factory=Estimation)
    triage: Triage = Field(default_factory=Triage)


class Milestone(Strict):
    name: str
    description: str | None = None
    target_date: str | None = None  # YYYY-MM-DD


class ProjectSpec(Strict):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    icon: str | None = None
    color: str | None = None
    priority: int | None = None
    start_date: str | None = None
    target_date: str | None = None
    milestones: list[Milestone] = Field(default_factory=list)


#: Only these four are confirmed to exist, having been read back off a live
#: template. Linear types the field as a bare string, so others may well be
#: valid — but guessing names here would fail deep inside templateCreate.
FormFieldType = Literal["title", "textarea", "dueDate", "labelGroup"]


class FormField(Strict):
    type: FormFieldType
    label: str
    required: bool = True
    #: textarea only — prefilled body text, rendered as a ProseMirror doc.
    default: str | None = None
    #: labelGroup only — name of the label group the field picks from.
    group: str | None = None


class IssueDefaults(Strict):
    """Values an issue starts with when created from the template."""

    title: str = ""
    priority: int | None = None  # 0 none, 1 urgent, 2 high, 3 medium, 4 low
    assignee: str | None = None  # "me", an email, or a display name
    state: str | None = None
    labels: list[str] = Field(default_factory=list)
    project: str | None = None
    milestone: str | None = None  # requires `project`


class Template(Strict):
    name: str
    # project/document templates use a different templateData shape that has not
    # been observed, so only issue templates are accepted.
    type: Literal["issue"] = "issue"
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    issue: IssueDefaults = Field(default_factory=IssueDefaults)
    form_fields: list[FormField] = Field(default_factory=list)


#: Linear stores priority as 0-4. Presets name it, since `priority: 1` reads
#: like the highest number wins when it is in fact Urgent.
PriorityName = Literal["none", "urgent", "high", "medium", "low"]
PRIORITY_VALUES: dict[str, int] = {"none": 0, "urgent": 1, "high": 2, "medium": 3, "low": 4}
PRIORITY_NAMES: dict[int, str] = {value: name for name, value in PRIORITY_VALUES.items()}

#: WorkflowStateFilter.type accepts these. Unlike state *names*, which a team is
#: free to rename, types are fixed — so a preset filtering on them stays portable.
StateTypeName = Literal["triage", "backlog", "unstarted", "started", "completed", "canceled"]

#: NullableCycleFilter exposes isActive/isNext/isPrevious booleans rather than
#: ids, so a cycle filter needs no lookup and survives the cycle rolling over.
CycleRef = Literal["active", "next", "previous", "none"]

# View preference vocabularies.
#
# Linear types every one of these as a bare `String` and validates none of them,
# so the schema cannot say what is legal and a wrong value fails silently. Each
# value below was read back off a view configured by hand in the UI — the same
# way templateData was recovered. Nothing here is guessed: a value absent from
# these lists is a value that has not been observed, not one known to be
# invalid. Extend them by configuring a view in the UI and running
# `linear-kit inspect views`.
ViewLayout = Literal["list", "board"]
ViewOrdering = Literal["priority", "sortOrder"]

#: `group_by` is the board's Columns / the list's grouping; `sub_group_by` is the
#: board's Rows. They are split because their observed values differ: `project`
#: has only ever been seen on the sub-grouping key, `workflowState` only on the
#: grouping key. The UI likely offers one list for both, but "likely" is exactly
#: what silently breaks a view here, so each key allows only what it has shown.
IssueGrouping = Literal["workflowState", "priority", "none"]
IssueSubGrouping = Literal["project", "priority", "none"]

#: Whether sub-issues nest under their parent or appear as flat rows.
IssueNesting = Literal["showAll", "none"]

#: How much completed work stays on the board. `week` is the UI's "Past week".
ShowCompleted = Literal["all", "week"]

# Not modelled: viewOrderingDirection. It read back null on every live view, so
# its vocabulary has never been seen and there is nothing to validate against.

#: The chips under "Display properties". Listing them in a preset is declarative:
#: `properties` names exactly what shows, and everything else is turned off. That
#: makes "everything except links" a list rather than eleven booleans, and keeps
#: a rerun from drifting as Linear adds new properties with new defaults.
#:
#: These map to `field*` booleans, so unlike the string keys above there is no
#: vocabulary to get wrong — only the name-to-key mapping, which is checked here.
DisplayProperty = Literal[
    "id",
    "status",
    "assignee",
    "priority",
    "project",
    "milestone",
    "labels",
    "due_date",
    "estimate",
    "cycle",
    "links",
    "time_in_status",
    "created",
    "updated",
]

PROPERTY_FIELDS: dict[str, str] = {
    "id": "fieldId",
    "status": "fieldStatus",
    "assignee": "fieldAssignee",
    "priority": "fieldPriority",
    "project": "fieldProject",
    "milestone": "fieldMilestone",
    "labels": "fieldLabels",
    "due_date": "fieldDueDate",
    "estimate": "fieldEstimate",
    "cycle": "fieldCycle",
    #: The "Links" chip is `fieldPreviewLinks`, not the similarly named
    #: `fieldLinkCount`. Confirmed by writing fieldPreviewLinks=false and watching
    #: the chip go dark; `fieldLinkCount` defaults to false and switching the chip
    #: on never wrote it.
    "links": "fieldPreviewLinks",
    "time_in_status": "fieldTimeInCurrentStatus",
    "created": "fieldDateCreated",
    "updated": "fieldDateUpdated",
}


class DateFilter(Strict):
    """A due-date window. Both bounds are YYYY-MM-DD and inclusive."""

    before: str | None = None
    after: str | None = None
    none: bool | None = None  # true = no due date set, false = any due date


class EstimateFilter(Strict):
    eq: float | None = None
    gte: float | None = None
    lte: float | None = None
    none: bool | None = None


class ViewFilter(Strict):
    """The curated subset of Linear's IssueFilter that presets can express.

    IssueFilter has ~60 fields, most of them internal or analytical. These are
    the ones the Linear UI itself offers when building a view, and every one of
    them is named rather than given as an id, so a preset stays portable.

    Fields combine with AND, matching how the UI stacks filter chips. `any_of`
    nests a list of alternatives under OR.
    """

    state: list[str] = Field(default_factory=list)  # state names, OR'd together
    state_type: list[StateTypeName] = Field(default_factory=list)
    assignee: str | None = None  # "me", an email, a display name, or "none"
    creator: str | None = None
    labels: list[str] = Field(default_factory=list)
    priority: list[PriorityName] = Field(default_factory=list)
    project: str | None = None  # project name, or "none"
    cycle: CycleRef | None = None
    team: str | None = None  # team key or name
    due_date: DateFilter | None = None
    estimate: EstimateFilter | None = None
    any_of: list["ViewFilter"] = Field(default_factory=list)


class ViewDisplay(Strict):
    """Grouping, ordering and layout.

    These live in viewPreferences, not on the view itself — a separate mutation
    against a separate object, keyed back to the view by customViewId.

    Every value here is validated locally against a vocabulary recovered from
    live views, because `preferences` is typed `JSONObject` and Linear validates
    *nothing*: writing `layout: bogus` is accepted, stored, and read back
    verbatim, leaving a view that silently renders wrong. A typo has to fail
    here or it will not fail at all.
    """

    layout: ViewLayout | None = None
    #: Board columns / list grouping.
    group_by: IssueGrouping | None = None
    #: Board rows. Ignored by Linear on a list layout.
    sub_group_by: IssueSubGrouping | None = None
    order_by: ViewOrdering | None = None
    #: Sort finished work by when it finished, rather than by `order_by`.
    order_completed_by_recency: bool | None = None
    show_completed: ShowCompleted | None = None
    show_sub_issues: bool | None = None
    #: Whether sub-issues nest under their parent. Only ever written on lists.
    nesting: IssueNesting | None = None
    show_triage: bool | None = None
    #: Empty columns on a board / empty groups on a list. Linear keeps these on
    #: separate keys per layout, so which one gets written depends on `layout`.
    show_empty_groups: bool | None = None
    #: Empty rows on a board.
    show_empty_sub_groups: bool | None = None
    #: Exactly which properties show. Anything omitted is turned off, so this is
    #: a complete statement rather than a set of overrides.
    properties: list[DisplayProperty] = Field(default_factory=list)
    #: Board columns to hide, named by workflow state. Only meaningful when
    #: `group_by: workflowState`, since the columns are the states — hiding by
    #: state name under any other grouping would name something that is not a
    #: column. Names are resolved to ids: `hiddenColumns` holds state ids, which
    #: was confirmed by writing them and watching the columns disappear.
    hide_states: list[str] = Field(default_factory=list)


class ViewSpec(Strict):
    name: str
    description: str | None = None
    #: Personal by default. A shared view shows up for the whole workspace, so
    #: opting in is deliberate rather than a default someone inherits.
    shared: bool = False
    icon: str | None = None
    color: str | None = None
    filter: ViewFilter = Field(default_factory=ViewFilter)
    display: ViewDisplay = Field(default_factory=ViewDisplay)


class TeamPreset(Strict):
    kind: Literal["team"] = "team"
    name: str
    description: str | None = None
    team: TeamSpec = Field(default_factory=TeamSpec)
    workflow_states: list[WorkflowState] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    templates: list[Template] = Field(default_factory=list)


class ViewsPreset(Strict):
    kind: Literal["views"] = "views"
    name: str
    description: str | None = None
    views: list[ViewSpec] = Field(default_factory=list)


class ProjectPreset(Strict):
    kind: Literal["project"] = "project"
    name: str
    description: str | None = None
    project: ProjectSpec = Field(default_factory=ProjectSpec)
    labels: list[Label] = Field(default_factory=list)


Preset = TeamPreset | ProjectPreset | ViewsPreset


def preset_path(name: str) -> Path:
    """Accept a bare preset name, or a path to a YAML file outside the bundle."""
    candidate = Path(name)
    if candidate.suffix in {".yaml", ".yml"} and candidate.exists():
        return candidate
    for suffix in (".yaml", ".yml"):
        bundled = PRESET_DIR / f"{name}{suffix}"
        if bundled.exists():
            return bundled
    known = ", ".join(sorted(p.stem for p in PRESET_DIR.glob("*.y*ml"))) or "none"
    raise FileNotFoundError(f"Preset {name!r} not found. Bundled presets: {known}.")


def load_team_preset(name: str) -> TeamPreset:
    data = yaml.safe_load(preset_path(name).read_text())
    return TeamPreset.model_validate(data)


def load_project_preset(name: str) -> ProjectPreset:
    data = yaml.safe_load(preset_path(name).read_text())
    return ProjectPreset.model_validate(data)


def load_views_preset(name: str) -> ViewsPreset:
    data = yaml.safe_load(preset_path(name).read_text())
    return ViewsPreset.model_validate(data)


def list_presets() -> list[tuple[str, str, str]]:
    """Return (name, kind, description) for every bundled preset."""
    out: list[tuple[str, str, str]] = []
    for path in sorted(PRESET_DIR.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text()) or {}
        out.append((path.stem, data.get("kind", "?"), data.get("description", "")))
    return out
