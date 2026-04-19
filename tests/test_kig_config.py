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
