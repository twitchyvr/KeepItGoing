# KeepItGoing — Claude Code Instructions

## Project Overview

KeepItGoing is a macOS automation tool that keeps Claude Code sessions productive. It monitors iTerm tabs, detects idle states, and sends context-aware continuation prompts. The system has three components: an AppleScript applet (UI automation), a Python prompt generator, and a Python hook handler.

## Build & Run

```bash
# Build the macOS app
./scripts/build.sh

# Install to ~/.claude + ~/bin + dist/
./scripts/install.sh

# Launch
open dist/KeepItGoing-ClaudeChat.app

# Check logs
tail -f /tmp/claude-keepitgoing/app.log
```

## Architecture

```
src/
├── main.applescript           # iTerm monitor (AppleScript idle handler)
├── keepitgoing-generate.py    # Prompt generator (Python, 2300+ lines)
└── keepitgoing-state.py       # Claude Code hook handler (Python, 150 lines)
bin/
└── kig                        # Per-tab toggle CLI (Bash)
scripts/
├── build.sh                   # Compile .applescript → .app
├── install.sh                 # Copy files + compile + install
└── uninstall.sh               # Remove installed files
```

## Conventions

- AppleScript: the applet uses `on idle` handler — macOS calls this repeatedly while the app runs
- Python: no external dependencies for the state writer. Generator uses only stdlib.
- All paths configurable via install.sh `--prefix`. Source uses `$HOME/` as placeholder — install.sh patches it.
- AppleScript edits: decompile with `osadecompile`, edit the `.applescript`, recompile with `osacompile` or `./scripts/build.sh`
- After editing the .applescript or .py: kill the running app, rebuild, relaunch. Launch Services caches running applets.

## Testing

- Manually: edit generator, run `python3 src/keepitgoing-generate.py --cwd /path/to/project`
- Verify stack detection: `python3 -c "...get_project_context('/path')..."` (see README)
- Check logs: `/tmp/claude-keepitgoing/app.log`
- No automated test suite yet (TODO: add pytest for the generator)

## What NOT to Do

- Don't commit compiled .app bundles (they're in dist/, gitignored)
- Don't hardcode `$HOME/` — use the install.sh patching mechanism
- Don't change the LICENSE without explicit instruction — currently TBD
- Don't add external Python dependencies to the generator or state writer (stdlib only)
