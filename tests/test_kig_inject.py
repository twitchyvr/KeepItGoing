"""Tests for the consolidated inject hybrid store."""

import json
from pathlib import Path

from kig_inject import (
    InjectEntry,
    InjectStore,
    load_store,
    save_store,
    add_entry,
    remove_entry,
    toggle_entry,
    set_master,
    filter_for_mode,
)


def test_load_store_empty_when_no_file(tmp_global_kig):
    store = load_store(tmp_global_kig / "inject.json")
    assert store.master_enabled is False
    assert store.entries == []


def test_add_entry_generates_id_and_persists(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    entry = add_entry(path, text="do the thing", for_modes=["all"])
    assert entry.id  # non-empty
    assert entry.text == "do the thing"
    assert entry.for_modes == ["all"]
    reloaded = load_store(path)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].text == "do the thing"


def test_remove_entry_by_one_indexed_number(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    add_entry(path, text="first", for_modes=["all"])
    add_entry(path, text="second", for_modes=["all"])
    remove_entry(path, 1)
    store = load_store(path)
    assert [e.text for e in store.entries] == ["second"]


def test_toggle_entry_flips_enabled(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    add_entry(path, text="x", for_modes=["all"])
    toggle_entry(path, 1)
    assert load_store(path).entries[0].enabled is False
    toggle_entry(path, 1)
    assert load_store(path).entries[0].enabled is True


def test_set_master(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    set_master(path, True)
    assert load_store(path).master_enabled is True
    set_master(path, False)
    assert load_store(path).master_enabled is False


def test_filter_for_mode_all_wildcard(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    add_entry(path, text="everywhere", for_modes=["all"])
    add_entry(path, text="only-simple", for_modes=["simple"])
    set_master(path, True)
    store = load_store(path)
    assert [e.text for e in filter_for_mode(store, "verbose")] == ["everywhere"]
    assert [e.text for e in filter_for_mode(store, "simple")] == [
        "everywhere",
        "only-simple",
    ]


def test_filter_for_mode_skips_disabled(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    add_entry(path, text="on", for_modes=["all"])
    add_entry(path, text="off", for_modes=["all"])
    set_master(path, True)
    toggle_entry(path, 2)
    store = load_store(path)
    assert [e.text for e in filter_for_mode(store, "minimal")] == ["on"]


def test_filter_for_mode_returns_empty_when_master_off(tmp_global_kig):
    path = tmp_global_kig / "inject.json"
    add_entry(path, text="x", for_modes=["all"])
    # master defaults to False
    store = load_store(path)
    assert filter_for_mode(store, "verbose") == []
