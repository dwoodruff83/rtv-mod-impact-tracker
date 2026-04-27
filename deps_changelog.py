#!/usr/bin/env python3
"""Generate a Markdown changelog for one mod-dependency, walking its tags.

For one dep (`--dep`) and either a single transition (`--from`/`--to`) or the
full tag history, emits a Markdown release-notes-style document covering
files added/deleted/modified and function-level changes per .gd file.

Usage:
    python deps_changelog.py --dep mcm                        # full tag history
    python deps_changelog.py --dep mcm --from v2.6.0 --to v2.7.0
    python deps_changelog.py --dep metro --since v3.0.0       # everything after v3.0.0
    python deps_changelog.py --dep mcm --output mcm_changelog.md
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

FUNC_SIG_RE = re.compile(r'^\s*func\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', re.MULTILINE)
SIGNAL_RE = re.compile(r'^\s*signal\s+([A-Za-z0-9_]+)(?:\s*\(([^)]*)\))?', re.MULTILINE)
EXTENDS_RE = re.compile(r'^\s*extends\s+(.+)$', re.MULTILINE)
CLASS_NAME_RE = re.compile(r'^\s*class_name\s+(.+)$', re.MULTILINE)


@dataclass
class FuncChange:
    name: str
    old_args: str | None = None
    new_args: str | None = None

    @property
    def kind(self) -> str:
        if self.old_args is None:
            return "added"
        if self.new_args is None:
            return "removed"
        return "signature_changed"


@dataclass
class FileChange:
    path: str
    status: str
    funcs: list[FuncChange] = field(default_factory=list)
    signals: list[FuncChange] = field(default_factory=list)
    extends_changed: tuple[str, str] | None = None
    class_name_changed: tuple[str, str] | None = None
    body_only: bool = False


# ---------- config ----------


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


def resolve_dep(config: dict, config_path: Path, name: str) -> tuple[Path, str]:
    workspace = config_path.parent
    for d in config.get("deps", []):
        if d.get("name") == name:
            return workspace / d["path"], d.get("display_name", name)
    registered = ", ".join(d.get("name", "?") for d in config.get("deps", [])) or "(none)"
    raise SystemExit(f"unknown dep: {name!r}. Registered: {registered}")


# ---------- git ----------


def run_git(args: list[str], cwd: Path, check: bool = True) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, check=check, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout


def list_tags(repo: Path) -> list[str]:
    return [t for t in run_git(["tag", "--list", "--sort=creatordate"], cwd=repo).splitlines() if t]


def commit_date(ref: str, repo: Path) -> str:
    return run_git(["log", "-1", "--format=%cs", ref], cwd=repo).strip()


def changed_paths(from_ref: str, to_ref: str, repo: Path) -> list[tuple[str, str]]:
    out = run_git(["diff", "--name-status", f"{from_ref}..{to_ref}"], cwd=repo)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        rows.append((parts[0][0], parts[-1].replace("\\", "/")))
    return rows


def file_at_ref(ref: str, path: str, repo: Path) -> str | None:
    r = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=repo, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout if r.returncode == 0 else None


# ---------- analysis ----------


def funcs_in(source: str) -> dict[str, str]:
    return {m.group(1): re.sub(r"\s+", "", m.group(2)) for m in FUNC_SIG_RE.finditer(source)}


def signals_in(source: str) -> dict[str, str]:
    return {m.group(1): re.sub(r"\s+", "", m.group(2) or "") for m in SIGNAL_RE.finditer(source)}


def first_match(p: re.Pattern, source: str) -> str | None:
    m = p.search(source)
    return m.group(1).strip() if m else None


def diff_pair(old: dict[str, str], new: dict[str, str]) -> list[FuncChange]:
    out: list[FuncChange] = []
    for name in sorted(set(old) | set(new)):
        if name not in old:
            out.append(FuncChange(name=name, new_args=new[name]))
        elif name not in new:
            out.append(FuncChange(name=name, old_args=old[name]))
        elif old[name] != new[name]:
            out.append(FuncChange(name=name, old_args=old[name], new_args=new[name]))
    return out


def diff_gd_file(path: str, from_ref: str, to_ref: str, repo: Path) -> FileChange:
    old = file_at_ref(from_ref, path, repo) or ""
    new = file_at_ref(to_ref, path, repo) or ""
    fc = FileChange(path=path, status="M")
    fc.funcs = diff_pair(funcs_in(old), funcs_in(new))
    fc.signals = diff_pair(signals_in(old), signals_in(new))
    old_extends = first_match(EXTENDS_RE, old)
    new_extends = first_match(EXTENDS_RE, new)
    if old_extends != new_extends:
        fc.extends_changed = (old_extends or "", new_extends or "")
    old_class = first_match(CLASS_NAME_RE, old)
    new_class = first_match(CLASS_NAME_RE, new)
    if old_class != new_class:
        fc.class_name_changed = (old_class or "", new_class or "")
    fc.body_only = not (fc.funcs or fc.signals or fc.extends_changed or fc.class_name_changed)
    return fc


# ---------- rendering ----------


def render_section(from_ref: str, to_ref: str, repo: Path) -> str:
    rows = changed_paths(from_ref, to_ref, repo)
    if not rows:
        return f"## {to_ref} ← {from_ref}\n\n*No changes between these refs.*\n"

    added = [p for s, p in rows if s == "A"]
    deleted = [p for s, p in rows if s == "D"]
    modified = [p for s, p in rows if s == "M"]
    renamed = [p for s, p in rows if s == "R"]

    gd_modified = sorted(p for p in modified if p.endswith(".gd"))
    other_modified = sorted(p for p in modified if not p.endswith(".gd"))

    file_changes = [diff_gd_file(p, from_ref, to_ref, repo) for p in gd_modified]

    n_added = sum(1 for fc in file_changes for f in fc.funcs if f.kind == "added")
    n_removed = sum(1 for fc in file_changes for f in fc.funcs if f.kind == "removed")
    n_sig = sum(1 for fc in file_changes for f in fc.funcs if f.kind == "signature_changed")
    n_sig_added = sum(1 for fc in file_changes for s in fc.signals if s.kind == "added")
    n_sig_removed = sum(1 for fc in file_changes for s in fc.signals if s.kind == "removed")

    date = commit_date(to_ref, repo)

    out = []
    out.append(f"## {to_ref} ← {from_ref}")
    out.append(f"*Tag date: {date}*")
    out.append("")
    out.append("### Summary")
    out.append(
        f"- Files: {len(modified)} modified, {len(added)} added, "
        f"{len(deleted)} deleted{f', {len(renamed)} renamed' if renamed else ''}"
    )
    if file_changes:
        out.append(
            f"- Functions: {n_added} added, {n_removed} removed, {n_sig} signature changed"
        )
    if n_sig_added or n_sig_removed:
        out.append(f"- Signals: {n_sig_added} added, {n_sig_removed} removed")
    out.append("")

    if added:
        out.append("### Added files")
        for p in sorted(added):
            out.append(f"- `{p}`")
        out.append("")

    if deleted:
        out.append("### Deleted files")
        for p in sorted(deleted):
            out.append(f"- `{p}`")
        out.append("")

    if file_changes:
        out.append("### Modified scripts")
        for fc in file_changes:
            out.append(f"\n#### `{fc.path}`")
            if fc.body_only:
                out.append("- Body changes only (no signature, `extends`, or `class_name` changes).")
                continue
            if fc.extends_changed:
                old_e, new_e = fc.extends_changed
                out.append(f"- `extends`: `{old_e}` → `{new_e}`")
            if fc.class_name_changed:
                old_c, new_c = fc.class_name_changed
                out.append(f"- `class_name`: `{old_c}` → `{new_c}`")
            adds = [f for f in fc.funcs if f.kind == "added"]
            rems = [f for f in fc.funcs if f.kind == "removed"]
            sigs = [f for f in fc.funcs if f.kind == "signature_changed"]
            sig_adds = [s for s in fc.signals if s.kind == "added"]
            sig_rems = [s for s in fc.signals if s.kind == "removed"]
            sig_changed = [s for s in fc.signals if s.kind == "signature_changed"]
            if adds:
                out.append("- Added: " + ", ".join(f"`{f.name}({f.new_args})`" for f in adds))
            if rems:
                out.append("- Removed: " + ", ".join(f"`{f.name}({f.old_args})`" for f in rems))
            if sigs:
                out.append("- Signature changed:")
                for f in sigs:
                    out.append(f"  - `{f.name}({f.old_args})` → `{f.name}({f.new_args})`")
            if sig_adds:
                out.append("- Signal added: " + ", ".join(f"`{s.name}({s.new_args})`" for s in sig_adds))
            if sig_rems:
                out.append("- Signal removed: " + ", ".join(f"`{s.name}({s.old_args})`" for s in sig_rems))
            if sig_changed:
                out.append("- Signal signature changed:")
                for s in sig_changed:
                    out.append(f"  - `{s.name}({s.old_args})` → `{s.name}({s.new_args})`")

    if other_modified:
        out.append("")
        out.append("### Modified non-script files")
        out.append(f"<details><summary>{len(other_modified)} files (click to expand)</summary>\n")
        for p in other_modified:
            out.append(f"- `{p}`")
        out.append("</details>")

    out.append("")
    return "\n".join(out)


def render_full(tags: list[str], repo: Path, dep_display: str) -> str:
    if len(tags) < 2:
        raise SystemExit(
            f"need at least 2 tags to make a changelog (have {len(tags)})."
        )
    out = [f"# {dep_display} changelog (upstream-derived)\n"]
    out.append(
        f"Generated from {len(tags)} tags in the upstream repo. Most recent transition first.\n"
    )
    for i in range(len(tags) - 1, 0, -1):
        out.append(render_section(tags[i - 1], tags[i], repo))
    return "\n".join(out)


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", type=Path, help="explicit path to mod_tracker.toml")
    p.add_argument("--dep", required=True, help="dep name (e.g. mcm, metro)")
    p.add_argument("--from", dest="from_ref", help="from-ref for a single-section render")
    p.add_argument("--to", dest="to_ref", help="to-ref for a single-section render")
    p.add_argument("--since", help="only include transitions after this tag")
    p.add_argument("--output", type=Path, help="write to this file (also prints to stdout)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config or find_config(Path(os.getcwd()))
    if not config_path:
        raise SystemExit("could not find mod_tracker.toml — pass --config <path>")
    config = load_config(config_path)
    repo, display = resolve_dep(config, config_path, args.dep)
    if not (repo / ".git").exists():
        raise SystemExit(f"{args.dep} not cloned at {repo} — run `deps_fetch sync {args.dep}` first")

    if args.from_ref and args.to_ref:
        text = f"# {display} changelog (upstream-derived)\n\n" + render_section(
            args.from_ref, args.to_ref, repo
        )
    else:
        tags = list_tags(repo)
        if args.since:
            if args.since not in tags:
                raise SystemExit(f"unknown --since tag: {args.since}")
            tags = tags[tags.index(args.since):]
        text = render_full(tags, repo, display)

    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"\n[written] {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
