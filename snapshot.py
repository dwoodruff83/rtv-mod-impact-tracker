#!/usr/bin/env python3
"""Capture a snapshot of decompiled Godot scripts into a versioned git history.

Reads configuration from `mod_tracker.toml` discovered by walking up from the
current working directory (or via --config). Defaults are tuned for Road to
Vostok modding workspaces, but the tool is game-agnostic — see README.

Usage:
    python snapshot.py                     # auto-detect version + buildid
    python snapshot.py --label 0.1.0.0     # override version label
    python snapshot.py --build 22674175    # override Steam buildid
    python snapshot.py --dry-run           # preview actions, write nothing
    python snapshot.py --init              # initialize history repo if missing
    python snapshot.py --config path.toml  # use an explicit config file
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

EXCLUDE_TOPLEVEL_DEFAULT = ["mods", ".godot", "gdre_export.log"]


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


def default_steam_install_root() -> Path:
    if sys.platform.startswith("win"):
        return Path(r"C:\Program Files (x86)\Steam\steamapps")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Steam" / "steamapps"
    return Path.home() / ".local" / "share" / "Steam" / "steamapps"


def resolve_paths(config: dict, config_path: Path) -> dict:
    workspace = config_path.parent
    paths = config.get("paths", {})
    steam = config.get("steam", {})

    decompiled = workspace / paths.get("decompiled", "reference/RTV_decompiled")
    history = workspace / paths.get("history", "reference/RTV_history")

    steam_root = (
        Path(steam["install_root"])
        if "install_root" in steam
        else default_steam_install_root()
    )
    app_id = steam.get("app_id")
    appmanifest = steam_root / f"appmanifest_{app_id}.acf" if app_id else None

    exclude = config.get("snapshot", {}).get("exclude_toplevel", EXCLUDE_TOPLEVEL_DEFAULT)

    return {
        "workspace": workspace,
        "decompiled": decompiled,
        "history": history,
        "appmanifest": appmanifest,
        "exclude_toplevel": set(exclude),
    }


def detect_version(project_godot: Path) -> str | None:
    if not project_godot.exists():
        return None
    text = project_godot.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^\s*config/version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def detect_buildid(appmanifest: Path | None) -> str | None:
    if appmanifest is None or not appmanifest.exists():
        return None
    text = appmanifest.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"buildid"\s+"(\d+)"', text)
    return m.group(1) if m else None


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, text=True, capture_output=True
    )


def init_repo(history_dir: Path) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    if (history_dir / ".git").exists():
        print(f"[skip] repo already initialized at {history_dir}")
        return
    run_git(["init", "-b", "main"], cwd=history_dir)
    (history_dir / ".gitignore").write_text(
        "# snapshot exclusions (also enforced by snapshot.py)\n"
        ".godot/\n"
        "gdre_export.log\n"
        "mods/\n",
        encoding="utf-8",
    )
    (history_dir / "README.md").write_text(
        "# History repo\n\n"
        "Versioned snapshots of decompiled game scripts, one commit per game patch.\n\n"
        "Managed by snapshot.py from rtv-mod-impact-tracker. Do not edit by hand.\n\n"
        "Tags use the pattern `game-v<version>-build<buildid>`.\n",
        encoding="utf-8",
    )
    run_git(["add", ".gitignore", "README.md"], cwd=history_dir)
    run_git(["commit", "-m", "Initialize history repo"], cwd=history_dir)
    print(f"[init] created {history_dir} as a git repo")


def sync(source: Path, dest: Path, exclude: set[str], dry_run: bool) -> None:
    if not source.exists():
        raise SystemExit(f"source dir missing: {source}")

    preserved = {".git", "README.md", ".gitignore"}
    existing_top = {p.name for p in dest.iterdir() if p.name not in preserved}
    incoming_top = {p.name for p in source.iterdir() if p.name not in exclude}

    to_remove = existing_top - incoming_top
    for name in sorted(to_remove):
        target = dest / name
        print(f"[delete] {target}")
        if not dry_run:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    for name in sorted(incoming_top):
        src = source / name
        dst = dest / name
        print(f"[copy]   {name}")
        if dry_run:
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def commit_and_tag(
    history_dir: Path,
    version: str,
    buildid: str | None,
    message: str | None,
    dry_run: bool,
) -> str | None:
    status = run_git(["status", "--porcelain"], cwd=history_dir).stdout
    if not status.strip():
        print("[skip] no changes to commit — snapshot is identical to HEAD")
        return None

    tag = f"game-v{version}-build{buildid}" if buildid else f"game-v{version}"

    if not message:
        iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        buildpart = f", build {buildid}" if buildid else ""
        message = f"Game v{version}{buildpart} (captured {iso})"

    print(f"[commit] {message}")
    print(f"[tag]    {tag}")
    if dry_run:
        return tag

    run_git(["add", "-A"], cwd=history_dir)
    run_git(["commit", "-m", message], cwd=history_dir)

    existing = run_git(["tag", "--list", tag], cwd=history_dir).stdout.strip()
    if existing:
        print(f"[warn] tag {tag} already exists — not re-tagging")
    else:
        run_git(["tag", tag], cwd=history_dir)
    return tag


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", type=Path, help="explicit path to mod_tracker.toml")
    p.add_argument("--label", help="override auto-detected version label")
    p.add_argument(
        "--build",
        help="override auto-detected build id (use when appmanifest has drifted past the decompiled version)",
    )
    p.add_argument("--message", help="override commit message")
    p.add_argument("--dry-run", action="store_true", help="print planned actions without writing")
    p.add_argument("--init", action="store_true", help="initialize history repo if missing")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    config_path = args.config or find_config(Path(os.getcwd()))
    if not config_path:
        raise SystemExit(
            "could not find mod_tracker.toml. Either:\n"
            "  - cd into a workspace that contains one, or\n"
            "  - pass --config <path>\n"
            "See examples/road-to-vostok.toml for a template."
        )
    config = load_config(config_path)
    paths = resolve_paths(config, config_path)

    print(f"config:  {config_path}")
    print(f"workspace: {paths['workspace']}")

    if args.init or not (paths["history"] / ".git").exists():
        if not args.dry_run:
            init_repo(paths["history"])
        else:
            print(f"[dry-run] would init repo at {paths['history']}")
            if not (paths["history"] / ".git").exists():
                print("[dry-run] repo doesn't exist yet — aborting further actions")
                return 0

    version = args.label or detect_version(paths["decompiled"] / "project.godot")
    if not version:
        raise SystemExit(
            f"could not detect version from {paths['decompiled'] / 'project.godot'} — pass --label to override"
        )
    buildid = args.build or detect_buildid(paths["appmanifest"])

    project_version = detect_version(paths["decompiled"] / "project.godot")
    if args.label and project_version and project_version != args.label and not args.build:
        print(
            f"[warn] --label {args.label!r} doesn't match project.godot ({project_version!r}); "
            f"appmanifest buildid {buildid} probably doesn't apply — pass --build explicitly"
        )

    print(f"version: {version}")
    print(f"buildid: {buildid or '(not found)'}")
    print(f"source:  {paths['decompiled']}")
    print(f"history: {paths['history']}")
    print()

    sync(paths["decompiled"], paths["history"], paths["exclude_toplevel"], args.dry_run)
    tag = commit_and_tag(paths["history"], version, buildid, args.message, args.dry_run)

    if tag and not args.dry_run:
        print(f"\n[done] snapshot committed and tagged as {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
