"""One-shot migration from kig-pins.json + kig-inject.txt → kig/inject.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from kig_inject import add_entry, load_store, save_store, set_master


def _archive(src: Path, legacy_dir: Path) -> None:
    if not src.exists():
        return
    legacy_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(legacy_dir / src.name))


def migrate_legacy(*, claude_home: Path, kig_home: Path) -> None:
    """Idempotent migration. Safe to run on every install.sh."""
    legacy = kig_home / "legacy"
    inject_path = kig_home / "inject.json"
    kig_home.mkdir(parents=True, exist_ok=True)

    pins_src = claude_home / "kig-pins.json"
    if pins_src.exists():
        try:
            data = json.loads(pins_src.read_text())
            for text in data.get("pins", []):
                if text:
                    add_entry(inject_path, text=text, for_modes=["all"])
        except json.JSONDecodeError:
            pass
        _archive(pins_src, legacy)

    inject_src = claude_home / "kig-inject.txt"
    enabled_src = claude_home / "kig-inject.enabled"
    if inject_src.exists():
        text = inject_src.read_text().strip()
        if text:
            add_entry(inject_path, text=text, for_modes=["all"])
        if enabled_src.exists():
            set_master(inject_path, True)
        _archive(inject_src, legacy)
        _archive(enabled_src, legacy)
