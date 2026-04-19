"""Consolidated inject: replaces /kig-pin and /kig-inject.

Hybrid model (design spec §2):
  - master_enabled: top-level on/off switch for the whole list
  - entries: ordered list, each individually toggleable, each with a
    `for` filter (subset of [minimal, simple, verbose] OR ["all"] wildcard)
"""

from __future__ import annotations

import datetime as _dt
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Mode = Literal["minimal", "simple", "verbose"]


@dataclass
class InjectEntry:
    id: str
    text: str
    enabled: bool = True
    for_modes: list[str] = field(default_factory=lambda: ["all"])
    added: str = ""


@dataclass
class InjectStore:
    master_enabled: bool = False
    entries: list[InjectEntry] = field(default_factory=list)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return secrets.token_hex(4)


def load_store(path: Path) -> InjectStore:
    if not path.exists():
        return InjectStore()
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return InjectStore()
    entries = [
        InjectEntry(
            id=e.get("id") or _new_id(),
            text=e.get("text", ""),
            enabled=bool(e.get("enabled", True)),
            for_modes=list(e.get("for", ["all"])),
            added=e.get("added", ""),
        )
        for e in raw.get("entries", [])
    ]
    return InjectStore(
        master_enabled=bool(raw.get("master_enabled", False)),
        entries=entries,
    )


def save_store(path: Path, store: InjectStore) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "master_enabled": store.master_enabled,
        "entries": [
            {
                "id": e.id,
                "text": e.text,
                "enabled": e.enabled,
                "for": e.for_modes,
                "added": e.added,
            }
            for e in store.entries
        ],
    }
    path.write_text(json.dumps(data, indent=2))


def add_entry(path: Path, *, text: str, for_modes: list[str]) -> InjectEntry:
    store = load_store(path)
    entry = InjectEntry(
        id=_new_id(),
        text=text,
        enabled=True,
        for_modes=list(for_modes),
        added=_now_iso(),
    )
    store.entries.append(entry)
    save_store(path, store)
    return entry


def remove_entry(path: Path, one_indexed: int) -> None:
    store = load_store(path)
    idx = one_indexed - 1
    if 0 <= idx < len(store.entries):
        del store.entries[idx]
        save_store(path, store)


def toggle_entry(path: Path, one_indexed: int) -> None:
    store = load_store(path)
    idx = one_indexed - 1
    if 0 <= idx < len(store.entries):
        store.entries[idx].enabled = not store.entries[idx].enabled
        save_store(path, store)


def set_master(path: Path, enabled: bool) -> None:
    store = load_store(path)
    store.master_enabled = enabled
    save_store(path, store)


def filter_for_mode(store: InjectStore, mode: Mode) -> list[InjectEntry]:
    """Return enabled entries whose `for` array matches mode (or wildcard)."""
    if not store.master_enabled:
        return []
    return [
        e
        for e in store.entries
        if e.enabled and ("all" in e.for_modes or mode in e.for_modes)
    ]
