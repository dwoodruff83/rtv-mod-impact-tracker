# CLAUDE.md — rtv-mod-impact-tracker

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is a **standalone, dependency-free CLI tool** for tracking decompiled Godot game scripts across patches. The public README has the user-facing docs; this file covers Claude-specific guardrails.

## Hard constraints

- **Standard library only.** No `pip` dependencies, no `requirements.txt`, no `pyproject.toml`. If asked to add one, push back first.
- **Four scripts, focused responsibilities.** `snapshot.py` (capture), `analyze_mods.py` (per-mod impact diff), `changelog.py` (game-side Markdown changelog), `fetch_version.py` (Steam backfill orchestrator). A new top-level concern should be a fifth script only if it can't fit cleanly into these; otherwise consider whether it belongs in a sibling repo.
- **No game content ever.** This tool *consumes* decompiled scripts; it must never ship or commit them. Decompiled game code is a copyright grey zone — keep this repo clean of it.
- **Python 3.11+** is the floor (for `tomllib`). Avoid 3.12-only features without good reason.
- **Cross-platform default.** Avoid hardcoding OS-specific paths in code. The user's `mod_tracker.toml` location is the anchor for everything else.

## Architecture

The four scripts compose around a single shared artifact: the **history git repo** at `paths.history` (default `reference/RTV_history`). It is the diff engine — there is no separate database, index, or cache.

- **`snapshot.py` is the only writer.** It copies the current decompile in, `git add -A`, commits, and tags as `game-v<version>-build<buildid>`. That tag format is the contract every other script depends on.
- **`analyze_mods.py` and `changelog.py` are readers.** They shell out to `git diff --name-status <from>..<to>` and `git show <ref>:<path>` against the history repo. No git library — just `subprocess.run(["git", ...])`.
- **`fetch_version.py` is an orchestrator.** It does *not* re-implement snapshotting; it shells out to sibling `snapshot.py` (resolved via `Path(__file__).resolve().parent / "snapshot.py"`) after running DepotDownloader + GDRE_Tools. Keeps the snapshot logic in one place.

### Cross-script duplication to keep in sync

- **Config discovery** (`find_config` walking up from `cwd`, `load_config` reading TOML, `resolve_paths` building workspace-relative paths) is reimplemented in each script. Change them in lockstep, or extract to a shared module if a fourth call site emerges.
- **GDScript signature extraction** lives in two places: `FUNC_SIG_RE`, `EXTENDS_RE`/`CLASS_SIG_RE`, and the whitespace-normalized arg-list logic appear in both `analyze_mods.py` (used for sig-change detection on overridden files) and `changelog.py` (used for function-level changelog entries). Improvements to the regex or normalization need to land in both.
- **`take_over_path()` detection** is `analyze_mods.py`-only: handles both literal `take_over_path("res://...")` and identifier-form `take_over_path(IDENT)` where `IDENT` resolves to a same-file `const IDENT := "res://..."`. The classification is intentionally conservative (favors false positives over false negatives).

## Conventions

- All workspace paths in code are derived from `mod_tracker.toml` (resolved relative to that file's directory). Discovery walks up from `cwd`; `--config` is the explicit override.
- Plain technical voice in code, comments, docs, and commits. **No squire persona in this repo** — that's a sibling-workspace-only convention.
- Output that goes to stdout should be UTF-8 even on Windows. Scripts that print user-facing content (`analyze_mods.py`, `changelog.py`, `fetch_version.py`) re-wrap `sys.stdout`/`sys.stderr` at module load when the encoding isn't UTF-8.

## Where to test

The sibling workspace at `F:\RoadToVostokMods\` is the canonical smoke-test environment. It has:

- A populated `reference/RTV_history/` with multiple `game-v*` snapshot tags
- Three real mods in `mods/`: CatAutoFeed, PunisherGuarantee, Wallet
- `mod_tracker.toml` at the root and `.bat` wrappers for all four scripts

Smoke test:

```bash
cd F:\RoadToVostokMods
.\analyze_mods.bat --list-tags         # should list multiple game-v* tags
.\analyze_mods.bat                     # should classify the 3 mods
.\changelog.bat | head -50             # should emit Markdown
.\snapshot.bat --dry-run               # should report no changes if decompile unchanged
.\fetch_version.bat list               # should print the manifests registry
```

If all five work end-to-end without errors, the tool is healthy. The fetch_version pipeline (`fetch`/`backfill`) is heavier — it actually downloads from Steam — so don't run it as part of routine smoke-testing unless you're specifically validating that path.

## Status

- MIT licensed.
- Currently a **private local repo**; will flip public when polished. Not yet pushed to any remote.
- Originally extracted from `F:\RoadToVostokMods\tools\version_tracker\` (now deleted there) on 2026-04-19.
