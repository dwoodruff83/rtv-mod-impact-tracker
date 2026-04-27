#!/usr/bin/env python3
"""Cross-reference dep changes against your mods' call sites.

For one dep and a tag pair, walks the dep's source at both tags to find:
- functions removed
- functions whose signature changed
- functions added (new surface available — informational, not a break)

Then walks every .gd file under your `mods/` directory to find method calls
(`.method_name(`). For each call site whose method name matches a
removed-or-changed name, the mod is flagged 🔴 broken. If it only matches an
added name (you happen to call something that didn't exist in the from-tag),
that's 🟡 review (likely a coincidence, not actually a break).

Heuristic and conservative
--------------------------
This is a *name match*, not a type-aware analysis. False positives are
expected: if you have a local method `apply_from_config()` and the dep also
exposes one with that name, both will be reported. Read each hit with that
in mind. Constants, autoload paths, and class_name resolution aren't tracked.

Usage:
    python deps_audit.py --dep mcm --from v2.6.0 --to v2.7.0
    python deps_audit.py --dep mcm                    # latest two tags
    python deps_audit.py --dep mcm --output mcm_audit.html
    python deps_audit.py --dep mcm --include-added    # also flag uses of new APIs
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

FUNC_DEF_RE = re.compile(r'^\s*func\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', re.MULTILINE)
SIGNAL_DEF_RE = re.compile(r'^\s*signal\s+([A-Za-z0-9_]+)(?:\s*\(([^)]*)\))?', re.MULTILINE)
# Method calls: ".method_name(" — captures the name. Skips the leading dot
# so we catch `obj.foo(` and `Loader.foo(` alike.
METHOD_CALL_RE = re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)\s*\(')


@dataclass
class ApiChange:
    name: str
    kind: str  # "added", "removed", "signature_changed"
    old_args: str | None = None
    new_args: str | None = None
    where: str = ""  # file path inside the dep where the symbol lives (best-effort)


@dataclass
class CallSite:
    file: Path
    line: int
    text: str  # the line content
    method: str
    api_change: ApiChange | None = None


@dataclass
class ModHit:
    mod_id: str
    mod_dir: Path
    broken: list[CallSite] = field(default_factory=list)
    review: list[CallSite] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.broken:
            return "broken"
        if self.review:
            return "review"
        return "safe"

    @property
    def status_icon(self) -> str:
        return {"safe": "🟢", "review": "🟡", "broken": "🔴"}[self.status]


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


def resolve_dep_repo(config: dict, config_path: Path, name: str) -> Path:
    workspace = config_path.parent
    for d in config.get("deps", []):
        if d.get("name") == name:
            return workspace / d["path"]
    registered = ", ".join(d.get("name", "?") for d in config.get("deps", [])) or "(none)"
    raise SystemExit(f"unknown dep: {name!r}. Registered: {registered}")


def resolve_mods_dir(config: dict, config_path: Path) -> Path:
    return config_path.parent / config.get("paths", {}).get("mods", "mods")


# ---------- git ----------


def run_git(args: list[str], cwd: Path, check: bool = True) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, check=check, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout


def list_tags(repo: Path) -> list[str]:
    return [t for t in run_git(["tag", "--list", "--sort=creatordate"], cwd=repo).splitlines() if t]


def gd_files_at_ref(ref: str, repo: Path) -> list[str]:
    out = run_git(["ls-tree", "-r", "--name-only", ref], cwd=repo)
    return [p.replace("\\", "/") for p in out.splitlines() if p.endswith(".gd")]


def file_at_ref(ref: str, path: str, repo: Path) -> str | None:
    r = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=repo, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout if r.returncode == 0 else None


# ---------- dep API extraction ----------


def collect_api_at_ref(ref: str, repo: Path) -> dict[str, tuple[str, str]]:
    """Returns {name: (args, source_path)} for every func and signal defined at ref."""
    api: dict[str, tuple[str, str]] = {}
    for path in gd_files_at_ref(ref, repo):
        src = file_at_ref(ref, path, repo) or ""
        for m in FUNC_DEF_RE.finditer(src):
            name = m.group(1)
            args = re.sub(r"\s+", "", m.group(2))
            # Take the first definition we see; ignore later collisions
            api.setdefault(name, (args, path))
        for m in SIGNAL_DEF_RE.finditer(src):
            name = m.group(1)
            args = re.sub(r"\s+", "", m.group(2) or "")
            api.setdefault(name, (args, path))
    return api


def diff_apis(old_api: dict[str, tuple[str, str]], new_api: dict[str, tuple[str, str]]) -> list[ApiChange]:
    changes: list[ApiChange] = []
    for name in sorted(set(old_api) | set(new_api)):
        if name in old_api and name not in new_api:
            args, where = old_api[name]
            changes.append(ApiChange(name=name, kind="removed", old_args=args, where=where))
        elif name in new_api and name not in old_api:
            args, where = new_api[name]
            changes.append(ApiChange(name=name, kind="added", new_args=args, where=where))
        else:
            old_args, _ = old_api[name]
            new_args, where = new_api[name]
            if old_args != new_args:
                changes.append(ApiChange(
                    name=name, kind="signature_changed",
                    old_args=old_args, new_args=new_args, where=where,
                ))
    return changes


# ---------- mod call-site scan ----------


def scan_mod_calls(mods_dir: Path) -> dict[str, list[CallSite]]:
    """{method_name: [CallSite, ...]} for every `.method(` site under mods/."""
    hits: dict[str, list[CallSite]] = {}
    if not mods_dir.exists():
        return hits
    for mod_dir in sorted(mods_dir.iterdir()):
        if not mod_dir.is_dir():
            continue
        for gd in mod_dir.rglob("*.gd"):
            try:
                lines = gd.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                # Skip comment-only matches by stripping after '#'
                effective = line.split("#", 1)[0]
                for m in METHOD_CALL_RE.finditer(effective):
                    name = m.group(1)
                    hits.setdefault(name, []).append(CallSite(
                        file=gd, line=i, text=line.rstrip(), method=name,
                    ))
    return hits


def mod_id_for(call: CallSite, mods_dir: Path) -> str:
    """Walk up from a call site to find the mod root (direct child of mods/)."""
    rel = call.file.resolve().relative_to(mods_dir.resolve())
    return rel.parts[0]


# ---------- analysis ----------


def audit(
    repo: Path, mods_dir: Path, from_ref: str, to_ref: str, include_added: bool
) -> tuple[list[ApiChange], list[ModHit]]:
    old_api = collect_api_at_ref(from_ref, repo)
    new_api = collect_api_at_ref(to_ref, repo)
    api_changes = diff_apis(old_api, new_api)

    breaking_names = {c.name: c for c in api_changes if c.kind in ("removed", "signature_changed")}
    added_names = {c.name: c for c in api_changes if c.kind == "added"}

    call_index = scan_mod_calls(mods_dir)
    mods: dict[str, ModHit] = {}

    for name, sites in call_index.items():
        if name in breaking_names:
            change = breaking_names[name]
            for s in sites:
                s.api_change = change
                mod = mod_id_for(s, mods_dir)
                hit = mods.setdefault(mod, ModHit(mod_id=mod, mod_dir=mods_dir / mod))
                hit.broken.append(s)
        elif include_added and name in added_names:
            change = added_names[name]
            for s in sites:
                s.api_change = change
                mod = mod_id_for(s, mods_dir)
                hit = mods.setdefault(mod, ModHit(mod_id=mod, mod_dir=mods_dir / mod))
                hit.review.append(s)

    # Include mods with zero hits as 🟢 safe
    if mods_dir.exists():
        for d in sorted(mods_dir.iterdir()):
            if d.is_dir() and (d / "mod.txt").exists() and d.name not in mods:
                mods[d.name] = ModHit(mod_id=d.name, mod_dir=d)

    return api_changes, sorted(mods.values(), key=lambda m: (m.status != "broken", m.status != "review", m.mod_id))


# ---------- rendering ----------


def render_text(api_changes: list[ApiChange], mods: list[ModHit],
                dep_name: str, from_ref: str, to_ref: str) -> str:
    breaking = [c for c in api_changes if c.kind in ("removed", "signature_changed")]
    added = [c for c in api_changes if c.kind == "added"]

    lines = [f"Dep audit: {dep_name}  {from_ref}  ->  {to_ref}", "=" * 72]
    lines.append(
        f"\nDep API changes: {len(breaking)} breaking, {len(added)} added"
    )
    if breaking:
        lines.append("\n[BREAKING API CHANGES]")
        for c in breaking:
            if c.kind == "removed":
                lines.append(f"  - {c.name}({c.old_args})  removed  [{c.where}]")
            else:
                lines.append(f"  ~ {c.name}({c.old_args})  ->  ({c.new_args})  [{c.where}]")
    lines.append("")

    buckets = {"broken": [], "review": [], "safe": []}
    for m in mods:
        buckets[m.status].append(m)

    for bucket in ("broken", "review", "safe"):
        if not buckets[bucket]:
            continue
        lines.append(f"[{bucket.upper()}]")
        for m in buckets[bucket]:
            count = len(m.broken) + len(m.review)
            suffix = f"  ({count} call sites)" if count else ""
            lines.append(f"  {m.status_icon} {m.mod_id}{suffix}")
            for s in m.broken:
                lines.append(
                    f"      [BROKEN] {s.file.name}:{s.line}  "
                    f".{s.method}(...)  -> {s.api_change.kind if s.api_change else '?'}"
                )
            for s in m.review:
                lines.append(
                    f"      [review] {s.file.name}:{s.line}  "
                    f".{s.method}(...)  -> uses new API"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def render_html(api_changes: list[ApiChange], mods: list[ModHit],
                dep_name: str, from_ref: str, to_ref: str) -> str:
    def esc(s: str) -> str:
        return html.escape(s)

    breaking = [c for c in api_changes if c.kind in ("removed", "signature_changed")]
    added = [c for c in api_changes if c.kind == "added"]

    out = []
    out.append(
        f'<div class="summary">{len(breaking)} breaking dep changes, '
        f'{len(added)} added &nbsp;·&nbsp; '
        f'{sum(1 for m in mods if m.status == "broken")} mods broken, '
        f'{sum(1 for m in mods if m.status == "review")} review, '
        f'{sum(1 for m in mods if m.status == "safe")} safe</div>'
    )

    if breaking:
        out.append('<h2 class="broken">Breaking dep changes</h2><ul>')
        for c in breaking:
            if c.kind == "removed":
                out.append(
                    f'<li class="del"><code>{esc(c.name)}({esc(c.old_args or "")})</code> '
                    f'removed <span class="path">[{esc(c.where)}]</span></li>'
                )
            else:
                out.append(
                    f'<li class="sig"><code>{esc(c.name)}({esc(c.old_args or "")})</code> &rarr; '
                    f'<code>{esc(c.name)}({esc(c.new_args or "")})</code> '
                    f'<span class="path">[{esc(c.where)}]</span></li>'
                )
        out.append("</ul>")

    if added:
        out.append('<h2 class="added">New APIs available</h2>')
        out.append('<details><summary>show {} added</summary><ul>'.format(len(added)))
        for c in added:
            out.append(
                f'<li><code>{esc(c.name)}({esc(c.new_args or "")})</code> '
                f'<span class="path">[{esc(c.where)}]</span></li>'
            )
        out.append("</ul></details>")

    for bucket, label in [("broken", "Broken"), ("review", "Review needed"), ("safe", "Safe")]:
        in_bucket = [m for m in mods if m.status == bucket]
        if not in_bucket:
            continue
        out.append(f'<h2 class="{bucket}">{label} ({len(in_bucket)})</h2>')
        for m in in_bucket:
            count = len(m.broken) + len(m.review)
            count_str = f' &middot; <span class="count">{count} call sites</span>' if count else ''
            out.append(f'<div class="mod {bucket}">')
            out.append(f'<h3>{m.status_icon} {esc(m.mod_id)}{count_str}</h3>')
            if m.broken or m.review:
                out.append("<ul>")
                for s in m.broken:
                    api = s.api_change
                    detail = ""
                    if api and api.kind == "signature_changed":
                        detail = f' <span class="api-detail">({esc(api.old_args or "")} &rarr; {esc(api.new_args or "")})</span>'
                    elif api and api.kind == "removed":
                        detail = ' <span class="api-detail">(removed)</span>'
                    out.append(
                        f'<li class="broken"><code>.{esc(s.method)}(...)</code>{detail} '
                        f'<span class="path">{esc(str(s.file.name))}:{s.line}</span><br>'
                        f'<pre class="callsite">{esc(s.text)}</pre></li>'
                    )
                for s in m.review:
                    out.append(
                        f'<li class="review"><code>.{esc(s.method)}(...)</code> '
                        f'<span class="api-detail">(new API)</span> '
                        f'<span class="path">{esc(str(s.file.name))}:{s.line}</span></li>'
                    )
                out.append("</ul>")
            out.append("</div>")

    style = """
    body { font: 14px/1.5 -apple-system, system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; color: #222; }
    h1 { margin-bottom: 0.25rem; }
    .subtitle { color: #666; margin-bottom: 1rem; font-size: 13px; }
    .summary { color: #444; margin-bottom: 2rem; padding: 0.5rem 1rem; background: #f4f4f5; border-radius: 4px; }
    h2 { margin-top: 2rem; padding-bottom: 0.25rem; border-bottom: 1px solid #ddd; }
    h2.broken { color: #b91c1c; } h2.review { color: #a16207; } h2.safe { color: #15803d; } h2.added { color: #2563eb; }
    .mod { border-left: 4px solid #ccc; padding: 0.5rem 1rem; margin: 0.75rem 0; background: #fafafa; }
    .mod.broken { border-color: #ef4444; } .mod.review { border-color: #eab308; } .mod.safe { border-color: #22c55e; }
    .mod h3 { margin: 0; font-size: 14px; }
    .count { color: #666; font-weight: normal; font-size: 12px; }
    code { background: #eee; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
    ul { margin: 0.4rem 0 0.4rem 0; padding-left: 1.4rem; }
    li { margin: 0.4rem 0; }
    li.broken { color: #991b1b; }
    li.review { color: #92400e; }
    li.del code, li.sig code { color: #991b1b; }
    .path { color: #888; font-size: 11px; font-family: ui-monospace, monospace; }
    .api-detail { color: #666; font-size: 12px; }
    pre.callsite {
      background: #0f172a; color: #e2e8f0; padding: 0.4rem 0.75rem; border-radius: 3px;
      font: 11px/1.4 ui-monospace, "Cascadia Code", Menlo, Consolas, monospace;
      margin: 0.25rem 0 0 0; white-space: pre; overflow-x: auto;
    }
    """
    body = "\n".join(out) if out else "<p>(no changes detected)</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{esc(dep_name)} dep audit</title><style>{style}</style></head>
<body>
<h1>{esc(dep_name)} — dep audit</h1>
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
        "--include-added", action="store_true",
        help="also flag mods using newly-added APIs (review-level — usually a coincidence)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config or find_config(Path(os.getcwd()))
    if not config_path:
        raise SystemExit("could not find mod_tracker.toml — pass --config <path>")
    config = load_config(config_path)
    repo = resolve_dep_repo(config, config_path, args.dep)
    mods_dir = resolve_mods_dir(config, config_path)

    if not (repo / ".git").exists():
        raise SystemExit(f"{args.dep} not cloned at {repo} — run `deps_fetch sync {args.dep}` first")
    if not mods_dir.exists():
        raise SystemExit(f"mods dir missing at {mods_dir}")

    tags = list_tags(repo)
    if args.list_tags:
        for t in tags:
            print(t)
        return 0

    if not tags or len(tags) < 2:
        raise SystemExit(f"need at least 2 tags on {args.dep} to audit (have {len(tags)})")

    from_ref = args.from_ref or tags[-2]
    to_ref = args.to_ref or tags[-1]

    api_changes, mods = audit(repo, mods_dir, from_ref, to_ref, args.include_added)
    print(render_text(api_changes, mods, args.dep, from_ref, to_ref))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            render_html(api_changes, mods, args.dep, from_ref, to_ref), encoding="utf-8"
        )
        print(f"[html] wrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
