"""Which workspace and team the directory you are standing in belongs to.

Provisioning commands name their target outright — you do not run `team create`
by accident. Issue commands are the opposite: they are run constantly, from
whatever repo is open, and `--workspace` has a default. That default is the
whole problem. A default is silent, and a silent default means a task filed
from the wrong repo lands in a real workspace, correctly, with no error.

So issue commands do not fall back to the default workspace. They read
`.linear-kit.toml` from the working directory upward:

    workspace = "my-workspace"
    team = "PAY"
    project = "Checkout v2"   # optional

and refuse to run without one, rather than guess. Explicit `--workspace` /
`--team` still win — the file is a default for the repo, not a lock on it.

Files **cascade**. Every `.linear-kit.toml` between the working directory and
the filesystem root contributes, outermost first, and each overrides only the
keys it names. A monorepo binds workspace and team once at its root, and a
subdirectory adds a line for its own project:

    repo/.linear-kit.toml                   workspace = "my-workspace", team = "PAY"
    repo/services/billing/.linear-kit.toml  project = "Billing"

Standing in `services/billing` then means workspace and team from the root, with
`project = "Billing"`. Required keys are checked against the merged result rather
than per file, which is what lets the inner file be one line. `project = ""`
clears an inherited project instead of inheriting it.

The files are committed, so the binding travels with the repo and is visible in a
diff. A central path -> workspace map would be invisible from inside the repo
and would rot the first time a directory is renamed.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BINDING_FILE = ".linear-kit.toml"
KEYS = ("workspace", "team", "project")


class BindingError(RuntimeError):
    pass


@dataclass
class Binding:
    workspace: str
    team: str
    project: str | None = None
    #: Every file that contributed, outermost first. A cascade means "which file
    #: bound this" can have more than one answer, and all of them matter.
    sources: list[Path] = field(default_factory=list)
    #: Which file won each key. In a cascade the nearest file is not necessarily
    #: the one that set the key being discussed, so an error or an override note
    #: has to name the file that actually did.
    origins: dict[str, Path] = field(default_factory=dict)
    #: Where a flag contradicted the files, phrased for the plan. A flag beating
    #: the binding is legitimate; doing it invisibly is not.
    overrides: list[str] = field(default_factory=list)


def find(start: Path | None = None) -> Binding | None:
    """Merge the cascade of binding files at and above `start`. None if there are none.

    Upward, so a command run from a subdirectory still finds the workspace and
    team at the repo root.

    A missing key is left empty rather than rejected here: whether the merge is
    complete depends on which flags the command was given, and only `require`
    sees those. Rejecting a partial cascade at read time is what made complete
    `-w`/`-t` flags unable to rescue one.
    """
    here = (start or Path.cwd()).resolve()
    chain = [d / BINDING_FILE for d in (here, *here.parents) if (d / BINDING_FILE).exists()]
    if not chain:
        return None
    # Walking up yields nearest first; applying them needs the reverse, so that
    # the nearest file is written last and wins.
    chain.reverse()

    merged: dict[str, str] = {}
    origins: dict[str, Path] = {}
    for path in chain:
        for key, value in _read(path).items():
            merged[key] = value
            origins[key] = path

    return Binding(
        workspace=merged.get("workspace") or "",
        team=merged.get("team") or "",
        project=merged.get("project") or None,
        sources=chain,
        origins=origins,
    )


def _read(path: Path) -> dict[str, str]:
    """One file's keys, unvalidated — only the merged cascade knows what is missing."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise BindingError(f"{path} is not valid TOML: {exc}") from None

    unknown = set(data) - set(KEYS)
    if unknown:
        # A typo'd key would otherwise be ignored, leaving the binding quietly
        # pointing somewhere other than the file appears to say.
        raise BindingError(
            f"{path} has unknown keys: {', '.join(sorted(unknown))}. Expected: {', '.join(KEYS)}."
        )
    # Empty values are kept rather than skipped: `project = ""` in an inner file
    # is how a subdirectory says "no project" against a root that names one.
    return {key: str(data[key]) for key in KEYS if key in data}


def require(workspace: str | None, team: str | None, *, need_team: bool = True) -> Binding:
    """Settle the target workspace and team, or explain what is missing.

    Flags win over the files — naming a target is saying where you mean, and the
    binding is a repo default, not a lock. But the files are read *even when the
    flags are complete*, so that a flag contradicting them is reported rather
    than silently obeyed. Reading them only when something was missing is what
    made an override invisible: no file read, no sources, no note, no trace.

    With no binding anywhere, complete flags stand on their own; a partial
    cascade is likewise completed by whichever flags fill its gaps. Anything
    still missing after both are merged raises rather than let the default
    workspace decide, naming what to pass and which files were read.
    """
    found = find()
    if found is None:
        if workspace and (team or not need_team):
            return Binding(workspace=workspace, team=team or "")
        wanted = [f for f, given in (("--workspace", workspace), ("--team", team)) if not given]
        if not need_team:
            wanted = [f for f in wanted if f != "--team"]
        raise BindingError(
            f"No {BINDING_FILE} above this directory, and {' and '.join(wanted)} not passed. "
            f"linear-kit has no default workspace: acting on the wrong one succeeds silently, "
            f"which is worse than refusing. Either pass the flags, or write a {BINDING_FILE} "
            f"in the repo root:\n"
            f'  workspace = "my-workspace"\n  team = "PAY"'
        )
    merged = overlay(found, workspace, team)
    required = ("workspace", "team") if need_team else ("workspace",)
    missing = [key for key in required if not getattr(merged, key)]
    if missing:
        # Reported against the whole cascade rather than one file: when an inner
        # file names only a project, no single file is the one at fault.
        where = ", ".join(str(p) for p in found.sources)
        flags = " and ".join(f"--{key}" for key in missing)
        raise BindingError(
            f"Binding is missing {' and '.join(repr(m) for m in missing)}. Read from: {where}. "
            f"Add the missing keys there, or pass {flags}."
        )
    return merged


def overlay(found: Binding, workspace: str | None, team: str | None) -> Binding:
    """Apply flags over a binding, recording every contradiction."""
    notes = [
        note
        for note in (
            _override(found, "--workspace", workspace, found.workspace),
            _override(found, "--team", team, found.team),
        )
        if note
    ]
    project = found.project
    if project and workspace and found.workspace and workspace.casefold() != found.workspace.casefold():
        # The bound project names something in the bound workspace. Carried into
        # another workspace it would resolve whatever happens to share the name
        # there — a silent misfile — or fail confusingly when nothing does.
        where = found.origins.get("project")
        notes.append(
            f"OVERRIDE: {workspace!r} is not the bound workspace — dropping bound project "
            f"{project!r}" + (f" from {where}" if where else "")
        )
        project = None
    return Binding(
        workspace=workspace or found.workspace,
        team=team or found.team,
        project=project,
        sources=found.sources,
        origins=found.origins,
        overrides=notes,
    )


def _override(found: Binding, flag: str, given: str | None, bound: str) -> str | None:
    """Phrase a flag beating the files, or None when it agrees with them.

    Compared as text, casefolded. A team can be named by key or by name, so `-t
    Payments` against `team = "PAY"` reads as a contradiction when it is the same
    team — telling those apart needs the API, and this runs before any call.
    Over-reporting is the safe direction: a spurious note is noise, a missing one
    is the silent misfile this module exists to prevent.
    """
    if not given or not bound or given.casefold() == bound.casefold():
        # An empty `bound` is a gap in the cascade, so a flag there fills in
        # rather than contradicts.
        return None
    key = flag.lstrip("-")
    where = found.origins.get(key)
    return f"OVERRIDE: {flag} {given} beats {bound!r}" + (f" from {where}" if where else "")
