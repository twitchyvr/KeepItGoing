"""Tests for /kig-library backing script."""

import json
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "bin" / "kig-library-cmd.py"


def run(args, env, cwd=None):
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        env={**env, "PYTHONPATH": str(HELPER.parent.parent / "src")},
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def test_add_to_project_library(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    r = run(["add", "--for", "simple", "project-specific note"], env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads((tmp_path / ".kig" / "simple.json").read_text())
    assert data["entries"][0]["text"] == "project-specific note"


def test_isolate_creates_marker(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    run(["isolate"], env, cwd=tmp_path)
    assert (tmp_path / ".kig" / "isolate").exists()


def test_unisolate_removes_marker(tmp_path):
    (tmp_path / ".kig").mkdir()
    (tmp_path / ".kig" / "isolate").touch()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    run(["unisolate"], env, cwd=tmp_path)
    assert not (tmp_path / ".kig" / "isolate").exists()


def test_suppress_adds_category(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    run(["suppress", "visual_verification"], env, cwd=tmp_path)
    data = json.loads((tmp_path / ".kig" / "suppress.json").read_text())
    assert "visual_verification" in data["categories"]
