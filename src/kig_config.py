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


def load_merged(cwd: Path | None = None) -> dict[str, Any]:
    """Global + project settings, project wins key-by-key. Placeholder for Task 2."""
    return load_global()
