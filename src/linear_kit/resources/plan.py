"""A plan is the list of mutations a command intends to run.

Building the plan first is what makes --dry-run honest: the same object is
either printed or executed, so a dry run cannot drift from a real one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from linear_kit.client import LinearClient


@dataclass
class Step:
    #: Human-readable line shown by --dry-run, e.g. "teamCreate  Payments (PAY)".
    label: str
    #: Runs the mutation and returns a short result string for the log.
    run: Callable[[LinearClient], str]
    #: Non-fatal steps log and continue when they fail (e.g. a label that exists).
    tolerant: bool = False


@dataclass
class Plan:
    title: str
    steps: list[Step] = field(default_factory=list)
    #: Facts discovered while planning that the user should see (e.g. "team PAY exists").
    notes: list[str] = field(default_factory=list)
    #: Shared scratch space so a later step can read an earlier step's ids.
    context: dict[str, Any] = field(default_factory=dict)

    def add(self, label: str, run: Callable[[LinearClient], str], *, tolerant: bool = False) -> None:
        self.steps.append(Step(label=label, run=run, tolerant=tolerant))
