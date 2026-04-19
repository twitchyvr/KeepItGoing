"""Tests for /loop lifecycle state tracking."""

import datetime as dt
import json
from pathlib import Path

from kig_loop_state import (
    record_loop_start,
    record_loop_end,
    is_loop_active,
    clear_if_stale,
    LOOP_STATE_DIR,
    STALE_MINUTES,
)


def test_start_marks_active(tmp_path, monkeypatch):
    monkeypatch.setattr("kig_loop_state.LOOP_STATE_DIR", tmp_path)
    record_loop_start("ttys001", cron_id="abc123")
    assert is_loop_active("ttys001") is True


def test_end_marks_inactive(tmp_path, monkeypatch):
    monkeypatch.setattr("kig_loop_state.LOOP_STATE_DIR", tmp_path)
    record_loop_start("ttys001", cron_id="abc123")
    record_loop_end("ttys001", cron_id="abc123")
    assert is_loop_active("ttys001") is False


def test_end_with_unknown_cron_id_noop(tmp_path, monkeypatch):
    monkeypatch.setattr("kig_loop_state.LOOP_STATE_DIR", tmp_path)
    record_loop_start("ttys001", cron_id="abc123")
    record_loop_end("ttys001", cron_id="different")
    assert is_loop_active("ttys001") is True  # unchanged


def test_clear_if_stale_when_old(tmp_path, monkeypatch):
    monkeypatch.setattr("kig_loop_state.LOOP_STATE_DIR", tmp_path)
    record_loop_start("ttys001", cron_id="abc123")
    # Forge an old mtime
    state_file = tmp_path / "loop-state-ttys001.json"
    old = (dt.datetime.now() - dt.timedelta(minutes=STALE_MINUTES + 1)).timestamp()
    import os

    os.utime(state_file, (old, old))
    assert clear_if_stale("ttys001") is True
    assert is_loop_active("ttys001") is False


def test_per_tty_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr("kig_loop_state.LOOP_STATE_DIR", tmp_path)
    record_loop_start("ttys001", cron_id="a")
    assert is_loop_active("ttys001") is True
    assert is_loop_active("ttys002") is False


def test_end_force_clears_regardless_of_cron_id(tmp_path, monkeypatch):
    """SessionEnd uses force=True to clear without matching cron_id."""
    monkeypatch.setattr("kig_loop_state.LOOP_STATE_DIR", tmp_path)
    record_loop_start("ttys001", cron_id="real-cron-1")
    record_loop_end("ttys001", cron_id="__session_end__")
    assert is_loop_active("ttys001") is True
    record_loop_end(
        "ttys001", cron_id="__session_end__", force=True, reason="session_end"
    )
    assert is_loop_active("ttys001") is False
