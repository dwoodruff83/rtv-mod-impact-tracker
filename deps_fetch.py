#!/usr/bin/env python3
"""Maintain local mirror clones of upstream mod-dependency repos.

Where snapshot.py + fetch_version.py track the *game* by rebuilding history
from decompiles, this script tracks *mod dependencies* (Metro Mod Loader, MCM,
etc.) where the upstream is already a git repo with proper tags. We just keep
a pristine clone of each one, fetch new tags on demand, and let the diff /
audit / changelog scripts read tags directly from those clones.

Subcommands
-----------
    list                Show registered deps and clone status (tag count, latest tag)
    sync                git clone (if missing) or git fetch --tags --force (if present),
                        for one or all deps
    tags <name>         Show every tag known for one dep, sorted by creation date
    add <name> ...      Register a new dep in mod_tracker.toml

Configuration
-------------
Reads `[[deps]]` array from mod_tracker.toml. Each entry needs:

    [[deps]]
    name           = "metro"                                  # short id used on CLI
    display_name   = "Metro Mod Loader"                       # human label
    repo           = "https://github.com/.../vostok-mod-loader"
    path           = "reference/MetroModLoader_source"        # workspace-relative
    modworkshop_id = 55623                                    # optional, for cross-ref

Typical workflow
----------------
    deps_fetch list                # see what's registered
    deps_fetch sync                # clone everything that's missing, fetch the rest
    deps_fetch tags mcm            # show every tag on the MCM clone
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


@dataclass
class Dep:
    name: str
    display_name: str
    repo: str
    path: Path
    modworkshop_id: int | None = None

    @classmethod
    def from_dict(cls, d: dict, workspace: Path) -> "Dep":
        for required in ("name", "repo", "path"):
            if required not in d:
                raise SystemExit(f"deps entry missing required field {required!r}: {d}")
        return cls(
            name=d["name"],
            display_name=d.get("display_name", d["name"]),
            repo=d["repo"],
            path=workspace / d["path"],
            modworkshop_id=d.get("modworkshop_id"),
        )


def find_config(start: Path) -> Path | None:
    cur = start.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / "mod_tracker.toml"
        if candidate.exists():
            return candidate
    return None


def load_config(config_path: Path) -> dict:
    with config_path.open("rb") as f:
        return tomllib.load(f)


def load_deps(config: dict, config_path: Path) -> list[Dep]:
    workspace = config_path.parent
    raw = config.get("deps", [])
    if not raw:
        return []
    return [Dep.from_dict(d, workspace) for d in raw]


def find_dep(deps: list[Dep], name: str) -> Dep:
    for d in deps:
        if d.name == name:
            return d
    raise SystemExit(
        f"unknown dep: {name!r}. Registered: {', '.join(d.name for d in deps) or '(none)'}"
    )


def run_git(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, check=check, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout


def is_clone(path: Path) -> bool:
    return (path / ".git").exists() or (path / "HEAD").exists()


def list_tags(path: Path) -> list[str]:
    if not is_clone(path):
        return []
    out = run_git(["tag", "--list", "--sort=creatordate"], cwd=path, check=False)
    return [t for t in out.splitlines() if t]


def latest_tag(path: Path) -> str | None:
    tags = list_tags(path)
    return tags[-1] if tags else None


def clone_or_fetch(dep: Dep, dry_run: bool = False) -> None:
    if not dep.path.exists():
        dep.path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[clone] {dep.name}: {dep.repo} -> {dep.path}")
        if dry_run:
            return
        run_git(["clone", "--no-checkout", dep.repo, str(dep.path)])
        return

    if not is_clone(dep.path):
        raise SystemExit(
            f"{dep.path} exists but is not a git clone — refusing to overwrite. "
            f"Move it aside or delete it, then re-run."
        )

    print(f"[fetch] {dep.name}: {dep.path}")
    if dry_run:
        return
    run_git(["fetch", "--tags", "--force", "origin"], cwd=dep.path)
    run_git(["fetch", "origin"], cwd=dep.path)


# ---------- subcommands ----------


def cmd_list(deps: list[Dep], _args: argparse.Namespace) -> int:
    if not deps:
        print("(no deps registered — add some with `deps_fetch add` or edit mod_tracker.toml)")
        return 0
    print(f"{'name':<10} {'tags':<6} {'latest':<14} {'path'}")
    print("-" * 80)
    for d in deps:
        tags = list_tags(d.path)
        latest = tags[-1] if tags else "-"
        status = f"{len(tags)}" if tags else ("missing" if not d.path.exists() else "no-tags")
        print(f"{d.name:<10} {status:<6} {latest:<14} {d.path}")
    return 0


def cmd_sync(deps: list[Dep], args: argparse.Namespace) -> int:
    selected = [find_dep(deps, args.name)] if args.name else deps
    if not selected:
        print("(no deps registered)")
        return 0
    for d in selected:
        clone_or_fetch(d, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"\n[done] synced {len(selected)} dep(s)")
    return 0


def cmd_tags(deps: list[Dep], args: argparse.Namespace) -> int:
    d = find_dep(deps, args.name)
    if not is_clone(d.path):
        raise SystemExit(f"{d.name} not cloned yet — run `deps_fetch sync {d.name}` first")
    tags = list_tags(d.path)
    if not tags:
        print(f"(no tags on {d.name})")
        return 0
    for t in tags:
        print(t)
    return 0


def cmd_add(deps: list[Dep], args: argparse.Namespace, config_path: Path) -> int:
    if any(d.name == args.name for d in deps):
        raise SystemExit(f"dep {args.name!r} already registered")

    text = config_path.read_text(encoding="utf-8")
    block = (
        "\n[[deps]]\n"
        f'name           = "{args.name}"\n'
        f'display_name   = "{args.display_name or args.name}"\n'
        f'repo           = "{args.repo}"\n'
        f'path           = "{args.path}"\n'
    )
    if args.modworkshop_id is not None:
        block += f"modworkshop_id = {args.modworkshop_id}\n"

    if not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text + block, encoding="utf-8")
    print(f"[add] appended dep {args.name!r} to {config_path}")
    print("       run `deps_fetch sync` to clone it.")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", type=Path, help="explicit path to mod_tracker.toml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show registered deps and clone status").set_defaults(func=cmd_list)

    s = sub.add_parser("sync", help="clone (if missing) or fetch tags (if present)")
    s.add_argument("name", nargs="?", help="dep name (omit to sync all)")
    s.add_argument("--dry-run", action="store_true", help="print planned actions without writing")
    s.set_defaults(func=cmd_sync)

    t = sub.add_parser("tags", help="list tags on a dep clone")
    t.add_argument("name", help="dep name")
    t.set_defaults(func=cmd_tags)

    a = sub.add_parser("add", help="register a new dep in mod_tracker.toml")
    a.add_argument("name", help="short id, e.g. 'mcm'")
    a.add_argument("--repo", required=True, help="upstream git URL")
    a.add_argument("--path", required=True, help="workspace-relative clone path")
    a.add_argument("--display-name", help="human label (default: same as name)")
    a.add_argument("--modworkshop-id", type=int, help="ModWorkshop mod id")
    a.set_defaults(func=cmd_add)

    return p.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config or find_config(Path(os.getcwd()))
    if not config_path:
        raise SystemExit(
            "could not find mod_tracker.toml. Either:\n"
            "  - cd into a workspace that contains one, or\n"
            "  - pass --config <path>"
        )
    deps = load_deps(load_config(config_path), config_path)

    if args.cmd == "add":
        return cmd_add(deps, args, config_path)
    return args.func(deps, args)


if __name__ == "__main__":
    sys.exit(main())
