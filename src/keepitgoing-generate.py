#!/usr/bin/env python3
"""
KeepItGoing Dynamic Prompt Generator v2.0
═══════════════════════════════════════════════════════════════════
Generates highly varied, context-aware prompts for Claude Code sessions.
Uses grammar-based composition with 15+ directive categories, 10+ structural
templates, dynamic project/git context, and history-based deduplication.

Usage:
    python3 keepitgoing-generate.py [--cwd /path/to/project] [--mode idle|permission|status]

Output: A single prompt string to stdout.
"""

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HISTORY_FILE = Path.home() / ".claude" / "hooks" / "state" / "prompt-history.json"
MAX_HISTORY = 80  # track last N prompts to avoid repetition
USER_DIRECTIVES_PATH = Path("~/.claude/keepitgoing-directives.json").expanduser()

# ═══════════════════════════════════════════════════════════════════
#  FRAGMENT POOLS — the raw material for prompt construction
# ═══════════════════════════════════════════════════════════════════

OPENERS_CONTINUE = [
    "yes, continue.",
    "keep going.",
    "proceed.",
    "continue —",
    "yes — and continue.",
    "go on.",
    "more. continue.",
    "yes, keep pushing.",
    "onward.",
    "next.",
    "carry on.",
    "don't stop.",
    "press forward.",
    "keep at it.",
    "moving on.",
    "push through.",
    "let's go.",
    "yes. next step.",
    "keep rolling.",
    "good — continue.",
    "yes, more.",
    "keep moving.",
    "advance.",
    "forge ahead.",
    "stay on it.",
    "yes — keep building.",
    "maintain momentum.",
    "proceed without delay.",
    "continue the sweep.",
    "don't pause.",
    "next phase.",
    "yes, drive forward.",
    "keep the pace.",
    "stay sharp — continue.",
    "yes — full speed.",
    "push on.",
    "continue uninterrupted.",
    "keep flowing.",
    "next item.",
    "yes. press on.",
    "maintain course.",
    "don't slow down.",
    "continue — no breaks.",
    "yes, next.",
    "keep iterating.",
    "cycle forward.",
    "yes — deeper now.",
    "continue the pass.",
    "onward and deeper.",
    "yes, onward.",
    "keep hammering.",
    "proceed — next objective.",
    "good work — next.",
    "yes, finish this.",
    "keep shipping.",
    "stay locked in.",
    "continue the loop.",
    "don't break stride.",
    "yes — push harder.",
    "another pass.",
    "rotate to the next item.",
    "yes — no stopping now.",
    "full send — keep going.",
    "keep up the cadence.",
    "next cycle.",
    "yes, maintain the standard.",
    "keep executing.",
    "next deliverable.",
    "move to the next task.",
    "proceed to the next objective.",
]

OPENERS_STATUS = [
    "what's the current state?",
    "status check —",
    "where do we stand?",
    "what's left in the queue?",
    "progress report.",
    "what's next?",
    "any blockers?",
    "how's the backlog?",
    "what's pending?",
    "what needs attention right now?",
    "what's the highest priority item?",
    "are there failing tests?",
    "any open PRs waiting?",
    "what was just completed?",
    "what's the next milestone?",
    "which issues are still open?",
    "how many tests are passing?",
    "is anything broken right now?",
    "what did you just finish?",
    "give me the rundown.",
    "what's the state of the branch?",
]

OPENERS_FOCUSED = [
    "focus on",
    "priority:",
    "drill into",
    "home in on",
    "zero in on",
    "concentrate on",
    "target:",
    "deep dive into",
    "spotlight on",
    "emphasize",
    "narrow focus:",
    "critical area:",
    "attention:",
    "hone in on",
]

OPENERS_TERSE = [
    "continue.",
    "go.",
    "next.",
    "more.",
    "onward.",
    "proceed.",
    "yes.",
    "keep going.",
    "push.",
    "advance.",
    "deeper.",
    "further.",
    "iterate.",
    "carry on.",
    "ship it.",
    "move.",
]

# ═══════════════════════════════════════════════════════════════════
#  INTENSIFIERS — set the rigor/thoroughness level
# ═══════════════════════════════════════════════════════════════════

INTENSIFIERS = [
    "be deeply comprehensive.",
    "rigorous mode.",
    "thorough sweep, no shortcuts.",
    "go deep, not wide.",
    "comprehensive pass, not a surface skim.",
    "exhaustive review.",
    "look closely.",
    "deep inspection this round.",
    "leave nothing unchecked.",
    "meticulous pass.",
    "forensic-level attention.",
    "maximum rigor.",
    "no surface-level work.",
    "be surgically precise.",
    "examine every edge.",
    "obsessive attention to detail.",
    "treat this as production-critical.",
    "zero tolerance for half-measures.",
    "this needs to be bulletproof.",
    "audit-level thoroughness.",
    "examine with fresh eyes.",
    "pretend this is a security audit.",
    "imagine a user will hit every edge case.",
    "think like a pentester.",
    "assume nothing works until proven.",
    "verify, don't assume.",
    "question every assumption.",
    "second-guess everything once.",
    "be your own worst critic.",
    "high bar — no compromises.",
    "production-grade quality.",
    "release-candidate scrutiny.",
    "as if this ships to 10k users tomorrow.",
    "world-class standards.",
    "no known issues when you're done.",
    "nothing gets a pass.",
    "perfection is the floor.",
    "ruthless quality bar.",
    "if it's not right, it doesn't ship.",
    "every detail matters.",
    # Deep thinking intensifiers
    "THINK DEEPLY about this. not surface-level. not the first idea. the RIGHT answer.",
    "think deeply. the easy path is almost never the right path.",
    "slow down and think. what's the RIGHT solution, not the fast one?",
    "don't take the easy path — take the RIGHT path. think it through.",
    "think before you type. plan before you code. reason before you act.",
    "depth over speed. the right answer at half the speed beats the wrong answer instantly.",
    "think like an architect, not a typist. every decision has consequences.",
    "pause. think. is this the best way, or just the first way that occurred to you?",
    "engage your full reasoning. this deserves more than pattern-matching.",
    "think three steps ahead. what does this choice lead to?",
    "be thorough in ways that matter. fill all the gaps you see.",
    "fill every gap. if something is missing, incomplete, or half-done — finish it.",
    "fill all the gaps you see — missing tests, missing docs, missing edge cases, missing UI states.",
    "leave no gap unfilled. every TODO, every missing piece, every rough edge — address it now.",
    "thoroughness is not optional. check what you'd normally skip.",
    "don't settle. the first working version is the starting point, not the finish line.",
]

# ═══════════════════════════════════════════════════════════════════
#  DIRECTIVE CATEGORIES — the core instruction fragments
#  Each category represents a concern area with 15-25 phrasings
# ═══════════════════════════════════════════════════════════════════

# The one directive that gets attached to every single prompt: tells Claude
# to always front-load its recommended option so KeepItGoing can auto-select
# "1" and be guaranteed to pick the right answer. Paired with the applet's
# broader menu auto-accept (which picks option 1 on numbered menus and "y"
# on [Y/n] prompts). Together: full automation of choice handling.
PERMANENT_DIRECTIVE = "when you show me a menu or ask y/n, always put your recommended option first — i may not be here to read it, the automation picks #1 by default."

# Variants so the permanent directive itself doesn't read robotically when it
# lands at the end of every prompt. Picked at random.
# De-escalation framing + option-ordering. Appended to every prompt to
# prevent Claude from interpreting directives as new commands. Without
# this, "ensure licensing" caused Claude to literally change the project
# from closed-source to open-source. The framing makes clear these are
# background mindset reminders, NOT action items to execute.
# Three concerns baked into every prompt's closing frame:
#   A. De-escalation: these are reminders, not new commands
#   B. Surface blockers: always tell the user what you're stuck on
#   C. Autonomy: never wait on design decisions — make the best-practice call
# Each variant hits all three so the user doesn't have to hope the right
# one gets picked from a rotation. Menus: recommendation = option 1.
# LOCKDOWN MODE: compressed to ~80 chars each to save tokens. Still
# covers: (1) de-escalation, (2) surface blockers, (3) autonomy, (4) menus.
# PREAMBLE: prepended to every prompt to prevent context-switching.
# The AI was interpreting directives as NEW tasks and dropping its current work.
# The preamble frames everything as ambient background — continue what you're
# doing, absorb the reminders, don't change course.
PREAMBLE_VARIANTS = [
    "[ambient — DO NOT change what you're doing. keep working on your current task. these are background reminders to absorb as you go, not new instructions.]",
    "[background — continue your current work. don't switch tasks. these are mindset reminders, not action items. absorb them and keep going.]",
    "[don't derail — stay on your current task. read these reminders passively. add to your mental checklist if useful, but do NOT stop or change direction.]",
    "[keep working — these are sideline reminders, not new assignments. continue what you're doing. absorb, don't react. stay focused on your current task.]",
    "[passive update — your current task is still the priority. these are ambient quality reminders. note them, don't act on them separately. keep building.]",
    "[stay on course — this is not a new task. this is a background quality nudge. continue your current work. fold these into your thinking, don't pivot to them.]",
    "[ambient context — don't stop. don't switch. these are reminders that run in the background of whatever you're already doing. continue.]",
    "[no context switch — you're in the middle of something. keep going. these directives are ambient, like a coach murmuring from the sideline. absorb and continue.]",
]

PERMANENT_DIRECTIVE_VARIANTS = [
    "(think deeply. fill gaps. blocked? say so. design calls? decide. menus: #1 = yours.)",
    "(think deeply. don't take the easy path. surface blockers. decide autonomously. menus: rec first.)",
    "(think deeply. fill all the gaps you see. say what you need. don't wait. menus: #1.)",
    "(think before you act. fill gaps. shout what blocks you. be decisive. menus: recommend as #1.)",
    "(depth over speed. fill every gap. surface blockers. be autonomous. menus: #1 = your pick.)",
    "(think deeply. do it right, not fast. need something? say it. menus: rec = option 1.)",
    "(the right path, not the easy path. fill gaps. blockers get repeated. menus: #1.)",
    "(think deeply. fill all gaps. tell me what's stuck. own the design calls. menus: rec first.)",
]

DIRECTIVES = {
    "dogfooding": [
        "dogfood everything you've built.",
        "use the thing yourself before signing off.",
        "dogfood, test, check — in that order.",
        "eat your own cooking first.",
        "make sure i always have a runnable executable of every latest working build.",
        "run the app. click every button. fill every form. break it before a user does.",
        "the ultimate test: would you use this yourself and be satisfied?",
        "if you haven't used it, you haven't tested it.",
        "dogfood every new feature before closing the issue.",
        "run it like a real user, not like a developer who knows the happy path.",
        "exercise the sad paths too — what happens when things go wrong?",
        "dogfood on a fresh state — clear caches, reset data, start from zero.",
        "use it the way someone who has never seen this code would use it.",
        "close the IDE. open the app. use it. that's your test.",
        "if you can't demo it live without nervousness, it's not done.",
        "test it in the real environment, not just in a dev sandbox.",
        "treat every interaction as a QA session.",
        "dogfood on real hardware — simulators and emulators don't count as proof.",
        "install the build on a device you actually use day-to-day.",
        "use the app under real-world conditions: bad network, low battery, interrupted by a call.",
        "if it's a CLI, run it in a fresh shell with no cached state. if it's a service, hit it from a clean client.",
        "the developer who built it is the worst tester for the happy path and the best tester for the sad paths — be both.",
        "dogfooding is not a phase. it is continuous, every build, every change.",
    ],
    "inspection": [
        "every element added, edited, removed, or touched gets visually inspected and functionally verified.",
        "every change — additions, edits, removals — must be seen, clicked, and verified end to end.",
        "every modified element is inspected visually and tested functionally.",
        "nothing ships without being seen, clicked, and scrolled past.",
        "verify with your own eyes, not just with assertions.",
        "look at the screen. does it look right? does it behave right?",
        "screenshot or it didn't happen — verify visually.",
        "click through every flow that touches your change.",
        "hover states, focus states, error states — check them all.",
        "does it still work with no data? with too much data? with bad data?",
        "resize the window. rotate the device. change the font size. does it survive?",
        "visual inspection: alignment, spacing, typography, contrast.",
        "functional verification: click, type, submit, navigate, undo.",
        "verify the change in context — not just in isolation.",
        "scroll up, scroll down, switch tabs — does the state persist correctly?",
        "for non-visual code, inspection means logs, traces, and output diffs — examine them with the same rigor as a UI.",
        "inspect the diff, the runtime behavior, and the side effects. all three.",
        "verify in light mode and dark mode. in portrait and landscape. on small screens and large.",
        "exercise empty, partial, full, and overflow states for every container.",
        "if the change touches state, verify state survives reload, resume, and backgrounding.",
    ],
    "code_review": [
        "code review on every diff, e2e on every flow, and ideate new improvements.",
        "every change gets code review and e2e coverage.",
        "no code without review, no feature without e2e.",
        "code review and e2e are non-negotiable.",
        "do not forget to visually verify, test, code review, and ideate new features.",
        "elements being visible isn't the same as elements fully functioning — verify both.",
        "use gh issues, gh prs, gh branches, gh code reviews to track everything.",
        "review your own diff before declaring it done.",
        "read the diff as if someone else wrote it. what would you flag?",
        "review for correctness, security, edge cases, and performance.",
        "code review: is there dead code? unused imports? type safety gaps?",
        "every PR gets a dual-pass review: functional then architectural.",
        "review with the reviewer persona: 'where will this break in prod?'",
        "check: are errors handled? are types tight? are edge cases covered?",
        "code review isn't optional. it's stage 6 of 8.",
        "review the diff line-by-line. then review it again at the file level. then at the architecture level.",
        "reject your own quick fixes. if it wouldn't pass review from a senior, it doesn't pass yours.",
        "review for naming, clarity, and intent — not just correctness.",
        "every PR gets a written review summary. 'lgtm' is not a review.",
        "if you can't explain why a line exists, it shouldn't exist.",
    ],
    "layout": [
        "the ui must be polished, not bland. magical auroras, fancy animated visualizations.",
        "no overhanging elements, no clipped text, no broken scroll.",
        "no overflow, no clipping, no stuck scroll states.",
        "layout checked: nothing overhangs, nothing clips, scroll works everywhere.",
        "every view scrolled through — no overhang, no clipping, no dead zones.",
        "text is legible and contrast passes throughout.",
        "find places to add magical auroras and animated visualizations — make it feel alive.",
        "visualize and graph out all possible data — if data exists, show it beautifully.",
        "the UI should feel delightful, not functional-but-boring.",
        "smooth transitions, purposeful animations, clear visual hierarchy.",
        "whitespace is a design tool. use it intentionally.",
        "every pixel is deliberate. nothing is accidental.",
        "mobile-first, then desktop — or vice versa, but test both.",
        "the loading state, the empty state, the error state — all of them designed.",
        "use cutting-edge and experimental design patterns.",
        "test the layout at the smallest supported viewport and the largest. it must work at both extremes.",
        "safe areas, notches, home indicators, status bars — nothing under the system UI.",
        "test with the system font set to its largest accessibility size. nothing breaks.",
        "animations have a purpose. if you can't justify it, cut it.",
        "every interactive element has a hit target large enough for a thumb.",
    ],
    "stamps": [
        "if it doesn't have a stamp of approval, it hasn't been rigorously checked — redo it.",
        "stamp of approval or it doesn't count. no stamp = not done = restart.",
        "no 'looks fine to me' — either stamped approved or not checked yet.",
        "every item is either stamp-approved or unverified. unverified means restart the check.",
        "if anything interrupted the check mid-way, restart from scratch.",
        "partial verification is zero verification. complete the full loop.",
        "if you had to rush, it's not verified. go back and do it properly.",
        "a skipped step invalidates the entire review. start over.",
        "every check has a definitive pass/fail. no maybes. no 'probably fine.'",
        "sign off explicitly on each item. if you can't, it's not done.",
        "the stamp is binary. approved or not. there is no 'mostly approved.'",
        "if you weren't paying full attention to the check, the check didn't happen.",
        "stamps are earned by evidence, not by vibes.",
    ],
    "ownership": [
        "all code is yours. there is no 'existing' code, no 'existing' conditions, no 'existing' issues.",
        "you own 100% of this codebase. 'pre-existing' is not a word here.",
        "nothing is legacy. nothing is someone else's problem. you own all of it.",
        "no 'this was already broken' excuses — you own every line.",
        "if it's in the repo, it's your responsibility. period.",
        "broken test? your test. broken feature? your feature. fix it.",
        "there is no blame. there is only the current state and what you do about it.",
        "own the bugs as much as you own the features.",
        "the codebase's quality is your quality. make it reflect well on you.",
        "treat every file as if you wrote it yesterday and need to defend it today.",
        "if you saw it and didn't fix it, you chose to leave it broken. own that choice.",
        "the build is yours. the pipeline is yours. the docs are yours. all of it.",
        "nothing in this repo is 'not my area.' there are no areas. there is the repo.",
    ],
    "issue_flow": [
        "every issue found: gh issue, branch, PR, test, merge to main.",
        "bugs get the full flow: gh issue, branch, PR, verification, merge.",
        "any issue: file a gh issue, cut a branch, open a PR, test it, merge.",
        "issue discovered? gh issue, branch, PR, tested, merged. every time.",
        "no drive-by fixes. every fix flows through the full git workflow.",
        "the flow is non-negotiable: issue → branch → PR → review → merge.",
        "if you found a bug while fixing something else, file a new issue for it.",
        "don't bundle unrelated fixes. separate issues, separate branches, separate PRs.",
        "link every PR to its issue. link every issue to its milestone.",
        "the git log should tell a story. each commit references an issue.",
        "every issue must be dogfooded individually before closure.",
        "close issues with evidence — what was tested, what was observed.",
        "no issue, no work. if you're touching code without an issue open, stop and file one.",
        "use the correct issue template. if no template fits, create one before opening the issue.",
        "branches are named after issues: <type>/<issue-number>-<slug>.",
        "PRs close issues with the 'Closes #N' syntax — every time, no exceptions.",
        "if work spans multiple concerns, split it into multiple issues. one PR, one concern.",
    ],
    "skip_nothing": [
        "nothing skipped. every step taken. CHANGELOG.md, README.md and Wiki always updated with screenshots.",
        "zero shortcuts, zero skipped steps.",
        "no step is optional.",
        "skip nothing, ever.",
        "every step exists for a reason. don't shortcut any of them.",
        "the checklist is the checklist. all items checked, all items done.",
        "if you think a step doesn't apply, you're wrong. do it anyway.",
        "convenience is not a reason to skip a step.",
        "speed without process is just fast failure.",
        "the full loop: code, test, type-check, lint, review, e2e, dogfood. all of it.",
        "there are 8 stages. you do all 8. every time.",
        "tired is not a reason to skip. late is not a reason to skip. urgent is not a reason to skip.",
        "the skipped step is always the one that bites you.",
        "the process is the safety net. cut the net and you fall.",
    ],
    "worktrees": [
        "use git worktrees to parallelize — if they're broken, fix them first.",
        "git worktrees for parallel work. repair them if they fail.",
        "parallelize aggressively with git worktrees. fix them if they break.",
        "git worktrees: run everything parallelizable in parallel.",
        "don't serialize work that can be parallelized. use worktrees.",
        "parallel agents, parallel worktrees, parallel progress.",
        "if one worktree is blocked, the others keep moving.",
        "maximize throughput: worktrees for independent tasks, sequential for dependent ones.",
        "one worktree per concurrent issue. clean teardown when the issue closes.",
        "worktrees are cheap. spin them up, tear them down, don't hoard them.",
    ],
    "apple_hig": [
        "follow Apple HIG, Apple design patterns, Apple code conventions throughout.",
        "Apple-guided design, Apple patterns, Apple standards — all of it.",
        "Apple HIG and Apple best practices are the baseline.",
        "design and code to Apple standards — HIG, patterns, conventions.",
        "use cutting-edge design patterns alongside Apple conventions.",
        "SwiftUI idioms, Apple naming conventions, platform-native feel.",
        "if Apple has a guideline for it, follow it. if they have a pattern, use it.",
        "this should feel like a first-party Apple app, not a cross-platform port.",
        "respect the platform. use system components where they exist.",
        "Apple's design language is the north star for visual decisions.",
        "for Apple platforms: HIG-compliant spacing, typography, and motion.",
        "Apple platforms: respect Dynamic Type, Reduce Motion, and the system color palette.",
    ],
    "platform": [
        "Apple guidelines win where there's any conflict.",
        "Apple standards take precedence in all design ties.",
        "Apple guidelines are the priority for all platform decisions.",
        "Apple standards are the north star.",
        "if the project supports multiple platforms, Apple leads the way.",
        "native feel on every platform, with Apple setting the bar.",
        "platform-native components wherever possible.",
        "no generic cross-platform compromises. each platform gets its best.",
    ],
    "platform_native": [
        "respect the platform you're building on. native conventions over generic ones.",
        "iOS gets HIG, Android gets Material, Windows gets Fluent, web gets web standards. no mixing.",
        "if the platform has a native pattern for it, use the native pattern.",
        "cross-platform projects still ship platform-native UX on each target.",
        "users expect their platform's conventions. don't fight muscle memory.",
        "system components beat custom components unless you have a documented reason.",
        "respect the platform's navigation model, gesture model, and lifecycle.",
        "for games and engines (Unity, Unreal): follow engine conventions and asset pipelines, not generic application patterns.",
        "for CLIs: follow POSIX conventions, exit codes, stdin/stdout/stderr discipline.",
        "for libraries: follow the host language's idioms — pythonic Python, idiomatic Rust, idiomatic Go.",
    ],
    "documentation": [
        "CHANGELOG.md, README.md, and Wiki must be current. always.",
        "if the code changed, the docs changed. they're inseparable.",
        "README reflects current state. CHANGELOG reflects recent changes. Wiki reflects architecture.",
        "a new user should be able to clone and succeed using only the README.",
        "every feature merge updates the docs. every breaking change updates the README.",
        "screenshots in the README. always. show, don't just tell.",
        "the Wiki has architecture decisions, onboarding guides, and workflow docs.",
        "CONTRIBUTING.md is up to date with actual contribution steps.",
        "release notes are plain-language, not a copy of the CHANGELOG.",
        "dead or outdated docs are worse than no docs. keep them alive.",
        "every public function, class, and module has a docstring or doc comment that explains why, not just what.",
        "architecture decisions get an ADR. reversible decisions don't need one; irreversible ones always do.",
        "if a new contributor can't get from clone to running in 15 minutes, the docs are broken.",
        "code comments explain intent and tradeoffs. the code itself explains mechanics.",
        "examples in the docs are tested examples — they actually run.",
    ],
    "accessibility": [
        "accessibility is not optional. contrast, focus order, screen reader support.",
        "use accessibility standards and best design practices throughout.",
        "every interactive element has a focus indicator and a label.",
        "contrast ratios pass WCAG AA at minimum.",
        "keyboard navigation works for the entire app.",
        "screen reader announces every state change meaningfully.",
        "don't just meet the guidelines — make it genuinely usable for everyone.",
        "test with VoiceOver. test with reduced motion. test with large text.",
        "accessibility is a feature, not an afterthought.",
        "color is never the sole indicator of state.",
        "test with TalkBack on Android. test with NVDA or JAWS on web. test with the platform's native screen reader.",
        "respect Reduce Motion. respect Increase Contrast. respect Bold Text.",
        "every image has alt text. every icon has a label. every input has an accessible name.",
        "tab order is logical, not visual.",
        "form errors are announced, not just shown.",
    ],
    "security": [
        "think like an attacker for 30 seconds. what would you try?",
        "no hardcoded secrets, no exposed API keys, no open redirects.",
        "validate all input at system boundaries.",
        "auth and session handling reviewed with extra scrutiny.",
        "dependencies pinned and audited for known vulnerabilities.",
        "error messages don't leak internal details.",
        "HTTPS everywhere. CORS configured tightly. CSP headers set.",
        "the principle of least privilege for every permission and scope.",
        "secrets live in a secret manager or environment variables, never in the repo. ever.",
        "scan the repo history for leaked secrets — old commits count too.",
        "audit dependencies for CVEs on every add and on a recurring schedule.",
        "validate, sanitize, and escape — at the boundary, not deep in the stack.",
        "treat all user input as hostile until proven otherwise.",
        "logs never contain passwords, tokens, PII, or payment data.",
        "rate-limit anything that can be abused. lock anything that can be brute-forced.",
        "every external API call has a timeout and a failure mode.",
        "supply chain matters: verify package signatures and provenance where possible.",
        "for mobile: keychain/keystore for secrets, never plain files. for web: httpOnly secure cookies, never localStorage for tokens.",
    ],
    "performance": [
        "no O(n^2) where O(n) will do. check your loops.",
        "lazy load what you can. prefetch what you know you'll need.",
        "profile before optimizing, but don't ignore obvious waste.",
        "bundle size matters. dead code elimination. tree shaking.",
        "database queries: are they indexed? are they N+1? are they cached?",
        "if it's slow, measure it. if it's fast, keep it fast.",
        "smooth 60fps for all animations and transitions.",
        "define performance budgets — cold start, p95, memory, bundle size — and enforce them.",
        "measure on the slowest supported device, not the dev machine.",
        "regressions beyond budget block the merge.",
        "for games: frame time, draw calls, GC allocations. for services: latency, throughput, tail latency. for clients: time-to-interactive.",
        "memory leaks are bugs. measure with the profiler, not by guessing.",
        "the fast path stays fast. add a perf test for any hot path so regressions are caught.",
        "asynchronous when it matters, synchronous when it's clearer. don't async for the aesthetic.",
    ],
    "ideation": [
        "as you work, ideate improvements and new features. file issues for them.",
        "every pass through the code is a chance to spot something better.",
        "what would make this 10x better? what would delight a user?",
        "think beyond the ticket. what adjacent improvements are obvious?",
        "the backlog should grow from your observations, not just from user complaints.",
        "spot patterns across issues. three similar bugs might be one root cause.",
        "what's the next feature this naturally leads to?",
        "look for UX friction. any moment of confusion is a bug.",
        "if you find yourself working around something, that's an issue to file.",
        "act as engineer and product manager simultaneously. file what you notice.",
        "undocumented observations are lost work. file the issue the moment you see it.",
        "label new ideas 'enhancement' or 'idea' so they don't pollute the bug backlog.",
        "if you wished a feature existed while building, that's a feature request — file it.",
    ],
    "github_ops": [
        "make sure the github repo is fully configured — wiki, pages, labels, milestones, Projects v2 board, Dependabot, branch protection.",
        "every issue has labels, milestone, AND is on the GitHub Project board. no orphan issues floating outside the project.",
        "PRs link to issues. issues link to milestones. milestones map to releases. releases map to tags. the chain is unbroken.",
        "use GitHub Projects v2 — kanban board (Backlog → To Do → In Progress → In Review → Done), custom fields for priority, sprint, area, and release target.",
        "the GitHub Project board reflects reality. if an issue is in progress, it's in the 'In Progress' column. if it's done, it's in 'Done'. keep it current.",
        "stale issues get triaged. duplicate issues get closed. open issues get worked. the backlog is clean, labeled, and prioritized.",
        "respond to every comment on every issue and PR. engagement is part of the job. no comment goes unacknowledged.",
        "respect the repo's existing license, visibility, and access model. never alter them without explicit instruction.",
        "labels are consistent: bug, feature, enhancement, refactor, documentation, test, ci/cd, security, performance, priority: critical/high/medium/low.",
        "issue and PR templates (YAML form-based) exist for every common workflow. create missing ones rather than skipping them.",
        "branch protection on main: required reviews, required CI, no force-push, no deletion. use rulesets for more granular control.",
        "Dependabot is configured for every package manager in the repo. .github/dependabot.yml must exist.",
        "secret scanning and push protection are enabled. no leaked keys ever reach the remote.",
        "GitHub Releases for every version: `gh release create vX.Y.Z --generate-notes`. auto-generated notes from merged PRs.",
        "milestones = releases. every milestone maps to exactly one version. when all issues in a milestone are closed, it's time to release.",
    ],
    "testing": [
        "no merge without tests for new logic and regression tests for fixed bugs.",
        "coverage without assertions is theater. assert behavior, not just execution.",
        "tests must be deterministic. flaky tests are bugs — fix them, don't retry them.",
        "every bug fix starts with a failing test that proves the bug exists.",
        "tests run fast or developers stop running them. keep the suite quick.",
        "test the failure paths as carefully as the success paths.",
        "mock at the boundary, not in the middle. tests that mock everything test nothing.",
        "if you can't write a test for it, the design is probably wrong.",
        "regression tests are non-negotiable. every fixed bug gets one. forever.",
    ],
    "testing_pyramid": [
        "TESTING PYRAMID: unit tests (constant during dev) → integration tests (every PR) → E2E tests (before release) → AI-UAT (before handing to humans). all four layers, always.",
        "UNIT TESTS: every function with logic gets a unit test. run them constantly — after every code change, not just before pushing. they must be instant (<5s total).",
        "INTEGRATION TESTS: test how services, APIs, databases, and modules talk to each other. run on every PR and commit. real connections, not mocks.",
        "E2E TESTS: test complete user journeys end-to-end — login, create, edit, delete, navigate. run before every release. Playwright for web, Detox/Maestro for mobile.",
        "AI-UAT: before passing to human testers, YOU are the first UAT pass. use the app as a real user would. screenshot every screen. file bugs for everything that confuses, breaks, or feels wrong.",
        "AI-UAT is not optional — you are the QA team before the QA team. dogfood, screenshot, assess UX, check flows, verify states, file issues. THEN it goes to humans.",
        "unit tests catch logic bugs. integration tests catch wiring bugs. E2E tests catch flow bugs. AI-UAT catches experience bugs. you need ALL FOUR.",
        "the testing pyramid has a shape for a reason: many fast unit tests at the base, fewer integration tests in the middle, selective E2E tests at the top, and AI-UAT as the final gate.",
        "don't skip layers. unit tests that pass don't prove the API works. integration tests that pass don't prove the user flow works. E2E that passes doesn't prove the UX makes sense. AI-UAT fills that last gap.",
        "testing frequency: unit = every save. integration = every PR. E2E = every release candidate. AI-UAT = end of every sprint/milestone before human handoff.",
        "AI-UAT checklist: (1) open app fresh (2) complete primary user flow (3) screenshot every screen (4) try edge cases (5) assess UX coherence (6) file issues for EVERYTHING wrong (7) write UAT report.",
        "unit tests assert correctness. integration tests assert connectivity. E2E tests assert functionality. AI-UAT asserts quality. a feature isn't done until all four pass.",
    ],
    "shift_left": [
        "SHIFT LEFT: catch problems as early as possible. a bug found in design costs 1x. in dev costs 10x. in production costs 100x. find it early.",
        "pre-commit hooks: linting, formatting, type-checking, and secrets scanning (gitleaks) run BEFORE code can be pushed. problems caught here cost nothing.",
        "think about security during design, not during testing. threat model the architecture before writing the first line of code.",
        "define API contracts (OpenAPI, GraphQL schema, Protobuf) BEFORE implementation. frontend and backend develop in parallel, no blocking.",
        "contract-first development: the API spec IS the source of truth. code is generated FROM the contract, not the other way around.",
        "every new feature starts with: what are the security implications? what data flows where? what could go wrong? answer these BEFORE coding.",
        "pre-push hooks catch what pre-commit hooks miss: run the test suite, check for TODO/FIXME that shouldn't ship, verify build succeeds.",
        "shift-left means: design reviews before code reviews, threat models before architecture, API contracts before implementations, test plans before test code.",
        "the cheapest bug fix is the one you never have to make. invest in planning, contracts, and threat modeling upfront.",
    ],
    "ai_uat": [
        "AI-UAT: before ANY human tester sees this feature, YOU perform the first acceptance test. use the app as a real user. screenshot everything. file every issue.",
        "AI-UAT is your responsibility. don't skip it. don't rush it. open the app fresh, complete the primary flow, try edge cases, assess UX, write a structured report.",
        "you are the QA team before the QA team exists. unit tests prove correctness. integration tests prove wiring. E2E proves flows. AI-UAT proves QUALITY.",
        "AI-UAT protocol: (1) fresh start (2) first impression test (3) primary flow walkthrough (4) edge case exploration (5) design assessment (6) requirements cross-check (7) structured report.",
        "AI-UAT verdict: PASS (ready for humans), CONDITIONAL PASS (minor issues, file them but proceed), FAIL (critical issues, fix before human handoff).",
        "every AI-UAT session produces a report: verdict, screenshots, issues found (with severity), design assessment, requirements checklist. no report = not tested.",
        "AI-UAT catches what automated tests cannot: 'does this make sense?' 'is this intuitive?' 'would a real user be confused here?' 'does this feel professional?'",
        "run AI-UAT at the end of every sprint/milestone, after every major feature, and before every release. it's the final gate before humans.",
    ],
    "progressive_delivery": [
        "don't ship big-bang releases. use progressive delivery: feature flags → canary → gradual rollout → full release.",
        "feature flags: deploy code to production with the feature OFF. turn on for 5% of users. monitor. expand or rollback based on data.",
        "canary deployments: route a small % of live traffic to the new version. if error rates spike, automatic rollback. no human decision needed at 3am.",
        "blue/green deployments: two identical environments. switch the router to the new version once verified. instant rollback = switch back.",
        "progressive delivery is a safety net. ship fast, but ship safely. the cost of a bad deploy is measured in user trust, not just engineering time.",
        "monitor canary metrics: error rate, latency (p50/p95/p99), crash rate, API failures, user engagement. any anomaly beyond threshold = auto-rollback.",
        "feature flags are not just for releases — they're for experiments. A/B test UI changes, pricing, copy, flows. data-driven decisions beat opinions.",
    ],
    "security_gates": [
        "SECURITY GATES: code→SAST, build→SCA, staging→DAST, deploy→container scan, production→RASP. every stage has a gate. no code passes without clearing it.",
        "SAST (Static Analysis): scan source code for vulnerabilities WITHOUT executing it — SQL injection, buffer overflows, XSS. run on every PR. CodeQL or Semgrep.",
        "SCA (Software Composition Analysis): scan ALL third-party dependencies for known CVEs and license conflicts. generate an SBOM. Dependabot, Snyk, or npm audit.",
        "DAST (Dynamic Analysis): test the RUNNING application from the outside, mimicking an attacker. find auth bypasses, XSS, injection flaws that SAST misses.",
        "every build artifact is immutable and signed. once built, it cannot be tampered with. container images get a final scan before deploy for zero-day CVEs.",
        "IaC scanning: validate Terraform, Kubernetes, and cloud configs for security misconfigurations — exposed S3 buckets, open ports, missing encryption.",
        "decide what's right for each gate: should a 'Medium' vulnerability block the build? for production projects, YES. for prototypes, maybe not. set the policy and enforce it.",
        "pre-commit secret scanning is non-negotiable. gitleaks or git-secrets catches API keys, tokens, and passwords BEFORE they enter the repo history.",
        "SBOM (Software Bill of Materials): know exactly what's in your software. every dependency, every transitive dependency, every version. auditability is not optional.",
    ],
    "llmops": [
        "LLMOPS: if your app uses AI, you need a parallel quality pipeline for the 'brain' — prompt versioning, evals, guardrails, cost monitoring.",
        "treat system prompts as code. version them in the repo. test changes to prompts the same way you test changes to code. prompt regressions are real bugs.",
        "AI EVALS: automated tests that grade model output for accuracy, tone, hallucination rate, and safety. run evals before deploying any prompt change.",
        "agentic guardrails: timeout limits on agent loops, action allowlists, cost caps per request, human-in-the-loop for destructive actions. agents can run away — prevent it.",
        "monitor AI spend: track cost per feature, per user, per model. a single prompt change can 10x your API bill. alert on cost anomalies immediately.",
        "pin model versions. test on new model versions before switching. maintain fallback chains (primary model → fallback model → graceful degradation).",
        "RAG pipeline maintenance: vector databases and retrieval sources must be clean, current, and secure. stale embeddings = stale answers = user distrust.",
        "for any AI-powered feature: what happens when the model is slow? when it hallucinates? when the API is down? design for degradation, not just for success.",
    ],
    "scope_discipline": [
        "stay on scope. the Issue you're working on defines the boundary. don't fix unrelated things, don't add unrelated features, don't refactor unrelated code.",
        "scope drift is the #1 source of oversized PRs, merge conflicts, and wasted reviews. one Issue, one branch, one concern, one PR.",
        "if you find a bug while fixing something else — file a new Issue. don't bundle the fix into the current PR.",
        "ask before every change: is this part of the current Issue? if not, it belongs in a separate branch.",
        "scope drift over time means the codebase accumulates 'while I was here' changes that nobody reviewed carefully. resist.",
        "a 5-file PR gets a thorough review. a 40-file PR gets a 'looks fine to me.' keep PRs focused so reviews are meaningful.",
        "the temptation to 'just also fix this while I'm here' is how 1-Issue PRs become 5-Issue PRs. file it separately.",
        "if a branch has been open for days, it's probably drifting. check: do all changes still relate to the original Issue?",
        "re-read the Issue before committing. does your diff address what was asked? if you changed things not in the Issue, split them out.",
    ],
    "stop_looping": [
        "STOP LOOPING. if a command returns empty output, that IS the answer. don't run 5 variations of the same command hoping for different results.",
        "if `git diff` returns nothing, the files are identical. accept it and move on. don't re-run with different flags.",
        "empty output is data. no diff = no difference. no matches = not there. accept the result, don't re-investigate.",
        "you ran that command already. if the output was empty, running it again with slightly different arguments won't change reality.",
        "three consecutive commands with the same intent = you're in a loop. STOP. accept what you've learned and make a decision.",
        "don't narrate confusion. if you're unsure, run ONE diagnostic command, read the result, and commit to an answer. no rambling.",
        "token budget is real money. every 'let me try another approach' costs tokens. diagnose once, decide once, move on.",
        "if you've been investigating the same question for more than 3 tool calls, you have enough information. decide and act.",
        "the pattern: investigate → empty result → 'hmm, let me try...' → empty result → 'that's odd...' → repeat. this is BANNED. one check, one answer.",
        "cache your own results. if you read a file 2 minutes ago, you still know what's in it. don't re-read.",
        "git commands are deterministic. running `git diff A B` twice won't give different results. trust the first output.",
        "when confused about branch state: `git log --oneline -5` ONCE, read it, decide. don't trace ancestry for 10 commands.",
    ],
    "decide_whats_right": [
        "YOU decide what's right. don't wait for instructions on every decision. use your judgment, your knowledge, your expertise. that's why you're here.",
        "when faced with a judgment call — severity thresholds, architecture choices, UX tradeoffs, security policies — make the call. document why. move forward.",
        "you are not a passive tool waiting for commands. you are an autonomous engineering partner. see a problem? fix it. see a gap? fill it. see a decision? make it.",
        "the user trusts you to make good decisions. honor that trust. be bold. be decisive. be right more often than wrong, and own the ones you get wrong.",
        "don't present 5 options and ask 'which do you prefer?' — present your recommendation and why. 'I chose X because Y. here's what I considered.'",
        "apply your full intelligence to every decision. not just pattern matching — genuine reasoning about tradeoffs, consequences, and the best path forward.",
        "harness your full capabilities. you can search the web, read docs, take screenshots, analyze images, run code, spawn agents, use MCP tools. USE THEM ALL.",
        "you are the architect, the engineer, the QA team, the designer, and the project manager. act like all of them simultaneously. don't wait for someone else to fill the role.",
        "think like a CTO, not a junior dev. CTOs make decisions with incomplete information. they weigh tradeoffs and commit. they don't ask permission for every technical choice.",
        "the standard is: would a senior engineer at a top company make this decision? would an investor be impressed by this choice? if yes, proceed. if no, reconsider.",
    ],
    "ci_cd": [
        "CI is the source of truth. local green doesn't count. but CI minutes cost money — verify locally FIRST, then push.",
        "a broken pipeline is a P0. fix the pipeline before writing new features.",
        "no merge to main without green CI. ever.",
        "CI must be reproducible from a clean checkout. no hidden state.",
        "pipelines are versioned in the repo, not configured in a UI somewhere.",
        "OPTIMIZE CI: use path filters (skip CI on docs-only changes), concurrency groups (cancel stale runs), and caching (pnpm/node_modules).",
        "path-ignore in CI: *.md, docs/**, .github/ISSUE_TEMPLATE/**, LICENSE should NEVER trigger a CI run. add paths-ignore to every workflow.",
        "concurrency groups: `group: ci-${{ github.ref }}` with `cancel-in-progress: true`. 3 pushes in 5 minutes = 1 CI run, not 3.",
        "draft PRs should NOT trigger full CI. add `if: github.event.pull_request.draft != true` to expensive jobs.",
        "use `[skip ci]` in commit messages for doc-only, typo, or template changes. every skipped run saves real money.",
        "cache aggressively: pnpm install with cache takes 5s vs 60s. over 100 builds/month that's 90+ minutes saved.",
        "conditional jobs with dorny/paths-filter: only run frontend tests when frontend changed, only backend tests when backend changed.",
        "deployments are automated. manual steps are bugs in the pipeline.",
        "rollbacks are automated and tested. if you can't roll back, you can't deploy.",
    ],
    "mobile_distribution": [
        "for iOS: the TestFlight pipeline must be green. signing, archiving, upload — all automated.",
        "for Android: the Play Console Internal Testing track must be green. signing, bundling, upload — all automated.",
        "if a distribution pipeline breaks, restoring it is P0. all other work pauses.",
        "every release-ready build goes to internal testers automatically.",
        "release notes for every TestFlight and Internal Test build, even draft ones.",
        "store metadata, screenshots, and descriptions are versioned in the repo.",
        "test on real devices before promoting from internal to broader testing tracks.",
        "certificates and provisioning profiles are documented and recoverable. losing them is a recoverable error, not a project-ending one.",
    ],
    "release_management": [
        "every release follows: milestone complete → merge develop→release branch → final test → merge to main → tag → `gh release create` → CHANGELOG update.",
        "milestones = releases. milestone 'v2.1' contains exactly the issues that ship in v2.1. no more, no less.",
        "use `gh release create vX.Y.Z --generate-notes` for auto-generated release notes from merged PRs. edit for clarity, but start from auto-gen.",
        "CHANGELOG.md updated with every release. Keep a Changelog format: Added, Changed, Deprecated, Removed, Fixed, Security.",
        "SemVer discipline: MAJOR for breaking changes, MINOR for new features, PATCH for bug fixes. every tag follows vMAJOR.MINOR.PATCH.",
        "draft releases for upcoming versions: `gh release create vX.Y.Z --draft`. fill in as PRs merge. publish when ready.",
        "every tag on main gets a GitHub Release. every Release links to its Milestone. every Milestone lists what shipped.",
        "the GitHub Project board's 'Release' field tracks which version each issue targets. filter by release to see what's in scope.",
        "before releasing: verify ALL issues in the milestone are closed, ALL PRs are merged, ALL tests pass, CHANGELOG is updated, version numbers bumped.",
        "release readiness checklist: tests green, no open blockers, CHANGELOG written, README current, version tagged, release notes drafted.",
    ],
    "error_handling": [
        "no swallowed exceptions. no empty catch blocks.",
        "no force-unwrap, no .unwrap(), no '!' on untrusted input.",
        "every failure path is handled explicitly or propagated with context.",
        "errors carry enough context to diagnose without a debugger.",
        "'it shouldn't happen' is not an error strategy. handle it anyway.",
        "fail loudly. silent failures are how data gets corrupted.",
        "user-facing errors are actionable. internal errors are diagnosable. neither leaks secrets.",
        "every external call has a timeout, a retry policy, and a circuit breaker where it matters.",
        "panics, crashes, and aborts are reserved for unrecoverable conditions. everything else is a typed error.",
    ],
    "observability": [
        "structured logs. meaningful messages. correlatable IDs.",
        "if it can fail, it must say so loudly and usefully when it does.",
        "metrics for the things that matter: latency, error rate, throughput, saturation.",
        "traces for distributed work. you can't debug what you can't see.",
        "logs without context are noise. include the request, the user (anonymized), the operation.",
        "alerts on user-impact, not on internal state. alert fatigue kills response quality.",
        "debug logs are fine in development, gated in production.",
        "a new engineer should be able to diagnose a production issue from the logs alone.",
    ],
    "data_safety": [
        "migrations are reversible or explicitly one-way with a documented backup step.",
        "never ship a schema change without a tested rollback.",
        "destructive operations (DROP, DELETE, rm -rf, format) get confirmation, dry-run, or backup. ideally all three.",
        "user data is sacred. treat every destructive operation as if it's running on production now.",
        "backups exist, are tested, and are restorable. an untested backup is not a backup.",
        "for analytics events: schema is versioned, additive changes only, no silent breaks.",
        "PII is minimized, encrypted at rest, encrypted in transit, and deleted on schedule.",
    ],
    "privacy": [
        "collect the minimum data needed. nothing more.",
        "every piece of PII has a documented purpose, retention period, and deletion path.",
        "users can see what's stored about them and request deletion.",
        "third-party SDKs are audited for what they collect and where it goes.",
        "consent is explicit, granular, and revocable.",
        "respect platform privacy frameworks (App Tracking Transparency, Android privacy dashboard, browser permissions).",
        "no analytics on sensitive flows without explicit consent.",
    ],
    "dependencies": [
        "lockfiles are committed. versions are pinned.",
        "every new dependency requires justification: why this, why not stdlib, license, maintenance health, CVE history.",
        "audit transitive dependencies on every add.",
        "fewer dependencies is better. each one is a long-term liability.",
        "abandoned packages are removed and replaced. unmaintained code is a security hole waiting to open.",
        "license compatibility is checked before adding. respect the project's licensing intent.",
        "vendoring is acceptable when the upstream is unstable or critical.",
    ],
    "git_hygiene": [
        "commits are atomic. one logical change per commit.",
        "commit messages explain why, not just what. the diff shows the what.",
        "rebase your feature branch onto the base branch before opening a PR.",
        "force-push only on your own feature branches. never on shared branches.",
        "no commits to main, master, or develop directly. ever.",
        "the git log is documentation. write it like documentation.",
        "squash noisy WIP commits before merge. keep history readable.",
        "tags are immutable releases. don't move them, don't delete them.",
        "signed commits where the platform supports it.",
    ],
    "refactoring": [
        "leave the code cleaner than you found it. boy scout rule.",
        "refactor in separate commits from feature work. reviewers will thank you.",
        "no behavior change in a refactor. no refactor in a behavior change.",
        "if you're afraid to refactor, the test coverage is wrong. fix that first.",
        "name things well. half of code quality is naming.",
        "delete code aggressively. dead code is debt.",
        "duplication is cheaper than the wrong abstraction — but the right abstraction is cheaper than both.",
        "comments that explain bad code should be replaced with better code, not better comments.",
    ],
    "types_and_contracts": [
        "types are documentation that the compiler enforces. use them.",
        "no 'any', no untyped dictionaries at boundaries, no implicit casts on untrusted data.",
        "tighten types as a refactor. loose types invite bugs.",
        "contracts at module boundaries are explicit: inputs, outputs, errors, side effects.",
        "for dynamic languages: use type hints, schemas, and runtime validation at boundaries.",
        "for statically-typed languages: lean on the type system. make illegal states unrepresentable.",
        "the type signature is the first thing a reader reads. make it tell the truth.",
    ],
    "definition_of_done": [
        "done means: issue closed, branch merged via reviewed PR, CI green, tests added, visual and functional verification attached, security checked, docs updated, dogfooded on real hardware where applicable, and follow-up ideas filed.",
        "anything less than the full definition of done is in-progress, not done.",
        "the definition of done is the same on a Tuesday as it is on a Friday afternoon.",
        "'done' has a checklist. check every box. no exceptions for small changes.",
        "if you marked it done and skipped a step, undo the marking and finish the step.",
    ],
    "no_phantom_work": [
        "if it isn't reflected in an issue, branch, commit, or PR, it didn't happen.",
        "no phantom commits. no untracked changes. no 'i fixed it on my machine.'",
        "the repository history is the project's memory. protect it.",
        "every change has a paper trail from idea to merge. reconstruct it or revert.",
        "work that exists only in your head is work that gets lost.",
    ],
    "build_reproducibility": [
        "every build is reproducible from a clean checkout.",
        "bootstrap is documented: README, Makefile, script, or devcontainer.",
        "no 'works on my machine.' if it works on your machine and not CI, your machine is wrong.",
        "tool versions are pinned (asdf, mise, .nvmrc, rust-toolchain.toml, Pipfile, etc.).",
        "if a new contributor can't go from clone to running in 15 minutes, file a bug.",
        "containers, devcontainers, or nix for environments where 'just install it' isn't enough.",
    ],
    "option_ordering": [
        "when you present me with choices, always put your recommended option first so i can pick 1 without thinking.",
        "any time you offer a numbered or lettered menu, the top entry must be your actual recommendation.",
        "if you ask me y/n, default to the answer you'd pick yourself and put it as the capital letter.",
        "never bury the right answer in option 3. the recommendation is always option 1.",
        "when you list choices, the order encodes your recommendation — safest / most correct is always first.",
        "don't make me think about which option to pick. give me your pick as option 1.",
    ],
    "surface_blockers": [
        "if you're waiting on me for anything — an API key, a credential, a config value, a decision — say it clearly and prominently.",
        "don't assume i saw your last message asking for something. if you're still blocked, repeat the ask.",
        "i may have stepped away for hours. if you need something from me, surface it every time you report status.",
        "blocked? say what you need, who you need it from, and what you'll do once you have it.",
        "never sit idle waiting for my input without loudly stating what's needed. be annoyingly clear about it.",
        "if you asked for something 3 hours ago and i haven't responded, ask again. persistence is fine.",
        "your status should always answer: what are you working on, what's next, and what (if anything) are you blocked on?",
    ],
    "autonomous_decisions": [
        "don't wait for permission on technical or design decisions. pick the best-practice answer and keep moving.",
        "architecture calls, naming decisions, library choices — make them using industry best practices. document why.",
        "if you're debating two approaches, pick the one that's simpler, more standard, and easier to change later.",
        "i trust your technical judgment. decide and move forward. leave a note in the commit or PR if it's non-obvious.",
        "the only decisions to ask me about: spending money, changing licenses, deleting user data, or altering public APIs.",
        "for everything else — file structure, patterns, tooling, conventions — just pick the best option and go.",
        "waiting for a design decision is worse than making a slightly imperfect one. momentum matters.",
        "if the choice is between 'wait for Matt to weigh in' and 'pick the safer/more conventional option', pick option 2.",
    ],
    "verify_everything_you_create": [
        "anything you create unsupervised must be self-verified before it's considered done. code, configs, assets, UI, data — everything.",
        "wrote a component? render it, screenshot it, check every state (empty, loading, populated, error, overflow). don't assume it looks right.",
        "generated an image? open it. check dimensions, format, transparency, visual correctness. don't trust the API response status alone.",
        "generated audio? play it back. verify type (SFX vs music vs speech), duration, format, volume. a 200 response doesn't mean correct output.",
        "wrote an API route? call it. verify the response shape, status codes, error handling, edge cases. curl it yourself.",
        "created a config file? validate it. parse it. run the tool that consumes it and verify it doesn't error.",
        "wrote a migration? run it forward. run it backward. verify the data looks right after both directions.",
        "built a layout? screenshot at 3+ viewport sizes. check dark mode. check Dynamic Type at max size. check RTL if applicable.",
        "generated any data (seed data, fixtures, mock data)? read it back. spot-check for correctness, completeness, and format.",
        "if you can't verify it with your own eyes or an existing tool, build a verification tool. 20 lines of checking is cheaper than a shipped bug.",
        "the rule: if you created it and nobody is watching, you are both the creator AND the QA. verify your own work before moving on.",
        "charts, graphs, visualizations: render them, verify axes, labels, and data accuracy. a beautiful chart with wrong data is worse than no chart.",
        "CI configs, GitHub Actions, build scripts: run them. a config that parses but doesn't do what you intended is a silent failure.",
        "don't move to the next task until the current one is verified. unverified work is unfinished work.",
        "audio specifically: play it back. is it the right type — SFX, music, ambient, or speech? check duration, sample rate, format, volume levels. no sound lottery.",
    ],
    "consider_alternatives": [
        "don't do the first thing that pops into your head. name 2-3 approaches, weigh tradeoffs, pick the best — then act.",
        "first idea is rarely the best idea. force yourself to list at least one alternative before committing to an approach.",
        "pause before implementing. is this the right shape for the problem, or just the first shape your brain produced?",
        "for creative work (features, components, new behavior), invoke the `brainstorming` skill BEFORE coding. premature commitment = rework.",
        "ask: what are 3 ways to solve this? what's the simplest? what's the most flexible? what's the cheapest? pick with reasons, not reflexes.",
        "if you started coding within 10 seconds of reading the task, stop. you skipped the thinking step. re-read, consider options, then proceed.",
        "'the obvious solution' is a trap. obvious ≠ correct. at least check whether an alternative is better before committing.",
        "tradeoff explicitly: simpler vs more flexible, faster vs cheaper, isolated vs integrated. pick your axis consciously, not by default.",
        "bigger decisions deserve longer thinking. a 2-line fix can be reflex; a new module cannot. match deliberation to scope.",
        "when a task could go 2+ ways, surface the options to the user instead of picking silently. 'A or B?' beats 'I chose A, hope it's right.'",
    ],
    "critical_analysis": [
        "analyze with a critical eye. ask 'why is this here?' and 'does this make sense?' about every piece of code, every file, every flow.",
        "question everything. why does this function exist? why this data shape? why this pattern? if you can't answer, investigate before moving on.",
        "'does this make sense?' is the most important question you can ask. ask it constantly. about the code, the UI, the flow, the architecture.",
        "if something looks weird, it IS weird — investigate, don't paper over. weird code is a bug hiding or a refactor waiting.",
        "don't accept the status quo just because it's there. every existing pattern was a decision — was it the right decision?",
        "when you fix a bug, ask: why did this bug happen? what class of bug is this? where else might it hide? file Issues for the related risks.",
        "be skeptical of your own work. re-read it with a reviewer's hat before declaring done.",
    ],
    "total_ownership": [
        "all code is Claude's code. there is no 'pre-existing' — if it's in the repo, you own it. bugs, failures, weird patterns, legacy code — all yours.",
        "never say 'this appears to be pre-existing' — that phrase is banned. if it's broken, fix it. if it's weird, question it. if it's unclear, investigate.",
        "a test failure isn't someone else's problem just because you didn't write the test. you own the test AND the code it tests.",
        "context compaction doesn't absolve you. if you forgot writing something, re-read memory, re-run the tests, trust evidence over fading memory.",
        "no 'this was already broken' excuses. if you saw it and didn't fix it, you chose to leave it broken. own that choice.",
        "broken test? your test. broken feature? your feature. weird pattern? your refactor. all of it is yours.",
        "zero failures is the only acceptable state. if there are 47 failures, fix all 47 — not 'the ones I introduced.'",
    ],
    "user_journey_thinking": [
        "every flow: walk it end-to-end from entry to goal. does it make sense? is the primary action obvious in under 1 second?",
        "dogfood with fresh eyes — pretend you've never seen this before. can a brand-new user navigate without instructions?",
        "check every entry point: cold start, deep link, push notification, tab switch, error recovery. all of them, not just the obvious one.",
        "verify happy paths AND sad paths: no data, partial data, overflow, error, offline, slow network, interrupted mid-flow.",
        "does the layout match user expectations? primary action where the thumb rests? secondary actions discoverable but not cluttered?",
        "if you need to write docs to explain the UI, the UI is broken. fix the UI.",
        "shortest path from intent to result — every extra tap is friction. count them and remove unnecessary ones.",
    ],
    "design_judgment": [
        "think like a designer, not just an engineer. would a brand-new user understand this without being told?",
        "Nielsen's heuristics: visibility of system status, match real-world mental models, user control, consistency, error prevention.",
        "Fitts's Law: primary actions go where the thumb naturally rests. Biggest, closest targets are easiest to hit.",
        "progressive disclosure — show simple case by default, reveal advanced options when asked. don't front-load complexity.",
        "7±2 rule: more than 9 options on a screen = cognitive overload. split or prioritize.",
        "consistency over novelty — match platform conventions unless you have a damn good reason not to.",
        "nested menus more than 2 deep = users get lost. flatten or redesign.",
        "every modal is a context switch. use sparingly. never stack them.",
        "the grandma test: would a non-technical person understand this screen without being told? if not, redesign.",
    ],
    "proactive_ideation": [
        "act as engineer AND product manager simultaneously. file what you notice, don't just fix what's asked.",
        "while building, notice friction points — file enhancement Issues immediately, don't 'remember for later.' undocumented observations are lost work.",
        "after every feature you touch, ask: what would make this 10x better? what adjacent improvements are obvious? file Issues for them.",
        "spot patterns across Issues — three similar bugs might have one root cause that's actually a design problem. file a refactor or design Issue.",
        "request features that make sense. propose enhancements. suggest changes. the user can't think of everything; you're their second brain.",
        "look for missing affordances — if a user would naturally expect X to be tappable/swipeable/long-pressable, make it so. file the Issue.",
        "the backlog should grow from YOUR observations, not just user complaints. be a proactive product partner.",
        "found a rough edge while fixing something else? file it. found a feature gap? file it. found a UX inconsistency? file it.",
    ],
    "containerized_dev": [
        "develop in Docker containers or devcontainers wherever the stack supports it. keeps the host clean across many projects.",
        "databases always containerized — Postgres, Redis, MongoDB, etc. never install them directly on the Mac.",
        "backend services in Docker Compose. one `docker compose up` should bootstrap the entire local environment.",
        "use devcontainers for reproducible environments. if it works in the container, it works everywhere.",
        "mobile dev needs native access (simulator), but containerize the backend/API it talks to.",
        "before installing a tool globally, ask: can this run in a container instead? fewer host dependencies = cleaner machine.",
        "16GB M1 constraint: prefer lightweight containers. stop what you're not using. don't run Docker + Xcode + simulator simultaneously unless necessary.",
    ],
    "cli_first": [
        "CLI tools are the golden ticket. use them, find them, or build them. never ask the user to do something a CLI can do.",
        "need to check something? there's a CLI for that. gh, eas, firebase, doctl, supabase, jq, curl — use them.",
        "don't ask the user to 'open System Settings and change X.' find the defaults write command and do it yourself.",
        "if a task can be automated with a script, build the script. if a CLI exists, use it. manual steps are bugs.",
        "install tools with brew. run them with bash. pipe them with jq. never tell the user to do what a command can do.",
        "MCP servers, APIs, tunnels, CLI tools — these are your hands. use them. the user hired you to work, not to give instructions.",
        "before saying 'you'll need to manually...' — stop. can you curl it? brew install it? osascript it? gh api it? then do it.",
    ],
    "build_your_own_tools": [
        "if the right verification tool doesn't exist, build it. a script that checks your work is always worth the 10 minutes.",
        "reusable tools become their own GitHub repos — full README, LICENSE (ask Matt first), CHANGELOG, CI, --help flag. not dropped in scripts/.",
        "one-off project scripts live in the project's scripts/ dir. reusable tools live at twitchyvr/<tool-name> with the full treatment.",
        "if you're building a tool that could help another project, make it a separate repo. buried scripts don't get reused.",
        "every reusable CLI tool needs: README, LICENSE, CHANGELOG, CONTRIBUTING, issue templates, CI, --help, --version, semver tags, one-command install.",
        "the best tools are the ones you build for the specific problem. generic tools miss domain-specific bugs.",
        "verification tools are first-class code. commit them, test them, document them, version them — whether they live in scripts/ or their own repo.",
        "if you find yourself doing the same manual verification twice, automate it the second time. if the second use is in a different project, make it a repo.",
        "LICENSE decisions are Matt's call. never assume MIT/Apache — ask first, or default to 'unlicensed pending decision'.",
    ],
    "continuous_verification": [
        "dogfood the app after every meaningful change. not at sprint end — after every change.",
        "visual verification is continuous, not a phase. screenshot before and after. compare. every time.",
        "build the app locally after every feature. if it doesn't build, nothing else matters.",
        "run the test suite after every code change, not just before pushing. catch regressions immediately.",
        "simulator/emulator testing after every UI change — does it look right? does it respond right? on both platforms?",
        "Detox or Maestro E2E on critical flows after every merge to main. automated, not manual.",
        "Playwright for any web-facing endpoints or admin dashboards. if it has a UI, it gets browser testing.",
        "the cadence is: code → build → test → visual check → dogfood → push. not code → push → pray.",
        "if the project has a simulator, use it every build. if it has Playwright, run it every PR. if it has Detox, run it every merge.",
        "adapt the verification tool to the stack: Detox/Maestro for mobile, Playwright for web, simctl for iOS native, xctest for Swift.",
        "verification isn't one tool — it's the right tool for each layer. unit tests for logic, E2E for flows, visual for UI, dogfood for UX.",
    ],
    "local_first": [
        "verify EVERYTHING locally before pushing. jest, lint, tsc, ratchets, build — all green locally or don't push.",
        "CI is a confirmation gate, not a test runner. if you're discovering failures in CI, you skipped local checks.",
        "run the bundle ratchet script locally. run the sentinel tests locally. run the dep justification check locally. then push.",
        "if you push and CI fails, that's a process failure — you should have caught it on your machine first.",
        "build the app locally before kicking off an EAS build. xcodebuild or expo export catches issues without burning cloud credits.",
        "visual verification happens on your screen first — screenshot the simulator, inspect the layout, THEN push for review.",
        "the local dev loop is free. CI minutes, EAS builds, and GitHub Actions are not. use the free one first.",
    ],
    "accessibility_as_testing": [
        "accessibility is mandatory AND it's your best testing tool. if VoiceOver can navigate it, the component tree is correct.",
        "every interactive element needs: accessibilityLabel, accessibilityRole, accessibilityHint where non-obvious.",
        "run the accessibility inspector on every screen. missing labels = missing test hooks = untestable UI.",
        "VoiceOver navigation is a free integration test — it proves the element hierarchy, focus order, and state announcements work.",
        "TalkBack on Android, VoiceOver on iOS. test both. they catch different issues.",
        "Dynamic Type at maximum size is a free layout stress test. if it doesn't break at xxxLarge, the layout is robust.",
        "contrast ratios aren't just accessibility — they're readability. WCAG AA minimum, AAA where possible.",
        "accessibility labels are documentation that the OS enforces. use them as your component's public API for testing.",
        "Reduce Motion, Increase Contrast, Bold Text — toggling these system settings is free QA. do it every build.",
    ],
    "verify_before_using": [
        "before adding or upgrading any package, look up its current docs — your training data may be outdated.",
        "never assume API syntax from memory. fetch the docs for the exact version you're using.",
        "new dependency? check: latest stable version, known CVEs, peer dependency conflicts, breaking changes in recent releases.",
        "version conflicts between packages are silent killers. check compatibility matrices before combining libraries.",
        "before using any API or SDK feature, verify it exists in the version you're targeting — not just in 'some version.'",
        "security advisories exist for a reason. check the package's GitHub issues and npm/PyPI advisories before depending on it.",
        "if you're not sure about the syntax, look it up. a 10-second doc fetch is cheaper than a 10-minute debug session.",
        "your training data has a cutoff. the library may have changed its API, deprecated methods, or introduced breaking changes since then.",
        "use context7 or web search to fetch current docs — especially for fast-moving libraries like Expo, React Native, Firebase, Next.js.",
        "check the CHANGELOG of any package you're upgrading. migration guides exist because breaking changes exist.",
    ],
    "requirements_persistence": [
        "re-read .project-brief.md and CLAUDE.md if you're unsure about a project constraint. they're the source of truth.",
        "never assume a requirement has changed unless you see it changed in the file. the brief is authoritative.",
        "project requirements survive context compaction because they're in files, not conversation history. read them.",
        "if you're about to make a decision that conflicts with .project-brief.md, stop and re-read the file first.",
        "the project brief is the contract. if a directive in this prompt conflicts with the brief, the brief wins.",
    ],
    "resource_cost_awareness": [
        "LOCKDOWN until ~May 1-9: EAS, GitHub Actions, DO, AND Claude tokens all maxed. Local-first, parallelize, batch, push once.",
        "use Fastlane, not EAS. local iOS build costs $0. cloud build costs $3-5. always local.",
        "parallelize the M1's 8 cores. jest + lint + tsc simultaneously. don't serialize what can run concurrently.",
        "don't waste tokens. no repeated file reads. no 'let me try this and see'. know before you run.",
        "one push = one green run. if you need a second push to fix CI, you already failed — next time diagnose locally first.",
        "batch ruthlessly. consolidate 5 fixups into 1 commit. 5 pushes = 5 CI runs wasted.",
        "can this be done without touching the cloud? then do that. never use what you don't need.",
        "diagnose locally, not via CI. push a guess and you've spent money finding out it's wrong.",
    ],
    "token_efficiency": [
        "be precise. every diagnostic run, every file read, every grep costs tokens. plan before you probe.",
        "don't read the same file twice. cache mentally. if you needed line 50 once, you still have it.",
        "avoid 'let me check' loops. know what you're looking for before you run the command.",
        "use targeted greps, not full-file reads. `grep -n 'pattern' file` beats reading 500 lines.",
        "compress your own output. short decisive sentences beat paragraphs of narration.",
        "parallelize independent work via subagents — one round-trip beats three sequential investigations.",
        "batch file reads. one `Read` with the right offset/limit beats five exploratory reads.",
    ],
    "resource_efficiency": [
        "run ALL checks locally before pushing — jest, lint, tsc, ratchets, sentinels. CI is for verification, not discovery.",
        "one push, one green CI. if you need 4 CI runs to pass, you're using CI as a test runner — stop.",
        "every failed CI run costs real money and real time. batch your fixes, verify locally, push once.",
        "EAS builds are expensive. only kick one off when CI is green AND the fix is verified.",
        "token budget matters. don't re-read files you just wrote. don't re-search things you just found.",
        "if a test keeps failing, stop and read the error — don't push 3 fix attempts to CI hoping one sticks.",
        "measure twice, push once. local verification is free. CI runs are not.",
        "consolidate commits before pushing. 5 fixup commits in 10 minutes is 5 CI runs wasted.",
        "if the same sentinel keeps failing, add a local pre-push hook so you never forget that check again.",
    ],
    "parallel_agents": [
        "spawn subagents for independent tasks. each gets a fresh context window — don't cram everything into one conversation.",
        "Agent Team pattern: orchestrator delegates, frontend/backend/test agents run in parallel with isolation: 'worktree'.",
        "launch multiple subagents in ONE message when tasks are independent. don't serialize what can parallelize.",
        "the main session is the manager — it routes, coordinates, verifies. heavy implementation goes to subagents.",
        "use isolation: 'worktree' for any subagent that writes code. prevents merge conflicts between parallel workers.",
        "research agents run in foreground (need their results). implementation agents run in background (independent work).",
        "after subagents return, verify: run tests, check for conflicts, review diffs. trust but verify.",
        "don't be a solo worker when you can be a team lead. decompose → delegate → parallelize → verify → merge.",
        "one agent per concern: UI agent, API agent, test agent, docs agent. each focused, each fresh, each fast.",
        "subagents are cheap. context is expensive. spawn a worker instead of stretching one conversation past 150K tokens.",
    ],
    "context_budget": [
        "context is finite — 200K on MiniMax, 1M on Claude. plan your token spend like a budget. don't waste on re-reads.",
        "on MiniMax: keep the orchestrator under 50K tokens. delegate everything else to subagents with fresh windows.",
        "system prompt + tools eat 10-15% of MiniMax's 200K window. every token there is 5× more costly than on Claude's 1M.",
        "approaching 150K tokens on MiniMax? spawn a subagent for the remaining work instead of risking early termination.",
        "after compaction: re-orient immediately. git status, re-read CLAUDE.md, check memory, review tasks. then resume.",
        "prompt caching saves 80% on input tokens. keep static content (tools, system prompt) stable to maximize cache hits.",
        "don't read files you just wrote. don't re-search things you just found. mental caching saves real tokens.",
        "compress your output. short decisive sentences beat verbose narration. every output token costs context for the next turn.",
        "multi-window workflow: framework in window 1, iteration in window 2. restart fresh rather than compacting.",
        "monitor your depth. if you've been in one conversation for 20+ tool calls, consider spawning a fresh subagent.",
    ],
    "quality_bar": [
        "never pick the simplest or fastest option. pick the BEST option — most robust, most scalable, most investible.",
        "build like investors are watching. every decision should make a pitch deck stronger, not weaker.",
        "the 'quick fix' is almost never the right fix. do it properly the first time. production-grade, always.",
        "don't optimize for speed of implementation. optimize for quality of outcome. long-term > short-term.",
        "ask: would a Series A startup ship this? would a senior engineer at a top company approve this? if not, redo it.",
        "the most user-friendly, most intuitive, most polished option wins. always. no exceptions.",
        "scalable architecture over quick hacks. maintainable code over clever code. robust solutions over brittle ones.",
        "every feature should feel like it was designed by someone who cares deeply about the user experience.",
        "don't build the minimum viable version. build the version that makes users say 'wow, someone actually thought about this.'",
        "think long-term. the decision you make now should still be the right decision in 2 years.",
        "simple ≠ best. the best solution is the one that handles all edge cases gracefully, scales naturally, and delights users.",
        "the right answer is rarely the fastest to implement. invest the extra time. it pays dividends.",
        "build for the user you want, not the deadline you have. quality is the only shortcut that works.",
        "every architectural choice: will this impress a technical co-founder? will this survive 100x growth? will users love this?",
        "cheap decisions compound into expensive problems. invest upfront in the best approach.",
    ],
    "stop_asking_approval": [
        "STOP asking for approval. STOP saying 'i need your approval' or 'waiting on your approval' or 'please approve.' just DO the work.",
        "you are autonomous. make decisions. don't ask permission for technical choices — just pick the best option and execute.",
        "if you're about to type 'should I...' or 'do you want me to...' — stop. the answer is yes. do the best thing and keep moving.",
        "the user hired you to WORK, not to ask questions. make the call, document why, and move on.",
        "don't block on me. if you need a design decision, make it using best practices. if you need approval for a technical choice, you already have it.",
        "every time you pause to ask permission, you're wasting time. the only things that need explicit approval: spending money, changing licenses, deleting user data, altering public APIs.",
        "you have blanket approval for all technical, design, and implementation decisions. use it. stop asking.",
        "if the choice is 'wait for approval' vs 'pick the best-practice answer and keep moving', ALWAYS pick option 2.",
        "'i need your input on...' — no you don't. you need to make the best decision and tell me about it after.",
        "autonomy is your default mode. asking is the exception, not the rule. be decisive.",
        "the user is probably not watching. they trust you to make good decisions. honor that trust by being decisive.",
        "blocked? surface what you need ONCE, then proceed with your best judgment. don't repeat 'waiting on approval' — that's a loop, not progress.",
    ],
    "visual_verification": [
        "TAKE A SCREENSHOT. use the computer-use MCP (mcp__computer-use__screenshot) to capture what the app actually looks like RIGHT NOW. don't guess — look.",
        "after every UI change: take a screenshot, LOOK at it, and ask 'does this make sense to a first-time user?' if not, fix it before moving on.",
        "screenshots are mandatory proof. no UI work is done without a screenshot proving it looks right. use mcp__computer-use__screenshot.",
        "visual verification means ACTUALLY LOOKING at the screen. take a screenshot with computer-use tools. examine it. describe what you see. identify problems.",
        "before closing any UI issue: screenshot the result. compare to what a user expects. if it doesn't match user expectations, it's not done.",
        "take screenshots at multiple states: empty, loading, populated, error, overflow. each one must look intentional and correct.",
        "screenshot the app on launch. is the first screen what a new user expects to see? does it immediately make sense? if not, that's a bug.",
        "use the visual-verify skill after any UI change. screenshot before AND after. compare. no visual regression ships.",
        "don't just check if the code compiles or the component renders. LOOK AT IT. take a screenshot. is it beautiful? is it intuitive? is it what the user expects?",
        "visual verification is not optional. every UI change gets: screenshot → inspect → verify layout/spacing/overflow/readability → fix issues → screenshot again.",
        "the computer-use MCP tools exist for a reason. use mcp__computer-use__screenshot to see what the user sees. your code output is not the product — the screen is.",
        "after building a feature, screenshot every screen it touches. walk through it like a user. does the flow make sense? would you be confused? fix what confuses.",
        "scroll down. scroll right. resize. rotate. screenshot each state. overflow, clipping, and broken layouts hide below the fold.",
        "on MiniMax/non-vision models: screenshot to /tmp/screen.png, then use mcp__MiniMax__understand_image with image_url=/tmp/screen.png to analyze it. you CAN see — use the tools.",
        "mcp__MiniMax__understand_image accepts local file paths OR URLs via the image_url parameter. screenshot to /tmp, then analyze. no excuses about not being able to see the UI.",
        "MiniMax tools: mcp__MiniMax__understand_image (image_url + prompt) for visual analysis, mcp__MiniMax__web_search (query) for docs/research. use both aggressively.",
        "reconnaissance-then-action pattern: start dev server → navigate → wait for networkidle → screenshot → inspect DOM → identify problems → fix → screenshot again. never act blind.",
        "for web apps: use Playwright to automate visual checks. page.screenshot(path='/tmp/verify.png', full_page=True) captures the entire page including below-the-fold content.",
        "screenshot the FULL page, not just the viewport. full_page=True in Playwright, or scroll and capture multiple screenshots. bugs hide below the fold.",
        "after every deploy or build: open the app in a browser, screenshot the landing page, and critically assess: is this what a paying customer expects to see?",
    ],
    "design_quality": [
        "STOP building generic AI slop. no more cookie-cutter layouts, no more bland component libraries with default styling. every UI must have a bold, intentional aesthetic direction.",
        "before writing any UI code: commit to a specific design direction. brutally minimal? luxury/refined? retro-futuristic? editorial? industrial? pick one and execute with precision.",
        "typography instantly signals quality. NEVER use Inter, Roboto, Arial, Open Sans, or system fonts. use distinctive fonts: Playfair Display, Clash Display, Bricolage Grotesque, Cabinet Grotesk, Crimson Pro.",
        "color palettes must be cohesive and intentional. dominant colors with sharp accents > timid, evenly-distributed palettes. no more purple gradients on white backgrounds.",
        "motion and animation should be orchestrated, not scattered. one well-timed page load with staggered reveals creates more delight than random hover effects everywhere.",
        "backgrounds create atmosphere. layer CSS gradients, geometric patterns, noise textures, subtle grain — not just solid #ffffff. depth makes the difference between 'app' and 'website template.'",
        "spatial composition: use asymmetry, overlap, grid-breaking elements, generous negative space. predictable centered layouts with even spacing is AI slop. be deliberate.",
        "the UI should look like a designer made it, not a developer who grabbed the nearest component library. every pixel is a design decision.",
        "loading states, empty states, error states — ALL of them designed, not afterthoughts. a styled empty state with a compelling illustration > a grey 'No items found' text.",
        "dark mode is not 'invert the colors.' it's a separate design pass with adjusted contrast, muted backgrounds, and considered color mapping. design it properly or don't ship it.",
        "icons should be consistent in style, weight, and visual language. don't mix icon sets. don't use default material icons everywhere. curate them.",
        "the difference between amateur and professional UI: shadows have purpose, borders have hierarchy, spacing has rhythm, and color has meaning. check all four.",
        "never produce UI that looks like it was generated by AI. that means: no generic card grids, no cookie-cutter dashboards, no 'hero section + three cards + testimonials' templates.",
        "every screen should pass the 'would this appear in a design portfolio?' test. if a designer wouldn't be proud to show it, it's not done.",
    ],
    "ux_coherence": [
        "the app must MAKE SENSE to someone who has never seen it before. if a new user can't figure out what to do in 5 seconds, the UX is broken.",
        "what does the user EXPECT to see when they open this app? build exactly that. not what's easiest to code — what the user's mental model demands.",
        "every screen must answer: where am I? what can I do here? what should I do first? if any answer is unclear, the screen is wrong.",
        "a tycoon game should feel like starting a business: pick a location, invest money, make decisions. NOT a feature test dashboard with shortcuts.",
        "an agent orchestrator should feel like a mission control center: clear status, focused workspace, one project at a time. NOT a wall of crowded panels.",
        "group features by what the USER thinks about, not by what the CODE organizes around. user mental model > developer mental model. always.",
        "if users report the UI 'doesn't make sense' — they're right. stop defending the implementation and redesign from the user's perspective.",
        "every app has a primary loop: the thing the user does 80% of the time. that loop must be obvious, fast, and delightful. everything else is secondary.",
        "overflow is a design failure, not a CSS problem. if content overflows, the design has too much content for the space. redesign the information hierarchy.",
        "crowded UI = failed prioritization. not everything can be visible at once. decide what matters most. hide the rest behind progressive disclosure.",
        "clunky means the user has to think about HOW to use the app instead of WHAT they want to do. remove every moment of 'how do I...'",
        "before adding any feature to a screen, ask: does this NEED to be here? can it live one tap deeper? will removing it make the primary action clearer?",
        "unintuitive UI is the #1 user complaint. take it seriously. screenshot the app, pretend you've never seen it, and honestly assess: does this make sense?",
        "the onboarding flow IS the product's first impression. if the first 30 seconds are confusing, the user has already mentally quit.",
        "scroll, overflow, clipping — these are the symptoms. the disease is trying to show too much at once. cure the disease, not the symptoms.",
        "every feature grouping should match how a user thinks about the task, not how the code is organized. if 'settings' has 40 items, it needs subcategories.",
        "users don't read. they scan. if the primary action isn't visually dominant (biggest, boldest, most prominent), they'll miss it.",
    ],
    "deep_thinking": [
        "THINK DEEPLY about what you're doing. don't pattern-match your way through this — reason about it from first principles.",
        "stop and think: what is the RIGHT solution here? not the fast one, not the easy one, not the familiar one — the RIGHT one.",
        "the easy path is almost never the right path. if your solution feels too easy, you probably missed something. dig deeper.",
        "think three moves ahead. what does this decision lead to in a week? in a month? in a year? build for the future.",
        "don't be a code monkey. be an architect. every line of code is a design decision — think about it like one.",
        "before implementing: what are 3 approaches? what are the tradeoffs? which one survives 100x growth? pick THAT one.",
        "engage deeply with the problem. shallow understanding produces shallow solutions. understand WHY before deciding HOW.",
        "the difference between good and great: good solves the stated problem. great solves the underlying need. think about what the user actually needs.",
        "resist the urge to start typing immediately. the best code is preceded by the best thinking. invest in understanding before implementation.",
        "think about the user who will use this in 6 months. think about the developer who will maintain this in a year. build for them, not for today.",
        "question the requirement. is this the right thing to build? does it serve the user's actual goal? sometimes the best code is the code you don't write.",
        "think holistically. this change doesn't exist in isolation — how does it affect the rest of the system? the user flow? the mental model?",
        "if you're about to do something 'quick and dirty' — stop. do it right. the quick fix today becomes the expensive rewrite tomorrow.",
    ],
    "fill_gaps": [
        "fill all the gaps you see. missing tests? write them. missing docs? add them. missing error handling? handle it. missing UI states? design them.",
        "look for what's MISSING, not just what's broken. the gap between 'it works' and 'it's complete' is where quality lives.",
        "every feature has gaps: missing edge cases, missing loading states, missing error messages, missing accessibility labels, missing docs. find them and fill them.",
        "after finishing a task, scan for gaps: is the README updated? are there new tests? are error states handled? are empty states designed? fill what's missing.",
        "incomplete work is worse than no work — it creates false confidence. if you touched it, complete it. fill every gap before moving on.",
        "the gaps you don't fill become the bugs your users find. edge cases, error paths, empty states, overflow handling — fill them NOW, not 'later.'",
        "when you see a TODO, a FIXME, a HACK, or a 'will handle this later' — handle it now. those comments are gaps begging to be filled.",
        "gaps compound. one missing error handler leads to a confusing UX which leads to a user complaint which leads to an urgent bug fix. fill it at the source.",
        "after every feature: list 5 things that could still be improved. file Issues for the ones you can't fix now. fix the ones you can.",
        "the difference between a demo and a product is the gaps. demos skip edge cases, error states, loading states, empty states. products don't. fill the gaps.",
        "look at this with a critical eye: what would a thorough QA engineer flag? what would a design reviewer catch? what would a user complain about? fill those gaps.",
        "a gap isn't just 'something missing' — it's also 'something half-done.' a feature that works but looks bad has a design gap. a test that passes but misses edge cases has a coverage gap. fill them.",
    ],
}

# ═══════════════════════════════════════════════════════════════════
#  STACK-AWARE DIRECTIVE FILTERING
#  Maps each directive category to the stacks where it's relevant.
#  If a category isn't listed here, it's universal (always included).
#  A category is included if ANY of its required stacks are present.
# ═══════════════════════════════════════════════════════════════════

# Categories that are ONLY relevant to specific stacks.
# If the project doesn't have any of the listed stacks, the category is excluded.
STACK_REQUIRED = {
    "apple_hig": {"ios", "apple"},
    "platform": {"ios", "apple", "android"},
    "mobile_distribution": {"ios", "android", "expo"},
    "accessibility_as_testing": {"ios", "android", "web", "expo"},
    "layout": {"ios", "android", "web", "expo", "unity", "game"},
    "user_journey_thinking": {"ios", "android", "web", "expo", "unity", "game"},
    "design_judgment": {"ios", "android", "web", "expo", "unity", "game"},
    "containerized_dev": {"web", "node", "python", "go", "rust"},
    "visual_verification": {"ios", "android", "web", "expo", "unity", "game", "apple"},
    "ux_coherence": {"ios", "android", "web", "expo", "unity", "game", "apple"},
    "design_quality": {"ios", "android", "web", "expo", "unity", "game", "apple"},
}

# ═══════════════════════════════════════════════════════════════════
#  STRUCTURAL TEMPLATES — how fragments are composed into messages
#  Slots: {opener} {intensity} {d1}..{d7} {context} {project}
# ═══════════════════════════════════════════════════════════════════

TEMPLATES_STANDARD = [
    "{opener} {intensity} {d1} {d2} {d3} {context}",
    "{context} {opener} {intensity} {d1} {d2} {d3}",
    "{opener} {d1} {d2} {intensity} {d3} {context}",
    "{d1} {d2} {opener} {intensity} {d3} {context}",
    "{context} — {opener} {d1} {d2} {d3} {d4}",
    "{opener} {d1} {d2} {d3} {d4} {intensity} {context}",
    "{intensity} {d1} {d2} {opener} {d3} {context}",
    "{context} {d1} {opener} {d2} {d3} {intensity}",
]

TEMPLATES_DETAILED = [
    "{opener} {intensity} {d1} {d2} {d3} {d4} {d5} {context}",
    "{context} {opener} {intensity} {d1} {d2} {d3} {d4} {d5} {d6}",
    "{opener} {d1} {d2} {d3} {intensity} {d4} {d5} {d6} {context}",
    "{intensity} — {d1} {d2} {d3} {d4} {d5} {opener} {context}",
    "{context} {d1} {d2} {d3} {opener} {intensity} {d4} {d5} {d6} {d7}",
]

TEMPLATES_TERSE = [
    "{opener}",
    "{opener} {d1}",
    "{opener} {d1} {context}",
    "{intensity} {opener}",
    "{d1} {opener}",
    "{opener} {intensity}",
]

TEMPLATES_FOCUSED = [
    "{focus_opener} {focus_area}. {d1} {d2} {context}",
    "{context} {focus_opener} {focus_area}. {intensity} {d1}",
    "{focus_opener} {focus_area} — {d1} {d2} {d3}. {context}",
]

TEMPLATES_STATUS = [
    "{status_opener} {d1} {context}",
    "{status_opener} then {d1} {d2} {context}",
    "{context} {status_opener} {d1}",
]

# ═══════════════════════════════════════════════════════════════════
#  FOCUS AREAS — for focused-mode prompts
# ═══════════════════════════════════════════════════════════════════

FOCUS_AREAS = [
    "testing and verification",
    "UI polish and animations",
    "code review and security",
    "documentation and README",
    "issue triage and backlog hygiene",
    "accessibility",
    "performance and bundle size",
    "git workflow and PR quality",
    "dogfooding the user experience",
    "error handling and edge cases",
    "the current open issues",
    "the failing tests",
    "the visual design and layout",
    "the API surface and types",
    "deployment readiness",
    "the data model and persistence layer",
]

# ═══════════════════════════════════════════════════════════════════
#  CONTEXT GENERATORS — dynamic runtime information
# ═══════════════════════════════════════════════════════════════════

TIME_TEMPLATES = [
    "for context: it's {date}, {time} in Chicago.",
    "fyi — today is {date}, currently {time} CT.",
    "context: {date}, {time}, Chicago.",
    "(time check: {date}, {time} Chicago time.)",
    "dateline: Chicago, {date}, {time}.",
    "timestamp: {date} at {time}, Chicago.",
    "grounding: it is {date}, {time} local (Chicago).",
    "situating you: {date}, {time} CT.",
    "{date}, {time} CT.",
    "it's {time} on {date}.",
    "right now: {date}, {time}.",
    "({date} — {time} Chicago)",
    "time context: {date}, {time} CT, Chicago IL.",
]


def load_user_data():
    """Load directives + settings from the user's JSON file."""
    default = {"directives": [], "settings": {"global_suffix": "Respond concisely."}}
    if not USER_DIRECTIVES_PATH.exists():
        return default
    try:
        return json.loads(USER_DIRECTIVES_PATH.read_text())
    except Exception:
        return default


def load_user_directives():
    """Back-compat: return just the directive text strings."""
    return [d["text"] for d in load_user_data().get("directives", []) if "text" in d]


def shell(cmd, timeout=5, cwd=None):
    """Run a shell command and return stdout, or empty string on failure.

    cmd can be a list (preferred, uses shell=False) or a string (uses shell=True).
    cwd is passed directly to subprocess.run instead of cd-chaining.
    """
    try:
        use_shell = isinstance(cmd, str)
        r = subprocess.run(
            cmd,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def get_time_context():
    """Generate a time/date context line with varied formatting."""
    now = datetime.now()
    date_formats = [
        now.strftime("%A, %B %-d, %Y"),
        now.strftime("%B %-d, %Y"),
        now.strftime("%a %b %-d"),
        now.strftime("%Y-%m-%d"),
        now.strftime("%A the %-dth of %B")
        if now.day not in (1, 2, 3, 21, 22, 23, 31)
        else now.strftime("%A, %B %-d"),
    ]
    time_formats = [
        now.strftime("%-I:%M %p %Z"),
        now.strftime("%-I:%M %p"),
        now.strftime("%H:%M"),
        now.strftime("%-I:%M%p").lower(),
    ]
    template = random.choice(TIME_TEMPLATES)
    return template.format(
        date=random.choice(date_formats), time=random.choice(time_formats)
    )


def get_git_context(cwd):
    """Get git state for the project."""
    if not cwd or not Path(cwd).exists():
        return {}
    ctx = {}
    branch = shell(["git", "branch", "--show-current"], cwd=cwd)
    if branch:
        ctx["branch"] = branch
    # Open issue count (fast, no network)
    issue_count = shell(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--json",
            "number",
            "--jq",
            "length",
        ],
        cwd=cwd,
    )
    if issue_count and issue_count.isdigit():
        ctx["open_issues"] = int(issue_count)
    # Recent commit subject
    last_commit = shell(["git", "log", "-1", "--format=%s"], cwd=cwd)
    if last_commit:
        ctx["last_commit"] = last_commit[:80]
    # Dirty files count
    dirty = shell(["git", "status", "--porcelain"], cwd=cwd)
    dirty_count = len(dirty.splitlines()) if dirty else 0
    if dirty_count:
        ctx["dirty_files"] = dirty_count
    return ctx


def load_project_brief(cwd):
    """Load project-specific requirements from .project-brief.md.

    Standardized method for persisting project requirements that Claude must
    never forget. Lives in the project root, one requirement per line (lines
    starting with - or *). The generator picks 1-2 random lines to inject
    into each prompt so Claude is constantly reminded of project-specific
    constraints even across context compaction and session restarts.
    """
    if not cwd:
        return []
    brief_path = Path(cwd) / ".project-brief.md"
    if not brief_path.exists():
        return []
    try:
        if brief_path.stat().st_size > 100000:  # 100KB sanity limit
            return []
        lines = brief_path.read_text().splitlines()
        reqs = []
        for line in lines:
            stripped = line.strip()
            if stripped and (stripped.startswith("- ") or stripped.startswith("* ")):
                reqs.append(stripped[2:].strip())
        return reqs
    except Exception:
        return []


def get_project_context(cwd):
    """Detect project type and name from the working directory."""
    if not cwd:
        return {}
    p = Path(cwd)
    ctx = {"name": p.name, "path": str(p)}

    # Detect project type by presence of key files
    markers = {
        "Package.swift": "swift",
        "Cargo.toml": "rust",
        "package.json": "node",
        "pyproject.toml": "python",
        "setup.py": "python",
        "go.mod": "go",
        "Makefile": "make",
        "CMakeLists.txt": "cpp",
        "*.xcodeproj": "xcode",
        "*.xcworkspace": "xcode",
    }
    for marker, ptype in markers.items():
        if "*" in marker:
            if list(p.glob(marker)):
                ctx["type"] = ptype
                break
        elif (p / marker).exists():
            ctx["type"] = ptype
            break

    # Detect stack capabilities — what platforms/targets does this project have?
    # Used to filter out irrelevant directive categories.
    # Scans the project root AND common monorepo subdirectories so that
    # e.g. a Next.js root + mobile/ with ios/android are both detected.
    stacks = set()

    # Directories to scan: project root + common monorepo child dirs
    scan_dirs = [p]
    for subdir_name in (
        "mobile",
        "app",
        "apps",
        "packages",
        "client",
        "server",
        "web",
        "frontend",
        "backend",
    ):
        subdir = p / subdir_name
        if subdir.is_dir():
            scan_dirs.append(subdir)
            # Also check one level deeper for monorepos like apps/mobile/, packages/web/
            try:
                for child in subdir.iterdir():
                    if (
                        child.is_dir()
                        and not child.name.startswith(".")
                        and child.name != "node_modules"
                    ):
                        scan_dirs.append(child)
            except PermissionError:
                pass

    for d in scan_dirs:
        # React Native / bare RN (no Expo): has ios/ and android/ subdirs
        # with native project files. Detects BEFORE Expo check so bare RN
        # projects that removed Expo are correctly identified.
        if (d / "ios").is_dir() and (
            (d / "ios" / "Podfile").exists()
            or list((d / "ios").glob("*.xcodeproj"))
            or list((d / "ios").glob("*.xcworkspace"))
        ):
            stacks.add("ios")
            stacks.add("apple")
        if (d / "android").is_dir() and (
            (d / "android" / "build.gradle").exists()
            or (d / "android" / "build.gradle.kts").exists()
            or (d / "android" / "settings.gradle").exists()
        ):
            stacks.add("android")

        # iOS native (root-level Xcode/Swift projects)
        if (
            (d / "Podfile").exists()
            or (d / "Package.swift").exists()
            or list(d.glob("*.xcodeproj"))
            or list(d.glob("*.xcworkspace"))
        ):
            stacks.add("ios")
            stacks.add("apple")

        # Android native (root-level Gradle)
        if (
            (d / "build.gradle").exists()
            or (d / "build.gradle.kts").exists()
            or (d / "settings.gradle").exists()
        ):
            stacks.add("android")

        # Web frameworks
        if (
            (d / "next.config.js").exists()
            or (d / "next.config.ts").exists()
            or (d / "next.config.mjs").exists()
            or (d / "vite.config.ts").exists()
            or (d / "vite.config.js").exists()
            or (d / "webpack.config.js").exists()
            or (d / "nuxt.config.ts").exists()
        ):
            stacks.add("web")
        # index.html at root or public/ (Express/static apps like Overlord-v2)
        if d == p and (
            (d / "index.html").exists() or (d / "public" / "index.html").exists()
        ):
            stacks.add("web")
        # Express/Hono/Fastify with a public/ or static/ dir = web UI
        if (d / "public" / "ui").is_dir() or (d / "public" / "index.html").exists():
            stacks.add("web")

        # Rust
        if (d / "Cargo.toml").exists():
            stacks.add("rust")
            stacks.add("systems")

        # C/C++
        if (
            (d / "CMakeLists.txt").exists()
            or list(d.glob("*.cpp"))
            or list(d.glob("*.h"))
        ):
            stacks.add("cpp")
            stacks.add("systems")

        # Go
        if (d / "go.mod").exists():
            stacks.add("go")
            stacks.add("systems")

        # Unity (C#)
        if list(d.glob("*.unity")) or (
            (d / "Assets").is_dir() and (d / "ProjectSettings").is_dir()
        ):
            stacks.add("unity")
            stacks.add("game")
            stacks.add("csharp")

        # Unreal Engine (C++)
        if (d / "Source").is_dir() and (
            list(d.glob("*.uproject")) or (d / "Config").is_dir()
        ):
            stacks.add("unreal")
            stacks.add("game")
            stacks.add("cpp")
        # Also detect .uproject files at top level
        if list(d.glob("*.uproject")):
            stacks.add("unreal")
            stacks.add("game")

        # Godot
        if (d / "project.godot").exists() or list(d.glob("*.godot")):
            stacks.add("godot")
            stacks.add("game")

        # Bevy / other Rust game engines (Cargo.toml + common game markers)
        if (d / "Cargo.toml").exists() and (d / "assets").is_dir():
            stacks.add("game")

        # Flutter / Dart
        if (d / "pubspec.yaml").exists():
            stacks.add("flutter")
            stacks.add("dart")
            # Flutter can target iOS, Android, web, desktop
            if (d / "ios").is_dir():
                stacks.add("ios")
            if (d / "android").is_dir():
                stacks.add("android")
            if (d / "web").is_dir():
                stacks.add("web")
            if (
                (d / "macos").is_dir()
                or (d / "windows").is_dir()
                or (d / "linux").is_dir()
            ):
                stacks.add("desktop")

        # Electron / Tauri (desktop apps with web UI)
        if (
            (d / "electron-builder.yml").exists()
            or (d / "electron-builder.json5").exists()
            or (d / "main.js").exists()
            and (d / "preload.js").exists()
        ):
            stacks.add("electron")
            stacks.add("desktop")
            stacks.add("web")
        if (d / "src-tauri").is_dir() or (d / "tauri.conf.json").exists():
            stacks.add("tauri")
            stacks.add("desktop")
            stacks.add("web")
            stacks.add("rust")

        # .NET / C#
        if (
            list(d.glob("*.csproj"))
            or list(d.glob("*.sln"))
            or list(d.glob("*.fsproj"))
        ):
            stacks.add("dotnet")
            stacks.add("csharp")

        # Java / Kotlin (non-Android)
        if (d / "pom.xml").exists() or list(d.glob("*.java")):
            stacks.add("java")
        if list(d.glob("*.kt")) or list(d.glob("*.kts")):
            stacks.add("kotlin")

        # Ruby
        if (d / "Gemfile").exists() and not (d / "Podfile").exists():
            stacks.add("ruby")
        if (d / "config.ru").exists() or (d / "Rakefile").exists():
            stacks.add("ruby")

        # PHP / Laravel
        if (d / "composer.json").exists() or (d / "artisan").exists():
            stacks.add("php")
            if (d / "artisan").exists():
                stacks.add("laravel")
                stacks.add("web")

        # Svelte / SvelteKit
        if (d / "svelte.config.js").exists() or (d / "svelte.config.ts").exists():
            stacks.add("svelte")
            stacks.add("web")

        # Node / TypeScript (server apps, CLIs, libraries)
        if (d / "package.json").exists():
            stacks.add("node")
        if (d / "tsconfig.json").exists():
            stacks.add("typescript")

        # Python
        if (
            (d / "pyproject.toml").exists()
            or (d / "setup.py").exists()
            or (d / "requirements.txt").exists()
        ):
            stacks.add("python")

        # Django / Flask / FastAPI
        if (d / "manage.py").exists():
            stacks.add("django")
            stacks.add("web")
        if list(d.glob("**/wsgi.py")) or list(d.glob("**/asgi.py")):
            stacks.add("web")

        # Fastlane (confirms native mobile distribution pipeline)
        if (d / "fastlane").is_dir() or (d / "Fastfile").exists():
            stacks.add("fastlane")

        # ── Additional web frameworks ──
        # Remix
        if (d / "remix.config.js").exists() or (d / "remix.config.ts").exists():
            stacks.add("remix")
            stacks.add("web")
        # Astro
        if (d / "astro.config.mjs").exists() or (d / "astro.config.ts").exists():
            stacks.add("astro")
            stacks.add("web")
        # Gatsby
        if (d / "gatsby-config.js").exists() or (d / "gatsby-config.ts").exists():
            stacks.add("gatsby")
            stacks.add("web")
        # Angular
        if (d / "angular.json").exists():
            stacks.add("angular")
            stacks.add("web")
        # Ember
        if (d / "ember-cli-build.js").exists():
            stacks.add("ember")
            stacks.add("web")
        # Solid.js
        if (d / "solid.config.ts").exists() or (d / "solid.config.js").exists():
            stacks.add("solidjs")
            stacks.add("web")
        # Qwik
        if list(d.glob("*qwik*")) and (d / "package.json").exists():
            stacks.add("qwik")
            stacks.add("web")

        # ── Backend frameworks ──
        # Rails
        if (d / "config" / "routes.rb").exists() or (d / "bin" / "rails").exists():
            stacks.add("rails")
            stacks.add("ruby")
            stacks.add("web")
        # Spring Boot (Java/Kotlin)
        if (d / "src" / "main" / "resources" / "application.properties").exists() or (
            d / "src" / "main" / "resources" / "application.yml"
        ).exists():
            stacks.add("spring")
            stacks.add("java")
            stacks.add("web")
        # Flask / FastAPI (Python)
        if (d / "app.py").exists() or (d / "main.py").exists():
            # Only mark if we already know it's Python
            if "python" in stacks:
                stacks.add("web")
        # Deno
        if (
            (d / "deno.json").exists()
            or (d / "deno.jsonc").exists()
            or (d / "deno.lock").exists()
        ):
            stacks.add("deno")
            stacks.add("typescript")
        # Bun
        if (d / "bun.lockb").exists() or (d / "bunfig.toml").exists():
            stacks.add("bun")
            stacks.add("typescript")

        # ── Desktop app frameworks ──
        # Qt (C++)
        if (
            list(d.glob("*.pro"))
            or list(d.glob("*.qml"))
            or (d / "CMakeLists.txt").exists()
            and list(d.glob("*.ui"))
        ):
            stacks.add("qt")
            stacks.add("desktop")
        # GTK
        if (
            list(d.glob("*.glade"))
            or (d / "meson.build").exists()
            and list(d.glob("**/*.vala"))
        ):
            stacks.add("gtk")
            stacks.add("desktop")
        # WPF / WinUI / MAUI (.NET desktop)
        if list(d.glob("*.xaml")):
            stacks.add("dotnet")
            stacks.add("desktop")
        # SwiftUI macOS app (not iOS)
        if (d / "Package.swift").exists() and not (d / "ios").is_dir():
            if (d / "Sources").is_dir():
                stacks.add("desktop")

        # ── Game engines (additional) ──
        # Defold
        if (d / "game.project").exists():
            stacks.add("defold")
            stacks.add("game")
        # Pygame / Pyglet / Arcade (Python games)
        if "python" in stacks and (d / "assets").is_dir():
            stacks.add("game")
        # Love2D (Lua)
        if (d / "main.lua").exists() and (d / "conf.lua").exists():
            stacks.add("love2d")
            stacks.add("game")
            stacks.add("lua")
        # RPG Maker
        if (d / "js" / "rpg_core.js").exists() or list(d.glob("*.rpgproject")):
            stacks.add("rpgmaker")
            stacks.add("game")
        # Phaser (JS game framework)
        if (d / "package.json").exists():
            try:
                _pkg = (d / "package.json").read_text()
                if "phaser" in _pkg:
                    stacks.add("phaser")
                    stacks.add("game")
                    stacks.add("web")
            except Exception:
                pass

        # ── Infrastructure / DevOps ──
        if (
            (d / "terraform.tf").exists()
            or (d / "main.tf").exists()
            or list(d.glob("*.tf"))
        ):
            stacks.add("terraform")
            stacks.add("infra")
        if (d / "pulumi.yaml").exists() or (d / "Pulumi.yaml").exists():
            stacks.add("pulumi")
            stacks.add("infra")
        if list(d.glob("*.yml")) and (d / "roles").is_dir():
            stacks.add("ansible")
            stacks.add("infra")
        if (d / "serverless.yml").exists() or (d / "serverless.ts").exists():
            stacks.add("serverless")
            stacks.add("infra")
            stacks.add("web")
        if (d / "cdk.json").exists():
            stacks.add("aws-cdk")
            stacks.add("infra")

        # ── Data / ML ──
        if list(d.glob("*.ipynb")):
            stacks.add("jupyter")
            stacks.add("data")
        if (d / "dbt_project.yml").exists():
            stacks.add("dbt")
            stacks.add("data")
        if (d / "MLproject").exists() or (d / "mlflow").is_dir():
            stacks.add("mlflow")
            stacks.add("ml")
        if list(d.glob("*.onnx")) or (d / "model").is_dir():
            stacks.add("ml")

        # ── Embedded / Hardware ──
        if (d / "platformio.ini").exists():
            stacks.add("platformio")
            stacks.add("embedded")
        if list(d.glob("*.ino")):
            stacks.add("arduino")
            stacks.add("embedded")
        if (d / "Kconfig").exists() or (d / "sdkconfig").exists():
            stacks.add("esp-idf")
            stacks.add("embedded")

        # ── Zig / Nim / Haskell / Elixir / other langs ──
        if (d / "build.zig").exists():
            stacks.add("zig")
            stacks.add("systems")
        if list(d.glob("*.nim")) or (d / "nimble").is_dir() or list(d.glob("*.nimble")):
            stacks.add("nim")
            stacks.add("systems")
        if (d / "stack.yaml").exists() or list(d.glob("*.cabal")):
            stacks.add("haskell")
        if (d / "mix.exs").exists():
            stacks.add("elixir")
            if (d / "lib").is_dir():
                stacks.add("phoenix")
                stacks.add("web")
        if (d / "rebar.config").exists():
            stacks.add("erlang")
        if list(d.glob("*.scala")) or (d / "build.sbt").exists():
            stacks.add("scala")
        if (
            list(d.glob("*.clj"))
            or (d / "project.clj").exists()
            or (d / "deps.edn").exists()
        ):
            stacks.add("clojure")
        if list(d.glob("*.ex")) and (d / "mix.exs").exists():
            pass  # already caught by elixir above
        if list(d.glob("*.r")) or list(d.glob("*.R")) or (d / "DESCRIPTION").exists():
            stacks.add("r")
            stacks.add("data")
        if list(d.glob("*.jl")) or (d / "Project.toml").exists():
            stacks.add("julia")
            stacks.add("data")
        if list(d.glob("*.v")) or (d / "v.mod").exists():
            stacks.add("vlang")
        if list(d.glob("*.cr")) or (d / "shard.yml").exists():
            stacks.add("crystal")
        if list(d.glob("*.odin")):
            stacks.add("odin")
            stacks.add("systems")
        if (d / "gleam.toml").exists():
            stacks.add("gleam")
        if list(d.glob("*.ml")) or (d / "dune-project").exists():
            stacks.add("ocaml")
        if list(d.glob("*.rkt")):
            stacks.add("racket")

        # ── Browser extensions ──
        if (d / "manifest.json").exists():
            try:
                _mf = (d / "manifest.json").read_text()[:200]
                if "manifest_version" in _mf:
                    stacks.add("browser_extension")
                    stacks.add("web")
            except Exception:
                pass

        # ── WASM ──
        if list(d.glob("*.wasm")) or list(d.glob("*.wat")):
            stacks.add("wasm")

        # ── Shader / Graphics ──
        if (
            list(d.glob("*.glsl"))
            or list(d.glob("*.hlsl"))
            or list(d.glob("*.wgsl"))
            or list(d.glob("*.metal"))
        ):
            stacks.add("shaders")
            stacks.add("graphics")

    # If nothing detected, mark as generic
    if not stacks:
        stacks.add("generic")
    ctx["stacks"] = stacks

    # Check for CLAUDE.md
    claude_md = p / "CLAUDE.md"
    if claude_md.exists():
        try:
            content = claude_md.read_text()[:500]
            ctx["has_claude_md"] = True
            # Extract project description from first meaningful line
            for line in content.split("\n"):
                line = line.strip().strip("#").strip()
                if line and len(line) > 10 and not line.startswith("---"):
                    ctx["description"] = line[:100]
                    break
        except Exception:
            pass

    return ctx


def build_project_line(git_ctx, proj_ctx):
    """Build a dynamic project context line."""
    # Scaffolding suppression: drop the meta prefix most of the time so
    # prompts don't all start with the same "(working on: X)" template tell.
    if random.random() > 0.35:
        return ""
    parts = []
    name = proj_ctx.get("name", "")
    if name:
        templates = [
            f"project: {name}.",
            f"(working on: {name})",
            f"[{name}]",
            f"current project: {name}.",
            f"repo: {name}.",
        ]
        parts.append(random.choice(templates))

    branch = git_ctx.get("branch", "")
    if branch and branch not in ("main", "develop", "master"):
        parts.append(f"branch: {branch}.")

    issues = git_ctx.get("open_issues")
    if issues is not None and issues > 0:
        templates = [
            f"{issues} open issues.",
            f"({issues} issues in backlog)",
            f"backlog: {issues} open.",
        ]
        parts.append(random.choice(templates))

    dirty = git_ctx.get("dirty_files", 0)
    if dirty > 0:
        parts.append(f"{dirty} uncommitted files.")

    if not parts:
        return ""
    # Use 1-3 parts randomly
    selected = random.sample(parts, min(len(parts), random.randint(1, 3)))
    return " ".join(selected)


# ═══════════════════════════════════════════════════════════════════
#  PROMPT ASSEMBLY ENGINE
# ═══════════════════════════════════════════════════════════════════


def pick(lst):
    return random.choice(lst)


def pick_n_categories(n, proj_ctx=None):
    """Select n unique directive categories and pick one phrasing from each.

    Stack-aware: filters out categories that don't apply to the current project.
    For example, a webapp-only project won't get mobile_distribution or apple_hig.
    """
    stacks = proj_ctx.get("stacks", {"generic"}) if proj_ctx else {"generic"}

    # Filter categories by stack relevance
    all_cats = list(DIRECTIVES.keys())
    eligible_cats = []
    for cat in all_cats:
        if cat in STACK_REQUIRED:
            # Category is stack-specific — only include if project has a matching stack
            if stacks.intersection(STACK_REQUIRED[cat]) or "generic" in stacks:
                eligible_cats.append(cat)
        else:
            # Universal category — always eligible
            eligible_cats.append(cat)

    # TWO-TIER priority system to avoid dilution across too many categories.
    #
    # Tier 1 ("critical"): 90% chance one is included. These are the user's
    # biggest recurring pain points — the things that cause the most rework.
    # Visual verification and UX coherence are critical because users have
    # repeatedly reported unintuitive, broken UI. Autonomy because the AI
    # wastes enormous amounts of time asking for approval.
    critical = [
        "visual_verification",
        "ux_coherence",
        "stop_asking_approval",
        "design_quality",
        "decide_whats_right",
        "stop_looping",
    ]
    critical = [c for c in critical if c in eligible_cats]

    # Tier 2 ("elevated"): 70% chance one is included, after critical.
    # Important but less urgent than the tier-1 problems.
    # deep_thinking, fill_gaps, decide_whats_right are universal.
    # llmops, testing_pyramid, ai_uat are for projects that use AI or need testing.
    elevated = [
        "parallel_agents",
        "quality_bar",
        "autonomous_decisions",
        "deep_thinking",
        "fill_gaps",
        "testing_pyramid",
        "ai_uat",
        "llmops",
        "shift_left",
    ]
    elevated = [c for c in elevated if c in eligible_cats]

    # Core categories (stamps, issue_flow) still included 50% of the time
    core = ["stamps", "issue_flow"]
    core = [c for c in core if c in eligible_cats]

    all_priority = critical + elevated + core
    optional = [c for c in eligible_cats if c not in all_priority]
    random.shuffle(optional)
    random.shuffle(critical)
    random.shuffle(elevated)

    selected = []

    # Tier 1: 90% chance to include at least one critical category
    if critical and random.random() < 0.90:
        selected.append(critical[0])

    # Tier 2: 70% chance to include at least one elevated category
    if elevated and random.random() < 0.70:
        selected.append(elevated[0])

    # Core: 50% chance
    if core and random.random() < 0.50:
        pick_core = random.choice(core)
        if pick_core not in selected:
            selected.append(pick_core)

    # Fill remaining slots from optional
    remaining = max(0, n - len(selected))
    for cat in optional:
        if remaining <= 0:
            break
        if cat not in selected:
            selected.append(cat)
            remaining -= 1

    random.shuffle(selected)
    return [pick(DIRECTIVES[cat]) for cat in selected[:n]]


def generate_standard(git_ctx, proj_ctx):
    template = pick(TEMPLATES_STANDARD)

    # MIXING LOGIC: Take 2 from system, 1 from your JSON
    user_data = load_user_data()
    user_pool = [d["text"] for d in user_data.get("directives", []) if "text" in d]
    global_suffix = user_data.get("settings", {}).get(
        "global_suffix", "Respond concisely."
    )
    system_directives = pick_n_categories(2, proj_ctx)

    if user_pool:
        directives = system_directives + [random.choice(user_pool)]
    else:
        directives = pick_n_categories(3, proj_ctx)

    random.shuffle(directives)
    context = get_time_context()
    project_line = build_project_line(git_ctx, proj_ctx)

    slots = {
        "opener": pick(OPENERS_CONTINUE),
        "intensity": pick(INTENSIFIERS),
        "context": context,
    }
    for i, d in enumerate(directives, 1):
        slots[f"d{i}"] = d
    for i in range(len(directives) + 1, 8):
        slots[f"d{i}"] = ""

    msg = template.format(**slots)
    # Apply user-configured global suffix from keepitgoing-directives.json
    if global_suffix:
        msg += " " + global_suffix

    if project_line:
        msg = project_line + " " + msg
    return _clean(msg, proj_ctx.get("path"))


def generate_detailed(git_ctx, proj_ctx):
    """Generate a detailed prompt. LOCKDOWN: reduced from 5-7 to 3-4 directives
    to save tokens. Revisit when resource constraints lift."""
    template = pick(TEMPLATES_DETAILED)
    directives = pick_n_categories(random.randint(3, 4), proj_ctx)
    context = get_time_context()
    project_line = build_project_line(git_ctx, proj_ctx)

    slots = {
        "opener": pick(OPENERS_CONTINUE),
        "intensity": pick(INTENSIFIERS),
        "context": context,
    }
    for i, d in enumerate(directives, 1):
        slots[f"d{i}"] = d
    for i in range(len(directives) + 1, 8):
        slots[f"d{i}"] = ""

    msg = template.format(**slots)
    if project_line:
        msg = project_line + " " + msg
    return _clean(msg, proj_ctx.get("path"))


def generate_terse(git_ctx, proj_ctx):
    """Generate a very short prompt (1-2 fragments)."""
    template = pick(TEMPLATES_TERSE)
    directives = pick_n_categories(1, proj_ctx)
    context = get_time_context()

    slots = {
        "opener": pick(OPENERS_TERSE),
        "intensity": pick(INTENSIFIERS),
        "context": context,
        "d1": directives[0] if directives else "",
    }
    for i in range(2, 8):
        slots[f"d{i}"] = ""

    return _clean(template.format(**slots), proj_ctx.get("path"))


def generate_focused(git_ctx, proj_ctx):
    """Generate a prompt focused on one specific area."""
    template = pick(TEMPLATES_FOCUSED)
    focus_area = pick(FOCUS_AREAS)
    directives = pick_n_categories(random.randint(2, 3), proj_ctx)
    context = get_time_context()

    slots = {
        "focus_opener": pick(OPENERS_FOCUSED),
        "focus_area": focus_area,
        "intensity": pick(INTENSIFIERS),
        "context": context,
    }
    for i, d in enumerate(directives, 1):
        slots[f"d{i}"] = d
    for i in range(len(directives) + 1, 8):
        slots[f"d{i}"] = ""

    msg = template.format(**slots)
    project_line = build_project_line(git_ctx, proj_ctx)
    if project_line:
        msg = project_line + " " + msg
    return _clean(msg, proj_ctx.get("path"))


def generate_status(git_ctx, proj_ctx):
    """Generate a status-check prompt."""
    template = pick(TEMPLATES_STATUS)
    directives = pick_n_categories(random.randint(1, 2), proj_ctx)
    context = get_time_context()

    slots = {
        "status_opener": pick(OPENERS_STATUS),
        "context": context,
    }
    for i, d in enumerate(directives, 1):
        slots[f"d{i}"] = d
    for i in range(len(directives) + 1, 8):
        slots[f"d{i}"] = ""

    msg = template.format(**slots)
    project_line = build_project_line(git_ctx, proj_ctx)
    if project_line:
        msg = project_line + " " + msg
    return _clean(msg, proj_ctx.get("path"))


def _clean(text, cwd=None):
    """Clean up generated text: normalize whitespace, fix punctuation, inject
    project requirements, prepend anti-derail preamble, and append the
    permanent framing directive."""
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    # Remove trailing spaces before punctuation
    text = re.sub(r" +([.,;:!?])", r"\1", text)
    # Fix double periods
    text = re.sub(r"\.\.+", ".", text)
    # Fix space at start
    text = text.strip()
    if not text.endswith((".", "!", "?")):
        text += "."
    # Inject 1-2 project requirements from .project-brief.md so Claude is
    # constantly reminded of project-specific constraints. These are the
    # requirements that "must never be forgotten" — they persist across
    # sessions and context compactions because they're re-injected every prompt.
    brief = load_project_brief(cwd)
    if brief:
        sample_n = min(len(brief), random.randint(1, 2))
        picked = random.sample(brief, sample_n)
        text += " [project requirements: " + "; ".join(picked) + "]"
    # Permanent framing: de-escalation + surface blockers + autonomy + menus.
    text += " " + random.choice(PERMANENT_DIRECTIVE_VARIANTS)
    # Preamble: anti-derail framing prepended to EVERY prompt so the AI
    # doesn't interpret the directive as a new task and context-switch.
    text = random.choice(PREAMBLE_VARIANTS) + " " + text
    return text


# ═══════════════════════════════════════════════════════════════════
#  HISTORY & DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════


def load_history():
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text())
    except Exception:
        pass
    return []


def save_history(history):
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        HISTORY_FILE.write_text(json.dumps(history[-MAX_HISTORY:]))
    except Exception:
        pass


def prompt_hash(text):
    """Create a fuzzy hash — normalize whitespace/punctuation to detect near-dupes."""
    normalized = re.sub(r"[^a-z0-9 ]", "", text.lower())
    normalized = re.sub(r"  +", " ", normalized).strip()
    # Use first 100 chars for matching (ignores context/time differences)
    return hashlib.md5(normalized[:100].encode()).hexdigest()[:12]


def is_too_similar(text, history):
    """Check if this prompt is too similar to recent ones."""
    h = prompt_hash(text)
    return h in history[-20:]  # check against last 20


# ═══════════════════════════════════════════════════════════════════
#  MAIN GENERATION PIPELINE
# ═══════════════════════════════════════════════════════════════════

GENERATORS = {
    "standard": generate_standard,
    "detailed": generate_detailed,
    "terse": generate_terse,
    "focused": generate_focused,
    "status": generate_status,
}

# Weighted selection of generation modes.
# LOCKDOWN MODE (April 2026): heavily biased toward terse/status (short = cheap tokens
# for Claude to process). Detailed mode nearly eliminated — long directive blasts burn
# Claude's token budget AND derail the task. Revisit when resource lockdown lifts.
MODE_WEIGHTS = {
    "standard": 25,
    "detailed": 5,
    "terse": 35,
    "focused": 15,
    "status": 20,
}


def pick_mode():
    modes = []
    for mode, weight in MODE_WEIGHTS.items():
        modes.extend([mode] * weight)
    return random.choice(modes)


def generate(cwd=None, mode=None):
    """Main entry point: generate a unique, dynamic prompt."""
    git_ctx = get_git_context(cwd) if cwd else {}
    proj_ctx = get_project_context(cwd) if cwd else {}

    history = load_history()

    # Try up to 10 times to generate a non-duplicate
    for attempt in range(10):
        gen_mode = mode if mode in GENERATORS else pick_mode()
        generator = GENERATORS[gen_mode]
        prompt = generator(git_ctx, proj_ctx)

        if not is_too_similar(prompt, history):
            break

    # Save to history
    history.append(prompt_hash(prompt))
    save_history(history)

    return prompt


def main():
    parser = argparse.ArgumentParser(description="KeepItGoing prompt generator")
    parser.add_argument(
        "--cwd", type=str, default=None, help="Project working directory"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=None,
        choices=["standard", "detailed", "terse", "focused", "status"],
        help="Force a specific generation mode",
    )
    args = parser.parse_args()

    prompt = generate(cwd=args.cwd, mode=args.mode)
    print(prompt)


if __name__ == "__main__":
    main()
