# rtv-mod-impact-tracker

**Track decompiled Godot game scripts across patches and tell which of your mods will break.**

Built primarily for [Road to Vostok](https://store.steampowered.com/app/1963610/) modding, but the analysis is generic — it works for any Godot game that uses `take_over_path()`-style script overrides and ships via Steam.

---

## The problem this solves

You've made a Road to Vostok mod that overrides `res://Scripts/Police.gd` to make boss spawns more reliable. The game gets patched. Now what?

- Did `Police.gd` change?
- If yes — did the function signatures your override depends on change, or just the bodies?
- Did the game add/remove any files that affect your other mods?
- Multiply this by every mod you maintain, every patch.

Without tooling, you find out by launching the game and watching it crash. With this tool, you find out from a Markdown report in 5 seconds.

---

## What you get

Four small Python scripts, each focused on one job:

| Script | What it does |
|--------|-------------|
| **`snapshot.py`** | Captures the current decompiled scripts into a git history repo, tagged with the game version + Steam build id. Run after each game patch. |
| **`analyze_mods.py`** | Walks your `mods/` folder, finds every `take_over_path()` call, diffs those overridden files between two snapshots, and classifies each mod as 🟢 safe / 🟡 review-needed / 🔴 broken. HTML output embeds collapsible per-file unified diffs (color-coded); use `--no-diffs` for sharing-safe reports. |
| **`changelog.py`** | Walks consecutive snapshot tags and emits a Markdown changelog of game-side changes — added/deleted/renamed files, function-level breakdowns of every modified script. Pastes cleanly into release notes. |
| **`fetch_version.py`** | Downloads a specific historical Steam build via DepotDownloader, decompiles it with GDRE_Tools, and snapshots it — all in one shot. Backfill old game versions you missed; reproduce any past patch from a manifest ID. Subcommands: `list`, `add`, `bootstrap`, `fetch`, `backfill`. |

The git repo *is* the diff engine, so you can also browse changes directly with `git log`, `git diff`, or VS Code's git UI on the history folder.

---

## Prerequisites

| Requirement | Version | How to get |
|------------|---------|------------|
| Python | 3.11+ (for `tomllib`) | https://www.python.org/downloads/ |
| Git | any recent version | https://git-scm.com/downloads |
| A Godot decompiler | n/a | [GDRE Tools](https://github.com/bruvzg/gdsdecomp) recommended |
| The game itself | own copy on Steam | (you already have this) |
| DepotDownloader | optional, only for `fetch_version.py` | auto-installed by `fetch_version.py bootstrap` |

No `pip install`. No third-party Python packages. Standard library only.

---

## Quickstart

A typical first run takes about five minutes after you have the prerequisites.

### 1. Decompile the game

Use [GDRE Tools](https://github.com/bruvzg/gdsdecomp). Either GUI (point it at `RTV.pck`, click "Recover Project") or CLI:

```bash
gdre_tools.exe --headless \
  --recover="C:\Program Files (x86)\Steam\steamapps\common\Road to Vostok\RTV.pck" \
  --output="C:\my-rtv-modding\reference\RTV_decompiled" \
  --scripts-only
```

`--scripts-only` keeps the output to the readable GDScript files you care about (instead of the full ~5 GB extraction).

### 2. Clone this repo

```bash
git clone https://github.com/<you>/rtv-mod-impact-tracker.git C:\rtv-mod-impact-tracker
```

### 3. Set up your modding workspace

Your modding workspace should look something like this:

```
C:\my-rtv-modding\
├── mod_tracker.toml           ← config you'll create next
├── mods/
│   ├── MyMod1/
│   └── MyMod2/
└── reference/
    ├── RTV_decompiled/        ← what GDRE just produced
    └── RTV_history/           ← will be created by snapshot.py
```

Create `mod_tracker.toml` at the workspace root by copying the example:

```toml
# mod_tracker.toml
[paths]
decompiled = "reference/RTV_decompiled"
history    = "reference/RTV_history"
mods       = "mods"

[steam]
app_id = 1963610   # Road to Vostok (full game). Use 2141300 for the Demo.

[snapshot]
exclude_toplevel = ["mods", ".godot", "gdre_export.log"]
```

All paths are relative to the directory the config lives in.

### 4. Take your first snapshot

From anywhere inside your workspace:

```bash
python C:\rtv-mod-impact-tracker\snapshot.py
```

You should see something like:

```
config:  C:\my-rtv-modding\mod_tracker.toml
workspace: C:\my-rtv-modding
[init] created C:\my-rtv-modding\reference\RTV_history as a git repo
version: 0.1.0.0
buildid: 22674175
[copy]   Scripts
[copy]   Resources
... (etc)
[commit] Game v0.1.0.0, build 22674175 (captured 2026-04-19 23:18 UTC)
[tag]    game-v0.1.0.0-build22674175

[done] snapshot committed and tagged as game-v0.1.0.0-build22674175
```

That's it — you have a baseline.

### 5. After the next game patch

Re-run GDRE to refresh `reference/RTV_decompiled`, then:

```bash
python C:\rtv-mod-impact-tracker\snapshot.py
python C:\rtv-mod-impact-tracker\analyze_mods.py --output report.html
python C:\rtv-mod-impact-tracker\changelog.py --output CHANGELOG.md
```

You now have:
- A new tagged snapshot in `reference/RTV_history/`
- An HTML report telling you which mods broke
- A Markdown changelog of every game-side change in this patch

---

## Optional: convenience wrappers

If you don't want to type the full path every time, drop one-line wrapper scripts at your workspace root.

**Windows (`.bat`):**
```bat
:: snapshot.bat
@python C:\rtv-mod-impact-tracker\snapshot.py %*

:: analyze_mods.bat
@python C:\rtv-mod-impact-tracker\analyze_mods.py %*

:: changelog.bat
@python C:\rtv-mod-impact-tracker\changelog.py %*

:: fetch_version.bat
@python C:\rtv-mod-impact-tracker\fetch_version.py %*
```

**macOS / Linux (`.sh`):**
```bash
#!/usr/bin/env bash
exec python ~/rtv-mod-impact-tracker/snapshot.py "$@"
```

After that, the daily commands become just `snapshot`, `analyze_mods`, `changelog`, `fetch_version`.

---

## Full command reference

### `snapshot.py`

Captures the current state of `reference/RTV_decompiled/` into the history repo.

```
python snapshot.py [options]
```

| Option | Effect |
|--------|--------|
| (no args) | Auto-detects version + buildid, syncs, commits, tags |
| `--label VERSION` | Override version label (default: read from `project.godot`) |
| `--build BUILDID` | Override Steam buildid (default: read from `appmanifest_<app_id>.acf`) |
| `--message TEXT` | Override the auto-generated commit message |
| `--dry-run` | Print planned actions, write nothing |
| `--init` | Initialize the history repo if it doesn't exist (also auto-runs on first snapshot) |
| `--config PATH` | Use a specific `mod_tracker.toml` (default: walk up from cwd) |

### `analyze_mods.py`

Diffs two snapshots and classifies mod impact.

```
python analyze_mods.py [--from REF] [--to REF] [options]
```

| Option | Effect |
|--------|--------|
| `--from REF` | From-ref (tag, branch, commit). Default: second-most-recent tag |
| `--to REF` | To-ref. Default: most-recent tag (or `HEAD` if `--from` given) |
| `--list-tags` | List all snapshot tags and exit |
| `--output PATH` | Write an HTML report to this path (in addition to stdout) |
| `--no-diffs` | Omit per-file unified diffs from the HTML (lighter file, no decompiled source embedded — useful for sharing reports) |
| `--config PATH` | Use a specific `mod_tracker.toml` |

**Example output (text):**
```
Mod impact: game-v0.1.0.0-build22674175  ->  game-v0.1.1.3-build22913400
========================================================================

[REVIEW]
  🟡 CatAutoFeed  (overrides: 1)
      - [M] res://Scripts/Database.gd  (body changed)
  🟡 PunisherGuarantee  (overrides: 1)
      - [M] res://Scripts/Police.gd  (body changed)

[SAFE]
  🟢 Wallet  (overrides: 0)
```

### `changelog.py`

Generates a Markdown changelog of game-side changes.

```
python changelog.py [options]
```

| Option | Effect |
|--------|--------|
| (no args) | Full changelog: every transition between consecutive tags |
| `--from REF --to REF` | Single-section changelog for one transition |
| `--since TAG` | Only include transitions after this tag |
| `--output PATH` | Write to file (also prints to stdout) |
| `--config PATH` | Use a specific `mod_tracker.toml` |

**Example output snippet:**
```markdown
## game-v0.1.1.1-build22906957 ← game-v0.1.0.0-build22674175
*Snapshot date: 2026-04-25*

### Summary
- Files: 242 modified, 22 added, 2 deleted, 1 renamed
- Functions: 8 added, 8 removed, 1 signature changed (across .gd files)

### Added files
- `Items/Medical/Gum/Gum.tres`
- `Loot/Custom/LT_Punisher_01.tres`
- `Shaders/Sharpen.gdshader`
...

### Modified scripts

#### `Scripts/AISpawner.gd`
- Added: `Initialize()`

#### `Scripts/Police.gd`
- Signature changed:
  - `Hit(damage)` → `Hit(damage, source)`
```

### `fetch_version.py`

Pulls a specific historical Steam build, decompiles it, and snapshots it.

```
python fetch_version.py <subcommand> [options]
```

| Subcommand | Effect |
|-----------|--------|
| `list` | Show all registered manifests and which already have snapshot tags |
| `add LABEL --manifest ID` | Register a manifest. Optional: `--build`, `--date`, `--note` |
| `bootstrap` | Download DepotDownloader (one-time setup; auto-runs if needed) |
| `fetch LABEL` | Pull, decompile, and snapshot one registered version. Optional: `--username`, `--keep` |
| `backfill` | Run `fetch` for every registered version that doesn't have a tag yet |

The manifests registry is a JSON file (default `manifests.json` at workspace root), with this shape:

```json
{
  "app_id": 1963610,
  "depot_id": 1963611,
  "versions": [
    {
      "label": "0.1.0.0",
      "build_id": "22674175",
      "manifest_id": "1669269531586957312",
      "date": "2026-04-07",
      "note": "Early Access Launch"
    }
  ]
}
```

Manifest IDs come from [SteamDB](https://steamdb.info/) — copy from your browser. SteamDB blocks automated requests, so registration is manual; everything else is automatic.

---

## Configuration reference

Every field in `mod_tracker.toml`:

```toml
[paths]
# All paths are relative to the directory mod_tracker.toml lives in.
decompiled = "reference/RTV_decompiled"   # output of GDRE Tools — your working copy
history    = "reference/RTV_history"      # the snapshot git repo (created by snapshot.py)
mods       = "mods"                        # where your mod source folders live

[steam]
app_id = 1963610            # Steam app ID. RTV full = 1963610, RTV demo = 2141300.
# install_root is auto-detected on Windows from the standard Steam path.
# Override here if Steam lives elsewhere:
# install_root = "D:/Steam/steamapps"

[snapshot]
# Top-level entries inside `decompiled` to skip when capturing.
exclude_toplevel = ["mods", ".godot", "gdre_export.log"]

# Optional. Only needed if you use fetch_version.py.
# All paths are workspace-relative.
# [fetch_version]
# manifests_file       = "manifests.json"
# gdre_exe             = "tools/GDRE_tools/gdre_tools.exe"
# depot_downloader_exe = "tools/DepotDownloader/DepotDownloader.exe"
# scratch_dir          = "tools/_versions"
```

The tool finds this file by walking up from your current working directory, so you can run commands from any subfolder of the workspace.

---

## How it works

### Snapshotting

`snapshot.py` reads your decompile, copies it into the history repo (excluding the configured top-level entries), `git add -A`s, commits, and tags. The history repo is just a regular git repo — nothing magical. You can browse it with VS Code's git UI, run `git log`, `git diff`, or push it to a private GitHub repo for backup.

Tag format: `game-v<version>-build<buildid>`, e.g. `game-v0.1.0.0-build22674175`.

### Mod-impact classification

`analyze_mods.py` walks every directory under `mods/`. For each mod:

1. Reads `mod.txt` to extract autoloads.
2. Scans every `.gd` file in the mod for:
   - `take_over_path("res://...")` literal calls
   - `take_over_path(IDENTIFIER)` calls where `IDENTIFIER` resolves to a `const IDENT := "res://..."` in the same file
3. For each overridden game-side path, runs `git diff --name-status <from>..<to>` to see if it changed.
4. For changed files, parses the *signatures* at both refs and compares.

A signature is:

- Function name + argument list (whitespace-normalized)
- `extends` declaration
- `class_name` declaration

If any signature changes, or if the file was deleted, the mod is flagged **broken**. If the file changed but signatures held, **review**. Otherwise **safe**.

The heuristic is intentionally conservative — it favors false positives (flagging safe things as broken) over false negatives (telling you something is safe when it isn't).

### Changelog

`changelog.py` walks all snapshot tags in chronological order and emits a Markdown section per consecutive pair. For each `.gd` file that changed, it computes function-level diffs (added, removed, signature-changed) using the same signature-extraction logic as `analyze_mods.py`. Non-script files are listed under a collapsed `<details>` block.

---

## What this tool does *not* do

- **Decompile the game.** Use [GDRE Tools](https://github.com/bruvzg/gdsdecomp). This tool consumes its output.
- **Ship game scripts.** The history repo is created locally on your machine from your own decompile and stays there. Do not push it to a public repo — decompiled game content is a copyright grey zone.
- **Generate migration patches.** It tells you *what* changed in the game scripts your override depends on, not *how* to adapt your override. That's still your job.
- **Detect logic-level breakage.** A function whose signature is unchanged but whose internal logic now violates assumptions your override depends on will be flagged 🟡 review, not 🔴 broken. Read the body diff to be sure.

---

## Troubleshooting

**"could not find mod_tracker.toml"** — You're running the script from a directory that has no `mod_tracker.toml` in it or any parent. Either `cd` into your workspace, or pass `--config /path/to/mod_tracker.toml` explicitly.

**"could not detect version from project.godot"** — The decompile didn't preserve `config/version` in `project.godot`, or that file doesn't exist where the config points. Pass `--label X.Y.Z` to override.

**"buildid: (not found)"** — Either the Steam app ID is wrong in your config, the appmanifest doesn't exist (game not installed via Steam?), or Steam lives somewhere non-standard. Either fix `[steam].app_id`, set `[steam].install_root`, or pass `--build NNN` explicitly. The snapshot will still work without a buildid — it just falls back to a `game-v<version>` tag.

**Unicode errors on Windows** — The scripts force UTF-8 on stdout, but if you're piping through tools that don't handle UTF-8 you may see garbled output. Redirect to a file with `--output` instead.

**"only one snapshot exists — nothing to diff against"** — You haven't taken a second snapshot yet. Run `snapshot.py` again after the next game patch.

---

## Contributing

Issues and PRs welcome. The codebase is intentionally small and dependency-free; please keep it that way. Three scripts, no plugins.

If you adapt this for a different Godot game, an example config in `examples/` would be appreciated.

---

## Acknowledgements

Built collaboratively with [Claude Code](https://claude.com/claude-code) (Anthropic). The design (using git as the diff engine, the safe/review/broken classification, the `const`-resolution heuristic, the function-level changelog) emerged from a planning conversation; Claude wrote the bulk of the implementation.

The Road to Vostok modding community on [VostokMods](https://github.com/Ryhon0/VostokMods) and [ModWorkshop](https://modworkshop.net/mod/49779) provided the context that made this useful.

---

## License

[MIT](LICENSE) — do whatever you want with this, just don't blame anyone if it eats your saves.
