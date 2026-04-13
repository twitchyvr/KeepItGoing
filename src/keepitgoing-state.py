#!/usr/bin/env python3
"""
KeepItGoing State Writer for Claude Code Hooks
Writes Claude session state to /tmp/claude-keepitgoing/ for the KeepItGoing app to read.
Each Claude session gets its own state file keyed by session_id.

Called by hooks in settings.json for: Stop, Notification, PermissionRequest,
PreToolUse, PostToolUse, SessionStart, SessionEnd
"""

import sys
import json
import time
import os
from pathlib import Path

STATE_DIR = Path("/tmp/claude-keepitgoing")


def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            sys.exit(0)
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass

    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd", "")

    state = {
        "event": event,
        "timestamp": time.time(),
        "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cwd": cwd,
        "session_id": session_id,
        "permission_mode": data.get("permission_mode", ""),
        "project_name": Path(cwd).name if cwd else "",
        "idle": False,
        "permission_pending": False,
        "ended": False,
    }

    if event == "Stop":
        msg = data.get("last_assistant_message", "")
        state["idle"] = True
        state["last_snippet"] = msg[:500] if msg else ""
        state["stop_hook_active"] = data.get("stop_hook_active", False)

    elif event == "Notification":
        ntype = data.get("notification_type", "")
        state["notification_type"] = ntype
        state["message"] = data.get("message", "")[:500]
        state["idle"] = ntype in ("idle_prompt", "permission_prompt")
        state["permission_pending"] = ntype == "permission_prompt"

    elif event == "PermissionRequest":
        state["tool_name"] = data.get("tool_name", "")
        state["idle"] = True
        state["permission_pending"] = True

    elif event in ("PreToolUse", "PostToolUse"):
        state["tool_name"] = data.get("tool_name", "")
        state["idle"] = False

    elif event == "SessionStart":
        state["idle"] = False
        state["source"] = data.get("source", "")
        # Auto-refresh system manifest if stale (>7 days) or missing.
        # Costs ~0.5s on session start, once a week. Keeps manifest current
        # so Claude doesn't waste tokens probing the system every session.
        manifest = Path.home() / ".claude" / "system" / "manifest.md"
        try:
            age = (
                time.time() - manifest.stat().st_mtime if manifest.exists() else 999999
            )
            if age > 604800:  # 7 days
                import subprocess

                subprocess.Popen(
                    [
                        "bash",
                        str(
                            Path.home() / ".claude" / "system" / "generate-manifest.sh"
                        ),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    elif event == "SessionEnd":
        state["ended"] = True
        state["reason"] = data.get("reason", "")
        # Write the ended state then clean up after a delay
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.write_text(json.dumps(state, indent=2))
        return

    elif event == "SubagentStart":
        state["idle"] = False
        state["agent_type"] = data.get("agent_type", "")

    elif event == "SubagentStop":
        # Don't mark idle — the parent session continues
        state["idle"] = False
        state["agent_type"] = data.get("agent_type", "")

    elif event == "PreCompact":
        state["idle"] = False
        state["compacting"] = True

    else:
        state["idle"] = False

    # Write state file
    state_file = STATE_DIR / f"{session_id}.json"
    state_file.write_text(json.dumps(state, indent=2))

    # Garbage collect: remove state files older than 2 hours or ended sessions > 5 min
    now = time.time()
    for f in STATE_DIR.glob("*.json"):
        if f.name == "prompt-history.json":
            continue
        try:
            age = now - f.stat().st_mtime
            if age > 7200:
                f.unlink()
            elif age > 300:
                try:
                    fdata = json.loads(f.read_text())
                    if fdata.get("ended"):
                        f.unlink()
                except Exception:
                    pass
        except Exception:
            pass


if __name__ == "__main__":
    main()
