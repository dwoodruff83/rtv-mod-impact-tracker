# CLAUDE.md — rtv-mod-impact-tracker

This is a **standalone, dependency-free CLI tool** for tracking decompiled Godot game scripts across patches. The public README has the user-facing docs; this file covers Claude-specific guardrails.

## Hard constraints

- **Standard library only.** No `pip` dependencies, no `requirements.txt`, no `pyproject.toml`. If asked to add one, push back first.
- **Three scripts only.** `snapshot.py`, `analyze_mods.py`, `changelog.py`. If a fourth concern emerges, consider whether it belongs in a sibling repo instead.
- **No game content ever.** This tool *consumes* decompiled scripts; it must never ship or commit them. Decompiled game code is a copyright grey zone — keep this repo clean of it.
- **Python 3.11+** is the floor (for `tomllib`). Avoid 3.12-only features without good reason.
- **Cross-platform default.** Avoid hardcoding OS-specific paths in code. The user's `mod_tracker.toml` location is the anchor for everything else.

## Conventions

- All workspace paths in code are derived from `mod_tracker.toml` (resolved relative to that file's directory). Discovery walks up from `cwd`; `--config` is the explicit override.
- Plain technical voice in code, comments, docs, and commits. **No squire persona in this repo** — that's a sibling-workspace-only convention.
- Output that goes to stdout should be UTF-8 even on Windows (each script forces this for cross-shell reliability).

## Where to test

The sibling workspace at `F:\RoadToVostokMods\` is the canonical smoke-test environment. It has:

- A populated `reference/RTV_history/` with multiple `game-v*` snapshot tags
- Three real mods in `mods/`: CatAutoFeed, PunisherGuarantee, Wallet
- `mod_tracker.toml` at the root and `.bat` wrappers for all three scripts

Smoke test:

```bash
cd F:\RoadToVostokMods
.\analyze_mods.bat --list-tags         # should list multiple game-v* tags
.\analyze_mods.bat                     # should classify the 3 mods
.\changelog.bat | head -50             # should emit Markdown
.\snapshot.bat --dry-run               # should report no changes if decompile unchanged
```

If all four work end-to-end without errors, the tool is healthy.

## Status

- MIT licensed.
- Currently a **private local repo**; will flip public when polished. Not yet pushed to any remote.
- Originally extracted from `F:\RoadToVostokMods\tools\version_tracker\` (now deleted there) on 2026-04-19.
