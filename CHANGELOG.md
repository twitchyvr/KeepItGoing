# Changelog

All notable changes to KeepItGoing will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Consolidated all KIG files into a single repository
- Build/install/uninstall scripts
- 70 directive categories with 748 total phrasings
- 84 detectable project stacks (monorepo-aware)
- Anti-derail preamble system (8 variants)
- Two-tier priority system (Critical 90% + Elevated 70%)
- Stack-aware directive filtering (no mobile directives on web-only projects)
- Deep thinking intensifiers (16 variants)
- "Fill all gaps" directives
- Visual verification directives with tool-specific instructions (Playwright, computer-use MCP, MiniMax)
- UX coherence directives
- Anti-AI-slop design quality directives
- DevSecOps security gates (SAST, SCA, DAST, RASP, CSPM)
- LLMOps directives (prompt versioning, evals, guardrails)
- Testing pyramid directives (unit, integration, E2E, AI-UAT)
- GitHub Projects v2 directives
- CI/CD optimization directives (path filters, concurrency, caching)
- Release management directives
- Progressive delivery directives (canary, feature flags, blue/green)

## [2.0.1] - 2026-04-07

### Fixed

- Screen detection now uses primary window/tab (responds to Cmd+1)
- Content-hash idle detection replaced brittle spinner-char heuristics

## [2.0.0] - 2026-04-01

### Added

- Dynamic prompt generator (Python) with grammar-based composition
- Hook-based state tracking (PreToolUse, PostToolUse, Notification, Stop events)
- Content-hash idle detection
- Compaction detection and re-orientation prompts
- Fetch-failure backoff for wedged sessions
- Blind nudge path for sessions with huge scrollback buffers
- User-configurable directives via JSON file
- `kig` CLI for per-tab on/off toggle

## [1.0.0] - 2026-03-15

### Added

- Initial AppleScript applet for iTerm + Claude Code
- Basic idle detection via spinner characters
- Simple continuation prompts
