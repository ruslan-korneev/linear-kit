"""Tests for the preset -> IssueFilter / preferences mapping.

These are the parts worth testing offline: they are pure, and they are where a
mistake is quiet. A wrong `labels` clause still produces a valid filter that the
API happily accepts — it just returns the wrong issues, which no amount of
schema typing catches. The live API covers the rest.
"""

from __future__ import annotations

from typing import Any

import pytest

from linear_kit.client import LinearError
from linear_kit.models import ViewDisplay, ViewFilter, ViewsPreset
from linear_kit.resources.view import _run_prefs, build_filter_data, build_preferences


class FakeResolver:
    """Stands in for Resolver, returning predictable ids and recording lookups."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def state_id(self, name: str) -> str:
        self.calls.append(("state", name))
        return f"state-{name.lower().replace(' ', '-')}"

    def label_ids(self, names: list[str]) -> list[str]:
        for name in names:
            self.calls.append(("label", name))
        return [f"label-{n.lower()}" for n in names]

    def user_id(self, ref: str) -> str:
        self.calls.append(("user", ref))
        return f"user-{ref.lower()}"

    def project_id(self, name: str) -> str:
        self.calls.append(("project", name))
        return f"project-{name.lower()}"

    def team_id(self, ref: str) -> str:
        self.calls.append(("team", ref))
        return f"team-{ref.lower()}"


def build(spec: ViewFilter) -> dict[str, Any]:
    return build_filter_data(FakeResolver(), spec)  # type: ignore[arg-type]


def clauses(spec: ViewFilter) -> list[dict[str, Any]]:
    return build(spec)["and"]


def prefs(display: ViewDisplay) -> dict[str, Any]:
    return build_preferences(FakeResolver(), display)  # type: ignore[arg-type]


def test_empty_filter_is_empty_object() -> None:
    # Not {"and": []} — an empty AND is a filter matching nothing in some engines,
    # and Linear's own unfiltered views read back as a bare {}.
    assert build(ViewFilter()) == {}


def test_values_in_one_field_are_ored_not_anded() -> None:
    # The whole point: an issue is never in two states at once, so `in`, not a
    # clause per state. Getting this wrong yields a view that is always empty.
    assert clauses(ViewFilter(state=["Todo", "In Progress"])) == [
        {"state": {"id": {"in": ["state-todo", "state-in-progress"]}}}
    ]


def test_fields_are_anded_together() -> None:
    got = clauses(ViewFilter(state_type=["started"], priority=["urgent"]))
    assert got == [
        {"state": {"type": {"in": ["started"]}}},
        {"priority": {"in": [1]}},
    ]


def test_priority_names_map_to_linears_numbers() -> None:
    # Linear's scale is inverted from intuition: urgent is 1, low is 4.
    assert clauses(ViewFilter(priority=["urgent", "high", "medium", "low", "none"])) == [
        {"priority": {"in": [1, 2, 3, 4, 0]}}
    ]


def test_labels_use_some_not_every() -> None:
    # `every` would require every label on every issue; a chip list means "any of".
    assert clauses(ViewFilter(labels=["bug", "api"])) == [
        {"labels": {"some": {"id": {"in": ["label-bug", "label-api"]}}}}
    ]


def test_assignee_me_stays_unresolved() -> None:
    resolver = FakeResolver()
    got = build_filter_data(resolver, ViewFilter(assignee="me"))  # type: ignore[arg-type]
    assert got["and"] == [{"assignee": {"isMe": {"eq": True}}}]
    # Pinning an id here would silently turn a shared "My work" view into
    # "whoever ran linear-kit"'s work.
    assert ("user", "me") not in resolver.calls


def test_named_assignee_is_resolved_to_an_id() -> None:
    assert clauses(ViewFilter(assignee="ada@example.com")) == [
        {"assignee": {"id": {"eq": "user-ada@example.com"}}}
    ]


def test_assignee_none_means_unassigned() -> None:
    assert clauses(ViewFilter(assignee="none")) == [{"assignee": {"null": True}}]


def test_creator_none_is_rejected() -> None:
    with pytest.raises(LinearError, match="every issue has a creator"):
        build(ViewFilter(creator="none"))


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("active", {"isActive": {"eq": True}}),
        ("next", {"isNext": {"eq": True}}),
        ("previous", {"isPrevious": {"eq": True}}),
        ("none", {"null": True}),
    ],
)
def test_cycle_uses_booleans_not_ids(ref: str, expected: dict[str, Any]) -> None:
    # Booleans keep the view correct after the cycle rolls over; an id would rot.
    assert clauses(ViewFilter(cycle=ref)) == [{"cycle": expected}]  # type: ignore[arg-type]


def test_project_none_means_no_project() -> None:
    assert clauses(ViewFilter(project="none")) == [{"project": {"null": True}}]


def test_due_date_bounds_are_inclusive() -> None:
    from linear_kit.models import DateFilter

    got = clauses(ViewFilter(due_date=DateFilter(after="2026-01-01", before="2026-03-01")))
    assert got == [{"dueDate": {"gte": "2026-01-01", "lte": "2026-03-01"}}]


def test_empty_due_date_is_rejected() -> None:
    from linear_kit.models import DateFilter

    with pytest.raises(LinearError, match="due_date"):
        build(ViewFilter(due_date=DateFilter()))


def test_empty_estimate_is_rejected() -> None:
    from linear_kit.models import EstimateFilter

    with pytest.raises(LinearError, match="estimate"):
        build(ViewFilter(estimate=EstimateFilter()))


def test_any_of_nests_alternatives_under_or() -> None:
    got = clauses(
        ViewFilter(
            state_type=["started"],
            any_of=[ViewFilter(priority=["urgent"]), ViewFilter(labels=["bug"])],
        )
    )
    assert got[0] == {"state": {"type": {"in": ["started"]}}}
    assert got[1] == {
        "or": [
            {"and": [{"priority": {"in": [1]}}]},
            {"and": [{"labels": {"some": {"id": {"in": ["label-bug"]}}}}]},
        ]
    }


def test_display_maps_yaml_names_to_linear_keys() -> None:
    got = prefs(ViewDisplay(layout="board", group_by="workflowState", order_by="priority"))
    assert got == {"layout": "board", "issueGrouping": "workflowState", "viewOrdering": "priority"}


def test_unset_display_keys_are_omitted_entirely() -> None:
    # An unset key must stay absent rather than go out as null: null is a value,
    # and writing it would pin Linear's default instead of leaving it alone.
    assert prefs(ViewDisplay(layout="list")) == {"layout": "list"}
    assert prefs(ViewDisplay()) == {}


def test_display_booleans_survive_the_mapping() -> None:
    got = prefs(ViewDisplay(show_sub_issues=False, show_triage=True))
    assert got == {"showSubIssues": False, "showTriageIssues": True}


def test_empty_groups_key_follows_the_layout() -> None:
    # Linear stores one key per layout and reads only its own. Writing the other
    # one is accepted and silently does nothing.
    board = prefs(ViewDisplay(layout="board", show_empty_groups=True, show_empty_sub_groups=True))
    assert board == {
        "layout": "board",
        "showEmptyGroups": True,
        "showEmptySubGroupsBoard": True,
    }

    lst = prefs(ViewDisplay(layout="list", show_empty_groups=True))
    assert lst == {"layout": "list", "showEmptyGroupsList": True}


def test_empty_groups_without_a_layout_is_rejected() -> None:
    # Guessing the layout here would pick a key at random and fail silently.
    with pytest.raises(LinearError, match="explicit `layout`"):
        prefs(ViewDisplay(show_empty_groups=True))


def test_properties_are_exclusive_not_additive() -> None:
    got = prefs(ViewDisplay(properties=["id", "status", "assignee"]))
    assert got["fieldId"] is True
    assert got["fieldStatus"] is True
    assert got["fieldAssignee"] is True
    # Everything modelled but unnamed is switched off, so the list is a complete
    # statement rather than a set of overrides.
    assert got["fieldLabels"] is False
    assert got["fieldProject"] is False
    assert got["fieldDateCreated"] is False


def test_properties_leave_unmodelled_fields_alone() -> None:
    # Turning off pull requests or SLA badges was never asked for; a preset that
    # lists display properties should not silently disable integrations.
    got = prefs(ViewDisplay(properties=["id"]))
    assert "fieldPullRequests" not in got
    assert "fieldSla" not in got
    assert "fieldSentryIssues" not in got


def test_links_maps_to_preview_links_not_link_count() -> None:
    # Two plausible keys exist. The chip is fieldPreviewLinks — confirmed by
    # writing it false and watching the chip go dark. fieldLinkCount is something
    # else and must not be touched.
    on = prefs(ViewDisplay(properties=["links"]))
    assert on["fieldPreviewLinks"] is True
    assert "fieldLinkCount" not in on

    # Omitting it is what makes "everything except links" an explicit false
    # rather than a default someone could flip back.
    off = prefs(ViewDisplay(properties=["id"]))
    assert off["fieldPreviewLinks"] is False


def test_no_properties_touches_no_fields() -> None:
    assert prefs(ViewDisplay(layout="list")) == {"layout": "list"}


@pytest.mark.parametrize("name", ["views-board", "views-lists"])
def test_bundled_presets_name_nothing_a_workspace_invents(name: str) -> None:
    """Labels and projects are per-workspace inventions; a bundled preset naming
    one could only ever apply where it was written.

    State names are the deliberate exception — `views-lists` needs Todo/Pause/In
    Progress specifically — but a missing state fails loudly through the resolver,
    listing what the team actually has, rather than producing a silent empty view.
    """
    from linear_kit.models import load_views_preset

    preset: ViewsPreset = load_views_preset(name)
    assert preset.views
    for view in preset.views:
        assert not view.filter.labels, f"{view.name} filters on a workspace-specific label"
        assert not view.filter.project, f"{view.name} names a workspace-specific project"


def test_board_preset_matches_the_requested_layout() -> None:
    from linear_kit.models import load_views_preset

    board = next(v for v in load_views_preset("views-board").views if v.name == "All Issues")
    assert board.display.layout == "board"
    assert board.display.group_by == "workflowState"   # columns
    assert board.display.sub_group_by == "project"     # rows
    assert board.display.show_completed == "week"
    assert board.display.show_empty_groups is True
    assert board.display.hide_states == ["Done", "Canceled", "Duplicate"]
    # Every property except links, which is not modelled pending observation.
    assert "labels" in board.display.properties
    assert "links" not in [p for p in board.display.properties]


def test_hide_states_requires_grouping_by_state() -> None:
    # Columns are only states when grouping by state; hiding "Done" under a
    # project grouping would name something that is not a column.
    with pytest.raises(LinearError, match="hide_states"):
        build_preferences(
            FakeResolver(),  # type: ignore[arg-type]
            ViewDisplay(layout="board", group_by="priority", hide_states=["Done"]),
        )


class FakeClient:
    """Enough of LinearClient to drive _run_prefs: canned read, recorded write."""

    def __init__(self, stored: dict[str, Any]) -> None:
        self._stored = stored
        self.written: dict[str, Any] | None = None

    def execute(self, _query: str, _vars: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"customView": {"organizationViewPreferences": {"preferences": self._stored}}}

    def mutate(self, _query: str, variables: dict[str, Any], _root: str) -> dict[str, Any]:
        self.written = variables["input"]["preferences"]
        return {"viewPreferences": {"id": "prefs-1"}}


def test_updating_preferences_keeps_settings_the_preset_does_not_name() -> None:
    """viewPreferencesUpdate replaces the object instead of merging into it.

    Sending only the preset's keys was observed to wipe layout, grouping and
    hiddenColumns off a configured view — so a rerun must overlay onto what is
    stored, or it would quietly destroy anything set by hand in the UI.
    """
    client = FakeClient({"showSnoozedItems": True, "columnOrderBoard": ["a", "b"], "layout": "list"})
    _run_prefs(client, "view-1", {"layout": "board"}, existing_id="prefs-1")  # type: ignore[arg-type]

    assert client.written == {
        "showSnoozedItems": True,
        "columnOrderBoard": ["a", "b"],
        "layout": "board",  # the preset wins where the two overlap
    }


def test_unset_stored_preferences_are_not_written_back() -> None:
    # The read is typed and returns every key, most of them null. Writing those
    # back would turn "never set" into a pinned value.
    client = FakeClient({"layout": "board", "showSnoozedItems": None, "hiddenColumns": None})
    _run_prefs(client, "view-1", {"issueGrouping": "priority"}, existing_id="prefs-1")  # type: ignore[arg-type]

    assert client.written == {"layout": "board", "issueGrouping": "priority"}


def test_creating_preferences_does_not_read_first() -> None:
    # Nothing to merge with on a brand new view.
    client = FakeClient({})
    _run_prefs(client, "view-1", {"layout": "board"}, existing_id=None)  # type: ignore[arg-type]
    assert client.written == {"layout": "board"}


def test_hide_states_resolves_names_to_ids() -> None:
    got = build_preferences(
        FakeResolver(),  # type: ignore[arg-type]
        ViewDisplay(layout="board", group_by="workflowState", hide_states=["Done", "Canceled"]),
    )
    assert got["hiddenColumns"] == ["state-done", "state-canceled"]
