# KeepItGoing

> Autonomous nudge engine for Claude Code sessions. Keeps AI agents productive, focused, and quality-driven when you step away.

KeepItGoing monitors your iTerm Claude Code sessions and sends context-aware continuation prompts when the AI goes idle or hits a permission prompt. Instead of Claude stopping and waiting for input, it keeps working — with 70 directive categories covering visual verification, testing pyramids, DevSecOps gates, UX coherence, design quality, and more.

## What It Does

- **Detects idle Claude Code sessions** in iTerm via screen content analysis
- **Sends dynamic continuation prompts** generated from 748 directive phrasings across 70 categories
- **Auto-accepts permission menus** by detecting numbered options and selecting the recommended choice
- **Stack-aware filtering** — a C++ project never hears about TestFlight; a web app never hears about Android signing (84 detectable stacks)
- **Anti-derail framing** — prompts are framed as ambient reminders, not task reassignments
- **Per-tab toggle** — `kig off` to disable for any session, `kig on` to re-enable

## Requirements

- macOS (Apple Silicon or Intel)
- [iTerm2](https://iterm2.com/)
- [Claude Code](https://claude.ai/claude-code) running in iTerm
- Python 3.10+

## Quick Start

```bash
# Clone
git clone https://github.com/twitchyvr/KeepItGoing.git
cd KeepItGoing

# Install (copies scripts, compiles the app)
./scripts/install.sh

# Launch
open dist/KeepItGoing-ClaudeChat.app

# Toggle per-tab
kig off    # pause for current tab
kig on     # resume
kig status # check state
```

## How It Works

```
┌─────────────────────────────────────────────────┐
│  KeepItGoing-ClaudeChat.app (AppleScript)       │
│  Polls iTerm every 30s, reads screen content    │
│                                                  │
│  ┌─────────┐   ┌──────────────┐                │
│  │ Idle?   │──→│ Generate     │──→ Send prompt  │
│  │ Menu?   │   │ Prompt (py)  │                 │
│  │ Working?│   └──────────────┘                 │
│  └─────────┘         ↑                          │
│       ↑              │                          │
│  Screen content   Git context                   │
│  Hook events      Project type                  │
│                   Stack detection                │
└─────────────────────────────────────────────────┘
         ↕
┌─────────────────────────────────────────────────┐
│  keepitgoing-state.py (Claude Code hook)        │
│  Fires on: PreToolUse, PostToolUse, Stop,       │
│  Notification, SessionStart, SessionEnd         │
│  Writes state to /tmp/claude-keepitgoing/       │
└─────────────────────────────────────────────────┘
```

### Components

| File                          | Purpose                                                    |
| ----------------------------- | ---------------------------------------------------------- |
| `src/main.applescript`        | iTerm monitor — detects idle/menu states, sends prompts    |
| `src/keepitgoing-generate.py` | Prompt generator — 70 categories, stack-aware, anti-derail |
| `src/keepitgoing-state.py`    | Hook handler — writes session state for the monitor        |
| `bin/kig`                     | CLI toggle — `kig on/off/status/list` per iTerm tab        |

### Directive Categories (70)

Grouped by concern: dogfooding, visual verification, UX coherence, design quality, testing pyramid, AI-UAT, code review, security gates, LLMOps, GitHub ops, CI/CD optimization, release management, progressive delivery, deep thinking, fill gaps, parallel agents, and 50+ more.

### Stack Detection (84 stacks)

Auto-detects from project files: web frameworks (Next.js, Vite, Svelte, Angular...), mobile (iOS, Android, React Native, Flutter), game engines (Unity, Unreal, Godot, Bevy), desktop (Electron, Tauri, Qt), systems (Rust, C++, Go, Zig), and dozens more. Monorepo-aware — scans subdirectories.

## Configuration

### Modes, Library, Config (v2.1+)

KIG supports three nudge modes per iTerm tab:

- **`minimal`** — tiny nudges like `"keep going"` / `"continue"` (15 curated entries)
- **`simple`** — short contextual prompts (~50 entries)
- **`verbose`** — the full 70-category directive engine (default)

```bash
kig mode minimal       # set per-tab mode
kig show               # resolved config + tab state + isolation status
kig mute 15m           # silence tab for a duration
kig loop               # alias: mute 15m + reminder to type /loop
```

Slash commands manage entries and settings (run each with `help` for examples):

| Command        | Purpose                                                                        |
| -------------- | ------------------------------------------------------------------------------ |
| `/kig-inject`  | Consolidated pin+inject hybrid — prepend user context to every nudge           |
| `/kig-library` | Add/remove nudge sentences; suppress global categories; `isolate` escape hatch |
| `/kig-config`  | Manage settings (mode, poll interval, scope strategy, /loop detection)         |

Storage: global under `~/.claude/kig/`, per-project under `.kig/`. See `docs/testing.md` for manual integration tests.

### Custom Directives (legacy — still supported for the verbose engine)

Copy the example and add your own:

```bash
cp config/keepitgoing-directives.json.example ~/.claude/keepitgoing-directives.json
```

Edit to add project-specific reminders that get mixed into generated prompts.

### Project Requirements

Create a `.project-brief.md` in any project root. Lines starting with `- ` or `* ` are injected into prompts when Claude is working in that directory:

```markdown
- This is a CLOSED-SOURCE project. Never change the license.
- Firebase Auth uses anonymous auth with AsyncStorage persistence.
- Every PR needs visual verification screenshots attached.
```

## Building

```bash
# Build only (no install)
./scripts/build.sh

# Build with custom generator path
./scripts/build.sh --generator-path /custom/path/to/keepitgoing-generate.py
```

The compiled `.app` goes to `dist/` (gitignored).

## Auto-Start on Login

```bash
osascript -e 'tell application "System Events" to make login item at end with properties {path:"'$(pwd)'/dist/KeepItGoing-ClaudeChat.app", hidden:true}'
```

## Logs

Runtime logs are at `/tmp/claude-keepitgoing/app.log` (auto-rotating at 512KB, old logs deleted after 3 days).

## License

**[PolyForm Noncommercial License 1.0.0](LICENSE)** — source-available, not freely commercial.

### You CAN (without asking)

- Use it personally (hobby projects, research, learning, experimentation)
- Study the code, modify it, share your changes
- Use it inside a nonprofit, educational institution, government agency, or public-safety/health/environmental organization
- Fork it, contribute back via PRs

### You CANNOT (without a commercial license)

- Sell it, resell it, or bundle it into a paid product
- Use it inside a commercial company's paid services
- Offer it as a SaaS / hosted service for paying customers
- Build a business on top of it without discussing terms

### Commercial licensing

Commercial use requires a separate written license. Open an [Issue](https://github.com/twitchyvr/KeepItGoing/issues) with the subject line **"Commercial License Request"** describing your intended use and I'll get back with terms.

See [LICENSE](LICENSE) for the full legal text.
