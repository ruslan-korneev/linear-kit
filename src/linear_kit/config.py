"""Workspace profiles stored in ~/.config/linear-kit/config.toml.

There is deliberately **no default workspace**. Every command takes its target
from `--workspace` or from the repo's `.linear-kit.toml` (see `binding.py`), and
refuses to run without one. A default is silent, and a silent default means
acting on the wrong workspace succeeds — the mutation lands, correctly, in a
real place nobody meant.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(
    os.environ.get("LINEAR_KIT_CONFIG_DIR", Path.home() / ".config" / "linear-kit")
)
CONFIG_PATH = CONFIG_DIR / "config.toml"


class ConfigError(RuntimeError):
    pass


def _load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def list_workspaces() -> list[str]:
    return sorted(_load().get("workspace", {}))


def _check_no_default(data: dict[str, Any]) -> None:
    """Reject a `default_workspace` line left over from when there was one.

    Ignoring it would leave the file stating a preference the tool no longer
    honours — a config that lies about where commands go is the same failure as
    a default, one step removed.
    """
    if "default_workspace" in data:
        raise ConfigError(
            f"{CONFIG_PATH} sets `default_workspace`, which linear-kit no longer honours: "
            "a silent default is how work lands in the wrong workspace. Delete that line. "
            "Targets now come from --workspace or a .linear-kit.toml in the repo."
        )


def resolve(name: str | None) -> tuple[str, str]:
    """Return (workspace_name, api_key). Env var wins over the config file.

    `name` is required. There is no fallback: not the configured default (gone),
    and not "the only workspace configured" (which silently becomes a default the
    moment a second one is added).
    """
    data = _load()
    _check_no_default(data)
    if not name:
        known = ", ".join(sorted(data.get("workspace", {}))) or "none"
        raise ConfigError(
            f"No workspace given. Pass --workspace or add a .linear-kit.toml to the repo. "
            f"Configured: {known}."
        )

    env_key = os.environ.get(f"LINEAR_API_KEY_{name.upper().replace('-', '_')}")
    if env_key:
        return name, env_key

    workspaces = data.get("workspace", {})
    if name not in workspaces:
        known = ", ".join(sorted(workspaces)) or "none"
        raise ConfigError(f"Unknown workspace {name!r}. Configured: {known}.")

    api_key = workspaces[name].get("api_key")
    if not api_key:
        raise ConfigError(f"Workspace {name!r} has no api_key.")
    return name, api_key


def save_key(name: str, api_key: str) -> None:
    """Rewrite config.toml with the key added or replaced. Keeps perms at 0600."""
    data = _load()
    data.pop("default_workspace", None)  # drop the dead key rather than carry it forward
    data.setdefault("workspace", {})[name] = {"api_key": api_key}
    _write(data)


def remove_key(name: str) -> None:
    data = _load()
    if name not in data.get("workspace", {}):
        raise ConfigError(f"Unknown workspace {name!r}.")
    data.pop("default_workspace", None)
    del data["workspace"][name]
    _write(data)


def _write(data: dict[str, Any]) -> None:
    lines: list[str] = []
    for ws, cfg in sorted(data.get("workspace", {}).items()):
        lines += [f"[workspace.{ws}]", f'api_key = "{cfg["api_key"]}"', ""]

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    CONFIG_PATH.write_text("\n".join(lines))
    CONFIG_PATH.chmod(0o600)
