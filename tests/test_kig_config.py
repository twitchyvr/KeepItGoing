"""Tests for kig_config module."""

import json
from pathlib import Path

import pytest

from kig_config import DEFAULTS, load_global, load_merged


def test_load_global_returns_defaults_when_no_file(tmp_global_kig):
    """With no settings.json, load_global returns DEFAULTS."""
    result = load_global()
    assert result == DEFAULTS


def test_defaults_shape():
    """DEFAULTS contains every documented key."""
    assert DEFAULTS["default_mode"] == "verbose"
    assert DEFAULTS["scope_mode"] == "per-category"
    assert DEFAULTS["poll_interval_sec"] == 30
    assert DEFAULTS["idle_threshold_sec"] == 60
    assert DEFAULTS["mute_on_loop_detect"] is True
    assert DEFAULTS["suggest_loop_when_long"] is True
    assert DEFAULTS["suggest_loop_threshold_min"] == 15


def test_load_merged_project_overrides_global(tmp_global_kig, tmp_project_kig):
    """Project .kig/settings.json wins key-by-key."""
    (tmp_global_kig / "settings.json").write_text(
        json.dumps({"default_mode": "simple", "poll_interval_sec": 45})
    )
    (tmp_project_kig / "settings.json").write_text(
        json.dumps({"default_mode": "minimal"})
    )
    result = load_merged(cwd=Path.cwd())
    assert result["default_mode"] == "minimal"  # project wins
    assert result["poll_interval_sec"] == 45  # global preserved
    assert result["scope_mode"] == "per-category"  # default preserved


def test_load_merged_walks_up_for_project_dir(tmp_global_kig, tmp_path, monkeypatch):
    """.kig/ can live in a parent directory of cwd."""
    project = tmp_path / "root"
    (project / ".kig").mkdir(parents=True)
    (project / ".kig" / "settings.json").write_text(
        json.dumps({"default_mode": "simple"})
    )
    sub = project / "src" / "deeply" / "nested"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    result = load_merged(cwd=Path.cwd())
    assert result["default_mode"] == "simple"


def test_load_merged_no_project_dir(tmp_global_kig, tmp_path, monkeypatch):
    """When no .kig/ is found, returns global-only merge."""
    lone = tmp_path / "lonely"
    lone.mkdir()
    monkeypatch.chdir(lone)
    (tmp_global_kig / "settings.json").write_text(
        json.dumps({"default_mode": "simple"})
    )
    result = load_merged(cwd=Path.cwd())
    assert result["default_mode"] == "simple"
