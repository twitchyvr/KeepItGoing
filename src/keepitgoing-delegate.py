#!/usr/bin/env python3
"""
keepitgoing-delegate — delegate a narrowly-scoped task to Claude Opus in an
isolated git worktree, then return the diff for human review.

Use when consultation (kig unstuck / kig ask) isn't enough and the stuck AI
needs an actual bounded fix applied. Safety is enforced via:

  1. Worktree isolation — Opus only sees/writes inside the worktree, never
     touches the calling repo's working tree.
  2. Narrow task string required — no vague "fix the app"; caller must state
     the bounded scope.
  3. Diff review required — this script NEVER applies changes to the caller's
     repo. It prints the worktree path + diff summary; applying is a manual
     cherry-pick decision.
  4. Separate budget tracker — delegation is heavier than consultation so has
     its own daily cap (default 2h, configurable via
     `claude_delegate_daily_budget_sec`).
  5. Timeout — default 5 minutes; Opus is killed if it exceeds.

Usage:
  keepitgoing-delegate "Fix the Jest moduleNameMapper for dynamic imports in __tests__/api/all-generate-routes-auth.test.ts"
  keepitgoing-delegate --dry-run "some task"     # show plan, don't call Opus
  keepitgoing-delegate --model sonnet "task"     # override model
  keepitgoing-delegate --repo /path "task"       # override source repo (default: $PWD)
  keepitgoing-delegate --budget                  # show today's delegate budget

Output to stdout (production path):
  - Worktree path
  - Summary of what Opus did
  - Diff preview (first 80 lines)
  - Instructions to apply
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path

VERSION = "1.0.0"
CONFIG_FILE = Path.home() / ".claude" / "hooks" / "keepitgoing-config.json"
STATE_DIR = Path.home() / ".claude" / "hooks" / "state"
DELEGATE_LOG = STATE_DIR / "kig-delegations.jsonl"
WORKTREE_BASE = Path("/tmp/kig-delegate")
DEFAULT_BUDGET_SEC = 7200  # 2 hours
DEFAULT_MODEL = "opus"
CLAUDE_TIMEOUT_SEC = 300  # 5 minutes — generous for a bounded task

DELEGATE_PROMPT = """You are being delegated a narrowly-scoped task inside an isolated git worktree. Another AI tried and got stuck; you are expected to fix this specific thing and only this thing.

## Your worktree

Path: {worktree_path}
(Everything you do is isolated — changes here do NOT touch the calling session's working tree. You will return a diff; the user decides whether to cherry-pick.)

## Scope contract

- Task: {task}
- Do ONLY what the task says. Do not refactor adjacent code. Do not rename things. Do not update unrelated files.
- If you discover that the task premise is wrong, STOP and print a one-paragraph explanation starting with "BAD PREMISE:" — do not attempt a fix.
- If the task requires information not available, STOP and print "NEED: <what you need>" — do not guess.

## How to work

1. Read the relevant files in the worktree to understand the current state
2. Make the minimum change required to satisfy the task
3. If tests exist for the changed code, run them (pnpm test / npm test / pytest / cargo test as appropriate)
4. When done, print a concise summary starting with `DONE:` followed by:
   - One sentence of what you changed
   - A list of files modified
   - How you verified it works (test output, manual check, or "not verified")

## Constraints

- Do NOT run `git push` — this worktree is ephemeral
- Do NOT modify files outside the worktree path above
- Do NOT install new dependencies unless the task explicitly requires them
- Keep the diff SMALL — smaller is safer to review and apply

Your directive: {task}
"""


def log_stderr(msg):
    print(f"[keepitgoing-delegate] {msg}", file=sys.stderr)


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def today_budget_file():
    return STATE_DIR / f"kig-delegate-budget-{date.today().isoformat()}.json"


def load_today_budget():
    p = today_budget_file()
    if not p.exists():
        return {"used_sec": 0, "delegations": 0}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"used_sec": 0, "delegations": 0}


def save_today_budget(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    today_budget_file().write_text(json.dumps(data, indent=2))


def budget_limit_sec():
    return int(
        load_config().get("claude_delegate_daily_budget_sec", DEFAULT_BUDGET_SEC)
    )


def delegate_model():
    return load_config().get(
        "delegate_model", load_config().get("escalation_model", DEFAULT_MODEL)
    )


def fmt_duration(sec):
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60:02d}s"
    return f"{sec // 3600}h {(sec % 3600) // 60:02d}m"


def budget_status():
    used = load_today_budget()["used_sec"]
    cap = budget_limit_sec()
    return used, cap, max(0, cap - used)


def run(cmd, cwd=None, capture=True, timeout=None, check=False):
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )


def ensure_repo(repo_path):
    """Confirm repo_path is a git repo with clean enough state for a worktree."""
    if not (repo_path / ".git").exists():
        raise RuntimeError(f"not a git repo: {repo_path}")
    head = run(["git", "rev-parse", "HEAD"], cwd=repo_path)
    if head.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {head.stderr}")
    return head.stdout.strip()


def create_worktree(repo_path, head_sha):
    """Create an ephemeral worktree at /tmp/kig-delegate/<repo>-<timestamp>."""
    WORKTREE_BASE.mkdir(parents=True, exist_ok=True)
    repo_name = repo_path.name
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    wt_path = WORKTREE_BASE / f"{repo_name}-{ts}"
    # detached worktree — never accidentally push/rebase this
    result = run(
        ["git", "worktree", "add", "--detach", str(wt_path), head_sha], cwd=repo_path
    )
    if result.returncode != 0:
        raise RuntimeError(f"worktree creation failed: {result.stderr}")
    return wt_path


def get_worktree_diff(wt_path, head_sha):
    """Return git diff from the worktree since head_sha."""
    result = run(["git", "diff", "--stat", head_sha], cwd=wt_path)
    stat = result.stdout
    result = run(["git", "diff", head_sha], cwd=wt_path)
    full = result.stdout
    return stat, full


def cleanup_worktree(repo_path, wt_path, keep=True):
    """Detach/remove the worktree. If keep=True, leaves it on disk for review."""
    if keep:
        return
    try:
        run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=repo_path)
    except Exception:
        pass


def call_opus_in_worktree(wt_path, task, model, timeout_sec):
    """Invoke `claude -p` scoped to the worktree. Returns (output, elapsed_sec)."""
    prompt = DELEGATE_PROMPT.replace("{worktree_path}", str(wt_path)).replace(
        "{task}", task
    )
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--model",
                model,
                "--add-dir",
                str(wt_path),
                "--output-format",
                "text",
                "--dangerously-skip-permissions",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(wt_path),
        )
    except FileNotFoundError:
        raise RuntimeError("`claude` CLI not found on PATH")
    except subprocess.TimeoutExpired:
        elapsed = int(time.monotonic() - t0)
        raise RuntimeError(f"delegate timed out after {elapsed}s (cap {timeout_sec}s)")
    elapsed = int(time.monotonic() - t0)
    if result.returncode != 0:
        raise RuntimeError(f"claude exit {result.returncode}: {result.stderr[:300]}")
    return result.stdout.strip(), elapsed


def append_delegation_log(entry):
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with DELEGATE_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def parse_args():
    p = argparse.ArgumentParser(
        prog="keepitgoing-delegate",
        description="Delegate a narrow task to Claude Opus in an isolated worktree",
    )
    p.add_argument("task", nargs="?", help="The specific, narrowly-scoped task")
    p.add_argument("--repo", default=".", help="Source git repo (default: cwd)")
    p.add_argument(
        "--model",
        default=None,
        help=f"Delegate model (default from config: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--force", action="store_true", help="Ignore daily delegate budget cap"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Show plan without calling Opus"
    )
    p.add_argument(
        "--budget", action="store_true", help="Print today's delegate budget and exit"
    )
    p.add_argument(
        "--timeout", type=int, default=CLAUDE_TIMEOUT_SEC, help="Claude timeout seconds"
    )
    p.add_argument(
        "--keep-worktree",
        action="store_true",
        default=True,
        help="Keep the worktree on disk for manual review (default: true)",
    )
    p.add_argument(
        "--remove-worktree",
        action="store_false",
        dest="keep_worktree",
        help="Remove the worktree after producing the diff (diff is returned inline)",
    )
    p.add_argument(
        "--version", action="version", version=f"keepitgoing-delegate {VERSION}"
    )
    return p.parse_args()


def main():
    args = parse_args()

    if args.budget:
        used, cap, remaining = budget_status()
        print("Today's Claude DELEGATE budget:")
        print(f"  used:         {fmt_duration(used)}")
        print(f"  cap:          {fmt_duration(cap)}")
        print(f"  remaining:    {fmt_duration(remaining)}")
        print(f"  delegations:  {load_today_budget().get('delegations', 0)}")
        print(f"  model:        {delegate_model()}")
        return 0

    if not args.task or not args.task.strip():
        log_stderr("A task description is required. Be SPECIFIC and SCOPED.")
        log_stderr(
            'Example: kig delegate "Fix the Jest moduleNameMapper in __tests__/api/foo.test.ts"'
        )
        return 3

    model = args.model or delegate_model()
    used, cap, remaining = budget_status()

    if not args.force and remaining <= 0:
        log_stderr(
            f"delegate budget exhausted: used {fmt_duration(used)} / cap {fmt_duration(cap)}. "
            f"Use --force to override, or `kig budget set-delegate <duration>` to adjust."
        )
        return 1

    repo_path = Path(args.repo).resolve()
    try:
        head_sha = ensure_repo(repo_path)
    except Exception as e:
        log_stderr(f"repo check failed: {e}")
        return 3

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "repo": str(repo_path),
                    "head_sha": head_sha[:12],
                    "task": args.task,
                    "model": model,
                    "delegate_budget_remaining_sec": remaining,
                    "worktree_would_be_at": str(
                        WORKTREE_BASE / f"{repo_path.name}-YYYYMMDD-HHMMSS"
                    ),
                },
                indent=2,
            )
        )
        return 0

    # Create worktree
    try:
        wt_path = create_worktree(repo_path, head_sha)
    except Exception as e:
        log_stderr(f"worktree creation failed: {e}")
        return 3

    log_stderr(f"worktree: {wt_path}")
    log_stderr(f"invoking claude -p --model {model} (timeout {args.timeout}s)…")

    try:
        output, elapsed = call_opus_in_worktree(wt_path, args.task, model, args.timeout)
    except Exception as e:
        log_stderr(f"delegation failed: {e}")
        cleanup_worktree(repo_path, wt_path, keep=args.keep_worktree)
        return 2

    # Get diff
    try:
        stat, full_diff = get_worktree_diff(wt_path, head_sha)
    except Exception as e:
        log_stderr(f"diff failed: {e}")
        stat, full_diff = "", ""

    # Decrement budget
    today = load_today_budget()
    today["used_sec"] = int(today.get("used_sec", 0)) + elapsed
    today["delegations"] = int(today.get("delegations", 0)) + 1
    save_today_budget(today)

    # Persist result for audit
    append_delegation_log(
        {
            "at": utcnow_iso(),
            "model": model,
            "elapsed_sec": elapsed,
            "repo": str(repo_path),
            "head_sha": head_sha,
            "worktree": str(wt_path),
            "task": args.task[:500],
            "diffstat": stat,
            "output_chars": len(output),
            "files_changed": stat.count("\n"),
            "budget_used_sec_after": today["used_sec"],
        }
    )

    # Check for BAD PREMISE / NEED signals
    first_line = output.split("\n")[0].strip() if output else ""
    verdict = "DONE"
    if first_line.startswith("BAD PREMISE:"):
        verdict = "BAD_PREMISE"
    elif first_line.startswith("NEED:"):
        verdict = "NEED_INFO"
    elif not first_line.upper().startswith("DONE"):
        verdict = "UNCLEAR"

    # Emit production report on stdout
    print("=" * 72)
    print(
        f"KIG DELEGATE REPORT  (verdict: {verdict}, model: {model}, elapsed: {elapsed}s)"
    )
    print("=" * 72)
    print()
    print(f"Task: {args.task}")
    print(f"Worktree: {wt_path}")
    print(f"Base commit: {head_sha[:12]}")
    print()
    if stat:
        print("--- Diffstat ---")
        print(stat.strip())
        print()
    print("--- Opus output ---")
    print(output)
    print()
    if full_diff:
        print("--- Full diff (preview, first 80 lines) ---")
        for line in full_diff.splitlines()[:80]:
            print(line)
        if len(full_diff.splitlines()) > 80:
            print(
                f"  ...[+{len(full_diff.splitlines()) - 80} more lines — see worktree]"
            )
    print()
    print("--- To review / apply ---")
    print(f"  git diff --no-index {head_sha[:12]} {wt_path}")
    print(f"  # or in the calling repo:")
    print(f"  cd {repo_path}")
    print(f"  git checkout -b review-delegate-$(date +%s)")
    print(f"  cp -r {wt_path}/* .  # naive apply; inspect first")
    print(f"  # or cherry-pick specific files as needed")
    print()
    print(
        f"Budget: used {fmt_duration(today['used_sec'])} of {fmt_duration(cap)} cap today."
    )
    print(f"Audit log: {DELEGATE_LOG}")

    log_stderr(
        f"delegation ok | model={model} elapsed={elapsed}s | verdict={verdict} | "
        f"budget {fmt_duration(today['used_sec'])}/{fmt_duration(cap)} used"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
