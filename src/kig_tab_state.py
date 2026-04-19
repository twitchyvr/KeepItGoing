"""Per-tab state: one JSON file per iTerm tab TTY."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from kig_config import global_kig_dir


@dataclass
class TabState:
    mode: str = "verbose"
    kig_on: bool = True
    mute_until: str | None = None
    last_prompt_sent: str | None = None


def _tab_path(tty: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tty)
    return global_kig_dir() / "tabs" / f"{safe}.json"


def load_tab(tty: str) -> TabState:
    path = _tab_path(tty)
    if not path.exists():
        return TabState()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return TabState()
    return TabState(
        mode=data.get("mode", "verbose"),
        kig_on=bool(data.get("kig_on", True)),
        mute_until=data.get("mute_until"),
        last_prompt_sent=data.get("last_prompt_sent"),
    )


def save_tab(tty: str, state: TabState) -> None:
    path = _tab_path(tty)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))


def set_mode(tty: str, mode: str) -> None:
    state = load_tab(tty)
    state.mode = mode
    save_tab(tty, state)


def set_mute_until(tty: str, iso: str) -> None:
    state = load_tab(tty)
    state.mute_until = iso
    save_tab(tty, state)


def clear_mute(tty: str) -> None:
    state = load_tab(tty)
    state.mute_until = None
    save_tab(tty, state)
