"""Tests for the repo -> workspace/team binding.

This is a safety mechanism, so the tests are mostly about what it *refuses*.
The failure it exists to prevent is silent: a task filed from the wrong repo
lands in a real workspace and reports success, so there is nothing to notice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from linear_kit.binding import BindingError, find, require


def write(directory: Path, text: str) -> Path:
    path = directory / ".linear-kit.toml"
    path.write_text(text)
    return path


def test_no_file_anywhere_is_not_an_error(tmp_path: Path) -> None:
    # Absent is a fact for the caller to act on, not a failure in itself —
    # reads fall back to the default workspace, writes refuse.
    assert find(tmp_path) is None


def test_binding_is_read_from_the_directory_itself(tmp_path: Path) -> None:
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    found = find(tmp_path)
    assert found is not None
    assert (found.workspace, found.team, found.project) == ("my-workspace", "PAY", None)


def test_binding_is_found_from_a_subdirectory(tmp_path: Path) -> None:
    # The file belongs at the repo root, but commands run from wherever you are.
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    deep = tmp_path / "src" / "widgets"
    deep.mkdir(parents=True)
    found = find(deep)
    assert found is not None
    assert found.team == "PAY"


def test_nearest_binding_wins(tmp_path: Path) -> None:
    write(tmp_path, 'workspace = "outer"\nteam = "OUT"\n')
    inner = tmp_path / "vendored"
    inner.mkdir()
    write(inner, 'workspace = "inner"\nteam = "IN"\n')
    found = find(inner)
    assert found is not None
    assert found.workspace == "inner"


def test_an_inner_file_overrides_only_the_keys_it_names(tmp_path: Path) -> None:
    """The monorepo case: one root binding, a project per service.

    Without the cascade the inner file would have to restate the workspace and
    team, and every one of those copies is a chance to drift from the root.
    """
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    service = tmp_path / "services" / "billing"
    service.mkdir(parents=True)
    write(service, 'project = "Billing"\n')

    found = find(service)
    assert found is not None
    assert (found.workspace, found.team, found.project) == ("my-workspace", "PAY", "Billing")


def test_an_inner_file_alone_is_not_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A project with no workspace above it binds nothing; the error names the
    # cascade rather than blaming the one file that is legitimately partial.
    service = tmp_path / "services" / "billing"
    service.mkdir(parents=True)
    write(service, 'project = "Billing"\n')
    monkeypatch.chdir(service)
    with pytest.raises(BindingError, match="missing 'workspace' and 'team'"):
        require(None, None)


def test_explicit_flags_complete_a_partial_cascade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file naming only a project is a gap, not a verdict: flags that fill the
    # gap must work, or the flags cannot rescue exactly the situation they exist
    # for. The project still applies — nothing was contradicted.
    service = tmp_path / "services" / "billing"
    service.mkdir(parents=True)
    write(service, 'project = "Billing"\n')
    monkeypatch.chdir(service)

    bound = require("my-workspace", "PAY")
    assert (bound.workspace, bound.team, bound.project) == ("my-workspace", "PAY", "Billing")
    # Filling a gap is not beating a file, so no override note.
    assert bound.overrides == []


def test_the_cascade_merges_more_than_two_levels(tmp_path: Path) -> None:
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\nproject = "Root"\n')
    mid = tmp_path / "services"
    mid.mkdir()
    write(mid, 'team = "OPS"\n')
    leaf = mid / "billing"
    leaf.mkdir()
    write(leaf, 'project = "Billing"\n')

    found = find(leaf)
    assert found is not None
    assert (found.workspace, found.team, found.project) == ("my-workspace", "OPS", "Billing")


def test_an_empty_project_clears_an_inherited_one(tmp_path: Path) -> None:
    # Otherwise a subdirectory could never opt out of the root's project, since
    # an absent key means "inherit".
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\nproject = "Checkout v2"\n')
    loose = tmp_path / "spikes"
    loose.mkdir()
    write(loose, 'project = ""\n')

    found = find(loose)
    assert found is not None
    assert found.project is None
    assert found.team == "PAY"


def test_sources_record_the_whole_cascade_nearest_last(tmp_path: Path) -> None:
    # Printed on every plan: an unexpected target should be visible before the
    # mutation, not inferred afterwards from where the issue turned up. With a
    # cascade, naming one file would hide where the other keys came from.
    root = write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    service = tmp_path / "services"
    service.mkdir()
    inner = write(service, 'project = "Billing"\n')

    found = find(service)
    assert found is not None and found.sources == [root, inner]


def test_optional_project_is_carried(tmp_path: Path) -> None:
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\nproject = "Checkout v2"\n')
    found = find(tmp_path)
    assert found is not None and found.project == "Checkout v2"


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    # Ignoring a typo would leave the binding pointing somewhere other than the
    # file appears to say — exactly the quiet wrongness this guards against.
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\nporject = "oops"\n')
    with pytest.raises(BindingError, match="unknown keys: porject"):
        find(tmp_path)


def test_an_unknown_key_is_caught_wherever_it_sits_in_the_cascade(tmp_path: Path) -> None:
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    service = tmp_path / "services"
    service.mkdir()
    write(service, 'proejct = "Billing"\n')
    with pytest.raises(BindingError, match="unknown keys: proejct"):
        find(service)


def test_missing_team_is_rejected_when_a_team_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, 'workspace = "my-workspace"\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(BindingError, match="missing 'team'"):
        require(None, None)


def test_a_workspace_only_cascade_is_enough_when_no_team_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `auth verify` and friends need only a workspace; a file naming one must
    # not be rejected over a team the command was never going to use.
    write(tmp_path, 'workspace = "my-workspace"\n')
    monkeypatch.chdir(tmp_path)
    bound = require(None, None, need_team=False)
    assert bound.workspace == "my-workspace"


def test_malformed_toml_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "workspace = ")
    with pytest.raises(BindingError, match="not valid TOML"):
        find(tmp_path)


def test_explicit_flags_need_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Naming both is saying where you mean; the file is a repo default, not a lock.
    monkeypatch.chdir(tmp_path)
    bound = require("other-workspace", "OPS")
    assert (bound.workspace, bound.team) == ("other-workspace", "OPS")
    assert bound.sources == []
    assert bound.overrides == []


def test_a_flag_beating_the_binding_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The flags are an escape hatch for people, not a silent way around the binding.

    Reading the files only when a flag was missing is what made an override
    invisible: no file read, no sources, no note, no trace of having gone
    somewhere other than the repo says.
    """
    root = write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    monkeypatch.chdir(tmp_path)

    bound = require("other-workspace", "OPS")
    assert (bound.workspace, bound.team) == ("other-workspace", "OPS")
    assert bound.sources == [root]  # read even though both flags were given
    assert bound.overrides == [
        f"OVERRIDE: --workspace other-workspace beats 'my-workspace' from {root}",
        f"OVERRIDE: --team OPS beats 'PAY' from {root}",
    ]


def test_a_flag_agreeing_with_the_binding_is_not_an_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Restating what the file says is not a contradiction, and crying override
    # every time would train people to skip the notes that matter.
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    monkeypatch.chdir(tmp_path)
    assert require("my-workspace", "pay").overrides == []  # case-insensitive


def test_an_override_names_the_file_that_set_the_key_not_the_nearest_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In a cascade the nearest file often does not mention the key being beaten;
    # naming it would point at a file that has nothing to do with the conflict.
    root = write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    service = tmp_path / "services"
    service.mkdir()
    write(service, 'project = "Billing"\n')
    monkeypatch.chdir(service)

    bound = require(None, "OPS")
    assert bound.overrides == [f"OVERRIDE: --team OPS beats 'PAY' from {root}"]


def test_flags_override_the_file_one_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\n')
    monkeypatch.chdir(tmp_path)

    assert require(None, "OPS").team == "OPS"
    assert require(None, "OPS").workspace == "my-workspace"
    assert require("other-workspace", None).team == "PAY"


def test_no_target_anywhere_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the whole module.

    There is nothing to fall back to — the default workspace was removed for
    exactly this reason. Guessing here would act on whatever happened to be
    configured, which succeeds, so nobody finds out.
    """
    monkeypatch.chdir(tmp_path)
    with pytest.raises(BindingError, match="no default workspace"):
        require(None, None)


def test_a_workspace_alone_still_refuses_without_a_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Half a target is not a target: the team would still come from nowhere.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(BindingError):
        require("my-workspace", None)


def test_a_workspace_alone_is_enough_when_no_team_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `issue update PAY-12` names the issue, and the identifier carries the team.
    monkeypatch.chdir(tmp_path)
    bound = require("my-workspace", None, need_team=False)
    assert bound.workspace == "my-workspace"


def test_a_workspace_override_drops_the_bound_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound project names something in the bound workspace, nowhere else.

    Carried into another workspace it would resolve whatever shares the name
    there — common names like "Backlog" exist everywhere — and the issue would
    silently join a stranger's project.
    """
    root = write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\nproject = "Checkout v2"\n')
    monkeypatch.chdir(tmp_path)

    bound = require("other-workspace", "OPS")
    assert bound.project is None
    assert any("Checkout v2" in note and str(root) in note for note in bound.overrides)


def test_a_workspace_flag_matching_the_binding_keeps_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Restating the bound workspace changes nothing, so the project stays —
    # including across a team override, since projects are workspace-level.
    write(tmp_path, 'workspace = "my-workspace"\nteam = "PAY"\nproject = "Checkout v2"\n')
    monkeypatch.chdir(tmp_path)

    assert require("My-Workspace", None).project == "Checkout v2"
    assert require(None, "OPS").project == "Checkout v2"
