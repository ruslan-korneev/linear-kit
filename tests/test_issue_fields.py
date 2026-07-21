"""Tests for the CLI options -> Issue{Create,Update}Input mapping.

Worth testing offline for the same reason the view filter is: the API accepts
every payload built here, so a mistake is quiet. `labelIds` is the sharp one —
it replaces the issue's labels rather than adding to them, so sending it when
the user never mentioned a label would silently strip the issue bare, and the
mutation would report success.
"""

from __future__ import annotations

from typing import Any

import pytest

from linear_kit.client import LinearError
from linear_kit.resources.issue import IssueFields, _build_input


class FakeResolver:
    """Stands in for Resolver, returning predictable ids and recording lookups."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def state_id(self, name: str) -> str:
        self.calls.append(("state", name))
        return f"state-{name.lower().replace(' ', '-')}"

    def label_id(self, name: str) -> str:
        self.calls.append(("label", name))
        return f"label-{name.lower()}"

    def label_ids(self, names: list[str]) -> list[str]:
        return [self.label_id(name) for name in names]

    def user_id(self, ref: str) -> str:
        self.calls.append(("user", ref))
        return f"user-{ref.lower()}"

    def project_id(self, name: str) -> str:
        self.calls.append(("project", name))
        return f"project-{name.lower()}"

    def milestone_id(self, project: str, name: str) -> str:
        self.calls.append(("milestone", f"{project}/{name}"))
        return f"milestone-{name.lower()}"


def build(fields: IssueFields, current_labels: list[str] | None = None) -> dict[str, Any]:
    # client is only touched to resolve --parent, which no test here exercises.
    return _build_input(None, FakeResolver(), fields, current_labels=current_labels)  # type: ignore[arg-type]


def test_unmentioned_fields_are_omitted() -> None:
    # On update every absent key means "keep what is there", so an option nobody
    # passed must not reach the payload at all.
    assert build(IssueFields()) == {}


def test_title_and_description_pass_through() -> None:
    got = build(IssueFields(title="Fix auth", description="body"))
    assert got == {"title": "Fix auth", "description": "body"}


def test_priority_names_map_to_linears_numbers() -> None:
    # Linear's scale is inverted from intuition: urgent is 1, low is 4.
    assert build(IssueFields(priority="urgent"))["priority"] == 1
    assert build(IssueFields(priority="low"))["priority"] == 4
    assert build(IssueFields(priority="none"))["priority"] == 0


def test_priority_is_case_insensitive() -> None:
    assert build(IssueFields(priority="Urgent"))["priority"] == 1


def test_unknown_priority_lists_the_valid_names() -> None:
    with pytest.raises(LinearError, match="none, urgent, high, medium, low"):
        build(IssueFields(priority="critical"))


def test_assignee_me_is_resolved_to_an_id() -> None:
    # Unlike a view filter, where `me` stays unresolved so it means whoever is
    # looking, an assignment names one person at the moment it is made.
    assert build(IssueFields(assignee="me"))["assigneeId"] == "user-me"


def test_assignee_none_sends_an_explicit_null() -> None:
    # Unassigning has to send null: omitting the key means "keep the assignee",
    # which is the opposite request.
    got = build(IssueFields(assignee="none"))
    assert got == {"assigneeId": None}
    assert "assigneeId" in got


def test_project_none_detaches() -> None:
    assert build(IssueFields(project="none")) == {"projectId": None}


def test_milestone_without_a_project_is_rejected() -> None:
    # A milestone is scoped to a project, so there is nothing to look it up in.
    with pytest.raises(LinearError, match="needs `--project`"):
        build(IssueFields(milestone="Beta"))


def test_milestone_is_resolved_within_its_project() -> None:
    got = build(IssueFields(project="Payments", milestone="Beta"))
    assert got == {"projectId": "project-payments", "projectMilestoneId": "milestone-beta"}


def test_no_label_option_sends_no_label_ids() -> None:
    """The one that matters: labelIds replaces, so it must stay out of the payload.

    Sending `labelIds: []` because nobody passed --label would strip every label
    off the issue, and issueUpdate would report success.
    """
    got = build(IssueFields(state="Done", priority="low"), current_labels=["Bug"])
    assert "labelIds" not in got


def test_label_states_the_complete_set() -> None:
    got = build(IssueFields(labels=["Feature"]), current_labels=["Bug"])
    assert got["labelIds"] == ["label-feature"]


def test_add_label_keeps_the_labels_already_there() -> None:
    # Without folding in the current labels, an --add-label would replace rather
    # than add — the exact trap labelIds sets.
    got = build(IssueFields(add_labels=["Feature"]), current_labels=["Bug"])
    assert got["labelIds"] == ["label-bug", "label-feature"]


def test_add_label_is_idempotent() -> None:
    got = build(IssueFields(add_labels=["Bug"]), current_labels=["Bug"])
    assert got["labelIds"] == ["label-bug"]


def test_add_label_matches_existing_labels_case_insensitively() -> None:
    got = build(IssueFields(add_labels=["bug"]), current_labels=["Bug"])
    assert got["labelIds"] == ["label-bug"]


def test_remove_label_drops_only_what_it_names() -> None:
    got = build(IssueFields(remove_labels=["Bug"]), current_labels=["Bug", "Feature"])
    assert got["labelIds"] == ["label-feature"]


def test_remove_label_validates_the_name() -> None:
    # A typo must fail loudly rather than remove nothing and report success.
    resolver = FakeResolver()
    _build_input(
        None,  # type: ignore[arg-type]
        resolver,
        IssueFields(remove_labels=["Bug"]),
        current_labels=["Bug", "Feature"],
    )
    assert ("label", "Bug") in resolver.calls


def test_add_and_remove_combine() -> None:
    got = build(
        IssueFields(add_labels=["Improvement"], remove_labels=["Bug"]),
        current_labels=["Bug", "Feature"],
    )
    assert got["labelIds"] == ["label-feature", "label-improvement"]


def test_label_cannot_be_mixed_with_add_or_remove() -> None:
    # One states the set outright, the other edits it — combining them makes the
    # result depend on which is applied first.
    with pytest.raises(LinearError, match="complete label list"):
        build(IssueFields(labels=["Bug"], add_labels=["Feature"]))
    with pytest.raises(LinearError, match="complete label list"):
        build(IssueFields(labels=["Bug"], remove_labels=["Feature"]))


def test_empty_label_list_clears_the_labels() -> None:
    # A library-level contract, not a CLI one: the CLI maps an absent --label to
    # None, and typer never yields an empty list, so [] can only come from a
    # caller stating "no labels" outright — and that must clear, not keep.
    got = build(IssueFields(labels=[]), current_labels=["Bug"])
    assert got["labelIds"] == []


def test_assignee_none_is_case_insensitive() -> None:
    # `--assignee None` is the sentinel, not a search for a user named "None".
    assert build(IssueFields(assignee="None")) == {"assigneeId": None}


def test_project_none_is_case_insensitive() -> None:
    assert build(IssueFields(project="NONE")) == {"projectId": None}


def test_state_and_dates_pass_through() -> None:
    got = build(IssueFields(state="In Review", due_date="2026-08-01", estimate=3))
    assert got == {"stateId": "state-in-review", "dueDate": "2026-08-01", "estimate": 3}
