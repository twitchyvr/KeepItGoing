"""Tests for one-shot migration from kig-pins.json + kig-inject.txt."""

import json
from pathlib import Path

from kig_inject import load_store
from kig_migrate import migrate_legacy


def test_migrates_pins_file(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-pins.json").write_text(
        json.dumps({"pins": ["do tests first", "commit often"]})
    )
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    store = load_store(kig_home / "inject.json")
    texts = [e.text for e in store.entries]
    assert texts == ["do tests first", "commit often"]
    # archived
    assert (kig_home / "legacy" / "kig-pins.json").exists()
    assert not (claude_home / "kig-pins.json").exists()


def test_migrates_inject_text_and_flag(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-inject.txt").write_text("the whole context block")
    (claude_home / "kig-inject.enabled").touch()
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    store = load_store(kig_home / "inject.json")
    assert [e.text for e in store.entries] == ["the whole context block"]
    assert store.master_enabled is True
    assert (kig_home / "legacy" / "kig-inject.txt").exists()
    assert (kig_home / "legacy" / "kig-inject.enabled").exists()
    assert not (claude_home / "kig-inject.txt").exists()


def test_is_idempotent(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-pins.json").write_text(json.dumps({"pins": ["x"]}))
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)  # no-op
    store = load_store(kig_home / "inject.json")
    assert [e.text for e in store.entries] == ["x"]


def test_merges_pins_and_inject_into_one_store(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-pins.json").write_text(json.dumps({"pins": ["a", "b"]}))
    (claude_home / "kig-inject.txt").write_text("ctx")
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    store = load_store(kig_home / "inject.json")
    assert [e.text for e in store.entries] == ["a", "b", "ctx"]
