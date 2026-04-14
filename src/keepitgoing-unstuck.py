#!/usr/bin/env python3
"""
keepitgoing-unstuck — escalate a stuck AI session to a smarter model.

When a MiniMax (or other cheap) session is spinning on a problem it can't solve —
looping, repeating commands, hitting the same error — this script captures its
recent context, ships it to Claude Opus/Sonnet via `claude -p`, and emits a
concise strategic nudge that can be fed back to the stuck session.

Usage:
  keepitgoing-unstuck --input-file <path>   # read session context from file
  keepitgoing-unstuck --stdin               # read session context from stdin
  keepitgoing-unstuck --model opus          # override escalation model
  keepitgoing-unstuck --force               # ignore daily budget
  keepitgoing-unstuck --dry-run             # print what would happen

Output (to stdout):
  The strategic nudge text — ready to feed as a prompt to the stuck session.

Exit codes:
  0  success — nudge printed to stdout, budget decremented
  1  budget exceeded (use --force to override)
  2  escalation model unreachable or returned nothing useful
  3  invalid input

Budget:
  Wall-clock seconds spent talking to Claude today are tracked in
  ~/.claude/hooks/state/kig-budget-YYYY-MM-DD.json. Daily cap configurable
  via ~/.claude/hooks/keepitgoing-config.json key 'claude_daily_budget_sec'
  (default: 21600 = 6 hours). Resets automatically each day.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path

VERSION = "1.0.0"
CONFIG_FILE = Path.home() / ".claude" / "hooks" / "keepitgoing-config.json"
BUDGET_DIR = Path.home() / ".claude" / "hooks" / "state"
ESCALATION_LOG = Path.home() / ".claude" / "hooks" / "state" / "kig-escalations.jsonl"
DEFAULT_BUDGET_SEC = 21600  # 6 hours
DEFAULT_MODEL = "opus"
MAX_INPUT_CHARS = 12000
CLAUDE_TIMEOUT_SEC = 120

CONSULT_PROMPT = """You are a senior engineer. A junior AI is working on a task and has a specific question. Answer it directly using the session context below.

RULES:
1. Answer the QUESTION asked. Do not restate it. Do not preface with "Great question" or "It seems you're asking".
2. Be SPECIFIC and rooted in the context — cite actual file names, function names, error messages visible in the session.
3. If the question is based on a wrong premise, say so in one sentence and correct the premise before answering.
4. Maximum 6 sentences OR a short numbered list.
5. If the answer requires information not visible in the context, say "need: X" in one line and stop.
6. No markdown fences, no JSON wrapper. Plain text that a junior AI can read and act on.
7. If a screenshot path is provided, USE YOUR Read TOOL on that path to see the image before answering.

Junior AI's question:
{question}

Session context (last chunk of its work):
---
{content}
---{image_section}"""


UNSTUCK_PROMPT = """You are a senior engineer asked to help unstick a junior AI that has been working on a problem and appears to be looping or making no forward progress.

Below is the last chunk of the junior AI's session (its thinking, commands, tool results, errors). Read it, identify the core blocker, and reply with a TIGHT strategic nudge that the junior AI can act on directly.

RULES for your response:
1. NO preamble, NO restating the problem, NO "I see you're trying to…". Get straight to the directive.
2. Maximum 5 sentences OR a short numbered list (1-4 items).
3. Be SPECIFIC. "Check the X" is useless. "Open file Y at line Z, change foo to bar because baz" is useful.
4. If the junior AI is genuinely stuck on something it can't solve (dependency issue, missing credentials, genuine framework bug), say so in one sentence and suggest the workaround.
5. If the junior AI has been investigating the wrong thing for a while, say so and redirect.
6. Your output will be fed as a prompt to the junior AI — write it as a directive TO the AI, not ABOUT it.
7. Do NOT output JSON, markdown fences, or any wrapper. Plain text directive only.
8. If a screenshot path is provided below, USE YOUR Read TOOL on that path to see the image, then factor what you see into your directive.

Junior AI's recent session:
---
{content}
---{image_section}"""


def log_stderr(msg):
    print(f"[keepitgoing-unstuck] {msg}", file=sys.stderr)


def load_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def today_budget_file():
    day = date.today().isoformat()
    return BUDGET_DIR / f"kig-budget-{day}.json"


def load_today_budget():
    path = today_budget_file()
    if not path.exists():
        return {"used_sec": 0, "escalations": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"used_sec": 0, "escalations": 0}


def save_today_budget(data):
    BUDGET_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    today_budget_file().write_text(json.dumps(data, indent=2))


def budget_limit_sec():
    return int(load_config().get("claude_daily_budget_sec", DEFAULT_BUDGET_SEC))


def escalation_model():
    return load_config().get("escalation_model", DEFAULT_MODEL)


def append_escalation_log(entry):
    ESCALATION_LOG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ESCALATION_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def fmt_duration(sec):
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60:02d}s"
    return f"{sec // 3600}h {(sec % 3600) // 60:02d}m"


def budget_status():
    used = load_today_budget()["used_sec"]
    cap = budget_limit_sec()
    remaining = max(0, cap - used)
    return used, cap, remaining


def read_input(args):
    if args.input_file:
        return Path(args.input_file).read_text()
    return sys.stdin.read()


def truncate(text, n):
    if len(text) <= n:
        return text
    return "...[truncated head]...\n" + text[-n:]


def call_escalation(content, model, timeout_sec, image_path=None, question=None):
    """Invoke `claude -p --model <model>`. Returns stdout.

    Mode is picked by whether a question is provided:
      - question=None → UNSTUCK mode (strategic nudge, picks its own focus)
      - question set  → CONSULT mode (answers the specific question)
    """
    image_section = ""
    if image_path:
        image_section = (
            f"\n\nA current screenshot has been captured at: {image_path}\n"
            f"Use your Read tool on this exact path to see the image. "
            f"Factor what you observe in it (layout, errors visible on screen, "
            f"simulator state, etc.) into your response."
        )
    if question:
        prompt = (
            CONSULT_PROMPT.replace("{question}", question.strip())
            .replace("{content}", content)
            .replace("{image_section}", image_section)
        )
    else:
        prompt = UNSTUCK_PROMPT.replace("{content}", content).replace(
            "{image_section}", image_section
        )
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError:
        raise RuntimeError("`claude` CLI not found on PATH")
    except subprocess.TimeoutExpired:
        elapsed = int(time.monotonic() - t0)
        raise RuntimeError(
            f"escalation timed out after {elapsed}s (cap {timeout_sec}s)"
        )
    elapsed = int(time.monotonic() - t0)
    if result.returncode != 0:
        raise RuntimeError(f"claude exit {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip(), elapsed


def parse_args():
    p = argparse.ArgumentParser(
        prog="keepitgoing-unstuck",
        description="Escalate a stuck AI session to Claude Opus/Sonnet",
    )
    src = p.add_mutually_exclusive_group(required=False)
    src.add_argument(
        "--input-file", help="File containing the stuck session's recent context"
    )
    src.add_argument("--stdin", action="store_true", help="Read context from stdin")
    p.add_argument(
        "--model",
        default=None,
        help=f"Escalation model (default from config: {DEFAULT_MODEL})",
    )
    p.add_argument("--force", action="store_true", help="Ignore daily budget cap")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without calling Claude",
    )
    p.add_argument(
        "--budget", action="store_true", help="Print today's budget status and exit"
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=CLAUDE_TIMEOUT_SEC,
        help="Claude timeout in seconds",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=MAX_INPUT_CHARS,
        help="Max input characters to send",
    )
    p.add_argument(
        "--image",
        default=None,
        help="Path to a screenshot PNG — Claude will Read it and factor the visual into the nudge",
    )
    p.add_argument(
        "--question",
        default=None,
        help="If set, switches to CONSULT mode — answers this specific question using session context "
        "(no strategic-nudge framing). Use when MiniMax knows what it needs to ask.",
    )
    p.add_argument(
        "--version", action="version", version=f"keepitgoing-unstuck {VERSION}"
    )
    return p.parse_args()


def main():
    args = parse_args()

    if args.budget:
        used, cap, remaining = budget_status()
        print(f"Today's Claude escalation budget:")
        print(f"  used:      {fmt_duration(used)}")
        print(f"  cap:       {fmt_duration(cap)}")
        print(f"  remaining: {fmt_duration(remaining)}")
        print(f"  escalations today: {load_today_budget().get('escalations', 0)}")
        return 0

    if not args.input_file and not args.stdin:
        args.stdin = True

    model = args.model or escalation_model()
    used, cap, remaining = budget_status()

    fallback_model = load_config().get("exhaustion_fallback_model", "haiku")
    if not args.force and remaining <= 0:
        if fallback_model and fallback_model != model:
            log_stderr(
                f"budget exhausted for {model}; falling back to {fallback_model} "
                f"(cheap; doesn't consume the {model} budget)"
            )
            model = fallback_model
            # Don't decrement budget for fallback calls — they're meant to be "free"
            skip_budget_decrement = True
        else:
            log_stderr(
                f"budget exhausted: used {fmt_duration(used)} / cap {fmt_duration(cap)}. "
                f"Use --force to override, or set exhaustion_fallback_model in config."
            )
            return 1
    else:
        skip_budget_decrement = False

    raw = read_input(args)
    content = truncate(raw, args.max_chars)
    excerpt = raw[:200].replace("\n", " ")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "model": model,
                    "budget_remaining_sec": remaining,
                    "input_chars": len(content),
                    "excerpt": excerpt,
                },
                indent=2,
            )
        )
        return 0

    try:
        # Validate image path up front if provided
        image_path = None
        if args.image:
            img = Path(args.image)
            if not img.exists():
                log_stderr(f"image not found: {args.image}")
                return 3
            image_path = str(img.resolve())
        nudge, elapsed = call_escalation(
            content,
            model,
            args.timeout,
            image_path=image_path,
            question=args.question,
        )
    except Exception as e:
        log_stderr(f"escalation failed: {e}")
        return 2

    if not nudge or len(nudge) < 10:
        log_stderr(f"escalation returned nothing useful ({len(nudge)} chars)")
        return 2

    # Decrement budget (unless we fell back to the exhaustion fallback model,
    # which is intentionally "free" — cheap enough that tracking is noise)
    today = load_today_budget()
    if not skip_budget_decrement:
        today["used_sec"] = int(today.get("used_sec", 0)) + elapsed
    today["escalations"] = int(today.get("escalations", 0)) + 1
    if skip_budget_decrement:
        today["fallback_calls"] = int(today.get("fallback_calls", 0)) + 1
    save_today_budget(today)

    # Log the escalation for auditability
    append_escalation_log(
        {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": model,
            "elapsed_sec": elapsed,
            "input_chars": len(content),
            "input_excerpt": excerpt,
            "nudge_chars": len(nudge),
            "nudge_preview": nudge[:200].replace("\n", " "),
            "budget_used_sec_after": today["used_sec"],
            "budget_cap_sec": cap,
        }
    )

    log_stderr(
        f"escalation ok | model={model} elapsed={elapsed}s | "
        f"budget {fmt_duration(today['used_sec'])} / {fmt_duration(cap)} used"
    )

    print(nudge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
