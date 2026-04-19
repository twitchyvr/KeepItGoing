# KIG Modes, Library & Config System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a four-layer KIG nudge system (per-tab mode → scoped libraries → user overlays → prompt) with consolidated `/kig-inject`, new `/kig-library` + `/kig-config`, `/loop` lifecycle awareness, and a pytest suite. 5 stages, 5 PRs.

**Architecture:** Python modules handle config load/merge, library scope resolution, inject hybrid state, and `/loop` lifecycle tracking — all stdlib-only. AppleScript monitor reads per-tab state, routes to the right library based on mode, applies mute during `/loop`. Slash commands shell out to Python helper scripts in `bin/` for all mutations. Old `kig-pins.json` + `kig-inject.txt` migrated on installer run.

**Tech Stack:** Python 3.10+ (stdlib only for runtime; pytest for tests), AppleScript, Bash. Storage: JSON files in `~/.claude/kig/` (global) and `.kig/` (project).

**Source spec:** `docs/superpowers/specs/2026-04-19-kig-modes-and-library-design.md`

---

## Stage Map

| Stage | PR                            | Outcome                                                           | Task range |
| ----- | ----------------------------- | ----------------------------------------------------------------- | ---------- |
| 1     | Config foundation             | Settings + scope resolver + migration shipped; no behavior change | 1–10       |
| 2     | Mode routing + seed libraries | `kig mode minimal\|simple\|verbose` works end-to-end              | 11–17      |
| 3     | Slash commands                | `/kig-inject` + `/kig-library` live; `/kig-pin` deleted           | 18–24      |
| 4     | `/loop` lifecycle             | Auto-mute on `/loop` start, resume on `/loop` end                 | 25–31      |
| 5     | `/kig-config` + `kig show`    | All settings exposed, diagnostic command polished                 | 32–37      |

Each stage ends with a commit, PR against `develop`, and dogfood pass per project CLAUDE.md.

---

## Global setup (do once before Stage 1)

### Task 0: Create working branch and pytest scaffold

**Files:**

- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 0.1: Verify you're on the right branch**

```bash
cd ~/GitRepos/KeepItGoing
git checkout -b feat/kig-modes-stage1 docs/kig-modes-design
```

Expected: `Switched to a new branch 'feat/kig-modes-stage1'`

- [ ] **Step 0.2: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 0.3: Create `tests/__init__.py`** (empty file)

```bash
touch tests/__init__.py
```

- [ ] **Step 0.4: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures for KIG tests."""
import json
import os
import shutil
import tempfile
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
```

- [ ] **Step 0.5: Add `src/` to pytest path**

Add to `pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = src
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 0.6: Verify pytest runs (zero tests)**

```bash
cd ~/GitRepos/KeepItGoing && python3 -m pytest
```

Expected: `no tests ran` exit code 5, but no errors.

- [ ] **Step 0.7: Commit scaffold**

```bash
git add pytest.ini tests/
git commit -m "chore: add pytest scaffold for KIG test suite

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Stage 1 — Config foundation

**Outcome:** Three Python modules (`kig_config`, `kig_scope`, `kig_inject`) plus migration in `install.sh`. No behavior change yet — existing verbose generator still runs for all tabs. All new modules unit-tested.

### Task 1: `kig_config.py` — load global settings with defaults

**Files:**

- Create: `src/kig_config.py`
- Create: `tests/test_kig_config.py`

- [ ] **Step 1.1: Write the failing test for defaults**

Create `tests/test_kig_config.py`:

```python
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
```

- [ ] **Step 1.2: Run the test — expect failure**

```bash
python3 -m pytest tests/test_kig_config.py -v
```

Expected: `ImportError: cannot import name 'DEFAULTS' from 'kig_config'` OR `ModuleNotFoundError`.

- [ ] **Step 1.3: Create minimal `src/kig_config.py` to pass**

```python
"""KIG configuration: load, merge, resolve global + project settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "default_mode": "verbose",
    "scope_mode": "per-category",
    "poll_interval_sec": 30,
    "idle_threshold_sec": 60,
    "mute_on_loop_detect": True,
    "suggest_loop_when_long": True,
    "suggest_loop_threshold_min": 15,
}


def global_kig_dir() -> Path:
    """Resolve ~/.claude/kig/ honoring KIG_HOME override for tests."""
    env = os.environ.get("KIG_HOME")
    if env:
        return Path(env)
    return Path.home() / ".claude" / "kig"


def load_global() -> dict[str, Any]:
    """Read global settings.json and return merged-with-defaults dict."""
    path = global_kig_dir() / "settings.json"
    if not path.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def load_merged(cwd: Path | None = None) -> dict[str, Any]:
    """Global + project settings, project wins key-by-key. Placeholder for Task 2."""
    return load_global()
```

- [ ] **Step 1.4: Run the tests — expect pass**

```bash
python3 -m pytest tests/test_kig_config.py -v
```

Expected: `2 passed`.

- [ ] **Step 1.5: Commit**

```bash
git add src/kig_config.py tests/test_kig_config.py
git commit -m "feat(config): load global KIG settings with defaults

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2: `kig_config.py` — merge project settings over global

**Files:**

- Modify: `src/kig_config.py`
- Modify: `tests/test_kig_config.py`

- [ ] **Step 2.1: Add failing test for project override**

Append to `tests/test_kig_config.py`:

```python
def test_load_merged_project_overrides_global(tmp_global_kig, tmp_project_kig):
    """Project .kig/settings.json wins key-by-key."""
    (tmp_global_kig / "settings.json").write_text(
        json.dumps({"default_mode": "simple", "poll_interval_sec": 45})
    )
    (tmp_project_kig / "settings.json").write_text(
        json.dumps({"default_mode": "minimal"})
    )
    result = load_merged(cwd=Path.cwd())
    assert result["default_mode"] == "minimal"       # project wins
    assert result["poll_interval_sec"] == 45         # global preserved
    assert result["scope_mode"] == "per-category"    # default preserved


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
```

- [ ] **Step 2.2: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_config.py -v
```

Expected: 3 new tests fail (project override ignored).

- [ ] **Step 2.3: Implement project walk-up and merge**

Replace `load_merged` in `src/kig_config.py`:

```python
def find_project_kig(cwd: Path) -> Path | None:
    """Walk up from cwd looking for a .kig/ directory. Return it or None."""
    cur = cwd.resolve()
    while True:
        candidate = cur / ".kig"
        if candidate.is_dir():
            return candidate
        if cur.parent == cur:
            return None
        cur = cur.parent


def load_project(cwd: Path) -> dict[str, Any]:
    """Read project .kig/settings.json (if any) filtered to known keys."""
    proj = find_project_kig(cwd)
    if proj is None:
        return {}
    path = proj / "settings.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if k in DEFAULTS}


def load_merged(cwd: Path | None = None) -> dict[str, Any]:
    """Defaults <- global settings <- project settings. Later wins."""
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in load_global().items() if k in DEFAULTS})
    if cwd is None:
        cwd = Path.cwd()
    merged.update(load_project(cwd))
    return merged
```

- [ ] **Step 2.4: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_config.py -v
```

Expected: `5 passed`.

- [ ] **Step 2.5: Commit**

```bash
git add src/kig_config.py tests/test_kig_config.py
git commit -m "feat(config): merge project .kig/settings.json over global

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3: `kig_scope.py` — `resolve_library()` full matrix

**Files:**

- Create: `src/kig_scope.py`
- Create: `tests/test_kig_scope.py`

- [ ] **Step 3.1: Write the full test matrix**

Create `tests/test_kig_scope.py`:

```python
"""Tests for library scope resolution."""
from kig_scope import Entry, resolve_library, Suppress


def E(text: str, category: str = "misc", entry_id: str | None = None) -> Entry:
    return Entry(id=entry_id or text[:4], text=text, category=category)


def test_isolate_ignores_global():
    g = [E("global-a")]
    p = [E("proj-a")]
    result = resolve_library(g, p, scope_mode="per-category",
                             suppress=Suppress(), isolate=True)
    assert [e.text for e in result] == ["proj-a"]


def test_override_replaces_global_when_project_nonempty():
    g = [E("global-a"), E("global-b")]
    p = [E("proj-a")]
    result = resolve_library(g, p, scope_mode="override",
                             suppress=Suppress(), isolate=False)
    assert [e.text for e in result] == ["proj-a"]


def test_override_falls_back_to_global_when_project_empty():
    g = [E("global-a")]
    result = resolve_library(g, [], scope_mode="override",
                             suppress=Suppress(), isolate=False)
    assert [e.text for e in result] == ["global-a"]


def test_additive_concatenates():
    g = [E("g1"), E("g2")]
    p = [E("p1")]
    result = resolve_library(g, p, scope_mode="additive",
                             suppress=Suppress(), isolate=False)
    assert [e.text for e in result] == ["g1", "g2", "p1"]


def test_per_category_filters_by_category():
    g = [E("g1", category="tests"), E("g2", category="docs")]
    p = [E("p1", category="docs")]
    result = resolve_library(
        g, p, scope_mode="per-category",
        suppress=Suppress(categories={"tests"}), isolate=False,
    )
    assert [e.text for e in result] == ["g2", "p1"]


def test_per_category_filters_by_id():
    g = [E("g1", entry_id="abc"), E("g2", entry_id="def")]
    result = resolve_library(
        g, [], scope_mode="per-category",
        suppress=Suppress(ids={"abc"}), isolate=False,
    )
    assert [e.text for e in result] == ["g2"]


def test_empty_global_empty_project_returns_empty():
    result = resolve_library([], [], scope_mode="per-category",
                             suppress=Suppress(), isolate=False)
    assert result == []


def test_isolate_with_empty_project_returns_empty():
    result = resolve_library([E("g")], [], scope_mode="per-category",
                             suppress=Suppress(), isolate=True)
    assert result == []
```

- [ ] **Step 3.2: Run — expect import failure**

```bash
python3 -m pytest tests/test_kig_scope.py -v
```

Expected: `ModuleNotFoundError: No module named 'kig_scope'`.

- [ ] **Step 3.3: Implement `src/kig_scope.py`**

```python
"""Library scope resolution: merge global + project libraries per scope_mode."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

ScopeMode = Literal["per-category", "additive", "override"]


@dataclass
class Entry:
    id: str
    text: str
    category: str = "misc"


@dataclass
class Suppress:
    categories: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)


def resolve_library(
    global_lib: Iterable[Entry],
    project_lib: Iterable[Entry],
    *,
    scope_mode: ScopeMode,
    suppress: Suppress,
    isolate: bool,
) -> list[Entry]:
    """Merge global and project libraries according to scope_mode.

    Rules (design spec §Dynamic behavior):
      - isolate=True               → project only
      - scope_mode="override"      → project if non-empty else global
      - scope_mode="additive"      → global ++ project (no filtering)
      - scope_mode="per-category"  → filter global by suppress, then ++ project
    """
    g = list(global_lib)
    p = list(project_lib)
    if isolate:
        return p
    if scope_mode == "override":
        return p if p else g
    if scope_mode == "additive":
        return g + p
    filtered = [
        e for e in g
        if e.category not in suppress.categories
        and e.id not in suppress.ids
    ]
    return filtered + p
```

- [ ] **Step 3.4: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_scope.py -v
```

Expected: `8 passed`.

- [ ] **Step 3.5: Commit**

```bash
git add src/kig_scope.py tests/test_kig_scope.py
git commit -m "feat(scope): resolve_library with per-category/additive/override modes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4: `kig_inject.py` — hybrid pin+inject load/save

**Files:**

- Create: `src/kig_inject.py`
- Create: `tests/test_kig_inject.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_kig_inject.py`:

```python
"""Tests for the consolidated inject hybrid store."""
import json
from pathlib import Path

from kig_inject import (
    InjectEntry, InjectStore,
    load_store, save_store, add_entry, remove_entry, toggle_entry,
    set_master, filter_for_mode,
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
    assert [e.text for e in filter_for_mode(store, "simple")] == ["everywhere", "only-simple"]


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
```

- [ ] **Step 4.2: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_inject.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement `src/kig_inject.py`**

```python
"""Consolidated inject: replaces /kig-pin and /kig-inject.

Hybrid model (design spec §2):
  - master_enabled: top-level on/off switch for the whole list
  - entries: ordered list, each individually toggleable, each with a
    `for` filter (subset of [minimal, simple, verbose] OR ["all"] wildcard)
"""
from __future__ import annotations

import datetime as _dt
import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Mode = Literal["minimal", "simple", "verbose"]


@dataclass
class InjectEntry:
    id: str
    text: str
    enabled: bool = True
    for_modes: list[str] = field(default_factory=lambda: ["all"])
    added: str = ""


@dataclass
class InjectStore:
    master_enabled: bool = False
    entries: list[InjectEntry] = field(default_factory=list)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return secrets.token_hex(4)


def load_store(path: Path) -> InjectStore:
    if not path.exists():
        return InjectStore()
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return InjectStore()
    entries = [
        InjectEntry(
            id=e.get("id") or _new_id(),
            text=e.get("text", ""),
            enabled=bool(e.get("enabled", True)),
            for_modes=list(e.get("for", ["all"])),
            added=e.get("added", ""),
        )
        for e in raw.get("entries", [])
    ]
    return InjectStore(
        master_enabled=bool(raw.get("master_enabled", False)),
        entries=entries,
    )


def save_store(path: Path, store: InjectStore) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "master_enabled": store.master_enabled,
        "entries": [
            {
                "id": e.id,
                "text": e.text,
                "enabled": e.enabled,
                "for": e.for_modes,
                "added": e.added,
            }
            for e in store.entries
        ],
    }
    path.write_text(json.dumps(data, indent=2))


def add_entry(path: Path, *, text: str, for_modes: list[str]) -> InjectEntry:
    store = load_store(path)
    entry = InjectEntry(
        id=_new_id(),
        text=text,
        enabled=True,
        for_modes=list(for_modes),
        added=_now_iso(),
    )
    store.entries.append(entry)
    save_store(path, store)
    return entry


def remove_entry(path: Path, one_indexed: int) -> None:
    store = load_store(path)
    idx = one_indexed - 1
    if 0 <= idx < len(store.entries):
        del store.entries[idx]
        save_store(path, store)


def toggle_entry(path: Path, one_indexed: int) -> None:
    store = load_store(path)
    idx = one_indexed - 1
    if 0 <= idx < len(store.entries):
        store.entries[idx].enabled = not store.entries[idx].enabled
        save_store(path, store)


def set_master(path: Path, enabled: bool) -> None:
    store = load_store(path)
    store.master_enabled = enabled
    save_store(path, store)


def filter_for_mode(store: InjectStore, mode: Mode) -> list[InjectEntry]:
    """Return enabled entries whose `for` array matches mode (or wildcard)."""
    if not store.master_enabled:
        return []
    return [
        e for e in store.entries
        if e.enabled and ("all" in e.for_modes or mode in e.for_modes)
    ]
```

- [ ] **Step 4.4: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_inject.py -v
```

Expected: `8 passed`.

- [ ] **Step 4.5: Commit**

```bash
git add src/kig_inject.py tests/test_kig_inject.py
git commit -m "feat(inject): hybrid pin+inject store with master+per-entry toggles

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5: Migration helper — convert old pin/inject files

**Files:**

- Create: `src/kig_migrate.py`
- Create: `tests/test_kig_migrate.py`

- [ ] **Step 5.1: Write failing migration tests**

Create `tests/test_kig_migrate.py`:

```python
"""Tests for one-shot migration from kig-pins.json + kig-inject.txt."""
import json
from pathlib import Path

from kig_inject import load_store
from kig_migrate import migrate_legacy


def test_migrates_pins_file(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-pins.json").write_text(
        json.dumps({"pins": ["do tests first", "commit often"]})
    )
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    store = load_store(kig_home / "inject.json")
    texts = [e.text for e in store.entries]
    assert texts == ["do tests first", "commit often"]
    # archived
    assert (kig_home / "legacy" / "kig-pins.json").exists()
    assert not (claude_home / "kig-pins.json").exists()


def test_migrates_inject_text_and_flag(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-inject.txt").write_text("the whole context block")
    (claude_home / "kig-inject.enabled").touch()
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    store = load_store(kig_home / "inject.json")
    assert [e.text for e in store.entries] == ["the whole context block"]
    assert store.master_enabled is True
    assert (kig_home / "legacy" / "kig-inject.txt").exists()
    assert (kig_home / "legacy" / "kig-inject.enabled").exists()
    assert not (claude_home / "kig-inject.txt").exists()


def test_is_idempotent(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-pins.json").write_text(json.dumps({"pins": ["x"]}))
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)  # no-op
    store = load_store(kig_home / "inject.json")
    assert [e.text for e in store.entries] == ["x"]


def test_merges_pins_and_inject_into_one_store(tmp_path):
    claude_home = tmp_path / ".claude"
    kig_home = claude_home / "kig"
    claude_home.mkdir()
    (claude_home / "kig-pins.json").write_text(json.dumps({"pins": ["a", "b"]}))
    (claude_home / "kig-inject.txt").write_text("ctx")
    migrate_legacy(claude_home=claude_home, kig_home=kig_home)
    store = load_store(kig_home / "inject.json")
    assert [e.text for e in store.entries] == ["a", "b", "ctx"]
```

- [ ] **Step 5.2: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_migrate.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement `src/kig_migrate.py`**

```python
"""One-shot migration from kig-pins.json + kig-inject.txt → kig/inject.json."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from kig_inject import add_entry, load_store, save_store, set_master


def _archive(src: Path, legacy_dir: Path) -> None:
    if not src.exists():
        return
    legacy_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(legacy_dir / src.name))


def migrate_legacy(*, claude_home: Path, kig_home: Path) -> None:
    """Idempotent migration. Safe to run on every install.sh."""
    legacy = kig_home / "legacy"
    inject_path = kig_home / "inject.json"
    kig_home.mkdir(parents=True, exist_ok=True)

    pins_src = claude_home / "kig-pins.json"
    if pins_src.exists():
        try:
            data = json.loads(pins_src.read_text())
            for text in data.get("pins", []):
                if text:
                    add_entry(inject_path, text=text, for_modes=["all"])
        except json.JSONDecodeError:
            pass
        _archive(pins_src, legacy)

    inject_src = claude_home / "kig-inject.txt"
    enabled_src = claude_home / "kig-inject.enabled"
    if inject_src.exists():
        text = inject_src.read_text().strip()
        if text:
            add_entry(inject_path, text=text, for_modes=["all"])
        if enabled_src.exists():
            set_master(inject_path, True)
        _archive(inject_src, legacy)
        _archive(enabled_src, legacy)
```

- [ ] **Step 5.4: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_migrate.py -v
```

Expected: `4 passed`.

- [ ] **Step 5.5: Commit**

```bash
git add src/kig_migrate.py tests/test_kig_migrate.py
git commit -m "feat(migrate): one-shot legacy pin/inject → inject.json converter

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 6: Wire migration + kig-pin deletion into `install.sh`

**Files:**

- Modify: `scripts/install.sh`

- [ ] **Step 6.1: Read current install.sh to find the right insertion point**

```bash
cat ~/GitRepos/KeepItGoing/scripts/install.sh
```

Note where files get copied to `~/.claude/commands/`.

- [ ] **Step 6.2: Add migration call and kig-pin removal**

Append to `scripts/install.sh` (just before the final success message):

```bash
# --- KIG Modes migration (one-shot, idempotent) ---
KIG_HOME="${HOME}/.claude/kig"
mkdir -p "${KIG_HOME}/tabs" "${KIG_HOME}/legacy"

# Run legacy migration
python3 -c "
import sys
sys.path.insert(0, '$(pwd)/src')
from pathlib import Path
from kig_migrate import migrate_legacy
migrate_legacy(claude_home=Path.home() / '.claude', kig_home=Path('${KIG_HOME}'))
"

# Delete old slash command
rm -f "${HOME}/.claude/commands/kig-pin.md"

echo "✓ KIG modes migration complete — legacy files archived to ${KIG_HOME}/legacy/"
```

- [ ] **Step 6.3: Manually verify migration with stub legacy files**

```bash
mkdir -p /tmp/kig-migrate-test/.claude
echo '{"pins": ["test-pin-1"]}' > /tmp/kig-migrate-test/.claude/kig-pins.json
echo "test-inject-text" > /tmp/kig-migrate-test/.claude/kig-inject.txt
touch /tmp/kig-migrate-test/.claude/kig-inject.enabled
HOME=/tmp/kig-migrate-test python3 -c "
import sys; sys.path.insert(0, '$(pwd)/src')
from pathlib import Path
from kig_migrate import migrate_legacy
migrate_legacy(claude_home=Path('/tmp/kig-migrate-test/.claude'),
               kig_home=Path('/tmp/kig-migrate-test/.claude/kig'))
"
cat /tmp/kig-migrate-test/.claude/kig/inject.json
```

Expected output: JSON with `master_enabled: true` and two entries (`test-pin-1`, `test-inject-text`).

- [ ] **Step 6.4: Clean up test fixture**

```bash
rm -rf /tmp/kig-migrate-test
```

- [ ] **Step 6.5: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): wire legacy migration + kig-pin.md deletion

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 7: Open PR for Stage 1

- [ ] **Step 7.1: Push branch**

```bash
git push -u origin feat/kig-modes-stage1
```

- [ ] **Step 7.2: Create GitHub Issue for the whole epic**

```bash
gh issue create \
  --title "[feature]: KIG modes, library & config system (5-stage rollout)" \
  --label feature,enhancement \
  --body "Tracks the full design in \`docs/superpowers/specs/2026-04-19-kig-modes-and-library-design.md\`. 5 stages, 5 PRs. Stage 1 (config foundation) first."
```

Record the issue number (e.g., #42).

- [ ] **Step 7.3: Create Stage 1 PR**

```bash
gh pr create \
  --base develop \
  --title "Stage 1 — KIG config foundation (settings + scope + inject + migration)" \
  --body "$(cat <<'EOF'
## Summary
- `kig_config.py` — defaults + global + project merge
- `kig_scope.py` — `resolve_library()` across per-category / additive / override
- `kig_inject.py` — consolidated pin+inject hybrid store
- `kig_migrate.py` — one-shot converter for `kig-pins.json` + `kig-inject.txt`
- `install.sh` — runs migration on every install, deletes `kig-pin.md`

No user-visible behavior change yet. Foundation only.

## Test plan
- [ ] `python3 -m pytest` — all green (kig_config, kig_scope, kig_inject, kig_migrate)
- [ ] Run `scripts/install.sh` on a machine with stub legacy files; verify conversion
- [ ] Re-run install.sh; verify idempotency (no duplicate entries)

Part of #42 (epic).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 7.4: Dogfood Stage 1**

Run `./scripts/install.sh` on your actual machine, confirm `~/.claude/kig/` is created and any pre-existing `kig-pins.json` / `kig-inject.txt` are archived. Confirm `/kig-pin` slash command is gone. No other behavior change expected.

---

## Stage 2 — Mode routing + seed libraries

**Outcome:** `kig mode minimal` on tab T causes tab T's nudges to come from the tiny minimal library instead of the verbose generator. First-tab use case works.

### Task 8: Create seed `minimal.json`

**Files:**

- Create: `src/kig_seeds/minimal.json`

- [ ] **Step 8.1: Create new branch**

```bash
cd ~/GitRepos/KeepItGoing
git checkout develop
git pull
git checkout -b feat/kig-modes-stage2
```

- [ ] **Step 8.2: Write seed file**

Create `src/kig_seeds/minimal.json`:

```json
{
  "entries": [
    { "id": "min001", "text": "keep going", "category": "minimal" },
    { "id": "min002", "text": "continue", "category": "minimal" },
    { "id": "min003", "text": "don't stop", "category": "minimal" },
    {
      "id": "min004",
      "text": "you have more to finish",
      "category": "minimal"
    },
    { "id": "min005", "text": "keep working", "category": "minimal" },
    { "id": "min006", "text": "not done yet", "category": "minimal" },
    { "id": "min007", "text": "there's more", "category": "minimal" },
    { "id": "min008", "text": "push through", "category": "minimal" },
    { "id": "min009", "text": "what's next?", "category": "minimal" },
    { "id": "min010", "text": "resume", "category": "minimal" },
    { "id": "min011", "text": "pick back up", "category": "minimal" },
    { "id": "min012", "text": "don't pause", "category": "minimal" },
    { "id": "min013", "text": "stay focused", "category": "minimal" },
    { "id": "min014", "text": "finish it", "category": "minimal" },
    { "id": "min015", "text": "keep at it", "category": "minimal" }
  ]
}
```

- [ ] **Step 8.3: Commit**

```bash
git add src/kig_seeds/minimal.json
git commit -m "feat(seeds): minimal-mode library (15 short nudges)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 9: Create seed `simple.json`

**Files:**

- Create: `src/kig_seeds/simple.json`

- [ ] **Step 9.1: Write seed file with 50 entries**

Create `src/kig_seeds/simple.json`:

```json
{
  "entries": [
    {
      "id": "s001",
      "text": "keep going — break the task into the next small step",
      "category": "simple"
    },
    {
      "id": "s002",
      "text": "continue. Run the tests if you're at a checkpoint.",
      "category": "simple"
    },
    {
      "id": "s003",
      "text": "don't pause. Commit what's working and keep moving.",
      "category": "simple"
    },
    {
      "id": "s004",
      "text": "what's the next subtask? Name it and start it.",
      "category": "simple"
    },
    {
      "id": "s005",
      "text": "if you're stuck, say what's blocking — out loud is clearer.",
      "category": "simple"
    },
    {
      "id": "s006",
      "text": "small step forward. Don't try to finish in one leap.",
      "category": "simple"
    },
    {
      "id": "s007",
      "text": "check git status, then keep going from the last good point.",
      "category": "simple"
    },
    {
      "id": "s008",
      "text": "you've got momentum. Don't break it looking for perfection.",
      "category": "simple"
    },
    {
      "id": "s009",
      "text": "ship working code now; refine in the next commit.",
      "category": "simple"
    },
    {
      "id": "s010",
      "text": "re-read the last task description. What haven't you done?",
      "category": "simple"
    },
    {
      "id": "s011",
      "text": "pick the smallest remaining thing and finish it.",
      "category": "simple"
    },
    {
      "id": "s012",
      "text": "run the tests. Green? Keep going. Red? Fix first.",
      "category": "simple"
    },
    {
      "id": "s013",
      "text": "you're closer than you think. Keep pushing.",
      "category": "simple"
    },
    {
      "id": "s014",
      "text": "don't start something new — finish the current thing.",
      "category": "simple"
    },
    {
      "id": "s015",
      "text": "save progress with a commit, then continue.",
      "category": "simple"
    },
    {
      "id": "s016",
      "text": "what's the acceptance criterion? Are you meeting it?",
      "category": "simple"
    },
    {
      "id": "s017",
      "text": "keep it simple. No new abstractions unless needed.",
      "category": "simple"
    },
    {
      "id": "s018",
      "text": "walk through the edge cases. Did you cover empty input?",
      "category": "simple"
    },
    {
      "id": "s019",
      "text": "what would you do if you had 5 more minutes? Do that.",
      "category": "simple"
    },
    { "id": "s020", "text": "stop narrating. Execute.", "category": "simple" },
    {
      "id": "s021",
      "text": "the test is the spec. Does it pass?",
      "category": "simple"
    },
    {
      "id": "s022",
      "text": "check the file you last edited. Is it saved?",
      "category": "simple"
    },
    {
      "id": "s023",
      "text": "one clear step, then the next. Don't jump around.",
      "category": "simple"
    },
    {
      "id": "s024",
      "text": "if the fix is 3 lines, write 3 lines. Don't refactor.",
      "category": "simple"
    },
    {
      "id": "s025",
      "text": "read the error message carefully, then act.",
      "category": "simple"
    },
    {
      "id": "s026",
      "text": "you have the answer already. Just write it.",
      "category": "simple"
    },
    {
      "id": "s027",
      "text": "commit the failing test first, then make it pass.",
      "category": "simple"
    },
    {
      "id": "s028",
      "text": "re-read the requirement. Is this actually what was asked?",
      "category": "simple"
    },
    {
      "id": "s029",
      "text": "don't add features the task didn't ask for.",
      "category": "simple"
    },
    {
      "id": "s030",
      "text": "is there a simpler version of this that would work?",
      "category": "simple"
    },
    {
      "id": "s031",
      "text": "finish the current PR before starting a new one.",
      "category": "simple"
    },
    {
      "id": "s032",
      "text": "the plan is in the spec. Follow it task-by-task.",
      "category": "simple"
    },
    {
      "id": "s033",
      "text": "short commits, clear messages. Keep going.",
      "category": "simple"
    },
    {
      "id": "s034",
      "text": "a failing test is progress. Green it and move on.",
      "category": "simple"
    },
    {
      "id": "s035",
      "text": "the next step is obvious once you look at the code.",
      "category": "simple"
    },
    {
      "id": "s036",
      "text": "don't polish. Get it working first.",
      "category": "simple"
    },
    {
      "id": "s037",
      "text": "what does the test expect? Match that shape exactly.",
      "category": "simple"
    },
    {
      "id": "s038",
      "text": "trust the scaffolding. Don't rebuild what's already there.",
      "category": "simple"
    },
    {
      "id": "s039",
      "text": "keep the diff small. Easier to review, easier to revert.",
      "category": "simple"
    },
    {
      "id": "s040",
      "text": "what's left on the checklist? Do the next box.",
      "category": "simple"
    },
    {
      "id": "s041",
      "text": "one file at a time. Finish, save, move.",
      "category": "simple"
    },
    {
      "id": "s042",
      "text": "don't over-engineer. YAGNI.",
      "category": "simple"
    },
    {
      "id": "s043",
      "text": "are the tests green? If yes, ship it.",
      "category": "simple"
    },
    {
      "id": "s044",
      "text": "what's the 20% that gets 80% done right now?",
      "category": "simple"
    },
    {
      "id": "s045",
      "text": "the blocker is almost always smaller than it feels.",
      "category": "simple"
    },
    {
      "id": "s046",
      "text": "stop reading code. Start writing.",
      "category": "simple"
    },
    {
      "id": "s047",
      "text": "if it runs, commit it. Then improve.",
      "category": "simple"
    },
    {
      "id": "s048",
      "text": "don't second-guess a passing test.",
      "category": "simple"
    },
    {
      "id": "s049",
      "text": "the feature isn't done until it's dogfooded.",
      "category": "simple"
    },
    {
      "id": "s050",
      "text": "you're 2 minutes from finished. Keep going.",
      "category": "simple"
    }
  ]
}
```

- [ ] **Step 9.2: Commit**

```bash
git add src/kig_seeds/simple.json
git commit -m "feat(seeds): simple-mode library (50 short nudges)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10: `kig_modes.py` — mode-based library loader and nudge picker

**Files:**

- Create: `src/kig_modes.py`
- Create: `tests/test_kig_modes.py`

- [ ] **Step 10.1: Write failing tests**

Create `tests/test_kig_modes.py`:

```python
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
```

- [ ] **Step 10.2: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_modes.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 10.3: Implement `src/kig_modes.py`**

```python
"""Mode routing: picks the nudge text based on per-tab mode.

- minimal → random line from minimal seed + project/global additions
- simple  → random line from simple seed + project/global additions
- verbose → delegates to existing keepitgoing-generate.py
"""
from __future__ import annotations

import importlib
import json
import random
from pathlib import Path
from typing import Literal

from kig_config import find_project_kig, global_kig_dir
from kig_scope import Entry, Suppress, resolve_library

Mode = Literal["minimal", "simple", "verbose"]

SEEDS_DIR = Path(__file__).resolve().parent / "kig_seeds"


def _read_entries(path: Path) -> list[Entry]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return [
        Entry(id=e["id"], text=e["text"], category=e.get("category", "misc"))
        for e in data.get("entries", [])
    ]


def load_mode_library(mode: Mode, cwd: Path | None = None) -> list[Entry]:
    """Load the resolved (global ∪ project) library for a mode."""
    if mode not in ("minimal", "simple"):
        return []
    seed = _read_entries(SEEDS_DIR / f"{mode}.json")
    global_file = global_kig_dir() / f"{mode}.json"
    global_extra = _read_entries(global_file)
    global_all = seed + global_extra

    project_lib: list[Entry] = []
    if cwd is None:
        cwd = Path.cwd()
    proj = find_project_kig(cwd)
    if proj is not None:
        project_lib = _read_entries(proj / f"{mode}.json")

    return resolve_library(
        global_all, project_lib,
        scope_mode="per-category",
        suppress=Suppress(),
        isolate=(proj is not None and (proj / "isolate").exists()),
    )


def verbose_generate(cwd: Path) -> str:
    """Invoke the existing verbose generator. Overridable in tests."""
    mod = importlib.import_module("keepitgoing-generate".replace("-", "_"))
    return mod.generate(cwd=str(cwd))


def pick_nudge(*, mode: Mode, cwd: Path) -> str:
    """Return the text to send in the next nudge."""
    if mode == "verbose":
        return verbose_generate(cwd)
    lib = load_mode_library(mode, cwd=cwd)
    if not lib:
        return "keep going"  # last-resort fallback
    return random.choice(lib).text
```

- [ ] **Step 10.4: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_modes.py -v
```

Expected: `4 passed`.

- [ ] **Step 10.5: Commit**

```bash
git add src/kig_modes.py tests/test_kig_modes.py
git commit -m "feat(modes): route nudge generation by per-tab mode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 11: Per-tab state helper

**Files:**

- Create: `src/kig_tab_state.py`
- Create: `tests/test_kig_tab_state.py`

- [ ] **Step 11.1: Write failing tests**

Create `tests/test_kig_tab_state.py`:

```python
"""Tests for per-tab state file."""
import json
from pathlib import Path

from kig_tab_state import TabState, load_tab, save_tab, set_mode, clear_mute, set_mute_until


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
```

- [ ] **Step 11.2: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_tab_state.py -v
```

- [ ] **Step 11.3: Implement `src/kig_tab_state.py`**

```python
"""Per-tab state: one JSON file per iTerm tab TTY."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from kig_config import global_kig_dir


@dataclass
class TabState:
    mode: str = "verbose"
    kig_on: bool = True
    mute_until: str | None = None
    last_prompt_sent: str | None = None


def _tab_path(tty: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tty)
    return global_kig_dir() / "tabs" / f"{safe}.json"


def load_tab(tty: str) -> TabState:
    path = _tab_path(tty)
    if not path.exists():
        return TabState()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return TabState()
    return TabState(
        mode=data.get("mode", "verbose"),
        kig_on=bool(data.get("kig_on", True)),
        mute_until=data.get("mute_until"),
        last_prompt_sent=data.get("last_prompt_sent"),
    )


def save_tab(tty: str, state: TabState) -> None:
    path = _tab_path(tty)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))


def set_mode(tty: str, mode: str) -> None:
    state = load_tab(tty)
    state.mode = mode
    save_tab(tty, state)


def set_mute_until(tty: str, iso: str) -> None:
    state = load_tab(tty)
    state.mute_until = iso
    save_tab(tty, state)


def clear_mute(tty: str) -> None:
    state = load_tab(tty)
    state.mute_until = None
    save_tab(tty, state)
```

- [ ] **Step 11.4: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_tab_state.py -v
```

Expected: `5 passed`.

- [ ] **Step 11.5: Commit**

```bash
git add src/kig_tab_state.py tests/test_kig_tab_state.py
git commit -m "feat(state): per-tab state file (mode, kig_on, mute_until)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 12: Extend `bin/kig` with `mode` subcommand

**Files:**

- Modify: `bin/kig`

- [ ] **Step 12.1: Read current `bin/kig` to understand the CLI framework**

```bash
head -80 ~/GitRepos/KeepItGoing/bin/kig
```

Note how current subcommands (`on`, `off`, `status`) are dispatched.

- [ ] **Step 12.2: Add `mode` subcommand dispatcher**

In the case/switch at the end of `bin/kig`, add a new branch:

```bash
mode)
    TTY="$(tty 2>/dev/null || echo 'unknown')"
    NEW_MODE="${2:-}"
    if [ -z "${NEW_MODE}" ]; then
        python3 -c "
import sys
sys.path.insert(0, '$(dirname "$0")/../src' if False else '${HOME}/.claude/kig/_src')
from kig_tab_state import load_tab
print(load_tab('${TTY}').mode)
"
        exit 0
    fi
    case "${NEW_MODE}" in
        minimal|simple|verbose) ;;
        *) echo "Error: mode must be minimal|simple|verbose" >&2; exit 2;;
    esac
    python3 -c "
import sys
sys.path.insert(0, '${HOME}/.claude/kig/_src')
from kig_tab_state import set_mode
set_mode('${TTY}', '${NEW_MODE}')
"
    echo "Tab ${TTY}: mode=${NEW_MODE}"
    ;;
```

- [ ] **Step 12.3: Extend `install.sh` to copy `src/*.py` into `~/.claude/kig/_src/` for runtime**

In `scripts/install.sh`, after the migration block, add:

```bash
# Copy Python runtime modules to a stable location CLI tools can import from
KIG_SRC="${HOME}/.claude/kig/_src"
mkdir -p "${KIG_SRC}"
cp -v src/kig_config.py src/kig_scope.py src/kig_inject.py \
      src/kig_modes.py src/kig_tab_state.py src/kig_migrate.py \
      "${KIG_SRC}/"
# Seeds too
mkdir -p "${KIG_SRC}/kig_seeds"
cp -v src/kig_seeds/*.json "${KIG_SRC}/kig_seeds/"
```

- [ ] **Step 12.4: Manually test the mode subcommand**

```bash
./scripts/install.sh
# Open a new iTerm tab, then:
kig mode minimal
kig mode
# Expected: "Tab /dev/ttysXXX: mode=minimal" then "minimal"
kig mode verbose
kig mode
# Expected: "verbose"
```

- [ ] **Step 12.5: Commit**

```bash
git add bin/kig scripts/install.sh
git commit -m "feat(cli): 'kig mode' subcommand — per-tab mode setting

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 13: Wire AppleScript to read per-tab mode and route prompt generation

**Files:**

- Modify: `src/main.applescript`

- [ ] **Step 13.1: Find the prompt-generation call in `main.applescript`**

```bash
grep -n "keepitgoing-generate" ~/GitRepos/KeepItGoing/src/main.applescript
```

Note the line number where the Python generator is invoked.

- [ ] **Step 13.2: Replace the direct generator call with a mode-aware dispatch**

In `main.applescript`, find the section that does `set prompt_text to do shell script "python3 ... keepitgoing-generate.py ..."`. Replace with a helper that reads the tab state first.

Add this handler near the top of `main.applescript`:

```applescript
on pickNudgeForTab(ttyName, cwdPath)
    set kigSrc to (POSIX path of (path to home folder)) & ".claude/kig/_src"
    set shellCmd to "python3 -c \"
import sys
sys.path.insert(0, '" & kigSrc & "')
from kig_tab_state import load_tab
from kig_modes import pick_nudge
from pathlib import Path
state = load_tab('" & ttyName & "')
if not state.kig_on:
    print('__KIG_SKIP__')
else:
    print(pick_nudge(mode=state.mode, cwd=Path('" & cwdPath & "')))
\""
    return do shell script shellCmd
end pickNudgeForTab
```

Replace the existing direct generator call with:

```applescript
set nudgeText to my pickNudgeForTab(currentTTY, currentCwd)
if nudgeText is "__KIG_SKIP__" then
    return
end if
-- existing code that sends nudgeText to the tab
```

(`currentTTY` and `currentCwd` are existing variables in `main.applescript` — adapt names to the actual ones used in the file.)

- [ ] **Step 13.3: Rebuild and relaunch the app**

```bash
pkill -f "KeepItGoing-ClaudeChat" || true
./scripts/build.sh
open dist/KeepItGoing-ClaudeChat.app
```

- [ ] **Step 13.4: Dogfood — first-tab minimal mode**

In iTerm tab 1 (the one running Claude Code), run:

```bash
kig mode minimal
```

Wait one poll interval (30s). Watch `/tmp/claude-keepitgoing/app.log` — verify that the next nudge is one of the 15 minimal entries (e.g., `"keep going"`, `"continue"`), not a verbose directive.

```bash
tail -f /tmp/claude-keepitgoing/app.log
```

- [ ] **Step 13.5: Commit**

```bash
git add src/main.applescript
git commit -m "feat(monitor): AppleScript reads per-tab mode, routes to kig_modes.pick_nudge

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 14: Open PR for Stage 2

- [ ] **Step 14.1: Push and open PR**

```bash
git push -u origin feat/kig-modes-stage2
gh pr create \
  --base develop \
  --title "Stage 2 — KIG mode routing + seed libraries (minimal/simple/verbose)" \
  --body "$(cat <<'EOF'
## Summary
- `src/kig_seeds/minimal.json` (15 entries) and `simple.json` (50 entries)
- `src/kig_modes.py` — mode dispatch, seed loader, verbose delegation
- `src/kig_tab_state.py` — per-tab state file (TTY → `{mode, kig_on, mute_until}`)
- `bin/kig mode <minimal|simple|verbose>` CLI
- `src/main.applescript` reads per-tab mode, routes prompt generation

`kig mode minimal` on first tab now produces tiny nudges instead of the full verbose engine.

## Test plan
- [ ] `python3 -m pytest` — all green (kig_modes, kig_tab_state)
- [ ] Manual: `kig mode minimal` on iTerm tab 1, verify next nudge is a seed entry
- [ ] Manual: `kig mode simple`, verify next nudge is a simple-library entry
- [ ] Manual: `kig mode verbose`, verify existing generator output
- [ ] Manual: `kig mode` with no arg prints current mode

Part of #42.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 14.2: Dogfood live**

Run your real-world use case: Claude Code in iTerm tab 1, `kig mode minimal`. Verify a full hour of nudges are all from the minimal library.

---

## Stage 3 — Slash commands (`/kig-inject` + `/kig-library`, delete `/kig-pin`)

**Outcome:** The consolidated `/kig-inject` and the new `/kig-library` slash commands work. Old `/kig-pin` removed.

### Task 15: Python helper `bin/kig-inject-cmd.py`

**Files:**

- Create: `bin/kig-inject-cmd.py`
- Create: `tests/test_kig_inject_cmd.py`

- [ ] **Step 15.1: Create branch**

```bash
git checkout develop && git pull
git checkout -b feat/kig-modes-stage3
```

- [ ] **Step 15.2: Write failing tests for the helper**

Create `tests/test_kig_inject_cmd.py`:

```python
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
        capture_output=True, text=True, check=False,
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
```

- [ ] **Step 15.3: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_inject_cmd.py -v
```

Expected: helper not found.

- [ ] **Step 15.4: Implement `bin/kig-inject-cmd.py`**

```python
#!/usr/bin/env python3
"""CLI helper backing the /kig-inject slash command."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kig_config import find_project_kig, global_kig_dir
from kig_inject import (
    add_entry, load_store, remove_entry, save_store,
    set_master, toggle_entry,
)


def resolve_inject_path(is_global: bool) -> Path:
    if is_global:
        return global_kig_dir() / "inject.json"
    proj = find_project_kig(Path.cwd())
    if proj is None:
        # Create .kig/ in cwd for project-scope default
        proj = Path.cwd() / ".kig"
        proj.mkdir(exist_ok=True)
    return proj / "inject.json"


def cmd_add(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    entry = add_entry(path, text=args.text, for_modes=args.f)
    print(f"Added [{len(load_store(path).entries)}]: {entry.text}")
    print(f"  for: {','.join(entry.for_modes)}")
    print(f"  saved to: {path}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    before = len(load_store(path).entries)
    remove_entry(path, args.n)
    after = len(load_store(path).entries)
    print(f"Removed entry #{args.n}. {after} remain (was {before}).")
    return 0


def cmd_toggle(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    toggle_entry(path, args.n)
    store = load_store(path)
    idx = args.n - 1
    if 0 <= idx < len(store.entries):
        state = "on" if store.entries[idx].enabled else "off"
        print(f"Entry #{args.n}: now {state}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    store = load_store(path)
    print(f"master: {'on' if store.master_enabled else 'off'}")
    if not store.entries:
        print("(no entries)")
        return 0
    for i, e in enumerate(store.entries, start=1):
        state = "on" if e.enabled else "off"
        tag = ",".join(e.for_modes)
        print(f"  [{i}] {state} ({tag}) — {e.text}")
    print(f"source: {path}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    return cmd_list(args)


def cmd_on(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    set_master(path, True)
    print(f"master: on ({path})")
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    set_master(path, False)
    print(f"master: off ({path})")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    path = resolve_inject_path(args.g)
    from kig_inject import InjectStore
    save_store(path, InjectStore(master_enabled=False, entries=[]))
    print(f"cleared: {path}")
    return 0


HELP = """\
/kig-inject — consolidated context injection (replaces /kig-pin + old /kig-inject)

SUBCOMMANDS
  add [--global] [--for all|minimal|simple|verbose ...] "text"
  remove [--global] <N>
  toggle [--global] <N>     # flip enabled/disabled for entry N
  list [--global]
  show [--global]           # alias for list
  on [--global]             # master switch on
  off [--global]            # master switch off
  clear [--global]          # wipe all entries + master off
  help

EXAMPLES
  /kig-inject add "working on Rust crate; don't touch Python"
  /kig-inject add --for simple "check logs at /tmp/claude-keepitgoing/"
  /kig-inject list
  /kig-inject toggle 2
  /kig-inject off

SAVES TO
  Project:  ./.kig/inject.json (default)
  Global:   ~/.claude/kig/inject.json (with --global)
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP)
        return 0
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-g", "--global", dest="g", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("-f", "--for", nargs="+", default=["all"], dest="f")
    a.add_argument("text")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove")
    r.add_argument("n", type=int)
    r.set_defaults(func=cmd_remove)

    t = sub.add_parser("toggle")
    t.add_argument("n", type=int)
    t.set_defaults(func=cmd_toggle)

    for name, fn in [("list", cmd_list), ("show", cmd_show),
                     ("on", cmd_on), ("off", cmd_off), ("clear", cmd_clear)]:
        s = sub.add_parser(name)
        s.set_defaults(func=fn)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 15.5: Make executable and run tests**

```bash
chmod +x bin/kig-inject-cmd.py
python3 -m pytest tests/test_kig_inject_cmd.py -v
```

Expected: `4 passed`.

- [ ] **Step 15.6: Commit**

```bash
git add bin/kig-inject-cmd.py tests/test_kig_inject_cmd.py
git commit -m "feat(cli): /kig-inject backing script with full CRUD + master toggle

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 16: Python helper `bin/kig-library-cmd.py`

**Files:**

- Create: `bin/kig-library-cmd.py`
- Create: `tests/test_kig_library_cmd.py`

- [ ] **Step 16.1: Write failing tests**

Create `tests/test_kig_library_cmd.py`:

```python
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
        capture_output=True, text=True, check=False,
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
```

- [ ] **Step 16.2: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_library_cmd.py -v
```

- [ ] **Step 16.3: Implement `bin/kig-library-cmd.py`**

```python
#!/usr/bin/env python3
"""CLI helper backing the /kig-library slash command."""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

from kig_config import find_project_kig, global_kig_dir


def resolve_scope_dir(is_global: bool) -> Path:
    if is_global:
        d = global_kig_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d
    proj = find_project_kig(Path.cwd())
    if proj is None:
        proj = Path.cwd() / ".kig"
        proj.mkdir(exist_ok=True)
    return proj


def _lib_path(scope_dir: Path, mode: str) -> Path:
    # verbose additions live in verbose-entries.json; minimal/simple each in their own file
    if mode == "verbose":
        return scope_dir / "verbose-entries.json"
    return scope_dir / f"{mode}.json"


def _load_lib(path: Path) -> dict:
    if not path.exists():
        return {"entries": []}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"entries": []}


def _save_lib(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _expand_for(for_arg: list[str]) -> list[str]:
    if "all" in for_arg:
        return ["minimal", "simple", "verbose"]
    return for_arg


def cmd_add(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(args.g)
    for mode in _expand_for(args.f):
        path = _lib_path(scope, mode)
        data = _load_lib(path)
        data["entries"].append({
            "id": secrets.token_hex(4),
            "text": args.text,
            "category": f"user-{mode}",
        })
        _save_lib(path, data)
        print(f"Added to {path}: {args.text}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(args.g)
    mode = args.mode
    path = _lib_path(scope, mode)
    data = _load_lib(path)
    idx = args.n - 1
    if 0 <= idx < len(data["entries"]):
        removed = data["entries"].pop(idx)
        _save_lib(path, data)
        print(f"Removed: {removed['text']}")
    else:
        print(f"Index {args.n} out of range (have {len(data['entries'])})", file=sys.stderr)
        return 2
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(args.g)
    for mode in ("minimal", "simple", "verbose"):
        path = _lib_path(scope, mode)
        data = _load_lib(path)
        print(f"[{mode}] {path}")
        if not data["entries"]:
            print("  (no entries)")
            continue
        for i, e in enumerate(data["entries"], start=1):
            print(f"  [{i}] {e['text']}")
    return 0


def cmd_isolate(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(False)  # isolate is always project
    (scope / "isolate").touch()
    print(f"isolated: {scope}")
    return 0


def cmd_unisolate(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(False)
    marker = scope / "isolate"
    if marker.exists():
        marker.unlink()
    print(f"unisolated: {scope}")
    return 0


def cmd_suppress(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(False)
    path = scope / "suppress.json"
    data = _load_lib(path) if path.exists() else {"categories": [], "ids": []}
    if "categories" not in data:
        data["categories"] = []
    if "ids" not in data:
        data["ids"] = []
    # Heuristic: treat short lowercase word as category, hex-ish as id
    target = args.target
    if all(c.isalnum() or c == "_" for c in target) and not target.startswith("directive_"):
        if target not in data["categories"]:
            data["categories"].append(target)
    else:
        if target not in data["ids"]:
            data["ids"].append(target)
    path.write_text(json.dumps(data, indent=2))
    print(f"suppressed: {target} → {path}")
    return 0


def cmd_unsuppress(args: argparse.Namespace) -> int:
    scope = resolve_scope_dir(False)
    path = scope / "suppress.json"
    if not path.exists():
        print("no suppress list")
        return 0
    data = json.loads(path.read_text())
    for key in ("categories", "ids"):
        if args.target in data.get(key, []):
            data[key].remove(args.target)
    path.write_text(json.dumps(data, indent=2))
    print(f"unsuppressed: {args.target}")
    return 0


HELP = """\
/kig-library — manage the nudge-sentence library

SUBCOMMANDS
  add [--global] [--for all|minimal|simple|verbose ...] "text"
  remove [--global] --mode <minimal|simple|verbose> <N>
  list [--global]
  suppress <category-or-id>      # only makes sense for project scope
  unsuppress <id>
  isolate                        # this project ignores globals completely
  unisolate
  help

EXAMPLES
  /kig-library add "don't commit compiled .app bundles"
  /kig-library add --global --for simple "check the logs at /tmp/..."
  /kig-library suppress visual_verification
  /kig-library isolate

SAVES TO
  Project:  ./.kig/{verbose-entries,minimal,simple,suppress}.json
  Global:   ~/.claude/kig/{verbose-entries,minimal,simple,suppress}.json
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP); return 0
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-g", "--global", dest="g", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("-f", "--for", nargs="+", default=["all"], dest="f")
    a.add_argument("text")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove")
    r.add_argument("--mode", required=True, choices=["minimal", "simple", "verbose"])
    r.add_argument("n", type=int)
    r.set_defaults(func=cmd_remove)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("isolate").set_defaults(func=cmd_isolate)
    sub.add_parser("unisolate").set_defaults(func=cmd_unisolate)

    s = sub.add_parser("suppress"); s.add_argument("target"); s.set_defaults(func=cmd_suppress)
    u = sub.add_parser("unsuppress"); u.add_argument("target"); u.set_defaults(func=cmd_unsuppress)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 16.4: Make executable and run tests**

```bash
chmod +x bin/kig-library-cmd.py
python3 -m pytest tests/test_kig_library_cmd.py -v
```

Expected: `4 passed`.

- [ ] **Step 16.5: Commit**

```bash
git add bin/kig-library-cmd.py tests/test_kig_library_cmd.py
git commit -m "feat(cli): /kig-library backing script with add/remove/list/suppress/isolate

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 17: Slash-command markdown files

**Files:**

- Modify: `~/.claude/commands/kig-inject.md`
- Create: `~/.claude/commands/kig-library.md`
- Create: project-local copies under `.claude/commands/` (to be installed)

- [ ] **Step 17.1: Create install-source versions**

Create `config/kig-inject.md.tmpl`:

````markdown
---
description: Consolidated pin+inject hybrid — prepend user context to KIG nudges
argument-hint: [add|remove|toggle|list|on|off|clear|help] [--global] [--for MODE...] [text]
allowed-tools: Bash
---

# /kig-inject — consolidated context injection

Replaces the old `/kig-pin` + `/kig-inject`. Use this to save reminders/context that KIG prepends to every nudge. Entries form a list; each is individually toggleable; a master switch turns the whole block on/off.

Run the backing script with the user's arguments:

```bash
~/.claude/kig/_src/../../../bin/kig-inject-cmd.py "$@"
```
````

## Subcommands

| Command                               | Effect                                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------ |
| `add [--global] [--for MODES] "text"` | Append entry (MODES = one or more of `all`, `minimal`, `simple`, `verbose`; default `all`) |
| `remove [--global] <N>`               | Remove entry by 1-indexed position                                                         |
| `toggle [--global] <N>`               | Flip entry's enabled/disabled without removing                                             |
| `list [--global]`                     | Show all entries with state and mode tags                                                  |
| `show [--global]`                     | Alias for list                                                                             |
| `on [--global]`                       | Master switch on                                                                           |
| `off [--global]`                      | Master switch off (entries preserved)                                                      |
| `clear [--global]`                    | Wipe all entries                                                                           |
| `help`                                | This text                                                                                  |

## Examples

```
/kig-inject add "working on Rust crate — don't touch Python files"
/kig-inject add --for simple "check logs at /tmp/claude-keepitgoing/"
/kig-inject list
/kig-inject toggle 2
/kig-inject off
```

## Saves to

- Project (default): `./.kig/inject.json`
- Global (`--global`): `~/.claude/kig/inject.json`

````

Create `config/kig-library.md.tmpl`:

```markdown
---
description: Manage the KIG nudge-sentence library (project-scoped by default)
argument-hint: [add|remove|list|suppress|isolate|help] [--global] [--for MODE...] [text-or-target]
allowed-tools: Bash
---

# /kig-library — manage nudge sentences

Add or remove sentences the KIG monitor pulls from when nudging. Project scope by default; `--global` to affect every project. Use `suppress` to opt out of specific global categories, or `isolate` for a full blackout of globals.

Run the backing script with the user's arguments:

```bash
~/.claude/kig/_src/../../../bin/kig-library-cmd.py "$@"
````

## Subcommands

| Command                               | Effect                                                     |
| ------------------------------------- | ---------------------------------------------------------- |
| `add [--global] [--for MODES] "text"` | Add an entry; defaults to all three modes                  |
| `remove [--global] --mode MODE <N>`   | Remove Nth entry in that mode's library                    |
| `list [--global]`                     | Show all entries in all three modes                        |
| `suppress <category-or-id>`           | (project only) hide a global category/id from this project |
| `unsuppress <id>`                     | Undo a suppress                                            |
| `isolate`                             | (project only) ignore all globals for this project         |
| `unisolate`                           | Restore globals                                            |
| `help`                                | This text                                                  |

## Examples

```
/kig-library add "don't commit compiled .app bundles"
/kig-library add --global --for simple "run tests before committing"
/kig-library suppress visual_verification
/kig-library isolate
```

## Saves to

- Project: `./.kig/{verbose-entries,minimal,simple,suppress}.json`, `./.kig/isolate`
- Global (`--global`): `~/.claude/kig/{verbose-entries,minimal,simple}.json`

````

- [ ] **Step 17.2: Wire installer to copy templates into place**

In `scripts/install.sh`, after the `KIG_SRC` copy block, add:

```bash
# Install slash commands
CMD_DIR="${HOME}/.claude/commands"
mkdir -p "${CMD_DIR}"
cp config/kig-inject.md.tmpl "${CMD_DIR}/kig-inject.md"
cp config/kig-library.md.tmpl "${CMD_DIR}/kig-library.md"
````

- [ ] **Step 17.3: Run install, exercise commands**

```bash
./scripts/install.sh
# In Claude Code:
/kig-inject help
/kig-inject add "test entry"
/kig-inject list
/kig-library help
/kig-library add "project test entry"
/kig-library list
```

Verify each command prints expected output.

- [ ] **Step 17.4: Commit**

```bash
git add config/kig-inject.md.tmpl config/kig-library.md.tmpl scripts/install.sh
git commit -m "feat(commands): /kig-inject (consolidated) and /kig-library slash commands

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 18: PR for Stage 3

- [ ] **Step 18.1: Push and open PR**

```bash
git push -u origin feat/kig-modes-stage3
gh pr create \
  --base develop \
  --title "Stage 3 — Consolidated /kig-inject + /kig-library; /kig-pin deleted" \
  --body "$(cat <<'EOF'
## Summary
- `bin/kig-inject-cmd.py` — full CRUD backing script
- `bin/kig-library-cmd.py` — add/remove/list/suppress/isolate backing
- `config/kig-{inject,library}.md.tmpl` — slash-command markdown
- Installer copies templates into `~/.claude/commands/`
- `/kig-pin.md` removed (via Stage 1 installer)

## Test plan
- [ ] `python3 -m pytest` — green
- [ ] In Claude Code: `/kig-inject add "x"`, `/kig-inject list`, `/kig-inject remove 1`
- [ ] `/kig-library add "y"`, `/kig-library list`, `/kig-library suppress visual_verification`
- [ ] Confirm `~/.claude/commands/kig-pin.md` gone

Part of #42.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Stage 4 — `/loop` lifecycle

**Outcome:** When Claude Code runs `/loop`, KIG auto-mutes the tab within ≤30s of the cron starting, and auto-resumes within ≤30s of the cron being torn down. Plus: in verbose mode, KIG occasionally suggests `/loop` when work looks long-running.

### Task 19: `kig_loop_state.py` — tty-scoped loop tracker

**Files:**

- Create: `src/kig_loop_state.py`
- Create: `tests/test_kig_loop_state.py`

- [ ] **Step 19.1: Create branch**

```bash
git checkout develop && git pull
git checkout -b feat/kig-modes-stage4
```

- [ ] **Step 19.2: Write failing tests**

Create `tests/test_kig_loop_state.py`:

```python
"""Tests for /loop lifecycle state tracking."""
import datetime as dt
import json
from pathlib import Path

from kig_loop_state import (
    record_loop_start, record_loop_end, is_loop_active,
    clear_if_stale, LOOP_STATE_DIR, STALE_MINUTES,
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
```

- [ ] **Step 19.3: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_loop_state.py -v
```

- [ ] **Step 19.4: Implement `src/kig_loop_state.py`**

```python
"""Tracks Claude Code /loop lifecycle per iTerm tab."""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
from pathlib import Path

LOOP_STATE_DIR = Path("/tmp/claude-keepitgoing")
STALE_MINUTES = 30


def _state_path(tty: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tty)
    LOOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return LOOP_STATE_DIR / f"loop-state-{safe}.json"


def _load(tty: str) -> dict:
    path = _state_path(tty)
    if not path.exists():
        return {"active": False}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"active": False}


def _save(tty: str, data: dict) -> None:
    _state_path(tty).write_text(json.dumps(data, indent=2))


def record_loop_start(tty: str, *, cron_id: str) -> None:
    _save(tty, {
        "active": True,
        "started": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "cron_id": cron_id,
    })


def record_loop_end(tty: str, *, cron_id: str, reason: str = "stopped") -> None:
    cur = _load(tty)
    # only flip if cron_id matches (avoid cross-loop interference)
    if cur.get("active") and cur.get("cron_id") == cron_id:
        _save(tty, {
            "active": False,
            "ended": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "reason": reason,
        })


def is_loop_active(tty: str) -> bool:
    return bool(_load(tty).get("active"))


def clear_if_stale(tty: str) -> bool:
    """Force-clear if state file hasn't been modified in STALE_MINUTES."""
    path = _state_path(tty)
    if not path.exists():
        return False
    mtime = path.stat().st_mtime
    if time.time() - mtime > STALE_MINUTES * 60:
        _save(tty, {"active": False, "reason": "stale_auto_clear"})
        return True
    return False
```

- [ ] **Step 19.5: Run — expect pass**

```bash
python3 -m pytest tests/test_kig_loop_state.py -v
```

Expected: `5 passed`.

- [ ] **Step 19.6: Commit**

```bash
git add src/kig_loop_state.py tests/test_kig_loop_state.py
git commit -m "feat(loop): per-tty /loop lifecycle tracker with stale-clear safety

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 20: Extend `keepitgoing-state.py` with CronCreate/CronDelete hooks

**Files:**

- Modify: `src/keepitgoing-state.py`

- [ ] **Step 20.1: Read current hook file**

```bash
cat ~/GitRepos/KeepItGoing/src/keepitgoing-state.py
```

Note the event dispatch pattern (`if event == "PreToolUse": ...`).

- [ ] **Step 20.2: Add CronCreate / CronDelete / SessionEnd handlers**

At the top of `src/keepitgoing-state.py`, import the new module:

```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kig_loop_state import record_loop_start, record_loop_end
```

Add these handlers inside the existing event dispatch:

```python
def handle_cron_create(payload: dict) -> None:
    tool_input = payload.get("tool_input", {}) or {}
    # Only track crons that look like they came from /loop skill
    # (first cut: track everything; refine if false positives bite)
    cron_id = payload.get("tool_result", {}).get("id") or tool_input.get("id", "unknown")
    tty = os.environ.get("KIG_TTY") or payload.get("tty", "unknown")
    record_loop_start(tty, cron_id=str(cron_id))


def handle_cron_delete(payload: dict) -> None:
    tool_input = payload.get("tool_input", {}) or {}
    cron_id = tool_input.get("id", "unknown")
    tty = os.environ.get("KIG_TTY") or payload.get("tty", "unknown")
    record_loop_end(tty, cron_id=str(cron_id), reason="cron_delete")


def handle_session_end(payload: dict) -> None:
    tty = os.environ.get("KIG_TTY") or payload.get("tty", "unknown")
    # Force-end any active loop for this tab
    record_loop_end(tty, cron_id="__session_end__", reason="session_end")
```

Wire them in the existing event dispatcher:

```python
# inside the main dispatch (pattern will exist in the current file):
if event == "PreToolUse" and tool_name == "CronCreate":
    handle_cron_create(payload)
elif event == "PostToolUse" and tool_name == "CronDelete":
    handle_cron_delete(payload)
elif event == "SessionEnd":
    handle_session_end(payload)
```

Adapt variable names to what the file already uses.

- [ ] **Step 20.3: Manually test with a forged hook payload**

```bash
export KIG_TTY="/dev/ttys042"
echo '{"hook_event_name":"PreToolUse","tool_name":"CronCreate","tool_input":{"id":"test-cron-1"}}' \
  | python3 src/keepitgoing-state.py
python3 -c "
import sys; sys.path.insert(0, 'src')
from kig_loop_state import is_loop_active
print('active:', is_loop_active('/dev/ttys042'))
"
# Expected: active: True

echo '{"hook_event_name":"PostToolUse","tool_name":"CronDelete","tool_input":{"id":"test-cron-1"}}' \
  | python3 src/keepitgoing-state.py
python3 -c "
import sys; sys.path.insert(0, 'src')
from kig_loop_state import is_loop_active
print('active:', is_loop_active('/dev/ttys042'))
"
# Expected: active: False
```

- [ ] **Step 20.4: Commit**

```bash
git add src/keepitgoing-state.py
git commit -m "feat(hook): CronCreate/Delete/SessionEnd handlers for /loop tracking

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 21: AppleScript reads loop state and applies mute

**Files:**

- Modify: `src/main.applescript`

- [ ] **Step 21.1: Add loop-check before picking nudge**

In `main.applescript`, modify the `pickNudgeForTab` handler (from Task 13) to check loop state first:

```applescript
on pickNudgeForTab(ttyName, cwdPath)
    set kigSrc to (POSIX path of (path to home folder)) & ".claude/kig/_src"
    set shellCmd to "python3 -c \"
import sys
sys.path.insert(0, '" & kigSrc & "')
from kig_tab_state import load_tab
from kig_modes import pick_nudge
from kig_loop_state import is_loop_active, clear_if_stale
from pathlib import Path
tty = '" & ttyName & "'
# Stale-check first — force clear if the hook died mid-loop
clear_if_stale(tty)
if is_loop_active(tty):
    print('__KIG_LOOP_MUTED__')
    sys.exit(0)
state = load_tab(tty)
if not state.kig_on:
    print('__KIG_SKIP__')
    sys.exit(0)
# Honor explicit mute_until
import datetime as dt
if state.mute_until:
    try:
        mu = dt.datetime.fromisoformat(state.mute_until.replace('Z','+00:00'))
        if dt.datetime.now(dt.timezone.utc) < mu:
            print('__KIG_MUTED__')
            sys.exit(0)
    except ValueError:
        pass
print(pick_nudge(mode=state.mode, cwd=Path('" & cwdPath & "')))
\""
    return do shell script shellCmd
end pickNudgeForTab
```

And at the call site, treat any `__KIG_*__` sentinel as "skip this tick and log the reason":

```applescript
set nudgeText to my pickNudgeForTab(currentTTY, currentCwd)
if nudgeText starts with "__KIG_" then
    -- log to /tmp/claude-keepitgoing/app.log with nudgeText as reason
    return
end if
-- deliver nudgeText to the tab (existing code path)
```

- [ ] **Step 21.2: Rebuild and relaunch**

```bash
pkill -f "KeepItGoing-ClaudeChat" || true
./scripts/build.sh
open dist/KeepItGoing-ClaudeChat.app
```

- [ ] **Step 21.3: Manual lifecycle test**

In iTerm tab 1, in Claude Code:

1. Start a short loop: `/loop 1m echo "looping"`
2. In another window watch logs: `tail -f /tmp/claude-keepitgoing/app.log`
3. Confirm log says `__KIG_LOOP_MUTED__` for the duration
4. Either let `/loop` finish naturally or run `/loop stop`
5. Within ≤30s, confirm normal nudges resume

- [ ] **Step 21.4: Commit**

```bash
git add src/main.applescript
git commit -m "feat(monitor): AppleScript mutes during /loop, resumes on end

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 22: `bin/kig mute` and `kig loop` CLI subcommands

**Files:**

- Modify: `bin/kig`

- [ ] **Step 22.1: Add mute/loop subcommands**

In `bin/kig`, extend the dispatcher:

```bash
mute)
    TTY="$(tty 2>/dev/null || echo 'unknown')"
    DURATION="${2:-}"
    if [ -z "${DURATION}" ]; then
        python3 -c "
import sys; sys.path.insert(0, '${HOME}/.claude/kig/_src')
from kig_tab_state import clear_mute
clear_mute('${TTY}')
print('mute cleared for ${TTY}')
"
        exit 0
    fi
    # Parse duration like 5m, 1h, 30s
    NUM="${DURATION%[smh]}"
    UNIT="${DURATION: -1}"
    case "${UNIT}" in
        s) SECS="${NUM}" ;;
        m) SECS="$((NUM * 60))" ;;
        h) SECS="$((NUM * 3600))" ;;
        *) echo "Error: duration must end in s, m, or h (e.g. 5m)" >&2; exit 2 ;;
    esac
    python3 -c "
import datetime as dt, sys
sys.path.insert(0, '${HOME}/.claude/kig/_src')
from kig_tab_state import set_mute_until
until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=${SECS})
set_mute_until('${TTY}', until.isoformat().replace('+00:00','Z'))
print(f'muted ${TTY} until {until.isoformat()}')
"
    ;;
loop)
    # Alias for mute 15m + helpful message
    "$0" mute 15m
    echo ""
    echo "Tip: now type /loop 10m <your-prompt> in Claude. KIG will stay quiet."
    ;;
```

- [ ] **Step 22.2: Install and test**

```bash
./scripts/install.sh
kig mute 10s
# Wait 10s, then:
kig show  # (we'll build this in Stage 5 — for now use kig status)
kig mute
# Expected: "mute cleared"
kig loop
# Expected: mute set for 15m + tip message
kig mute
```

- [ ] **Step 22.3: Commit**

```bash
git add bin/kig
git commit -m "feat(cli): kig mute [duration] and kig loop subcommands

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 23: Suggest-`/loop` directive in verbose mode

**Files:**

- Modify: `src/keepitgoing-generate.py`

- [ ] **Step 23.1: Find the directive-selection logic**

```bash
grep -n "def generate" ~/GitRepos/KeepItGoing/src/keepitgoing-generate.py | head
```

Find the function that assembles the final prompt.

- [ ] **Step 23.2: Add suggest-loop heuristic**

Near the top of `generate()` (or the main prompt-assembly function), add:

```python
def _should_suggest_loop() -> bool:
    """Heuristic: suggest /loop when this tab has been non-idle > threshold."""
    import datetime as dt
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from kig_config import load_merged
    from kig_tab_state import load_tab

    cfg = load_merged()
    if not cfg.get("suggest_loop_when_long", True):
        return False
    threshold_min = int(cfg.get("suggest_loop_threshold_min", 15))
    tty = os.environ.get("KIG_TTY", "unknown")
    state = load_tab(tty)
    last = state.last_prompt_sent
    if not last:
        return False
    try:
        last_dt = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False
    elapsed_min = (dt.datetime.now(dt.timezone.utc) - last_dt).total_seconds() / 60
    return elapsed_min > threshold_min


SUGGEST_LOOP_TEXT = (
    "This work looks long-running. Consider `/loop 10m <your-prompt>` so the "
    "session keeps churning without nudges. Use `/loop stop` when done."
)
```

At the top of the prompt-assembly function, add the short-circuit:

```python
if _should_suggest_loop():
    return SUGGEST_LOOP_TEXT
# ...existing directive selection below...
```

- [ ] **Step 23.3: Manually test the heuristic**

```bash
# Forge a last_prompt_sent in the past
python3 -c "
import sys, datetime as dt
sys.path.insert(0, 'src')
from kig_tab_state import load_tab, save_tab
state = load_tab('/dev/ttys042')
state.last_prompt_sent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).isoformat()
save_tab('/dev/ttys042', state)
"
KIG_TTY=/dev/ttys042 python3 src/keepitgoing-generate.py
# Expected: the suggest-loop text
```

- [ ] **Step 23.4: Commit**

```bash
git add src/keepitgoing-generate.py
git commit -m "feat(generate): suggest /loop directive when work looks long-running

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 24: PR for Stage 4

- [ ] **Step 24.1: Push and open PR**

```bash
git push -u origin feat/kig-modes-stage4
gh pr create \
  --base develop \
  --title "Stage 4 — /loop lifecycle awareness (mute + resume + suggest)" \
  --body "$(cat <<'EOF'
## Summary
- `src/kig_loop_state.py` — per-tty /loop state tracker with stale-clear
- `src/keepitgoing-state.py` — CronCreate/CronDelete/SessionEnd handlers
- `src/main.applescript` — checks loop state + explicit mute before picking nudge
- `bin/kig mute [duration]` and `kig loop` subcommands
- `src/keepitgoing-generate.py` — suggest /loop directive when non-idle > 15min

## Test plan
- [ ] `python3 -m pytest` green (kig_loop_state)
- [ ] Start `/loop 1m echo x` in Claude Code, verify `__KIG_LOOP_MUTED__` in log
- [ ] `/loop stop`; within 30s, verify nudging resumes
- [ ] `kig mute 10s`, wait, verify mute clears automatically
- [ ] `kig loop`, verify 15m mute + tip message

Part of #42.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 24.2: Dogfood — run an actual long `/loop` for 30 minutes, confirm KIG stays silent and resumes cleanly**

---

## Stage 5 — `/kig-config` + `kig show`

**Outcome:** All settings (from `settings.json`) are readable/writable via `/kig-config`. `kig show` prints a compact status line for the current tab.

### Task 25: `bin/kig-config-cmd.py` backing script

**Files:**

- Create: `bin/kig-config-cmd.py`
- Create: `tests/test_kig_config_cmd.py`

- [ ] **Step 25.1: Create branch**

```bash
git checkout develop && git pull
git checkout -b feat/kig-modes-stage5
```

- [ ] **Step 25.2: Write failing tests**

Create `tests/test_kig_config_cmd.py`:

```python
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
        capture_output=True, text=True, check=False,
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
```

- [ ] **Step 25.3: Run — expect failure**

```bash
python3 -m pytest tests/test_kig_config_cmd.py -v
```

- [ ] **Step 25.4: Implement `bin/kig-config-cmd.py`**

```python
#!/usr/bin/env python3
"""CLI helper backing the /kig-config slash command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kig_config import DEFAULTS, find_project_kig, global_kig_dir, load_merged


def _coerce(key: str, raw: str):
    """Coerce string arg to the type DEFAULTS[key] expects."""
    target = DEFAULTS[key]
    if isinstance(target, bool):
        return raw.lower() in ("true", "yes", "on", "1")
    if isinstance(target, int):
        return int(raw)
    return raw  # string


def _scope_path(is_global: bool) -> Path:
    if is_global:
        d = global_kig_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / "settings.json"
    proj = find_project_kig(Path.cwd())
    if proj is None:
        proj = Path.cwd() / ".kig"
        proj.mkdir(exist_ok=True)
    return proj / "settings.json"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def cmd_set(args: argparse.Namespace) -> int:
    if args.key not in DEFAULTS:
        print(f"Unknown key: {args.key}. Known keys: {list(DEFAULTS)}", file=sys.stderr)
        return 2
    value = _coerce(args.key, args.value)
    path = _scope_path(args.g)
    data = _read(path)
    data[args.key] = value
    _write(path, data)
    print(f"{args.key} = {value!r}  →  {path}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    if args.key not in DEFAULTS:
        print(f"Unknown key: {args.key}", file=sys.stderr)
        return 2
    merged = load_merged()
    print(merged.get(args.key, DEFAULTS[args.key]))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    merged = load_merged()
    for k in DEFAULTS:
        print(f"{k} = {merged.get(k, DEFAULTS[k])!r}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    path = _scope_path(args.g)
    data = _read(path)
    if args.key in data:
        del data[args.key]
        _write(path, data)
        print(f"reset {args.key} in {path}")
    return 0


def cmd_reset_all(args: argparse.Namespace) -> int:
    path = _scope_path(args.g)
    _write(path, {})
    print(f"cleared all settings in {path}")
    return 0


HELP = """\
/kig-config — manage KIG settings (project or global)

SUBCOMMANDS
  set [--global] <key> <value>
  get <key>                 # shows resolved value (after merge)
  show                      # list all keys with resolved values
  reset [--global] <key>    # remove override (fall back to global or default)
  reset-all [--global]
  help

KEYS (defaults)
  default_mode = verbose         # minimal | simple | verbose
  scope_mode = per-category      # per-category | additive | override
  poll_interval_sec = 30
  idle_threshold_sec = 60
  mute_on_loop_detect = True
  suggest_loop_when_long = True
  suggest_loop_threshold_min = 15

EXAMPLES
  /kig-config set default_mode simple
  /kig-config set --global poll_interval_sec 60
  /kig-config get default_mode
  /kig-config show
  /kig-config reset default_mode
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP); return 0
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-g", "--global", dest="g", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_set)

    g = sub.add_parser("get"); g.add_argument("key"); g.set_defaults(func=cmd_get)
    sub.add_parser("show").set_defaults(func=cmd_show)

    r = sub.add_parser("reset"); r.add_argument("key"); r.set_defaults(func=cmd_reset)
    sub.add_parser("reset-all").set_defaults(func=cmd_reset_all)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 25.5: Make executable and run tests**

```bash
chmod +x bin/kig-config-cmd.py
python3 -m pytest tests/test_kig_config_cmd.py -v
```

Expected: `5 passed`.

- [ ] **Step 25.6: Commit**

```bash
git add bin/kig-config-cmd.py tests/test_kig_config_cmd.py
git commit -m "feat(cli): /kig-config backing script (set/get/show/reset)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 26: `/kig-config` slash-command template + installer wiring

**Files:**

- Create: `config/kig-config.md.tmpl`
- Modify: `scripts/install.sh`

- [ ] **Step 26.1: Write the template**

Create `config/kig-config.md.tmpl`:

````markdown
---
description: Manage KIG settings (timeouts, modes, scopes) — project or global scope
argument-hint: [set|get|show|reset|reset-all|help] [--global] [key] [value]
allowed-tools: Bash
---

# /kig-config — manage KIG settings

Read or change KIG settings such as default mode, poll interval, scope-resolution mode, /loop detection. Project scope by default; `--global` to change machine-wide defaults.

Run the backing script with the user's arguments:

```bash
~/.claude/kig/_src/../../../bin/kig-config-cmd.py "$@"
```
````

## Known settings

| Key                          | Type   | Default        | Meaning                                   |
| ---------------------------- | ------ | -------------- | ----------------------------------------- |
| `default_mode`               | string | `verbose`      | `minimal` / `simple` / `verbose`          |
| `scope_mode`                 | string | `per-category` | Library merge strategy                    |
| `poll_interval_sec`          | int    | `30`           | How often the monitor checks tabs         |
| `idle_threshold_sec`         | int    | `60`           | Seconds without activity = idle           |
| `mute_on_loop_detect`        | bool   | `true`         | Auto-mute when `/loop` detected           |
| `suggest_loop_when_long`     | bool   | `true`         | Nudge user to use `/loop` when work drags |
| `suggest_loop_threshold_min` | int    | `15`           | Minutes before suggest-loop fires         |

## Subcommands

| Command                        | Effect                                          |
| ------------------------------ | ----------------------------------------------- |
| `set [--global] <key> <value>` | Write override                                  |
| `get <key>`                    | Print resolved value (after merging all layers) |
| `show`                         | Print every key with its resolved value         |
| `reset [--global] <key>`       | Remove override (fall back to next layer)       |
| `reset-all [--global]`         | Wipe all overrides in that scope                |
| `help`                         | This text                                       |

## Examples

```
/kig-config set default_mode simple
/kig-config set --global poll_interval_sec 60
/kig-config get default_mode
/kig-config show
/kig-config reset default_mode
```

## Saves to

- Project: `./.kig/settings.json`
- Global (`--global`): `~/.claude/kig/settings.json`

````

- [ ] **Step 26.2: Extend installer**

Add to `scripts/install.sh`:

```bash
cp config/kig-config.md.tmpl "${CMD_DIR}/kig-config.md"
````

- [ ] **Step 26.3: Install and test**

```bash
./scripts/install.sh
# In Claude Code:
/kig-config help
/kig-config show
/kig-config set default_mode simple
/kig-config get default_mode
# Expected: "simple"
/kig-config reset default_mode
```

- [ ] **Step 26.4: Commit**

```bash
git add config/kig-config.md.tmpl scripts/install.sh
git commit -m "feat(commands): /kig-config slash command

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 27: `kig show` diagnostic command

**Files:**

- Modify: `bin/kig`

- [ ] **Step 27.1: Add `show` subcommand**

In `bin/kig`, add:

```bash
show)
    TTY="$(tty 2>/dev/null || echo 'unknown')"
    python3 -c "
import sys, datetime as dt
sys.path.insert(0, '${HOME}/.claude/kig/_src')
from kig_config import load_merged, find_project_kig
from kig_tab_state import load_tab
from kig_loop_state import is_loop_active
from pathlib import Path

cfg = load_merged()
state = load_tab('${TTY}')
proj = find_project_kig(Path.cwd())
isolated = (proj is not None and (proj / 'isolate').exists())
loop = is_loop_active('${TTY}')

print(f'TAB: ${TTY}')
print(f'  mode          = {state.mode}')
print(f'  kig_on        = {state.kig_on}')
print(f'  mute_until    = {state.mute_until or \"(none)\"}')
print(f'  loop_active   = {loop}')
print()
print('RESOLVED CONFIG:')
for k, v in cfg.items():
    print(f'  {k} = {v!r}')
print()
print(f'PROJECT .kig/ = {proj or \"(none)\"}')
print(f'  isolated    = {isolated}')
if isolated and proj:
    lib_files = sum(1 for f in proj.glob('*.json') if f.stat().st_size > 20)
    if lib_files == 0:
        print('  WARN: isolated with empty library — no nudges will fire')
"
    ;;
```

- [ ] **Step 27.2: Install and test**

```bash
./scripts/install.sh
kig show
# Expected: block with TAB, RESOLVED CONFIG, PROJECT sections
```

- [ ] **Step 27.3: Test the isolation warning**

```bash
cd ~/GitRepos/KeepItGoing
mkdir -p .kig && touch .kig/isolate
kig show | grep -A1 "isolated"
# Expected: "isolated = True" and "WARN: isolated with empty library" line
rm -f .kig/isolate
```

- [ ] **Step 27.4: Commit**

```bash
git add bin/kig
git commit -m "feat(cli): kig show — diagnostic dump of resolved config and state

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 28: Testing docs + final README update

**Files:**

- Create: `docs/testing.md`
- Modify: `README.md`

- [ ] **Step 28.1: Write `docs/testing.md`**

````markdown
# KIG Testing Guide

## Running unit tests

```bash
cd ~/GitRepos/KeepItGoing
python3 -m pytest
```
````

All modules in `src/kig_*.py` and `bin/kig-*-cmd.py` are covered.

## Manual integration tests

### 1. First-tab minimal mode

```bash
kig mode minimal
tail -f /tmp/claude-keepitgoing/app.log
```

Expected: next nudge (within 30s) is one of the 15 entries in `src/kig_seeds/minimal.json`.

### 2. Project isolation

```bash
cd ~/GitRepos/KeepItGoing
/kig-library isolate
/kig-library add "KIG-specific reminder only"
```

Expected: next verbose nudge in this project is only "KIG-specific reminder only" — no generic global directives.

### 3. `/loop` lifecycle

In Claude Code:

```
/loop 1m echo "loop test"
```

Expected in `/tmp/claude-keepitgoing/app.log`: `__KIG_LOOP_MUTED__` entries for 1 minute. Then `/loop stop` (or wait for completion) — within 30s, normal nudges resume.

### 4. Inject hybrid

```
/kig-inject add "one"
/kig-inject add "two"
/kig-inject toggle 2
/kig-inject on
```

Expected: next nudge prepended with `INJECTED CONTEXT: one` (but not `two`).

### 5. Migration

```bash
# Restore legacy files
cp ~/.claude/kig/legacy/kig-pins.json ~/.claude/
cp ~/.claude/kig/legacy/kig-inject.txt ~/.claude/
rm ~/.claude/kig/inject.json
./scripts/install.sh
```

Expected: `~/.claude/kig/inject.json` re-created with both legacy entries, old files re-archived, idempotent.

````

- [ ] **Step 28.2: Update `README.md` with new commands section**

Find the "Configuration" section in `README.md` and add a subsection:

```markdown
### Modes, Library, Config

KIG supports three nudge modes per iTerm tab:

- **`minimal`** — tiny nudges like `"keep going"` / `"continue"`
- **`simple`** — short contextual prompts (~50 entries)
- **`verbose`** — the full directive engine (default)

Set per-tab: `kig mode minimal|simple|verbose`

Manage library entries (`/kig-library`), context overlays (`/kig-inject`), and settings (`/kig-config`) with slash commands. Run any with `help` for full examples:

````

/kig-library help
/kig-inject help
/kig-config help

```

See `docs/testing.md` for manual integration tests.
```

- [ ] **Step 28.3: Commit**

```bash
git add docs/testing.md README.md
git commit -m "docs: testing guide and README section for modes/library/config

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 29: PR for Stage 5 + full dogfood

- [ ] **Step 29.1: Push and open PR**

```bash
git push -u origin feat/kig-modes-stage5
gh pr create \
  --base develop \
  --title "Stage 5 — /kig-config + kig show (settings surface polish)" \
  --body "$(cat <<'EOF'
## Summary
- `bin/kig-config-cmd.py` — set/get/show/reset backing
- `config/kig-config.md.tmpl` — slash command
- `bin/kig show` — full diagnostic dump with isolation warning
- `docs/testing.md` + README additions

## Test plan
- [ ] `python3 -m pytest` green (kig_config_cmd)
- [ ] `/kig-config set default_mode simple` + `/kig-config show` — verify
- [ ] `kig show` — confirm all fields present
- [ ] Isolation warning: `mkdir .kig && touch .kig/isolate && kig show`

Closes #42.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 29.2: Final dogfood sweep**

Run every manual test in `docs/testing.md`. Any failure → file Issue, do not close #42.

- [ ] **Step 29.3: After PR merge, close epic and tag release**

```bash
# After Stage 5 merges to develop → main
git checkout main
git pull
git tag -a v1.0.0 -m "KIG modes, library & config system (epic #42)"
git push origin v1.0.0
gh release create v1.0.0 --generate-notes
```

---

## Self-review checklist (run before handing plan off)

- [ ] Every spec section has at least one corresponding task
- [ ] No "TBD" / "TODO" / "fill in" placeholders
- [ ] Every type/signature referenced later matches its definition earlier (e.g. `Entry`, `InjectStore`, `TabState`, `Suppress`)
- [ ] Every command shown has its exact expected output
- [ ] Each stage is independently shippable
- [ ] Migration is idempotent and tested

---

## Handoff

Two execution options:

1. **Subagent-driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline execution** — execute in this session using executing-plans, batch with checkpoints

Tell me which, and I'll invoke the right sub-skill.
