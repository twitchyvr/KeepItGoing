#!/usr/bin/env python3
"""
keepitgoing-classify — classify the state of an AI turn so KIG can react intelligently.

Usage:
  keepitgoing-classify --input-file <path>           # Read AI output from file
  keepitgoing-classify --stdin                       # Read from stdin
  keepitgoing-classify --last-lines 30 --session <id>  # Pull last N lines from iTerm
  keepitgoing-classify --dry-run                     # Print what would happen, don't call model
  keepitgoing-classify --model haiku                 # Override classifier model (default: haiku)

Writes JSON state to /tmp/claude-keepitgoing/classification-<session>.json:
  {
    "schema_version": 1,
    "state": "working | asking_user | blocked | done | idle | unknown",
    "needs_user_input": bool,
    "direct_question": string | null,
    "urgency": "low | medium | high",
    "suggested_action": "escalate | quiet_wait | nudge_normal | priority_next",
    "confidence": 0.0-1.0,
    "classified_at": "ISO-8601 UTC",
    "classifier_model": "haiku",
    "input_excerpt": "first 200 chars of input"
  }

Fails gracefully: on any error (API down, parse error, timeout), writes state="unknown"
with the error details. KIG falls back to normal templated nudges in that case.

Backend: invokes `claude -p --model <model> --output-format text` as a subprocess.
Uses the user's existing Claude Code authentication — no API keys required.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.1.0"
SCHEMA_VERSION = 1
STATE_DIR = Path("/tmp/claude-keepitgoing")
CONFIG_FILE = Path.home() / ".claude" / "hooks" / "keepitgoing-config.json"
CLAUDE_JSON = Path.home() / ".claude.json"
DEFAULT_PROFILE = "haiku"
CLASSIFIER_TIMEOUT_SEC = 25
MAX_INPUT_CHARS = 8000

VALID_STATES = {"working", "asking_user", "blocked", "done", "idle", "unknown"}
VALID_ACTIONS = {"escalate", "quiet_wait", "nudge_normal", "priority_next"}

# Classifier profiles. Each maps a short name → how to invoke `claude -p`.
#  - base_url=None  → use system default (Anthropic auth from Claude Code)
#  - api_key_env    → env var name to look up; if missing, try ~/.claude.json MCP env
PROFILES = {
    "haiku": {
        "model": "haiku",
        "base_url": None,
        "api_key_env": None,
        "description": "Claude Haiku 4.5 via Anthropic (fast, cheap, per-call cost)",
    },
    "sonnet": {
        "model": "sonnet",
        "base_url": None,
        "api_key_env": None,
        "description": "Claude Sonnet via Anthropic (balanced, per-call cost)",
    },
    "opus": {
        "model": "opus",
        "base_url": None,
        "api_key_env": None,
        "description": "Claude Opus 4.6 via Anthropic (smartest, higher per-call cost)",
    },
    "minimax-highspeed": {
        "model": "MiniMax-M2.7-highspeed",
        "base_url": "https://api.minimax.io/anthropic",
        "api_key_env": "MINIMAX_API_KEY",
        "description": "MiniMax M2.7 highspeed (uses MiniMax plan tokens, not per-call)",
    },
    "minimax": {
        "model": "MiniMax-M2.7",
        "base_url": "https://api.minimax.io/anthropic",
        "api_key_env": "MINIMAX_API_KEY",
        "description": "MiniMax M2.7 standard (uses MiniMax plan tokens)",
    },
}


def load_profile(profile_name=None):
    """Resolve the active profile. Priority: --profile flag > config file > default."""
    if profile_name is None:
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text())
                profile_name = cfg.get("classifier_profile", DEFAULT_PROFILE)
            except Exception:
                profile_name = DEFAULT_PROFILE
        else:
            profile_name = DEFAULT_PROFILE
    if profile_name not in PROFILES:
        raise SystemExit(
            f"keepitgoing-classify: unknown profile {profile_name!r}. "
            f"Valid: {', '.join(PROFILES)}"
        )
    return profile_name, PROFILES[profile_name]


def resolve_api_key(env_var):
    """Look up an API key by env var, falling back to ~/.claude.json MCP env."""
    if not env_var:
        return None
    val = os.environ.get(env_var)
    if val:
        return val
    # Fall back to ~/.claude.json — MCP servers store their env there
    if CLAUDE_JSON.exists():
        try:
            blob = CLAUDE_JSON.read_text()
            # Naive regex extraction to avoid parsing the whole file
            m = re.search(rf'"{re.escape(env_var)}"\s*:\s*"([^"]+)"', blob)
            if m:
                return m.group(1)
        except Exception:
            pass
    return None


CLASSIFIER_PROMPT = """You are a classifier. Read the AI assistant's most recent turn below and output ONE JSON object with this exact shape — nothing else, no prose, no markdown fences.

{"state": "<state>", "needs_user_input": <bool>, "direct_question": <string or null>, "urgency": "<low|medium|high>", "suggested_action": "<action>", "confidence": <0.0-1.0>}

Where <state> is exactly one of:
- "asking_user": AI asked the user a direct question or is explicitly waiting for user input/decision
- "blocked": AI reports it is blocked on something outside its control (missing creds, build credits exhausted, etc.)
- "done": AI finished all active work and is waiting for next direction (e.g. "PR pushed, CI should pass, what's next?")
- "working": AI is mid-task, running commands, iterating — does not need user input
- "idle": AI is waiting on a long-running background task (build, test suite)

Where <action> is one of:
- "escalate": user needs to see this NOW (AI asked a direct question)
- "quiet_wait": don't nudge, user will respond when ready
- "nudge_normal": fine to send normal ambient prompt
- "priority_next": AI is done — nudge with next-priority-from-queue prompt

Where <direct_question> is the literal question the AI asked the user, or null if no direct question.

Set urgency=high only if state=asking_user AND the question blocks progress. Otherwise low or medium.
Set confidence to how sure you are (0.0-1.0).

Output the JSON object and nothing else.

AI turn to classify:
---
{content}
---"""


def log_stderr(msg):
    print(f"[keepitgoing-classify] {msg}", file=sys.stderr)


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_input(args):
    if args.input_file:
        return Path(args.input_file).read_text()
    if args.stdin:
        return sys.stdin.read()
    raise SystemExit("keepitgoing-classify: must supply --input-file or --stdin")


def truncate(text, n):
    if len(text) <= n:
        return text
    # Keep the tail — the most recent turn is usually what matters
    return "...[truncated]...\n" + text[-n:]


def call_classifier(content, profile, timeout_sec):
    """Invoke `claude -p` as a subprocess, routed per profile. Returns raw stdout string."""
    prompt = CLASSIFIER_PROMPT.replace("{content}", content)
    env = os.environ.copy()
    if profile.get("base_url"):
        env["ANTHROPIC_BASE_URL"] = profile["base_url"]
    if profile.get("api_key_env"):
        key = resolve_api_key(profile["api_key_env"])
        if not key:
            raise RuntimeError(
                f"API key for env var {profile['api_key_env']} not found — "
                "check ~/.claude.json or your shell env"
            )
        env["ANTHROPIC_API_KEY"] = key
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", profile["model"], "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except FileNotFoundError:
        raise RuntimeError("`claude` CLI not found on PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"classifier timed out after {timeout_sec}s")

    if result.returncode != 0:
        raise RuntimeError(
            f"classifier exit {result.returncode}: {result.stderr[:200]}"
        )
    return result.stdout


def extract_json(raw_output):
    """Find and parse the first JSON object in raw model output. Strips markdown fences."""
    # Strip ```json ... ``` fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        # Find first {...} block
        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object found in output: {raw_output[:200]!r}")
        candidate = match.group(0)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error: {e}; candidate: {candidate[:200]!r}")


def validate_and_normalize(data):
    """Validate classifier output against schema. Raise on violations. Return normalized dict."""
    required = ["state", "needs_user_input", "suggested_action", "confidence"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"missing required fields: {missing}")

    if data["state"] not in VALID_STATES:
        raise ValueError(f"invalid state: {data['state']!r} (valid: {VALID_STATES})")
    if data["suggested_action"] not in VALID_ACTIONS:
        raise ValueError(f"invalid action: {data['suggested_action']!r}")
    if not isinstance(data["needs_user_input"], bool):
        raise ValueError("needs_user_input must be bool")
    try:
        conf = float(data["confidence"])
    except (TypeError, ValueError):
        raise ValueError("confidence must be numeric")
    if not 0.0 <= conf <= 1.0:
        raise ValueError(f"confidence {conf} outside [0, 1]")
    data["confidence"] = conf

    # Optional fields: normalize
    data.setdefault("direct_question", None)
    data.setdefault("urgency", "low")
    if data["urgency"] not in {"low", "medium", "high"}:
        data["urgency"] = "low"
    return data


def build_unknown_result(reason, input_excerpt, model):
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "unknown",
        "needs_user_input": False,
        "direct_question": None,
        "urgency": "low",
        "suggested_action": "nudge_normal",
        "confidence": 0.0,
        "classified_at": utcnow_iso(),
        "classifier_model": model,
        "input_excerpt": input_excerpt,
        "error": reason,
    }


def write_state(session, payload):
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STATE_DIR / f"classification-{session}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def parse_args():
    p = argparse.ArgumentParser(
        prog="keepitgoing-classify",
        description="Classify AI turn state for KeepItGoing",
    )
    src = p.add_mutually_exclusive_group(required=False)
    src.add_argument("--input-file", help="Path to file containing AI output")
    src.add_argument("--stdin", action="store_true", help="Read AI output from stdin")
    p.add_argument(
        "--session",
        default=os.environ.get("CLAUDE_SESSION_ID", "default"),
        help="Session identifier (defaults to $CLAUDE_SESSION_ID or 'default')",
    )
    p.add_argument(
        "--profile",
        default=None,
        help=f"Classifier profile (valid: {', '.join(PROFILES)}). "
        f"Default: read from {CONFIG_FILE}, falls back to '{DEFAULT_PROFILE}'.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override the model inside the chosen profile (advanced; usually use --profile)",
    )
    p.add_argument(
        "--list-profiles",
        action="store_true",
        help="List all classifier profiles and exit",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=CLASSIFIER_TIMEOUT_SEC,
        help="Classifier timeout seconds",
    )
    p.add_argument(
        "--max-chars", type=int, default=MAX_INPUT_CHARS, help="Max input characters"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Don't call classifier; print plan"
    )
    p.add_argument("--output-file", help="Override output path (default: state dir)")
    p.add_argument(
        "--version", action="version", version=f"keepitgoing-classify {VERSION}"
    )
    return p.parse_args()


def main():
    args = parse_args()
    if args.list_profiles:
        for name, cfg in PROFILES.items():
            print(f"  {name:22}  {cfg['description']}")
            print(f"  {'':22}  model={cfg['model']}  base_url={cfg['base_url']}")
        return 0
    if not args.input_file and not args.stdin:
        args.stdin = True  # default when piped

    # Resolve profile (explicit --profile > config file > DEFAULT)
    profile_name, profile = load_profile(args.profile)
    # Allow --model to override the model within the profile
    if args.model:
        profile = dict(profile)
        profile["model"] = args.model

    t0 = time.monotonic()
    raw_input = read_input(args)
    content = truncate(raw_input, args.max_chars)
    excerpt = raw_input[:200].replace("\n", " ")

    if args.dry_run:
        log_stderr(
            f"DRY RUN: would classify {len(content)} chars via "
            f"profile={profile_name} model={profile['model']} base_url={profile['base_url']}"
        )
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "input_chars": len(content),
                    "session": args.session,
                    "profile": profile_name,
                    "model": profile["model"],
                },
                indent=2,
            )
        )
        return 0

    try:
        raw = call_classifier(content, profile, args.timeout)
        parsed = extract_json(raw)
        validated = validate_and_normalize(parsed)
        validated.update(
            {
                "schema_version": SCHEMA_VERSION,
                "classified_at": utcnow_iso(),
                "classifier_profile": profile_name,
                "classifier_model": profile["model"],
                "input_excerpt": excerpt,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
        )
        payload = validated
    except Exception as e:
        log_stderr(f"classifier failed (profile={profile_name}): {e}")
        payload = build_unknown_result(str(e), excerpt, profile["model"])
        payload["classifier_profile"] = profile_name

    if args.output_file:
        out_path = Path(args.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
    else:
        out_path = write_state(args.session, payload)

    log_stderr(
        f"wrote {out_path} state={payload['state']} action={payload['suggested_action']}"
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
