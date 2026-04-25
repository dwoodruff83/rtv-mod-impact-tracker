#!/usr/bin/env python3
"""Download a specific Steam build, decompile its .pck with GDRE_Tools, and
snapshot it into the history repo — all in one shot.

Steam only ever serves the latest build to the regular client, but Steam's
content servers retain every historical manifest. This tool lets us pull any
shipped patch by manifest ID, run it through GDRE_Tools, and tag the result
in our local game-history repo so we never miss an intermediate version.

Subcommands
-----------
    list                Show registered versions and which already have tags
    add <label> ...     Register a manifest in the manifests file
    bootstrap           Download DepotDownloader (one-time setup)
    fetch <label>       Full pipeline for one version
    backfill            Run fetch for every registered version that lacks a tag

Manifest IDs come from SteamDB (https://steamdb.info/app/<app_id>/depots/) —
copy from your browser. SteamDB blocks automated requests so the registration
step is manual; everything else is automatic.

Typical workflow
----------------
    python fetch_version.py bootstrap
    python fetch_version.py add 0.1.1.1 --manifest 7766554433221100 --build 22443322
    python fetch_version.py fetch 0.1.1.1
    python fetch_version.py backfill        # picks up anything else still missing

Configuration
-------------
Reads from `mod_tracker.toml` (auto-discovered or via --config). Optional
`[fetch_version]` section overrides defaults:

    [fetch_version]
    manifests_file       = "manifests.json"             # workspace-relative
    gdre_exe             = "tools/GDRE_tools/gdre_tools.exe"
    depot_downloader_exe = "tools/DepotDownloader/DepotDownloader.exe"
    scratch_dir          = "tools/_versions"
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DD_RELEASE_API = "https://api.github.com/repos/SteamRE/DepotDownloader/releases/latest"
DD_ASSET_NAME = "DepotDownloader-windows-x64.zip"

DEFAULTS = {
    "manifests_file": "manifests.json",
    "gdre_exe": "tools/GDRE_tools/gdre_tools.exe",
    "depot_downloader_exe": "tools/DepotDownloader/DepotDownloader.exe",
    "scratch_dir": "tools/_versions",
}


# ---------- config + paths ----------

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


@dataclass
class Paths:
    workspace: Path
    decompiled: Path
    history: Path
    manifests_file: Path
    gdre_exe: Path
    depot_downloader_exe: Path
    scratch_dir: Path
    snapshot_py: Path  # sibling to this script
    config_path: Path


def resolve_paths(config: dict, config_path: Path) -> Paths:
    workspace = config_path.parent
    pcfg = config.get("paths", {})
    fcfg = config.get("fetch_version", {})

    def rel(key: str, section: dict) -> Path:
        return workspace / section.get(key, DEFAULTS[key])

    return Paths(
        workspace=workspace,
        decompiled=workspace / pcfg.get("decompiled", "reference/RTV_decompiled"),
        history=workspace / pcfg.get("history", "reference/RTV_history"),
        manifests_file=rel("manifests_file", fcfg),
        gdre_exe=rel("gdre_exe", fcfg),
        depot_downloader_exe=rel("depot_downloader_exe", fcfg),
        scratch_dir=rel("scratch_dir", fcfg),
        snapshot_py=Path(__file__).resolve().parent / "snapshot.py",
        config_path=config_path,
    )


# ---------- registry ----------

@dataclass
class Version:
    label: str
    manifest_id: str
    build_id: str | None = None
    date: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Version":
        return cls(
            label=d["label"],
            manifest_id=str(d["manifest_id"]),
            build_id=str(d["build_id"]) if d.get("build_id") else None,
            date=d.get("date"),
            note=d.get("note"),
        )

    def to_dict(self) -> dict:
        out: dict = {"label": self.label, "manifest_id": self.manifest_id}
        if self.build_id:
            out["build_id"] = self.build_id
        if self.date:
            out["date"] = self.date
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Registry:
    app_id: int
    depot_id: int
    versions: list[Version]
    raw: dict
    path: Path

    @classmethod
    def load(cls, path: Path) -> "Registry":
        if not path.exists():
            raise SystemExit(
                f"manifests file missing: {path}\n"
                "Create it with a JSON object containing app_id, depot_id, and versions=[]"
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        versions = [Version.from_dict(v) for v in raw.get("versions", [])]
        return cls(
            app_id=int(raw["app_id"]),
            depot_id=int(raw["depot_id"]),
            versions=versions,
            raw=raw,
            path=path,
        )

    def save(self) -> None:
        out = dict(self.raw)
        out["app_id"] = self.app_id
        out["depot_id"] = self.depot_id
        out["versions"] = [v.to_dict() for v in self.versions]
        self.path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def find(self, label: str) -> Version | None:
        for v in self.versions:
            if v.label == label:
                return v
        return None

    def upsert(self, v: Version) -> bool:
        for i, existing in enumerate(self.versions):
            if existing.label == v.label:
                self.versions[i] = v
                return False  # updated
        self.versions.append(v)
        return True  # added


# ---------- git tag check ----------

def existing_tags(history: Path) -> set[str]:
    if not (history / ".git").exists():
        return set()
    res = subprocess.run(
        ["git", "tag", "--list"], cwd=history, capture_output=True, text=True, check=True
    )
    return {line.strip() for line in res.stdout.splitlines() if line.strip()}


def expected_tag(v: Version) -> str:
    return f"game-v{v.label}-build{v.build_id}" if v.build_id else f"game-v{v.label}"


# ---------- DepotDownloader ----------

def bootstrap_depot_downloader(paths: Paths, force: bool = False) -> None:
    if paths.depot_downloader_exe.exists() and not force:
        print(f"[skip] DepotDownloader already present at {paths.depot_downloader_exe}")
        return

    dd_dir = paths.depot_downloader_exe.parent
    dd_dir.mkdir(parents=True, exist_ok=True)

    print(f"[fetch] querying latest release: {DD_RELEASE_API}")
    with urllib.request.urlopen(DD_RELEASE_API) as resp:
        release = json.loads(resp.read())
    asset = next((a for a in release.get("assets", []) if a["name"] == DD_ASSET_NAME), None)
    if asset is None:
        raise SystemExit(f"asset {DD_ASSET_NAME} not found in latest release")

    zip_path = dd_dir / DD_ASSET_NAME
    print(f"[fetch] downloading {asset['browser_download_url']} ({asset['size']:,} bytes)")
    urllib.request.urlretrieve(asset["browser_download_url"], zip_path)

    print(f"[unzip] extracting to {dd_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dd_dir)
    zip_path.unlink()

    if not paths.depot_downloader_exe.exists():
        raise SystemExit(
            f"extraction did not produce {paths.depot_downloader_exe} — release layout may have changed"
        )
    print(f"[done] DepotDownloader installed at {paths.depot_downloader_exe}")


def run_depot_downloader(
    paths: Paths, reg: Registry, v: Version, dest: Path, username: str | None
) -> None:
    if not paths.depot_downloader_exe.exists():
        raise SystemExit("DepotDownloader missing — run: fetch_version.py bootstrap")

    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(paths.depot_downloader_exe),
        "-app", str(reg.app_id),
        "-depot", str(reg.depot_id),
        "-manifest", v.manifest_id,
        "-dir", str(dest),
        "-validate",
    ]
    if username:
        # -remember-password caches the session token (in DepotDownloader's
        # .DepotDownloader subdir) so subsequent runs skip 2FA until Steam
        # expires the session, typically weeks.
        cmd += ["-username", username, "-remember-password"]
    print(f"[steam] {' '.join(cmd)}")
    print("[steam] DepotDownloader will prompt for password and Steam Guard if needed.")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise SystemExit(f"DepotDownloader exited with code {res.returncode}")


# ---------- GDRE_Tools ----------

def find_pck(download_dir: Path) -> Path:
    pcks = list(download_dir.rglob("*.pck"))
    if not pcks:
        raise SystemExit(f"no .pck found under {download_dir}")
    if len(pcks) > 1:
        # prefer RTV.pck if present
        rtv = [p for p in pcks if p.name.lower() == "rtv.pck"]
        if rtv:
            return rtv[0]
        raise SystemExit(f"multiple .pck files under {download_dir}: {pcks}")
    return pcks[0]


def run_gdre(paths: Paths, pck_path: Path, output_dir: Path) -> None:
    """Recover a .pck into a Godot project using GDRE_Tools.

    GDRE_Tools v2.5+ takes flags directly (no `--` separator):
        gdre_tools.exe --headless --recover=<pck> --output=<dir>
    """
    if not paths.gdre_exe.exists():
        raise SystemExit(f"GDRE_Tools missing at {paths.gdre_exe}")
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(paths.gdre_exe),
        "--headless",
        f"--recover={pck_path}",
        f"--output={output_dir}",
    ]
    print(f"[gdre]  {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0 or not any(output_dir.iterdir()):
        raise SystemExit(f"GDRE_Tools failed to decompile {pck_path} (exit {res.returncode})")


# ---------- pipeline ----------

def sync_decompiled(source: Path, dest: Path) -> None:
    """Replace dest with source contents (preserving dest's parent)."""
    if dest.exists():
        for p in dest.iterdir():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    else:
        dest.mkdir(parents=True, exist_ok=True)
    for p in source.iterdir():
        target = dest / p.name
        if p.is_dir():
            shutil.copytree(p, target)
        else:
            shutil.copy2(p, target)


def call_snapshot(paths: Paths, label: str, build_id: str | None) -> None:
    cmd = [
        sys.executable, str(paths.snapshot_py),
        "--config", str(paths.config_path),
        "--label", label,
    ]
    if build_id:
        cmd += ["--build", build_id]
    print(f"[snap]  {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise SystemExit(f"snapshot.py exited with {res.returncode}")


def fetch_one(paths: Paths, reg: Registry, v: Version, username: str | None, keep: bool) -> None:
    print(f"\n=== fetching {v.label} (manifest {v.manifest_id}) ===")
    workdir = paths.scratch_dir / v.label
    download_dir = workdir / "download"
    decompile_dir = workdir / "decompiled"

    run_depot_downloader(paths, reg, v, download_dir, username)
    pck = find_pck(download_dir)
    print(f"[gdre]  found pck: {pck}")
    run_gdre(paths, pck, decompile_dir)

    # GDRE often nests output under a folder named after the pck — flatten if so
    entries = list(decompile_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / "project.godot").exists():
        flat_source = entries[0]
    else:
        flat_source = decompile_dir
    if not (flat_source / "project.godot").exists():
        raise SystemExit(f"GDRE output missing project.godot at {flat_source}")

    sync_decompiled(flat_source, paths.decompiled)
    call_snapshot(paths, v.label, v.build_id)

    if not keep:
        print(f"[clean] removing {workdir}")
        shutil.rmtree(workdir, ignore_errors=True)


# ---------- subcommands ----------

def cmd_list(paths: Paths, _args: argparse.Namespace) -> int:
    reg = Registry.load(paths.manifests_file)
    tags = existing_tags(paths.history)
    print(f"app_id={reg.app_id} depot_id={reg.depot_id}")
    print(f"{'label':<10} {'build':<10} {'manifest':<22} {'date':<11} tagged?")
    print("-" * 70)
    for v in reg.versions:
        tag = expected_tag(v)
        marker = "yes" if tag in tags else ""
        print(f"{v.label:<10} {v.build_id or '-':<10} {v.manifest_id:<22} {v.date or '-':<11} {marker}")
    return 0


def cmd_add(paths: Paths, args: argparse.Namespace) -> int:
    reg = Registry.load(paths.manifests_file)
    v = Version(
        label=args.label,
        manifest_id=args.manifest,
        build_id=args.build,
        date=args.date,
        note=args.note,
    )
    added = reg.upsert(v)
    reg.save()
    print(f"[{'add' if added else 'update'}] {v.label} manifest={v.manifest_id} build={v.build_id or '-'}")
    return 0


def cmd_bootstrap(paths: Paths, args: argparse.Namespace) -> int:
    bootstrap_depot_downloader(paths, force=args.force)
    return 0


def cmd_fetch(paths: Paths, args: argparse.Namespace) -> int:
    reg = Registry.load(paths.manifests_file)
    v = reg.find(args.label)
    if v is None:
        raise SystemExit(f"unknown label: {args.label} (run `list` to see registered)")
    if not paths.depot_downloader_exe.exists():
        bootstrap_depot_downloader(paths)
    fetch_one(paths, reg, v, args.username, args.keep)
    return 0


def cmd_backfill(paths: Paths, args: argparse.Namespace) -> int:
    reg = Registry.load(paths.manifests_file)
    if not paths.depot_downloader_exe.exists():
        bootstrap_depot_downloader(paths)
    tags = existing_tags(paths.history)
    pending = [v for v in reg.versions if expected_tag(v) not in tags]
    if not pending:
        print("[done] no versions need backfilling")
        return 0
    print(f"[plan] backfilling {len(pending)} version(s): {', '.join(v.label for v in pending)}")
    for v in pending:
        fetch_one(paths, reg, v, args.username, args.keep)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, help="explicit path to mod_tracker.toml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show registered versions and tag status").set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="register a manifest")
    a.add_argument("label", help="version label, e.g. 0.1.1.1")
    a.add_argument("--manifest", required=True, help="Steam manifest ID from SteamDB")
    a.add_argument("--build", help="Steam build ID (used in tag name)")
    a.add_argument("--date", help="release date YYYY-MM-DD")
    a.add_argument("--note", help="free-form note")
    a.set_defaults(func=cmd_add)

    b = sub.add_parser("bootstrap", help="download DepotDownloader")
    b.add_argument("--force", action="store_true", help="redownload even if present")
    b.set_defaults(func=cmd_bootstrap)

    f = sub.add_parser("fetch", help="download + decompile + snapshot one version")
    f.add_argument("label", help="version label, e.g. 0.1.1.1")
    f.add_argument("--username", help="Steam username (DepotDownloader will prompt for password and 2FA)")
    f.add_argument("--keep", action="store_true", help="keep intermediate download/decompile dirs")
    f.set_defaults(func=cmd_fetch)

    bf = sub.add_parser("backfill", help="fetch every registered version missing a tag")
    bf.add_argument("--username", help="Steam username")
    bf.add_argument("--keep", action="store_true", help="keep intermediates")
    bf.set_defaults(func=cmd_backfill)

    args = p.parse_args()

    config_path = args.config or find_config(Path(os.getcwd()))
    if not config_path:
        raise SystemExit("could not find mod_tracker.toml — pass --config <path>")
    paths = resolve_paths(load_config(config_path), config_path)

    return args.func(paths, args)


if __name__ == "__main__":
    sys.exit(main())
