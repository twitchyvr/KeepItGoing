"""KIG configuration: load, merge, resolve global + project settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "default_mode": "verbose",
    "scope_mode": "per-category",
    "poll_interval_sec": 30,
    "idle_threshold_sec": 60,
    "mute_on_loop_detect": True,
    "suggest_loop_when_long": True,
    "suggest_loop_threshold_min": 15,
}


def global_kig_dir() -> Path:
    """Resolve ~/.claude/kig/ honoring KIG_HOME override for tests."""
    env = os.environ.get("KIG_HOME")
    if env:
        return Path(env)
    return Path.home() / ".claude" / "kig"


def load_global() -> dict[str, Any]:
    """Read global settings.json and return merged-with-defaults dict."""
    path = global_kig_dir() / "settings.json"
    if not path.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def find_project_kig(cwd: Path) -> Path | None:
    """Walk up from cwd looking for a .kig/ directory. Return it or None."""
    cur = cwd.resolve()
    while True:
        candidate = cur / ".kig"
        if candidate.is_dir():
            return candidate
        if cur.parent == cur:
            return None
        cur = cur.parent


def load_project(cwd: Path) -> dict[str, Any]:
    """Read project .kig/settings.json (if any) filtered to known keys."""
    proj = find_project_kig(cwd)
    if proj is None:
        return {}
    path = proj / "settings.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if k in DEFAULTS}


def load_merged(cwd: Path | None = None) -> dict[str, Any]:
    """Defaults <- global settings <- project settings. Later wins."""
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in load_global().items() if k in DEFAULTS})
    if cwd is None:
        cwd = Path.cwd()
    merged.update(load_project(cwd))
    return merged
