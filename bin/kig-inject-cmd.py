#!/usr/bin/env python3
"""CLI helper backing the /kig-inject slash command.

Defaults to GLOBAL scope (inject is an ambient user-level context override).
Use --project to scope to the current project's .kig/.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Locate KIG Python modules. In production they live at ~/.claude/kig/_src/;
# in dev / tests PYTHONPATH usually points at the repo src/ instead.
_KIG_SRC = Path.home() / ".claude" / "kig" / "_src"
if _KIG_SRC.is_dir() and str(_KIG_SRC) not in sys.path:
    sys.path.insert(0, str(_KIG_SRC))

from kig_config import find_project_kig, global_kig_dir
from kig_inject import (
    InjectStore,
    add_entry,
    load_store,
    remove_entry,
    save_store,
    set_master,
    toggle_entry,
)


def resolve_inject_path(is_project: bool) -> Path:
    if not is_project:
        return global_kig_dir() / "inject.json"
    proj = find_project_kig(Path.cwd())
    if proj is None:
        proj = Path.cwd() / ".kig"
        proj.mkdir(exist_ok=True)
    return proj / "inject.json"


def _parse_for(for_arg):
    if isinstance(for_arg, str):
        modes = [m.strip() for m in for_arg.split(",") if m.strip()]
    else:
        modes = list(for_arg)
    return modes or ["all"]


def cmd_add(args):
    path = resolve_inject_path(args.project)
    entry = add_entry(path, text=args.text, for_modes=_parse_for(args.f))
    print(f"Added [{len(load_store(path).entries)}]: {entry.text}")
    print(f"  for: {','.join(entry.for_modes)}")
    print(f"  saved to: {path}")
    return 0


def cmd_remove(args):
    path = resolve_inject_path(args.project)
    before = len(load_store(path).entries)
    remove_entry(path, args.n)
    after = len(load_store(path).entries)
    print(f"Removed entry #{args.n}. {after} remain (was {before}).")
    return 0


def cmd_toggle(args):
    path = resolve_inject_path(args.project)
    toggle_entry(path, args.n)
    store = load_store(path)
    idx = args.n - 1
    if 0 <= idx < len(store.entries):
        state = "on" if store.entries[idx].enabled else "off"
        print(f"Entry #{args.n}: now {state}")
    return 0


def cmd_list(args):
    path = resolve_inject_path(args.project)
    store = load_store(path)
    print(f"master: {'on' if store.master_enabled else 'off'}")
    if not store.entries:
        print("(no entries)")
        return 0
    for i, e in enumerate(store.entries, start=1):
        state = "on" if e.enabled else "off"
        tag = ",".join(e.for_modes)
        print(f"  [{i}] {state} ({tag}) - {e.text}")
    print(f"source: {path}")
    return 0


def cmd_on(args):
    path = resolve_inject_path(args.project)
    set_master(path, True)
    print(f"master: on ({path})")
    return 0


def cmd_off(args):
    path = resolve_inject_path(args.project)
    set_master(path, False)
    print(f"master: off ({path})")
    return 0


def cmd_clear(args):
    path = resolve_inject_path(args.project)
    save_store(path, InjectStore(master_enabled=False, entries=[]))
    print(f"cleared: {path}")
    return 0


HELP = """\
/kig-inject - consolidated context injection (replaces /kig-pin + old /kig-inject)

Adds a persistent list of reminders KIG prepends to every nudge. Each entry
is individually toggleable; a master switch turns the whole list on/off.

SUBCOMMANDS
  add [--project] [--for MODES...] "text"
  remove [--project] <N>
  toggle [--project] <N>
  list [--project]
  show [--project]           alias for list
  on [--project]             master switch on
  off [--project]            master switch off (entries preserved)
  clear [--project]          wipe entries + master off
  help

EXAMPLES
  /kig-inject add "working on Rust crate; don't touch Python"
  /kig-inject add --for simple "check logs at /tmp/claude-keepitgoing/"
  /kig-inject list
  /kig-inject toggle 2
  /kig-inject off

SCOPE
  Default:   global  (~/.claude/kig/inject.json) - affects every session
  --project: this project only  (./.kig/inject.json)

Modes for --for:  all | minimal | simple | verbose  (default: all)
"""


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP)
        return 0
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--project", action="store_true", help="scope to project .kig/")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument(
        "-f",
        "--for",
        default="all",
        dest="f",
        help="comma-separated modes: all | minimal | simple | verbose",
    )
    a.add_argument("text")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove")
    r.add_argument("n", type=int)
    r.set_defaults(func=cmd_remove)

    t = sub.add_parser("toggle")
    t.add_argument("n", type=int)
    t.set_defaults(func=cmd_toggle)

    for name, fn in [
        ("list", cmd_list),
        ("show", cmd_list),
        ("on", cmd_on),
        ("off", cmd_off),
        ("clear", cmd_clear),
    ]:
        s = sub.add_parser(name)
        s.set_defaults(func=fn)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
