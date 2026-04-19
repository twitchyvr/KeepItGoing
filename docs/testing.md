# KIG Testing Guide

## Running unit tests

```bash
cd ~/GitRepos/KeepItGoing
/opt/homebrew/bin/pytest
```

Covers `src/kig_*.py` modules and all `bin/kig-*-cmd.py` helpers. Note: the shell alias `pytest` resolves to `python3 -m pytest`, which may fail if pytest isn't in the system python's site-packages. Always use the Homebrew binary directly.

## Manual integration tests

### 1. First-tab mode routing

```bash
kig mode minimal
tail -f /tmp/claude-keepitgoing/app.log
```

Expected within one poll interval: next nudge is one of the 15 entries in `src/kig_seeds/minimal.json` (e.g. `"keep going"`, `"continue"`), not a full verbose directive.

### 2. Project isolation

```bash
cd ~/GitRepos/KeepItGoing
/kig-library isolate
/kig-library add "KIG-specific reminder only"
```

Expected: next verbose nudge in this project contains only `"KIG-specific reminder only"` — no generic global directives.

### 3. `/loop` lifecycle

In a Claude Code session:

```
/loop 1m echo "loop test"
```

Expected log entries (`/tmp/claude-keepitgoing/app.log`): `[kig] skip nudge | reason=__KIG_LOOP_MUTED__ | cwd=...` for the duration of the loop. After `/loop stop` (or auto-teardown), nudging resumes within ≤30s.

### 4. Inject hybrid

```
/kig-inject add "one"
/kig-inject add "two"
/kig-inject toggle 2
/kig-inject on
```

Expected: next nudge prepended with the `INJECTED CONTEXT:` block containing only `"one"` (entry #2 is toggled off).

### 5. Migration

```bash
# Simulate legacy state
echo '{"pins": ["test"]}' > ~/.claude/kig-pins.json
echo "ctx" > ~/.claude/kig-inject.txt
touch ~/.claude/kig-inject.enabled

./scripts/install.sh
```

Expected: the three legacy files are archived to `~/.claude/kig/legacy/`, `~/.claude/kig/inject.json` now contains both entries with `master_enabled: true`, and re-running install.sh is a clean no-op (no duplication).

### 6. Config roundtrip

```bash
/kig-config set default_mode simple
/kig-config get default_mode    # → simple
kig show                        # → default_mode = 'simple'
/kig-config reset default_mode
/kig-config get default_mode    # → verbose (fallback to default)
```
