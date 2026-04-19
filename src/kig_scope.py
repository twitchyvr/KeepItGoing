"""Library scope resolution: merge global + project libraries per scope_mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

ScopeMode = Literal["per-category", "additive", "override"]


@dataclass
class Entry:
    id: str
    text: str
    category: str = "misc"


@dataclass
class Suppress:
    categories: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)


def resolve_library(
    global_lib: Iterable[Entry],
    project_lib: Iterable[Entry],
    *,
    scope_mode: ScopeMode,
    suppress: Suppress,
    isolate: bool,
) -> list[Entry]:
    """Merge global and project libraries according to scope_mode.

    Rules (design spec §Dynamic behavior):
      - isolate=True               → project only
      - scope_mode="override"      → project if non-empty else global
      - scope_mode="additive"      → global ++ project (no filtering)
      - scope_mode="per-category"  → filter global by suppress, then ++ project
    """
    g = list(global_lib)
    p = list(project_lib)
    if isolate:
        return p
    if scope_mode == "override":
        return p if p else g
    if scope_mode == "additive":
        return g + p
    filtered = [
        e
        for e in g
        if e.category not in suppress.categories and e.id not in suppress.ids
    ]
    return filtered + p
