"""One-shot migration from kig-pins.json + kig-inject.txt → kig/inject.json."""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path

from kig_inject import add_entry, set_master


def _archive(src: Path, legacy_dir: Path) -> None:
    """Move src into legacy_dir, timestamping the destination if it already exists.

    Timestamping keeps the archive truly archival — if the user restores a legacy
    file from backup and re-runs migration, earlier archive copies are preserved.
    """
    if not src.exists():
        return
    legacy_dir.mkdir(parents=True, exist_ok=True)
    dest = legacy_dir / src.name
    if dest.exists():
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = legacy_dir / f"{src.name}.{stamp}"
    shutil.move(str(src), str(dest))


def migrate_legacy(*, claude_home: Path, kig_home: Path) -> None:
    """Idempotent migration. Safe to run on every install.sh."""
    legacy = kig_home / "legacy"
    inject_path = kig_home / "inject.json"
    kig_home.mkdir(parents=True, exist_ok=True)

    pins_src = claude_home / "kig-pins.json"
    if pins_src.exists():
        try:
            data = json.loads(pins_src.read_text())
            # Two legacy shapes exist in the wild:
            #   dict: {"pins": ["a", "b"]}
            #   list: ["a", "b"]                 ← earlier rough cut
            if isinstance(data, dict):
                pins = data.get("pins", [])
            elif isinstance(data, list):
                pins = data
            else:
                pins = []
            for text in pins:
                if isinstance(text, str) and text:
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
