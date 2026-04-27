#!/usr/bin/env python3
"""Diff one mod-dependency between two of its upstream tags.

Reads `[[deps]]` from mod_tracker.toml, picks one (`--dep`), and produces a
text + optional HTML report of what changed in that dep's source between two
git tags. Includes:

- Files added / removed / modified
- For each changed .gd file: functions added, removed, or signature-changed
- For modified .gd files: collapsible per-file unified diffs (HTML)

Usage:
    python deps_diff.py --dep mcm --list-tags
    python deps_diff.py --dep mcm --from v2.6.0 --to v2.7.0
    python deps_diff.py --dep metro --from v3.0.0 --to v3.1.1 --output mcm_diff.html
    python deps_diff.py --dep mcm                          # latest two tags
"""

from __future__ import annotations

import argparse
import html
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
SIGNAL_RE = re.compile(r'^\s*signal\s+([A-Za-z0-9_]+)(?:\s*\(([^)]*)\))?', re.MULTILINE)


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
    status: str  # M, A, D, R
    funcs: list[FuncChange] = field(default_factory=list)
    signals: list[FuncChange] = field(default_factory=list)
    extends_changed: tuple[str, str] | None = None
    class_name_changed: tuple[str, str] | None = None
    body_only: bool = False
    diff_text: str = ""

    @property
    def has_signature_changes(self) -> bool:
        return bool(self.funcs or self.signals or self.extends_changed or self.class_name_changed)


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


def resolve_dep(config: dict, config_path: Path, name: str) -> Path:
    workspace = config_path.parent
    for d in config.get("deps", []):
        if d.get("name") == name:
            return workspace / d["path"]
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


def resolve_ref(ref: str, repo: Path) -> str:
    return run_git(["rev-parse", ref], cwd=repo).strip()


def changed_files(from_ref: str, to_ref: str, repo: Path) -> list[tuple[str, str]]:
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


def fetch_unified_diff(from_ref: str, to_ref: str, path: str, repo: Path) -> str:
    r = subprocess.run(
        ["git", "diff", "--no-color", "-U3", f"{from_ref}..{to_ref}", "--", path],
        cwd=repo, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout


# ---------- analysis ----------


def funcs_in(source: str) -> dict[str, str]:
    return {m.group(1): re.sub(r"\s+", "", m.group(2)) for m in FUNC_SIG_RE.finditer(source)}


def signals_in(source: str) -> dict[str, str]:
    return {m.group(1): re.sub(r"\s+", "", m.group(2) or "") for m in SIGNAL_RE.finditer(source)}


def first_match(pattern: re.Pattern, source: str) -> str | None:
    m = pattern.search(source)
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


def analyze_file(path: str, status: str, from_ref: str, to_ref: str, repo: Path,
                 include_diffs: bool) -> FileChange:
    fc = FileChange(path=path, status=status)
    if status in ("A", "D") or not path.endswith(".gd"):
        if include_diffs and status == "M":
            fc.diff_text = fetch_unified_diff(from_ref, to_ref, path, repo)
        return fc

    old = file_at_ref(from_ref, path, repo) or ""
    new = file_at_ref(to_ref, path, repo) or ""
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

    fc.body_only = not fc.has_signature_changes
    if include_diffs:
        fc.diff_text = fetch_unified_diff(from_ref, to_ref, path, repo)
    return fc


def analyze(from_ref: str, to_ref: str, repo: Path, include_diffs: bool) -> list[FileChange]:
    rows = changed_files(from_ref, to_ref, repo)
    return [analyze_file(p, s, from_ref, to_ref, repo, include_diffs) for s, p in sorted(rows, key=lambda r: r[1])]


# ---------- rendering ----------


def render_text(changes: list[FileChange], dep_name: str, from_ref: str, to_ref: str) -> str:
    if not changes:
        return f"{dep_name}: no changes between {from_ref} and {to_ref}\n"

    added = [c for c in changes if c.status == "A"]
    deleted = [c for c in changes if c.status == "D"]
    modified = [c for c in changes if c.status == "M"]
    sig_changes = [c for c in modified if c.has_signature_changes]

    lines = [f"Dep diff: {dep_name}  {from_ref}  ->  {to_ref}", "=" * 72]
    lines.append(
        f"\nFiles: {len(modified)} modified, {len(added)} added, {len(deleted)} deleted"
    )
    if sig_changes:
        lines.append(f"Modified .gd files with signature changes: {len(sig_changes)}")
    lines.append("")

    if added:
        lines.append("[ADDED]")
        for c in added:
            lines.append(f"  + {c.path}")
        lines.append("")

    if deleted:
        lines.append("[DELETED]")
        for c in deleted:
            lines.append(f"  - {c.path}")
        lines.append("")

    if sig_changes:
        lines.append("[FUNCTION / SIGNAL CHANGES]")
        for c in sig_changes:
            lines.append(f"  ~ {c.path}")
            if c.extends_changed:
                lines.append(f"      extends: {c.extends_changed[0]} -> {c.extends_changed[1]}")
            if c.class_name_changed:
                lines.append(f"      class_name: {c.class_name_changed[0]} -> {c.class_name_changed[1]}")
            for f in c.funcs:
                if f.kind == "added":
                    lines.append(f"      + func {f.name}({f.new_args})")
                elif f.kind == "removed":
                    lines.append(f"      - func {f.name}({f.old_args})")
                else:
                    lines.append(f"      ~ func {f.name}({f.old_args})  ->  ({f.new_args})")
            for s in c.signals:
                if s.kind == "added":
                    lines.append(f"      + signal {s.name}({s.new_args})")
                elif s.kind == "removed":
                    lines.append(f"      - signal {s.name}({s.old_args})")
                else:
                    lines.append(f"      ~ signal {s.name}({s.old_args})  ->  ({s.new_args})")
        lines.append("")

    body_only = [c for c in modified if not c.has_signature_changes]
    if body_only:
        lines.append(f"[OTHER MODIFIED] ({len(body_only)} files — body-only or non-script)")
        for c in body_only:
            lines.append(f"  . {c.path}")
        lines.append("")

    return "\n".join(lines) + "\n"


def render_html(changes: list[FileChange], dep_name: str, from_ref: str, to_ref: str) -> str:
    def esc(s: str) -> str:
        return html.escape(s)

    def render_diff(diff: str) -> str:
        lines = diff.splitlines()
        body_start = 0
        for i, ln in enumerate(lines):
            if ln.startswith("@@") or ln.startswith("+++ "):
                body_start = i
                break
        out = []
        for ln in lines[body_start:]:
            if ln.startswith("@@"):
                out.append(f'<span class="hunk">{esc(ln)}</span>')
            elif ln.startswith("+++") or ln.startswith("---"):
                out.append(f'<span class="filehdr">{esc(ln)}</span>')
            elif ln.startswith("+"):
                out.append(f'<span class="add">{esc(ln)}</span>')
            elif ln.startswith("-"):
                out.append(f'<span class="del-line">{esc(ln)}</span>')
            else:
                out.append(esc(ln))
        return "\n".join(out)

    added = [c for c in changes if c.status == "A"]
    deleted = [c for c in changes if c.status == "D"]
    modified = [c for c in changes if c.status == "M"]
    sig_changes = [c for c in modified if c.has_signature_changes]
    body_only = [c for c in modified if not c.has_signature_changes]

    sections = []

    summary = (
        f'<div class="summary">{len(modified)} modified, {len(added)} added, '
        f'{len(deleted)} deleted &nbsp;·&nbsp; '
        f'{len(sig_changes)} with signature changes</div>'
    )
    sections.append(summary)

    if added:
        sections.append('<h2 class="add">Added files</h2><ul>')
        for c in added:
            sections.append(f'<li><code>{esc(c.path)}</code></li>')
        sections.append("</ul>")

    if deleted:
        sections.append('<h2 class="del">Deleted files</h2><ul>')
        for c in deleted:
            sections.append(f'<li><code>{esc(c.path)}</code></li>')
        sections.append("</ul>")

    if sig_changes:
        sections.append('<h2 class="sig">Function / signal changes</h2>')
        for c in sig_changes:
            sections.append('<div class="file sig">')
            sections.append(f'<h3><code>{esc(c.path)}</code></h3>')
            if c.extends_changed:
                sections.append(
                    f'<div class="meta-change">extends: '
                    f'<code>{esc(c.extends_changed[0])}</code> &rarr; '
                    f'<code>{esc(c.extends_changed[1])}</code></div>'
                )
            if c.class_name_changed:
                sections.append(
                    f'<div class="meta-change">class_name: '
                    f'<code>{esc(c.class_name_changed[0])}</code> &rarr; '
                    f'<code>{esc(c.class_name_changed[1])}</code></div>'
                )
            adds = [f for f in c.funcs if f.kind == "added"]
            rems = [f for f in c.funcs if f.kind == "removed"]
            sigs = [f for f in c.funcs if f.kind == "signature_changed"]
            sig_adds = [s for s in c.signals if s.kind == "added"]
            sig_rems = [s for s in c.signals if s.kind == "removed"]
            sig_changed = [s for s in c.signals if s.kind == "signature_changed"]
            if adds:
                sections.append("<div><strong>Added funcs:</strong> " +
                                ", ".join(f'<code>{esc(f.name)}({esc(f.new_args or "")})</code>' for f in adds) + "</div>")
            if rems:
                sections.append("<div><strong>Removed funcs:</strong> " +
                                ", ".join(f'<code>{esc(f.name)}({esc(f.old_args or "")})</code>' for f in rems) + "</div>")
            if sigs:
                sections.append("<div><strong>Signature-changed funcs:</strong><ul>")
                for f in sigs:
                    sections.append(
                        f'<li><code>{esc(f.name)}({esc(f.old_args or "")})</code> &rarr; '
                        f'<code>{esc(f.name)}({esc(f.new_args or "")})</code></li>'
                    )
                sections.append("</ul></div>")
            if sig_adds:
                sections.append("<div><strong>Added signals:</strong> " +
                                ", ".join(f'<code>{esc(s.name)}({esc(s.new_args or "")})</code>' for s in sig_adds) + "</div>")
            if sig_rems:
                sections.append("<div><strong>Removed signals:</strong> " +
                                ", ".join(f'<code>{esc(s.name)}({esc(s.old_args or "")})</code>' for s in sig_rems) + "</div>")
            if sig_changed:
                sections.append("<div><strong>Signature-changed signals:</strong><ul>")
                for s in sig_changed:
                    sections.append(
                        f'<li><code>signal {esc(s.name)}({esc(s.old_args or "")})</code> &rarr; '
                        f'<code>signal {esc(s.name)}({esc(s.new_args or "")})</code></li>'
                    )
                sections.append("</ul></div>")
            if c.diff_text:
                line_count = c.diff_text.count("\n")
                sections.append(
                    f'<details class="diff"><summary>view diff ({line_count} lines)</summary>'
                    f'<pre>{render_diff(c.diff_text)}</pre></details>'
                )
            sections.append("</div>")

    if body_only:
        sections.append(f'<h2 class="body">Other modified ({len(body_only)} — body-only or non-script)</h2>')
        sections.append('<details><summary>show files</summary><ul>')
        for c in body_only:
            sections.append(f'<li><code>{esc(c.path)}</code>')
            if c.diff_text:
                ln = c.diff_text.count("\n")
                sections.append(
                    f' <details class="diff"><summary>diff ({ln} lines)</summary>'
                    f'<pre>{render_diff(c.diff_text)}</pre></details>'
                )
            sections.append("</li>")
        sections.append("</ul></details>")

    style = """
    body { font: 14px/1.5 -apple-system, system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; color: #222; }
    h1 { margin-bottom: 0.25rem; }
    .subtitle { color: #666; margin-bottom: 1rem; font-size: 13px; }
    .summary { color: #444; margin-bottom: 2rem; padding: 0.5rem 1rem; background: #f4f4f5; border-radius: 4px; }
    h2 { margin-top: 2rem; padding-bottom: 0.25rem; border-bottom: 1px solid #ddd; }
    h2.add { color: #15803d; } h2.del { color: #b91c1c; } h2.sig { color: #b91c1c; } h2.body { color: #666; }
    .file { border-left: 4px solid #ccc; padding: 0.5rem 1rem; margin: 0.75rem 0; background: #fafafa; }
    .file.sig { border-color: #ef4444; }
    .file h3 { margin: 0 0 0.5rem 0; font-size: 14px; }
    .meta-change { color: #b45309; font-size: 13px; margin: 0.2rem 0; }
    code { background: #eee; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
    ul { margin: 0.4rem 0 0.4rem 0; padding-left: 1.4rem; }
    li { margin: 0.15rem 0; }
    details.diff { margin: 0.4rem 0 0.6rem 0; }
    details.diff summary { cursor: pointer; color: #2563eb; font-size: 12px; user-select: none; }
    details.diff pre {
      background: #0f172a; color: #e2e8f0; padding: 0.75rem 1rem; border-radius: 4px;
      font: 12px/1.45 ui-monospace, "Cascadia Code", Menlo, Consolas, monospace;
      overflow-x: auto; margin: 0.4rem 0 0 0; white-space: pre;
    }
    .add { color: #4ade80; } .del-line { color: #f87171; } .hunk { color: #60a5fa; } .filehdr { color: #94a3b8; }
    """
    body = "\n".join(sections) if sections else "<p>(no changes)</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{esc(dep_name)} dep diff</title><style>{style}</style></head>
<body>
<h1>{esc(dep_name)} — dep diff</h1>
<div class="subtitle">from <code>{esc(from_ref)}</code> &nbsp;&rarr;&nbsp; to <code>{esc(to_ref)}</code></div>
{body}
</body></html>
"""


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", type=Path, help="explicit path to mod_tracker.toml")
    p.add_argument("--dep", required=True, help="dep name (e.g. mcm, metro)")
    p.add_argument("--from", dest="from_ref", help="from-ref tag (default: second-most-recent)")
    p.add_argument("--to", dest="to_ref", help="to-ref tag (default: most-recent)")
    p.add_argument("--list-tags", action="store_true", help="list known tags for the dep and exit")
    p.add_argument("--output", type=Path, help="also write HTML report to this path")
    p.add_argument(
        "--no-diffs", action="store_true",
        help="omit per-file unified diffs from HTML (lighter, no upstream source embedded)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config or find_config(Path(os.getcwd()))
    if not config_path:
        raise SystemExit("could not find mod_tracker.toml — pass --config <path>")
    config = load_config(config_path)
    repo = resolve_dep(config, config_path, args.dep)
    if not (repo / ".git").exists():
        raise SystemExit(f"{args.dep} not cloned at {repo} — run `deps_fetch sync {args.dep}` first")

    tags = list_tags(repo)
    if args.list_tags:
        for t in tags:
            print(t)
        return 0

    if not tags or len(tags) < 2:
        raise SystemExit(f"need at least 2 tags on {args.dep} to diff (have {len(tags)})")

    from_ref = args.from_ref or tags[-2]
    to_ref = args.to_ref or tags[-1]

    if resolve_ref(from_ref, repo) == resolve_ref(to_ref, repo):
        print(f"(no changes — {from_ref} and {to_ref} point to the same commit)")
        return 0

    changes = analyze(from_ref, to_ref, repo, include_diffs=not args.no_diffs)
    print(render_text(changes, args.dep, from_ref, to_ref))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_html(changes, args.dep, from_ref, to_ref), encoding="utf-8")
        print(f"[html] wrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
