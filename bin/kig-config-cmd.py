#!/usr/bin/env python3
"""CLI helper backing the /kig-config slash command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Locate KIG Python modules (installed layout: ~/.claude/kig/_src/).
_KIG_SRC = Path.home() / ".claude" / "kig" / "_src"
if _KIG_SRC.is_dir() and str(_KIG_SRC) not in sys.path:
    sys.path.insert(0, str(_KIG_SRC))

from kig_config import DEFAULTS, find_project_kig, global_kig_dir, load_merged


def _coerce(key: str, raw: str):
    target = DEFAULTS[key]
    if isinstance(target, bool):
        return raw.lower() in ("true", "yes", "on", "1")
    if isinstance(target, int):
        return int(raw)
    return raw


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


def cmd_set(args):
    if args.key not in DEFAULTS:
        print(f"Unknown key: {args.key}. Known keys: {list(DEFAULTS)}", file=sys.stderr)
        return 2
    value = _coerce(args.key, args.value)
    path = _scope_path(args.g)
    data = _read(path)
    data[args.key] = value
    _write(path, data)
    print(f"{args.key} = {value!r}  ->  {path}")
    return 0


def cmd_get(args):
    if args.key not in DEFAULTS:
        print(f"Unknown key: {args.key}", file=sys.stderr)
        return 2
    merged = load_merged()
    print(merged.get(args.key, DEFAULTS[args.key]))
    return 0


def cmd_show(args):
    merged = load_merged()
    for k in DEFAULTS:
        print(f"{k} = {merged.get(k, DEFAULTS[k])!r}")
    return 0


def cmd_reset(args):
    path = _scope_path(args.g)
    data = _read(path)
    if args.key in data:
        del data[args.key]
        _write(path, data)
        print(f"reset {args.key} in {path}")
    return 0


def cmd_reset_all(args):
    path = _scope_path(args.g)
    _write(path, {})
    print(f"cleared all settings in {path}")
    return 0


HELP = """\
/kig-config — manage KIG settings (project or global)

SUBCOMMANDS
  set [--global] <key> <value>
  get <key>                 shows resolved value (after merge)
  show                      list all keys with resolved values
  reset [--global] <key>    remove override (fall back to global or default)
  reset-all [--global]
  help

KEYS (defaults)
  default_mode = verbose         minimal | simple | verbose
  scope_mode = per-category      per-category | additive | override
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


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP)
        return 0
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-g", "--global", dest="g", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Parent parser so --global also works after the subcommand name.
    gparent = argparse.ArgumentParser(add_help=False)
    gparent.add_argument("-g", "--global", dest="g", action="store_true")

    s = sub.add_parser("set", parents=[gparent])
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_set)

    g = sub.add_parser("get", parents=[gparent])
    g.add_argument("key")
    g.set_defaults(func=cmd_get)
    sub.add_parser("show", parents=[gparent]).set_defaults(func=cmd_show)

    r = sub.add_parser("reset", parents=[gparent])
    r.add_argument("key")
    r.set_defaults(func=cmd_reset)
    sub.add_parser("reset-all", parents=[gparent]).set_defaults(func=cmd_reset_all)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
