# KIG Modes, Library & Config System — Design Spec

**Date:** 2026-04-19
**Status:** Draft — awaiting implementation plan
**Author:** Matt (with Claude Opus 4.7)

## Problem statement

KeepItGoing today has three pain points:

1. **`/kig-pin` and `/kig-inject` overlap confusingly.** They sit beside each other as two separate persistence mechanisms that both inject user context into nudges, but with different shapes (list-of-directives vs. single toggleable prompt). Users (including the author) conflate them.
2. **One-size-fits-all nudging.** Every tab gets the full directive engine (748 phrasings across 70 categories). For a simple "keep going" babysitting use case, this is massive overkill — noisy, expensive, derail-prone.
3. **No project-level sculpting.** Projects like KeepItGoing itself shouldn't hear generic "add E2E tests" or "check Firebase auth" nudges. Today there is no way to suppress globals for a specific project, only to add to them via `.project-brief.md`.
4. **`/loop` blindness.** When Claude is running `/loop 10m <cmd>`, KIG keeps nudging every 30 seconds, corrupting the loop's output and defeating the purpose.

## Goals

- Consolidate `kig-pin` and `kig-inject` into one hybrid model.
- Introduce three nudge modes — `minimal`, `simple`, `verbose` — selectable per iTerm tab.
- Add a user-facing library-management slash command that works globally or per-project, with category-level suppression and a full "isolate" escape hatch.
- Make KIG aware of `/loop` start AND end, silencing itself during and resuming cleanly after.
- Surface all settings (timeouts, modes, scopes) through a unified `/kig-config` command and extend the `kig` CLI.
- Ship with seed content, intuitive help text (every command has examples), and a pytest suite covering the merge/resolution logic.

## Non-goals

- Rewriting the AppleScript monitor loop.
- Replacing the existing verbose-mode directive generator — it stays as-is, just routed around in non-verbose modes.
- Cross-machine sync.
- Any form of release-notice / deprecation period — this is a personal tool; old commands are deleted outright.

## Architecture — four-layer composition

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Per-tab mode selector   → minimal | simple | verbose      │
├──────────────────────────────────────────────────────────────┤
│ 2. Source libraries (based on mode):                          │
│    - minimal  → ~/.claude/kig/minimal.json  (hand-curated)    │
│    - simple   → ~/.claude/kig/simple.json   (hand-curated)    │
│    - verbose  → existing generator + 70 categories            │
├──────────────────────────────────────────────────────────────┤
│ 3. Scope resolver (per-category | additive | override)        │
│    - merges global lib + project lib (.kig/) based on mode    │
│    - applies suppress list + isolate flag                     │
├──────────────────────────────────────────────────────────────┤
│ 4. User overlays (consolidated inject hybrid)                 │
│    - master on/off                                            │
│    - per-entry on/off                                         │
│    - per-entry mode filter (for: [minimal,simple,verbose])    │
└──────────────────────────────────────────────────────────────┘
           ↓
      Final prompt → sent to iTerm tab via existing AppleScript
```

## Storage layout

### Global (machine-wide) — `~/.claude/kig/`

```
~/.claude/kig/
├── settings.json              # global defaults
├── minimal.json               # hand-curated tiny nudges (~15 entries)
├── simple.json                # hand-curated short nudges (~50 entries)
├── inject.json                # hybrid inject list (global scope)
├── suppress.json              # category/id suppression list
├── tabs/<ttyname>.json        # per-tab runtime state
└── legacy/                    # archived pre-migration files
```

### Per-project — `.kig/` at project root

```
.kig/
├── settings.json              # overrides
├── minimal.json               # optional — layered per scope_mode
├── simple.json                # optional — same
├── verbose-entries.json       # user-authored verbose-mode additions
├── inject.json                # project-scoped inject hybrid
├── suppress.json              # which global categories/ids to suppress
└── isolate                    # empty marker — if present, no globals at all
```

## Data formats

### `inject.json` (hybrid pin+inject)

```jsonc
{
  "master_enabled": true,
  "entries": [
    {
      "id": "a1b2",
      "text": "never abandon half-written code without checking git status",
      "enabled": true,
      "for": ["simple", "verbose"],
      "added": "2026-04-19T14:12:00Z",
    },
  ],
}
```

**`for` field semantics:** values are any subset of `["minimal","simple","verbose"]`, OR the single wildcard string `["all"]` which matches every mode. The CLI `--for all` flag is stored as the literal wildcard `["all"]` (not expanded) so "all modes including future ones" intent is preserved across upgrades. Resolver treats `["all"]` as always-match.

### `suppress.json`

```jsonc
{
  "categories": ["visual_verification", "mobile_signing"],
  "ids": ["directive_042"],
}
```

### `settings.json` (same schema global and per-project; project wins key-by-key)

```jsonc
{
  "default_mode": "verbose", // minimal | simple | verbose
  "scope_mode": "per-category", // per-category | additive | override
  "poll_interval_sec": 30,
  "idle_threshold_sec": 60,
  "mute_on_loop_detect": true,
  "suggest_loop_when_long": true,
  "suggest_loop_threshold_min": 15,
}
```

### `tabs/<tty>.json` (per-tab runtime)

```jsonc
{
  "mode": "minimal",
  "kig_on": true,
  "mute_until": null, // ISO timestamp or null
  "last_prompt_sent": "2026-04-19T15:03:11Z",
}
```

### Seed libraries

`minimal.json` (~15 entries, each ≤ 6 words):

- `"keep going"`
- `"continue"`
- `"don't stop"`
- `"you have more to finish"`
- `"keep working"`
- `"not done yet"`
- `"there's more"`
- `"push through"`
- `"what's next?"`
- `"resume"`
- `"pick back up"`
- `"don't pause"`
- `"stay focused"`
- `"finish it"`
- `"keep at it"`

`simple.json` (~50 entries, each ≤ ~20 words). Examples:

- `"keep going — break the task into the next small step"`
- `"continue. Run the tests if you're at a checkpoint."`
- `"don't pause. Commit what's working and keep moving."`
- `"what's the next subtask? Name it and start it."`

Final seed content drafted in Stage 2; user reviews before merge.

## Slash commands (`~/.claude/commands/`)

| Command        | Purpose                                                                                                                                                                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/kig-inject`  | Consolidated pin+inject hybrid. Subcommands: `add`, `list`, `remove <N>`, `toggle <N>`, `on`, `off`, `clear`, `show`, `help`. Defaults to project scope; `--global` promotes. Supports `--for simple\|verbose\|minimal\|all` (default `all`). |
| `/kig-library` | Manage nudge-sentence library. Subcommands: `add`, `remove <N>`, `list`, `edit <N>`, `suppress <category-or-id>`, `unsuppress <id>`, `isolate`, `unisolate`, `help`. Same `--global` / `--for` flags.                                         |
| `/kig-config`  | Manage settings. Subcommands: `set <key> <value>`, `get <key>`, `show`, `reset <key>`, `reset-all`, `help`. Defaults to project scope; `--global` promotes.                                                                                   |
| `/kig-pin`     | **DELETED.** Removed outright during migration.                                                                                                                                                                                               |

### `kig` CLI new subcommands (`~/bin/kig`)

| Subcommand                                  | Purpose                                                                                                                        |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `kig mode <minimal\|simple\|verbose>`       | Set per-tab mode. No arg = show current.                                                                                       |
| `kig mute [duration]`                       | Silence this tab for the given duration (`5m`, `1h`, `30s`). No arg = clear any active mute for this tab (resume immediately). |
| `kig loop`                                  | Alias for `kig mute 15m` with message reminding user to type `/loop`.                                                          |
| `kig show`                                  | Print resolved config for this tab: mode, active libs, scope_mode, mute state, inject master state.                            |
| (existing) `on` / `off` / `status` / `list` | Unchanged.                                                                                                                     |

### UX examples baked into every `help` output

Every slash command's `help` and `kig <cmd> --help` prints:

1. One-sentence description
2. Every subcommand with its shape
3. At least three realistic examples
4. A "where does this save?" footnote pointing at the file path

Example for `/kig-library help`:

```
/kig-library — manage the nudge-sentence library

SUBCOMMANDS
  add [--global] [--for all|minimal|simple|verbose] "text"
  remove [--global] <N>
  list [--global]
  edit [--global] <N>
  suppress <category-or-id>
  unsuppress <id>
  isolate       # this project ignores globals completely
  unisolate
  help

EXAMPLES
  /kig-library add "don't commit compiled .app bundles"
  /kig-library add --global --for simple "check the logs at /tmp/..."
  /kig-library suppress visual_verification
  /kig-library isolate

SAVES TO
  Project:  .kig/{verbose-entries,minimal,simple,suppress}.json
  Global:   ~/.claude/kig/{verbose-entries,minimal,simple,suppress}.json
```

## Dynamic behavior

### Prompt generation (per poll tick)

```
1. AppleScript detects idle/menu in tab T
2. Read ~/.claude/kig/tabs/<tty>.json → {mode, mute_until, kig_on}
3. If !kig_on or mute_until > now → skip, log, return
4. Load resolved settings (global ∪ project, project wins)
5. Route by mode:
   - minimal → random line from resolved minimal library
   - simple  → random line from resolved simple library
   - verbose → existing generator + project verbose-entries, scope-filtered
6. Apply inject overlay (if master_enabled) → prepend enabled entries
   filtered by current mode via entry.for array
7. Deliver prompt through existing AppleScript pipeline
```

### Scope resolution

```python
def resolve_library(global_lib, project_lib, scope_mode, suppress, isolate):
    if isolate:
        return project_lib
    if scope_mode == "override" and project_lib:
        return project_lib
    if scope_mode == "additive":
        return global_lib + project_lib
    # per-category (default)
    filtered_global = [
        e for e in global_lib
        if e.category not in suppress.categories
        and e.id not in suppress.ids
    ]
    return filtered_global + project_lib
```

### `/loop` lifecycle detection

State file at `/tmp/claude-keepitgoing/loop-state-<tty>.json`.

`keepitgoing-state.py` (the existing hook) gains `CronCreate` / `CronDelete` handlers:

| Trigger                                            | Hook action                                          | Effect on AppleScript poll                                       |
| -------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------- |
| `PreToolUse: CronCreate` tagged as loop-skill      | write `{active: true, started: <ts>, cron_id: <id>}` | Next poll → set `mute_until` to now+5min; refreshed while active |
| `PostToolUse: CronDelete` matching tracked cron_id | write `{active: false, ended: <ts>}`                 | Next poll → clear `mute_until`, resume nudging ≤30s later        |
| `SessionEnd`                                       | write `{active: false, reason: "session_end"}`       | Same resume path (catches crashes)                               |
| Safety fallback                                    | `active:true` but state file unchanged >30min        | AppleScript force-resumes, logs the stall                        |

**Loop-skill identification:** inspect `CronCreate` arguments for the loop-skill marker. If the invocation cannot be reliably distinguished from other cron users, the first cut tracks ALL crons (over-mute tradeoff is acceptable — rare enough).

**Screen-parse fallback (B from Q4):** if the hook fails to fire for any reason, AppleScript's existing screen-content parser looks for `/loop` output markers and applies mute heuristically. Never the primary mechanism — only the safety net.

### Suggest-`/loop` directive (verbose mode only)

When `suggest_loop_when_long: true` AND the AppleScript observes a Claude session not-idling for > `suggest_loop_threshold_min` (default 15 min), the next **verbose-mode** nudge is a dedicated single directive:

> _This work looks long-running. Consider `/loop 10m <your-prompt>` so the session keeps churning without nudges. Use `/loop stop` when done._

Mutually exclusive with other verbose directives for that tick. Never fires in `minimal`/`simple` modes (those modes intentionally stay quiet).

## Migration

`scripts/install.sh` handles first-run conversion of pre-existing files:

1. If `~/.claude/kig-pins.json` exists → read entries → write as `~/.claude/kig/inject.json` with each entry marked `enabled:true, for:["all"]`. Archive old file to `~/.claude/kig/legacy/`.
2. If `~/.claude/kig-inject.txt` exists → read content → append as single entry in `~/.claude/kig/inject.json`. If `~/.claude/kig-inject.enabled` exists, set `master_enabled:true` (otherwise `false`). Archive both old files.
3. Delete `~/.claude/commands/kig-pin.md` outright.
4. Overwrite `~/.claude/commands/kig-inject.md` with new consolidated content.
5. Install `~/.claude/commands/kig-library.md` and `~/.claude/commands/kig-config.md`.
6. Write seed `minimal.json` and `simple.json` to `~/.claude/kig/`.

Installer is idempotent: re-running after partial migration skips steps already done.

## Testing approach

### Python unit tests (new `tests/` dir, pytest, stdlib where possible)

| Module                    | Key tests                                                                                                                              |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `kig_config.py`           | Merge global + project settings, precedence, bad JSON handling, defaults when files missing                                            |
| `kig_scope.py`            | `resolve_library()` full matrix: {per-category, additive, override} × {isolate, suppress, empty-project, empty-global, both-populated} |
| `kig_inject.py`           | Hybrid model: master on/off, entry toggle, `for:` mode filter, bad-id handling                                                         |
| `kig_loop_state.py`       | Cron lifecycle transitions, safety fallback (>30min stall), tty-scoping, concurrent tab isolation                                      |
| `keepitgoing-generate.py` | Mode routing: verify `minimal`/`simple` modes do NOT invoke the 152KB generator                                                        |

### Manual integration tests (`docs/testing.md`)

1. First-tab smoke: `kig mode minimal`, verify only `minimal.json` entries show in `/tmp/claude-keepitgoing/app.log`.
2. Project isolation: `cd` into KeepItGoing, `/kig-library isolate`, verify no generic global directives appear.
3. `/loop` lifecycle: start `/loop 1m echo hi`, verify tab is muted, let `/loop stop` run, verify resume ≤30s.
4. Inject hybrid: add 3 entries, toggle one off, verify only 2 prepended in next nudge.
5. Migration: run installer with old `kig-pins.json` + `kig-inject.txt` present, verify conversion and archiving.

## File impact

**New:**

- `src/kig_config.py`, `src/kig_scope.py`, `src/kig_inject.py`, `src/kig_loop_state.py`
- `~/.claude/commands/kig-library.md`, `~/.claude/commands/kig-config.md`
- `~/.claude/kig/minimal.json`, `simple.json` (seed)
- `tests/` directory with pytest suite
- `docs/testing.md`

**Modified:**

- `src/keepitgoing-generate.py` — mode routing at entry; scope resolution delegated to `kig_scope`
- `src/keepitgoing-state.py` — add `CronCreate` / `CronDelete` handlers
- `src/main.applescript` — per-tab state read, loop-state check, mute application
- `bin/kig` — new subcommands: `mode`, `mute`, `loop`, `show`
- `~/.claude/commands/kig-inject.md` — rewritten as hybrid
- `scripts/install.sh` — migration logic, new command installation

**Deleted:**

- `~/.claude/commands/kig-pin.md`

## Rollout sequence

Shipped in 5 stages, each independently valuable, each a separate PR against `develop` with its own GitHub Issue and dogfooding pass.

1. **Stage 1 — Config foundation.** Settings schema, scope resolver, migration. No user-visible behavior change. Full pytest coverage for the merge/resolution logic.
2. **Stage 2 — Mode routing + seed libraries.** `minimal` / `simple` modes usable; first-tab use case (`kig mode minimal`) works end-to-end.
3. **Stage 3 — Consolidated `/kig-inject` + `/kig-library`.** Slash commands live; `/kig-pin` deleted.
4. **Stage 4 — `/loop` lifecycle.** Hook handler, AppleScript integration, suggest-loop directive.
5. **Stage 5 — `/kig-config` + `kig show`.** Polish: expose everything, intuitive `show` output.

## Open items (not blockers)

- **Seed content for `minimal.json` / `simple.json`** — ~15 + ~50 entries drafted at Stage 2; user reviews before merge.
- **Exact `/loop` detection marker** — confirm whether `CronCreate` tool-args include a recognizable loop-skill tag. If not, first cut tracks ALL crons as loop-active (over-mute is an acceptable tradeoff).

## Risks

- **AppleScript polling performance** — reading multiple JSON files per tab per 30s tick. Mitigated by caching resolved config in-memory with a file-mtime check, reloading only on change.
- **Hook race conditions** — `CronCreate` fires before cron actually runs; `CronDelete` fires on teardown. Safety fallback (>30min stall auto-clear) covers edge cases where hooks drop.
- **Over-isolation footgun** — `/kig-library isolate` plus empty project library = silent KIG forever. `kig show` must flag this clearly ("WARN: isolated with empty library — no nudges will fire").
