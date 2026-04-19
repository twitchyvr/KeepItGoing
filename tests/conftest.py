"""Shared pytest fixtures for KIG tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_global_kig(tmp_path, monkeypatch):
    """Create a temporary ~/.claude/kig/ and point KIG_HOME at it."""
    kig_dir = tmp_path / "claude-home" / "kig"
    kig_dir.mkdir(parents=True)
    (kig_dir / "tabs").mkdir()
    monkeypatch.setenv("KIG_HOME", str(kig_dir))
    return kig_dir


@pytest.fixture
def tmp_project_kig(tmp_path, monkeypatch):
    """Create a temporary project with .kig/ and chdir into it."""
    project = tmp_path / "project"
    kig = project / ".kig"
    kig.mkdir(parents=True)
    monkeypatch.chdir(project)
    return kig


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))
