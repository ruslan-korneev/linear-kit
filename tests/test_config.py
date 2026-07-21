"""Tests for workspace profiles — mostly that there is no default.

A default workspace is the one setting that makes every other guard pointless:
whatever the binding says, a command that quietly falls back still lands
somewhere real and reports success.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from linear_kit import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    return tmp_path / "config.toml"


def test_resolve_needs_a_name_even_with_one_workspace(isolated_config: Path) -> None:
    """"The only one configured" is a default that appears the moment a second is added.

    It would work right up until the day it silently picked wrong.
    """
    config.save_key("my-workspace", "lin_api_1")
    with pytest.raises(config.ConfigError, match="No workspace given"):
        config.resolve(None)


def test_resolve_lists_what_is_configured_when_nothing_is_named(isolated_config: Path) -> None:
    config.save_key("my-workspace", "lin_api_1")
    config.save_key("other", "lin_api_2")
    with pytest.raises(config.ConfigError, match="Configured: my-workspace, other"):
        config.resolve(None)


def test_resolve_returns_the_named_key(isolated_config: Path) -> None:
    config.save_key("my-workspace", "lin_api_1")
    assert config.resolve("my-workspace") == ("my-workspace", "lin_api_1")


def test_unknown_workspace_lists_the_known_ones(isolated_config: Path) -> None:
    config.save_key("my-workspace", "lin_api_1")
    with pytest.raises(config.ConfigError, match="Configured: my-workspace"):
        config.resolve("typo")


def test_env_var_wins_over_the_file(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config.save_key("my-workspace", "lin_api_file")
    monkeypatch.setenv("LINEAR_API_KEY_MY_WORKSPACE", "lin_api_env")
    assert config.resolve("my-workspace") == ("my-workspace", "lin_api_env")


def test_saving_a_key_never_writes_a_default(isolated_config: Path) -> None:
    config.save_key("my-workspace", "lin_api_1")
    assert "default_workspace" not in isolated_config.read_text()


def test_a_leftover_default_is_rejected_not_ignored(isolated_config: Path) -> None:
    """A config stating a preference the tool ignores is a lie about where work goes.

    Silently dropping the line would leave someone believing they had pinned a
    default, which is the failure this removal was meant to end.
    """
    isolated_config.write_text(
        'default_workspace = "my-workspace"\n\n[workspace.my-workspace]\napi_key = "lin_api_1"\n'
    )
    with pytest.raises(config.ConfigError, match="no longer honours"):
        config.resolve("my-workspace")


def test_saving_over_a_leftover_default_clears_it(isolated_config: Path) -> None:
    # The escape hatch: `auth add` rewrites the file without the dead key, so the
    # rejection above is a one-time fix rather than a wall.
    isolated_config.write_text(
        'default_workspace = "my-workspace"\n\n[workspace.my-workspace]\napi_key = "lin_api_1"\n'
    )
    config.save_key("other", "lin_api_2")
    assert "default_workspace" not in isolated_config.read_text()
    assert config.resolve("my-workspace") == ("my-workspace", "lin_api_1")


def test_removing_a_key_keeps_the_others(isolated_config: Path) -> None:
    config.save_key("my-workspace", "lin_api_1")
    config.save_key("other", "lin_api_2")
    config.remove_key("other")
    assert config.list_workspaces() == ["my-workspace"]
    assert config.resolve("my-workspace") == ("my-workspace", "lin_api_1")


def test_removing_the_last_key_leaves_an_empty_config(isolated_config: Path) -> None:
    config.save_key("my-workspace", "lin_api_1")
    config.remove_key("my-workspace")
    assert config.list_workspaces() == []
