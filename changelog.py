#!/usr/bin/env python3
"""Generate a Markdown changelog from the history repo's tagged snapshots.

For each consecutive pair of tags (or a specific --from/--to), emits a section
listing added/deleted/modified files and, for each modified .gd file, a
function-level breakdown: functions added, removed, or with changed signatures.

Usage:
    python changelog.py                         # full history, all tags
    python changelog.py --from <ref> --to <ref> # single transition
    python changelog.py --output CHANGELOG.md   # write to file (also stdout)
    python changelog.py --since <tag>           # everything after a given tag
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
    status: str  # M, A, D, R...
    funcs: list[FuncChange] = field(default_factory=list)
    extends_changed: tuple[str, str] | None = None
    class_name_changed: tuple[str, str] | None = None
    body_only: bool = False


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


def resolve_history(config: dict, config_path: Path) -> Path:
    return config_path.parent / config.get("paths", {}).get("history", "reference/RTV_history")


def run_git(args: list[str], cwd: Path, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True)
    return r.stdout


def list_tags(history: Path) -> list[str]:
    return [t for t in run_git(["tag", "--list", "--sort=creatordate"], cwd=history).splitlines() if t]


def commit_date(ref: str, history: Path) -> str:
    return run_git(["log", "-1", "--format=%cs", ref], cwd=history).strip()


def changed_files(from_ref: str, to_ref: str, history: Path) -> list[tuple[str, str]]:
    out = run_git(["diff", "--name-status", f"{from_ref}..{to_ref}"], cwd=history)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        rows.append((parts[0][0], parts[-1].replace("\\", "/")))
    return rows


def file_at_ref(ref: str, path: str, history: Path) -> str | None:
    r = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=history, text=True, capture_output=True,
    )
    return r.stdout if r.returncode == 0 else None


def funcs_in(source: str) -> dict[str, str]:
    return {
        m.group(1): re.sub(r"\s+", "", m.group(2))
        for m in FUNC_SIG_RE.finditer(source)
    }


def first_match(pattern: re.Pattern, source: str) -> str | None:
    m = pattern.search(source)
    return m.group(1).strip() if m else None


def diff_gd_file(path: str, from_ref: str, to_ref: str, history: Path) -> FileChange:
    old = file_at_ref(from_ref, path, history) or ""
    new = file_at_ref(to_ref, path, history) or ""

    old_funcs = funcs_in(old)
    new_funcs = funcs_in(new)

    funcs: list[FuncChange] = []
    for name in sorted(set(old_funcs) | set(new_funcs)):
        if name not in old_funcs:
            funcs.append(FuncChange(name=name, new_args=new_funcs[name]))
        elif name not in new_funcs:
            funcs.append(FuncChange(name=name, old_args=old_funcs[name]))
        elif old_funcs[name] != new_funcs[name]:
            funcs.append(FuncChange(name=name, old_args=old_funcs[name], new_args=new_funcs[name]))

    old_extends = first_match(EXTENDS_RE, old)
    new_extends = first_match(EXTENDS_RE, new)
    extends_changed = (old_extends, new_extends) if old_extends != new_extends else None

    old_class = first_match(CLASS_NAME_RE, old)
    new_class = first_match(CLASS_NAME_RE, new)
    class_name_changed = (old_class, new_class) if old_class != new_class else None

    fc = FileChange(path=path, status="M", funcs=funcs)
    fc.extends_changed = extends_changed
    fc.class_name_changed = class_name_changed
    fc.body_only = not (funcs or extends_changed or class_name_changed)
    return fc


def render_section(from_ref: str, to_ref: str, history: Path) -> str:
    rows = changed_files(from_ref, to_ref, history)
    if not rows:
        return f"## {to_ref} ← {from_ref}\n\n*No changes between these refs.*\n"

    added = [p for s, p in rows if s == "A"]
    deleted = [p for s, p in rows if s == "D"]
    modified = [p for s, p in rows if s == "M"]
    renamed = [p for s, p in rows if s == "R"]

    gd_modified = [p for p in modified if p.endswith(".gd")]
    other_modified = [p for p in modified if not p.endswith(".gd")]

    file_changes = [diff_gd_file(p, from_ref, to_ref, history) for p in sorted(gd_modified)]

    n_added_funcs = sum(1 for fc in file_changes for f in fc.funcs if f.kind == "added")
    n_removed_funcs = sum(1 for fc in file_changes for f in fc.funcs if f.kind == "removed")
    n_sig_changed = sum(1 for fc in file_changes for f in fc.funcs if f.kind == "signature_changed")

    date = commit_date(to_ref, history)

    out = []
    out.append(f"## {to_ref} ← {from_ref}")
    out.append(f"*Snapshot date: {date}*")
    out.append("")
    out.append("### Summary")
    out.append(
        f"- Files: {len(modified)} modified, {len(added)} added, "
        f"{len(deleted)} deleted{f', {len(renamed)} renamed' if renamed else ''}"
    )
    if file_changes:
        out.append(
            f"- Functions: {n_added_funcs} added, {n_removed_funcs} removed, "
            f"{n_sig_changed} signature changed (across .gd files)"
        )
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
            added_funcs = [f for f in fc.funcs if f.kind == "added"]
            removed_funcs = [f for f in fc.funcs if f.kind == "removed"]
            sig_changed = [f for f in fc.funcs if f.kind == "signature_changed"]
            if added_funcs:
                out.append(f"- Added: {', '.join(f'`{f.name}({f.new_args})`' for f in added_funcs)}")
            if removed_funcs:
                out.append(f"- Removed: {', '.join(f'`{f.name}({f.old_args})`' for f in removed_funcs)}")
            if sig_changed:
                out.append("- Signature changed:")
                for f in sig_changed:
                    out.append(f"  - `{f.name}({f.old_args})` → `{f.name}({f.new_args})`")

    if other_modified:
        out.append("")
        out.append("### Modified non-script files")
        out.append(f"<details><summary>{len(other_modified)} files (click to expand)</summary>\n")
        for p in sorted(other_modified):
            out.append(f"- `{p}`")
        out.append("</details>")
    out.append("")
    return "\n".join(out)


def render_full(tags: list[str], history: Path) -> str:
    if len(tags) < 2:
        raise SystemExit(
            f"need at least 2 snapshots to make a changelog (have {len(tags)}). "
            "Take more snapshots first."
        )
    out = ["# Game changelog (decompile-derived)\n"]
    out.append(
        f"Generated from {len(tags)} snapshots in the history repo. "
        "Most recent transition first.\n"
    )
    for i in range(len(tags) - 1, 0, -1):
        out.append(render_section(tags[i - 1], tags[i], history))
    return "\n".join(out)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, help="explicit path to mod_tracker.toml")
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
    history = resolve_history(load_config(config_path), config_path)
    if not history.exists():
        raise SystemExit(f"history repo missing at {history}")

    if args.from_ref and args.to_ref:
        text = "# Game changelog (decompile-derived)\n\n" + render_section(
            args.from_ref, args.to_ref, history
        )
    else:
        tags = list_tags(history)
        if args.since:
            if args.since not in tags:
                raise SystemExit(f"unknown --since tag: {args.since}")
            tags = tags[tags.index(args.since):]
        text = render_full(tags, history)

    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"\n[written] {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
