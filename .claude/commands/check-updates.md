---
description: Check tracked mod-deps and the game itself for updates not yet captured locally
allowed-tools: Bash, Read, Glob, Grep
---

Check for updates across everything rtv-mod-impact-tracker tracks. The user wants a concise status report — no analysis or remediation unless something's actually new.

## Setup

Discover paths via `mod_tracker.toml` walk-up from the cwd (same convention every script in this tool uses). Required fields:

- `[[deps]]` array — each entry has `name`, `path` (mirror clone, workspace-relative), `repo` (upstream URL).
- `[paths] history` (default `reference/RTV_history`) — the game history repo.
- `[steam] app_id` — for locating `appmanifest_<app_id>.acf`. Default Steam install on Windows is `C:\Program Files (x86)\Steam\steamapps`; override via `[steam] install_root`.

If no `mod_tracker.toml` is reachable from cwd, stop and tell the user to `cd` into a workspace that has one.

**Locating the tracker scripts:** the canonical version of this command lives in the rtv-mod-impact-tracker repo at `.claude/commands/check-updates.md`. Resolve `deps_fetch.py` via, in order of preference:
1. `git -C <cwd> rev-parse --show-toplevel` if the cwd happens to be inside the tracker repo.
2. A `deps_fetch` / `deps_fetch.bat` wrapper on PATH.
3. Ask the user where their tracker checkout lives.

## Step 1 — deps

For each `[[deps]]` entry:

1. Capture pre-fetch baseline (skip silently if the mirror isn't cloned yet — `deps_fetch sync` will clone it):
   - Latest tag: `git -C <dep.path> tag --list --sort=creatordate | tail -1`
   - Default-branch tip: `git -C <dep.path> log -1 --format='%h %ci' origin/master 2>/dev/null || git -C <dep.path> log -1 --format='%h %ci' origin/main`

2. Sync: `python <tracker-repo>/deps_fetch.py sync`

3. Re-capture state with the same two commands. Classify:
   - 🟢 no new tags AND default-branch tip unchanged
   - 🟡 default-branch tip moved but no new release tag (interesting context, not actionable for the diff scripts)
   - 🔴 a new release tag landed — this is what `deps_diff` / `deps_audit` / `deps_changelog` operate on

## Step 2 — game

1. Read `appmanifest_<app_id>.acf`, extract buildid via regex `"buildid"\s+"(\d+)"`.
2. List `game-v*-build*` tags in the history repo: `git -C <history> tag --list 'game-v*'`.
3. Parse buildids out of those tag names (last `\d+` segment). Compare:
   - 🟢 the local Steam buildid matches some existing tag (game is up-to-date in our history) — note that creator-date order ≠ version order if the user has backfilled, so this is a set-membership check, not a "find latest" check.
   - 🔴 the local buildid is NOT in the set — user should re-decompile and run `snapshot.py`. (If the appmanifest is missing entirely, report 🟡 with "Steam appmanifest not found at expected path — game tracking can't be checked from this machine.")

## Output

A single compact Markdown table:

| Track | Status | Detail |
|------|--------|--------|
| MCM (or whichever deps are registered) | 🟢/🟡/🔴 | latest tag · default-branch tip · what's new |
| Metro | 🟢/🟡/🔴 | (same) |
| Game | 🟢/🟡/🔴 | local Steam build · matching/missing tag |

Follow with ONE line:
- If everything is 🟢: "Nothing actionable."
- Otherwise, name the concrete next command — e.g. `python <tracker>/deps_diff.py --dep metro --from <prev-tag> --to <new-tag> --output diff.html`, or "re-decompile the new build and run `snapshot.py`."

Don't speculate beyond what the data shows. Don't analyze the diffs themselves — that's `deps_audit` / `analyze_mods` territory, not this command.
