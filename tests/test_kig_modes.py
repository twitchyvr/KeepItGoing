"""Tests for mode-based nudge generation."""

import json
import random
from pathlib import Path

import pytest

from kig_modes import pick_nudge, load_mode_library


def test_load_mode_library_reads_seed(tmp_global_kig, monkeypatch):
    # Point seeds dir to our repo src/kig_seeds
    import kig_modes

    seeds = Path(__file__).resolve().parent.parent / "src" / "kig_seeds"
    monkeypatch.setattr(kig_modes, "SEEDS_DIR", seeds)
    lib = load_mode_library("minimal")
    assert len(lib) >= 10
    assert all(hasattr(e, "text") for e in lib)


def test_pick_nudge_minimal_returns_from_seed(tmp_global_kig, monkeypatch):
    import kig_modes

    seeds = Path(__file__).resolve().parent.parent / "src" / "kig_seeds"
    monkeypatch.setattr(kig_modes, "SEEDS_DIR", seeds)
    random.seed(0)
    text = pick_nudge(mode="minimal", cwd=Path.cwd())
    assert isinstance(text, str)
    assert 0 < len(text) < 50  # minimal lines are short


def test_pick_nudge_simple_returns_from_seed(tmp_global_kig, monkeypatch):
    import kig_modes

    seeds = Path(__file__).resolve().parent.parent / "src" / "kig_seeds"
    monkeypatch.setattr(kig_modes, "SEEDS_DIR", seeds)
    text = pick_nudge(mode="simple", cwd=Path.cwd())
    assert isinstance(text, str)
    assert len(text) > 0


def test_pick_nudge_verbose_delegates(monkeypatch, tmp_global_kig):
    """Verbose mode should NOT use the seed libraries."""
    import kig_modes

    sentinel = "FROM-VERBOSE-GENERATOR"
    monkeypatch.setattr(kig_modes, "verbose_generate", lambda cwd: sentinel)
    text = pick_nudge(mode="verbose", cwd=Path.cwd())
    assert text == sentinel
