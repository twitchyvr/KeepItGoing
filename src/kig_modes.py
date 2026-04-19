"""Mode routing: picks the nudge text based on per-tab mode.

- minimal → random line from minimal seed + project/global additions
- simple  → random line from simple seed + project/global additions
- verbose → delegates to existing keepitgoing-generate.py
"""

from __future__ import annotations

import importlib
import json
import random
from pathlib import Path
from typing import Literal

from kig_config import find_project_kig, global_kig_dir
from kig_scope import Entry, Suppress, resolve_library

Mode = Literal["minimal", "simple", "verbose"]

SEEDS_DIR = Path(__file__).resolve().parent / "kig_seeds"


def _read_entries(path: Path) -> list[Entry]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return [
        Entry(id=e["id"], text=e["text"], category=e.get("category", "misc"))
        for e in data.get("entries", [])
    ]


def load_mode_library(mode: Mode, cwd: Path | None = None) -> list[Entry]:
    """Load the resolved (global ∪ project) library for a mode."""
    if mode not in ("minimal", "simple"):
        return []
    seed = _read_entries(SEEDS_DIR / f"{mode}.json")
    global_file = global_kig_dir() / f"{mode}.json"
    global_extra = _read_entries(global_file)
    global_all = seed + global_extra

    project_lib: list[Entry] = []
    if cwd is None:
        cwd = Path.cwd()
    proj = find_project_kig(cwd)
    if proj is not None:
        project_lib = _read_entries(proj / f"{mode}.json")

    return resolve_library(
        global_all,
        project_lib,
        scope_mode="per-category",
        suppress=Suppress(),
        isolate=(proj is not None and (proj / "isolate").exists()),
    )


def verbose_generate(cwd: Path) -> str:
    """Invoke the existing verbose generator. Overridable in tests."""
    mod = importlib.import_module("keepitgoing-generate".replace("-", "_"))
    return mod.generate(cwd=str(cwd))


def pick_nudge(*, mode: Mode, cwd: Path) -> str:
    """Return the text to send in the next nudge."""
    if mode == "verbose":
        return verbose_generate(cwd)
    lib = load_mode_library(mode, cwd=cwd)
    if not lib:
        return "keep going"  # last-resort fallback
    return random.choice(lib).text
