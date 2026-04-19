"""Tests for the /kig-inject backing script CLI."""

import json
import subprocess
import sys
from pathlib import Path


HELPER = Path(__file__).resolve().parent.parent / "bin" / "kig-inject-cmd.py"


def run(args, env):
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        env={**env, "PYTHONPATH": str(HELPER.parent.parent / "src")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_add_and_list(tmp_path):
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (tmp_path / ".claude" / "kig").mkdir(parents=True)
    r1 = run(["add", "the thing"], env)
    assert r1.returncode == 0, r1.stderr
    r2 = run(["list"], env)
    assert r2.returncode == 0
    assert "the thing" in r2.stdout


def test_remove_by_index(tmp_path):
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (tmp_path / ".claude" / "kig").mkdir(parents=True)
    run(["add", "one"], env)
    run(["add", "two"], env)
    run(["remove", "1"], env)
    r = run(["list"], env)
    assert "one" not in r.stdout
    assert "two" in r.stdout


def test_toggle_disables_entry(tmp_path):
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (tmp_path / ".claude" / "kig").mkdir(parents=True)
    run(["add", "x"], env)
    run(["toggle", "1"], env)
    r = run(["list"], env)
    assert "off" in r.stdout.lower()


def test_master_on_off(tmp_path):
    env = {"HOME": str(tmp_path), "KIG_HOME": str(tmp_path / ".claude" / "kig")}
    (tmp_path / ".claude" / "kig").mkdir(parents=True)
    run(["on"], env)
    r = run(["show"], env)
    assert "master: on" in r.stdout.lower()
