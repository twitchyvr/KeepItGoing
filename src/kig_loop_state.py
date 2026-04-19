"""Tracks Claude Code /loop lifecycle per iTerm tab."""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
from pathlib import Path

LOOP_STATE_DIR = Path("/tmp/claude-keepitgoing")
STALE_MINUTES = 30


def _state_path(tty: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tty)
    LOOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return LOOP_STATE_DIR / f"loop-state-{safe}.json"


def _load(tty: str) -> dict:
    path = _state_path(tty)
    if not path.exists():
        return {"active": False}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"active": False}


def _save(tty: str, data: dict) -> None:
    _state_path(tty).write_text(json.dumps(data, indent=2))


def record_loop_start(tty: str, *, cron_id: str) -> None:
    _save(
        tty,
        {
            "active": True,
            "started": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "cron_id": cron_id,
        },
    )


def record_loop_end(
    tty: str, *, cron_id: str, reason: str = "stopped", force: bool = False
) -> None:
    """End a tracked loop. Unless force=True, only ends if cron_id matches
    the currently tracked one (prevents a mismatched CronDelete from
    accidentally unmuting a different active loop)."""
    cur = _load(tty)
    if not cur.get("active"):
        return
    if force or cur.get("cron_id") == cron_id:
        _save(
            tty,
            {
                "active": False,
                "ended": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "reason": reason,
            },
        )


def is_loop_active(tty: str) -> bool:
    return bool(_load(tty).get("active"))


def clear_if_stale(tty: str) -> bool:
    """Force-clear if state file hasn't been modified in STALE_MINUTES."""
    path = _state_path(tty)
    if not path.exists():
        return False
    mtime = path.stat().st_mtime
    if time.time() - mtime > STALE_MINUTES * 60:
        _save(tty, {"active": False, "reason": "stale_auto_clear"})
        return True
    return False
