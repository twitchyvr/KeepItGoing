#!/usr/bin/env python3
"""CLI helper backing the /kig-library slash command.

Defaults to PROJECT scope (libraries are typically project-specific).
Use --global to affect every project.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

from kig_config import find_project_kig, global_kig_dir


def resolve_scope_dir(is_global: bool) -> Path:
    if is_global:
        d = global_kig_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d
    proj = find_project_kig(Path.cwd())
    if proj is None:
        proj = Path.cwd() / ".kig"
        proj.mkdir(exist_ok=True)
    return proj


def _lib_path(scope_dir: Path, mode: str) -> Path:
    if mode == "verbose":
        return scope_dir / "verbose-entries.json"
    return scope_dir / f"{mode}.json"


def _load_lib(path: Path) -> dict:
    if not path.exists():
        return {"entries": []}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"entries": []}


def _save_lib(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _expand_for(for_arg):
    # Accept either a string ("all" or "simple,verbose") or a pre-split list.
    if isinstance(for_arg, str):
        modes = [m.strip() for m in for_arg.split(",") if m.strip()]
    else:
        modes = list(for_arg)
    if "all" in modes or not modes:
        return ["minimal", "simple", "verbose"]
    return modes


def cmd_add(args):
    scope = resolve_scope_dir(args.g)
    for mode in _expand_for(args.f):
        path = _lib_path(scope, mode)
        data = _load_lib(path)
        data["entries"].append(
            {
                "id": secrets.token_hex(4),
                "text": args.text,
                "category": f"user-{mode}",
            }
        )
        _save_lib(path, data)
        print(f"Added to {path}: {args.text}")
    return 0


def cmd_remove(args):
    scope = resolve_scope_dir(args.g)
    path = _lib_path(scope, args.mode)
    data = _load_lib(path)
    idx = args.n - 1
    if 0 <= idx < len(data["entries"]):
        removed = data["entries"].pop(idx)
        _save_lib(path, data)
        print(f"Removed: {removed['text']}")
    else:
        print(
            f"Index {args.n} out of range (have {len(data['entries'])})",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_list(args):
    scope = resolve_scope_dir(args.g)
    for mode in ("minimal", "simple", "verbose"):
        path = _lib_path(scope, mode)
        data = _load_lib(path)
        print(f"[{mode}] {path}")
        if not data["entries"]:
            print("  (no entries)")
            continue
        for i, e in enumerate(data["entries"], start=1):
            print(f"  [{i}] {e['text']}")
    return 0


def cmd_isolate(args):
    scope = resolve_scope_dir(False)
    (scope / "isolate").touch()
    print(f"isolated: {scope}")
    return 0


def cmd_unisolate(args):
    scope = resolve_scope_dir(False)
    marker = scope / "isolate"
    if marker.exists():
        marker.unlink()
    print(f"unisolated: {scope}")
    return 0


def cmd_suppress(args):
    scope = resolve_scope_dir(False)
    path = scope / "suppress.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    data.setdefault("categories", [])
    data.setdefault("ids", [])
    target = args.target
    if all(c.isalnum() or c == "_" for c in target) and not target.startswith(
        "directive_"
    ):
        if target not in data["categories"]:
            data["categories"].append(target)
    else:
        if target not in data["ids"]:
            data["ids"].append(target)
    path.write_text(json.dumps(data, indent=2))
    print(f"suppressed: {target} -> {path}")
    return 0


def cmd_unsuppress(args):
    scope = resolve_scope_dir(False)
    path = scope / "suppress.json"
    if not path.exists():
        print("no suppress list")
        return 0
    data = json.loads(path.read_text())
    for key in ("categories", "ids"):
        if args.target in data.get(key, []):
            data[key].remove(args.target)
    path.write_text(json.dumps(data, indent=2))
    print(f"unsuppressed: {args.target}")
    return 0


HELP = """\
/kig-library - manage the nudge-sentence library

Add or remove sentences the KIG monitor pulls from. Project scope by default;
--global affects every project on the machine.

SUBCOMMANDS
  add [--global] [--for MODES...] "text"
  remove [--global] --mode <minimal|simple|verbose> <N>
  list [--global]
  suppress <category-or-id>   (project only) hide a global category/id
  unsuppress <id>
  isolate                     (project only) ignore ALL globals
  unisolate
  help

EXAMPLES
  /kig-library add "don't commit compiled .app bundles"
  /kig-library add --global --for simple "check logs at /tmp/..."
  /kig-library suppress visual_verification
  /kig-library isolate

SCOPE
  Default:    this project  (./.kig/*.json)
  --global:   machine-wide  (~/.claude/kig/*.json)
"""


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP)
        return 0
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-g", "--global", dest="g", action="store_true")
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
    r.add_argument("--mode", required=True, choices=["minimal", "simple", "verbose"])
    r.add_argument("n", type=int)
    r.set_defaults(func=cmd_remove)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("isolate").set_defaults(func=cmd_isolate)
    sub.add_parser("unisolate").set_defaults(func=cmd_unisolate)

    s = sub.add_parser("suppress")
    s.add_argument("target")
    s.set_defaults(func=cmd_suppress)
    u = sub.add_parser("unsuppress")
    u.add_argument("target")
    u.set_defaults(func=cmd_unsuppress)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
