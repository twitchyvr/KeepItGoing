"""Tests for per-tab state file."""

import json
from pathlib import Path

from kig_tab_state import (
    TabState,
    load_tab,
    save_tab,
    set_mode,
    clear_mute,
    set_mute_until,
)


def test_load_tab_defaults(tmp_global_kig):
    state = load_tab("ttys001")
    assert state.mode == "verbose"
    assert state.kig_on is True
    assert state.mute_until is None


def test_set_mode_persists(tmp_global_kig):
    set_mode("ttys001", "minimal")
    assert load_tab("ttys001").mode == "minimal"


def test_set_mute_until_persists(tmp_global_kig):
    set_mute_until("ttys002", "2026-04-19T15:00:00Z")
    assert load_tab("ttys002").mute_until == "2026-04-19T15:00:00Z"


def test_clear_mute_nulls_field(tmp_global_kig):
    set_mute_until("ttys003", "2026-04-19T15:00:00Z")
    clear_mute("ttys003")
    assert load_tab("ttys003").mute_until is None


def test_tty_name_sanitized(tmp_global_kig):
    """Slashes and colons in tty path must be safe for filename."""
    set_mode("/dev/ttys003", "simple")
    assert load_tab("/dev/ttys003").mode == "simple"
