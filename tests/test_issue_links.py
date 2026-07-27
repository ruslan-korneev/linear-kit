"""Tests for planning links between issues.

What matters here is direction and idempotence, and both fail quietly. Linear
stores "A blocks B" and "B blocks A" as the same relation type, told apart only
by which side of the pair each issue sits on — so a swapped payload creates a
real, wrong link and the mutation reports success. And since `blocked by` is
read off `inverseRelations` rather than `relations`, a skip check looking at the
wrong side would re-send links that already exist.

Deliberately not covered: whether Linear itself accepts these payloads. That was
established against the live API (see README's "Linear API notes"); these tests
pin the mapping from command-line options onto them.
"""

from __future__ import annotations

from typing import Any

import pytest

from linear_kit.client import LinearError
from linear_kit.resources.issue import (
    RELATION_KINDS,
    ExistingLinks,
    IssueLinks,
    _existing_links,
    _plan_links,
    plan_issue_link,
)
from linear_kit.resources.plan import Plan


class FakeClient:
    """Answers issue lookups from a table and records the mutations it is sent."""

    def __init__(self, issues: dict[str, dict[str, Any]]) -> None:
        self.issues = issues
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def execute(self, _query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        ref = (variables or {})["id"]
        issue = self.issues.get(ref)
        if issue is None:
            raise LinearError("Could not find referenced Issue [INPUT_ERROR]")
        return {"issue": issue}

    def mutate(self, _query: str, variables: dict[str, Any], root: str) -> dict[str, Any]:
        self.sent.append((root, variables))
        if root == "issueRelationCreate":
            return {
                "issueRelation": {
                    "type": variables["input"]["type"],
                    "issue": {"identifier": "SRC"},
                    "relatedIssue": {"identifier": "DST"},
                }
            }
        return {"issue": {"identifier": "PAY-2", "url": "https://example.invalid/PAY-2"}}


def issue(identifier: str, **extra: Any) -> dict[str, Any]:
    return {"id": f"id-{identifier}", "identifier": identifier, "title": identifier, **extra}


def client_with(*identifiers: str, **issues: dict[str, Any]) -> FakeClient:
    table = {name: issue(name) for name in identifiers}
    table.update({k.replace("_", "-"): v for k, v in issues.items()})
    return FakeClient(table)


def run_steps(plan: Plan, client: FakeClient) -> list[dict[str, Any]]:
    """Execute the planned steps and return the inputs they sent."""
    for step in plan.steps:
        step.run(client)  # type: ignore[arg-type]
    return [variables for _root, variables in client.sent]


def plan_links(
    links: IssueLinks, existing: ExistingLinks | None = None, *targets: str
) -> tuple[Plan, FakeClient]:
    client = client_with(*targets)
    plan = Plan(title="test")
    _plan_links(
        client,  # type: ignore[arg-type]
        plan,
        source_id="id-PAY-1",
        source_ref="PAY-1",
        links=links,
        existing=existing,
    )
    return plan, client


def test_blocks_sends_the_source_as_the_blocking_issue() -> None:
    plan, client = plan_links(IssueLinks(blocks=["PAY-2"]), None, "PAY-2")
    assert run_steps(plan, client) == [
        {
            "input": {
                "id": client.sent[0][1]["input"]["id"],
                "type": "blocks",
                "issueId": "id-PAY-1",
                "relatedIssueId": "id-PAY-2",
            }
        }
    ]


def test_blocked_by_swaps_the_two_sides() -> None:
    # The same relation type as --blocks, and the swap is the entire difference.
    # Sending it unswapped would record the opposite of what was asked, and
    # Linear would report success.
    plan, client = plan_links(IssueLinks(blocked_by=["PAY-2"]), None, "PAY-2")
    sent = run_steps(plan, client)[0]["input"]
    assert (sent["type"], sent["issueId"], sent["relatedIssueId"]) == (
        "blocks", "id-PAY-2", "id-PAY-1",
    )


def test_duplicate_of_marks_the_named_issue_as_the_duplicate() -> None:
    plan, client = plan_links(IssueLinks(duplicate_of=["PAY-2"]), None, "PAY-2")
    sent = run_steps(plan, client)[0]["input"]
    assert (sent["type"], sent["issueId"]) == ("duplicate", "id-PAY-1")


def test_duplicate_of_warns_that_linear_moves_the_state() -> None:
    # Confirmed live: a Backlog issue marked duplicate came back in Duplicate.
    plan, _client = plan_links(IssueLinks(duplicate_of=["PAY-2"]), None, "PAY-2")
    assert any("Duplicate state" in note for note in plan.notes)


def test_an_existing_link_is_skipped_and_reported() -> None:
    existing = ExistingLinks(outgoing=frozenset({("blocks", "id-PAY-2")}))
    plan, _client = plan_links(IssueLinks(blocks=["PAY-2"]), existing, "PAY-2")
    assert plan.steps == []
    assert plan.notes == ["PAY-1 already blocks PAY-2 — skipped"]


def test_blocked_by_checks_the_inverse_side_for_an_existing_link() -> None:
    # "PAY-2 blocks PAY-1" is stored on PAY-1 as an inverse relation. Checking
    # `outgoing` instead would re-send it on every run.
    existing = ExistingLinks(incoming=frozenset({("blocks", "id-PAY-2")}))
    plan, _client = plan_links(IssueLinks(blocked_by=["PAY-2"]), existing, "PAY-2")
    assert plan.steps == []


def test_related_counts_as_present_whichever_way_round_it_is_stored() -> None:
    # Confirmed live: creating A→B related and then B→A related leaves one
    # relation, direction rewritten — so both sides mean the same link.
    existing = ExistingLinks(incoming=frozenset({("related", "id-PAY-2")}))
    plan, _client = plan_links(IssueLinks(related=["PAY-2"]), existing, "PAY-2")
    assert plan.steps == []


def test_the_opposite_block_is_planned_but_flagged() -> None:
    # Linear accepts a mutual block, so this is a real state — worth saying out
    # loud, since it is usually a mistyped direction rather than a request.
    existing = ExistingLinks(incoming=frozenset({("blocks", "id-PAY-2")}))
    plan, _client = plan_links(IssueLinks(blocks=["PAY-2"]), existing, "PAY-2")
    assert len(plan.steps) == 1
    assert any("opposite direction" in note for note in plan.notes)


def test_linking_an_issue_to_itself_is_refused_while_planning() -> None:
    client = FakeClient({"PAY-1": issue("PAY-1")})
    with pytest.raises(LinearError, match="cannot be linked to itself"):
        _plan_links(
            client,  # type: ignore[arg-type]
            Plan(title="test"),
            source_id="id-PAY-1",
            source_ref="PAY-1",
            links=IssueLinks(blocks=["PAY-1"]),
        )


def test_an_unknown_issue_fails_before_any_step_is_planned() -> None:
    plan = Plan(title="test")
    client = client_with("PAY-2")
    with pytest.raises(LinearError, match="No issue 'PAY-999'"):
        _plan_links(
            client,  # type: ignore[arg-type]
            plan,
            source_id="id-PAY-1",
            source_ref="PAY-1",
            links=IssueLinks(blocks=["PAY-2"], related=["PAY-999"]),
        )


def test_a_child_is_reparented_by_updating_the_child() -> None:
    # parentId lives on the sub-issue, so --child writes to the other issue.
    plan, client = plan_links(IssueLinks(children=["PAY-2"]), None, "PAY-2")
    run_steps(plan, client)
    assert client.sent == [("issueUpdate", {"id": "id-PAY-2", "input": {"parentId": "id-PAY-1"}})]


def test_an_existing_child_is_skipped() -> None:
    existing = ExistingLinks(children=frozenset({"id-PAY-2"}))
    plan, _client = plan_links(IssueLinks(children=["PAY-2"]), existing, "PAY-2")
    assert plan.steps == []
    assert plan.notes == ["PAY-2 is already a sub-issue of PAY-1 — skipped"]


def test_existing_links_are_indexed_by_side() -> None:
    indexed = _existing_links(
        {
            "parent": {"id": "id-PAY-0"},
            "children": {"nodes": [{"id": "id-PAY-3"}]},
            "relations": {"nodes": [{"type": "blocks", "relatedIssue": {"id": "id-PAY-2"}}]},
            "inverseRelations": {"nodes": [{"type": "related", "issue": {"id": "id-PAY-4"}}]},
        }
    )
    assert indexed == ExistingLinks(
        outgoing=frozenset({("blocks", "id-PAY-2")}),
        incoming=frozenset({("related", "id-PAY-4")}),
        children=frozenset({"id-PAY-3"}),
        parent="id-PAY-0",
    )


def test_an_issue_with_no_links_indexes_empty() -> None:
    assert _existing_links({"parent": None}) == ExistingLinks()


def test_every_relation_kind_is_reachable_from_the_options() -> None:
    # A kind nobody can name is a kind that does not exist; this catches a flag
    # added to RELATION_KINDS but never wired into IssueLinks.
    links = IssueLinks(
        blocks=["a"], blocked_by=["b"], related=["c"], duplicate_of=["d"]
    )
    assert {kind.flag for kind, _ref in links.relations()} == {
        kind.flag for kind in RELATION_KINDS.values()
    }


def test_link_with_nothing_to_do_lists_the_options() -> None:
    client = client_with("PAY-1")
    with pytest.raises(LinearError, match="--blocks"):
        plan_issue_link(client, "PAY-1", links=IssueLinks())  # type: ignore[arg-type]


def test_link_plans_a_parent_change_on_the_issue_itself() -> None:
    client = FakeClient(
        {
            "PAY-1": issue("PAY-1", parent=None, children={"nodes": []},
                           relations={"nodes": []}, inverseRelations={"nodes": []}),
            "PAY-9": issue("PAY-9"),
        }
    )
    plan = plan_issue_link(client, "PAY-1", links=IssueLinks(), parent="PAY-9")  # type: ignore[arg-type]
    run_steps(plan, client)
    assert client.sent == [("issueUpdate", {"id": "id-PAY-1", "input": {"parentId": "id-PAY-9"}})]


def test_link_skips_a_parent_the_issue_already_has() -> None:
    client = FakeClient(
        {
            "PAY-1": issue("PAY-1", parent={"id": "id-PAY-9"}, children={"nodes": []},
                           relations={"nodes": []}, inverseRelations={"nodes": []}),
            "PAY-9": issue("PAY-9"),
        }
    )
    plan = plan_issue_link(client, "PAY-1", links=IssueLinks(), parent="PAY-9")  # type: ignore[arg-type]
    assert plan.steps == []
    assert plan.notes == ["PAY-1 is already a sub-issue of PAY-9 — skipped"]
