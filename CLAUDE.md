# CLAUDE.md — rtv-mod-impact-tracker

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is a **standalone, dependency-free CLI tool** for tracking decompiled Godot game scripts across patches AND for tracking the upstream source of mod-dependency repos (mod loaders, MCM-style frameworks, registries) so mod authors can see what changed before each release. The public README has the user-facing docs; this file covers Claude-specific guardrails.

## Hard constraints

- **Standard library only.** No `pip` dependencies, no `requirements.txt`, no `pyproject.toml`. If asked to add one, push back first.
- **Eight scripts, two families, focused responsibilities.**
  - **Game tracking** (Steam-sourced; uses parallel `*_history` git repo because upstream isn't a git repo): `snapshot.py` (capture decompile into history), `analyze_mods.py` (per-mod impact diff), `changelog.py` (game-side Markdown changelog), `fetch_version.py` (Steam backfill orchestrator).
  - **Dep tracking** (GitHub-sourced; uses upstream's own tags via local mirror clones): `deps_fetch.py` (sync mirror clones), `deps_diff.py` (HTML+text diff between two upstream tags), `deps_audit.py` (cross-references dep changes against mods' call sites), `deps_changelog.py` (Markdown release notes per dep).
  - A new top-level concern should be a ninth script only if it can't fit cleanly into these; otherwise consider whether it belongs in a sibling repo.
- **No game content ever.** This tool *consumes* decompiled scripts; it must never ship or commit them. Decompiled game code is a copyright grey zone — keep this repo clean of it.
- **No upstream source mirrored into this repo either.** The deps mirror clones live in the *user's* workspace under `reference/<DepName>_source/`, not here.
- **Python 3.11+** is the floor (for `tomllib`). Avoid 3.12-only features without good reason.
- **Cross-platform default.** Avoid hardcoding OS-specific paths in code. The user's `mod_tracker.toml` location is the anchor for everything else.

## Architecture

The eight scripts compose around two artifacts:

1. **The game history git repo** at `paths.history` (default `reference/RTV_history`) — written exclusively by `snapshot.py`, read by `analyze_mods.py` and `changelog.py`. Tag format `game-v<version>-build<buildid>` is the contract.
2. **Per-dep mirror clones** at `[[deps]].path` (e.g. `reference/MetroModLoader_source`) — written exclusively by `deps_fetch.py` (`git clone` / `git fetch --tags`), read by the other deps scripts. Tags come straight from upstream; we don't re-tag.

There is no separate database, index, or cache. Git is the diff engine for both families.

### Script-level notes

- **`snapshot.py` is the only writer to game history.** Copies the current decompile in, `git add -A`, commits, and tags. That tag format is the contract every other game-tracking script depends on.
- **`analyze_mods.py` / `changelog.py`** shell out to `git diff --name-status <from>..<to>` and `git show <ref>:<path>` against the game history repo. No git library — just `subprocess.run(["git", ...])`.
- **`fetch_version.py` is an orchestrator.** It does *not* re-implement snapshotting; it shells out to sibling `snapshot.py` (resolved via `Path(__file__).resolve().parent / "snapshot.py"`) after running DepotDownloader + GDRE_Tools. Keeps the snapshot logic in one place.
- **`deps_fetch.py` is the only writer to dep mirrors.** Clones missing repos with `--no-checkout`, fetches tags on existing ones with `--force`. Other deps scripts assume the mirror is current.
- **`deps_diff.py`, `deps_audit.py`, `deps_changelog.py`** all consume one mirror clone at a time, indexed by the `--dep <name>` flag (matching a `[[deps]] name=` entry in `mod_tracker.toml`).

### Cross-script duplication to keep in sync

- **Config discovery** (`find_config` walking up from `cwd`, `load_config` reading TOML, `resolve_paths` building workspace-relative paths) is reimplemented in each script. Change them in lockstep, or extract to a shared module if churn becomes painful.
- **GDScript signature extraction** lives in multiple places: `FUNC_SIG_RE`, `SIGNAL_RE`, `EXTENDS_RE`/`CLASS_SIG_RE`, and the whitespace-normalized arg-list logic appear in `analyze_mods.py`, `changelog.py`, `deps_diff.py`, `deps_audit.py`, and `deps_changelog.py`. Improvements to the regex or normalization need to land in all of them.
- **`take_over_path()` detection** is `analyze_mods.py`-only: handles both literal `take_over_path("res://...")` and identifier-form `take_over_path(IDENT)` where `IDENT` resolves to a same-file `const IDENT := "res://..."`. Conservative classification (favors false positives over false negatives).
- **UTF-8 forcing in subprocess calls.** Every `subprocess.run` reading git output passes `encoding="utf-8", errors="replace"` to avoid Windows cp1252 decode failures on `.tscn` and similar mixed-binary files. Don't drop this.

## Conventions

- All workspace paths in code are derived from `mod_tracker.toml` (resolved relative to that file's directory). Discovery walks up from `cwd`; `--config` is the explicit override.
- Plain technical voice in code, comments, docs, and commits.
- Output that goes to stdout should be UTF-8 even on Windows. User-facing scripts re-wrap `sys.stdout`/`sys.stderr` at module load when the encoding isn't UTF-8.

## Smoke test guidance

A working test workspace needs:

- A populated history repo with at least 2 `game-v*` snapshot tags
- One or more real mods in `mods/` (each with a `mod.txt`)
- `mod_tracker.toml` at the workspace root
- Optionally: at least one `[[deps]]` entry with the dep already cloned, so the deps_* scripts have something to operate on

Minimum smoke check, after `cd`-ing into such a workspace:

```bash
python <repo>/snapshot.py --dry-run
python <repo>/analyze_mods.py --list-tags
python <repo>/changelog.py | head -50
python <repo>/fetch_version.py list
python <repo>/deps_fetch.py list
python <repo>/deps_diff.py --dep <name> --list-tags
python <repo>/deps_audit.py --dep <name>
python <repo>/deps_changelog.py --dep <name>
```

If all run without errors, the tool is healthy. The `fetch_version.py fetch`/`backfill` paths actually download from Steam — don't run them as part of routine smoke-testing unless validating that path.

## Status

- MIT licensed.
- Designed primarily for Road to Vostok modding but the analysis is generic — works for any Godot game whose `.pck` can be decompiled (snapshot/analyze_mods/changelog/fetch_version) and any GitHub-hosted mod-dependency repo with semver tags (deps_*).
