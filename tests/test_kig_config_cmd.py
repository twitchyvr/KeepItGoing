"""Tests for /kig-config backing script."""

import json
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "bin" / "kig-config-cmd.py"


def run(args, env, cwd=None):
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        env={**env, "PYTHONPATH": str(HELPER.parent.parent / "src")},
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def test_set_project_key(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    r = run(["set", "default_mode", "simple"], env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads((tmp_path / ".kig" / "settings.json").read_text())
    assert data["default_mode"] == "simple"


def test_set_global_key(tmp_path):
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    r = run(["set", "--global", "poll_interval_sec", "60"], env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads((tmp_path / ".claude" / "kig" / "settings.json").read_text())
    assert data["poll_interval_sec"] == 60


def test_get_key_shows_resolved_value(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    run(["set", "default_mode", "simple"], env, cwd=tmp_path)
    r = run(["get", "default_mode"], env, cwd=tmp_path)
    assert "simple" in r.stdout


def test_reset_key_removes_from_file(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    run(["set", "default_mode", "simple"], env, cwd=tmp_path)
    run(["reset", "default_mode"], env, cwd=tmp_path)
    data = json.loads((tmp_path / ".kig" / "settings.json").read_text())
    assert "default_mode" not in data


def test_rejects_unknown_key(tmp_path):
    (tmp_path / ".kig").mkdir()
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (Path(env["KIG_HOME"])).mkdir(parents=True)
    r = run(["set", "nonsense_key", "x"], env, cwd=tmp_path)
    assert r.returncode != 0
