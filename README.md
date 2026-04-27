# rtv-mod-impact-tracker

[![ModWorkshop](https://img.shields.io/badge/ModWorkshop-56405-orange)](https://modworkshop.net/mod/56405)

**Tell which of your Godot-game mods will break before you launch the game — and track the upstream libraries you depend on for breaking changes between releases.**

Built primarily for [Road to Vostok](https://store.steampowered.com/app/1963610/) modding, but the analysis is generic. The game-tracking pipeline (`snapshot.py` / `analyze_mods.py` / `changelog.py` / `fetch_version.py`) works for **any Godot game that uses `take_over_path()`-style script overrides and ships via Steam**. The dep-tracking pipeline (`deps_*.py`) works for **any GitHub-hosted upstream with semver tags** — mod loaders, config-menu frameworks, content registries, etc. Add an entry per upstream in `mod_tracker.toml` and the tool handles the rest.

---

## The problems this solves

**Problem 1 — game patches breaking your mods.** You override `res://Scripts/Police.gd` to make boss spawns more reliable. The game gets patched. Did `Police.gd` change? Did the function signatures your override depends on change, or just the bodies? Multiply this by every mod you maintain, every patch.

Without tooling, you find out by launching the game and watching it crash. With this tool, you find out from an HTML report in 5 seconds.

**Problem 2 — upstream library updates breaking your mods.** Your mod depends on a popular mod loader or a config-menu framework. The author cuts a new version. Did any of the API methods your mod calls change signature or get removed? What new APIs are now available that you could simplify your code with?

Without tooling, you find out by reading every release commit by hand or by users reporting bugs. With this tool, you point `deps_audit.py` at the new tag and get a punch list.

---

## What you get

Eight small Python scripts split into two families:

**Game tracking** — for the host game you're modding. Steam-sourced; uses a parallel `*_history` git repo because the upstream isn't a git repo.

| Script | What it does |
|--------|-------------|
| **`snapshot.py`** | Captures the current decompiled scripts into a git history repo, tagged with the game version + Steam build id. Run after each game patch. |
| **`analyze_mods.py`** | Walks your `mods/` folder, finds every `take_over_path()` call, diffs those overridden files between two snapshots, and classifies each mod as 🟢 safe / 🟡 review-needed / 🔴 broken. HTML output embeds collapsible per-file unified diffs (color-coded); use `--no-diffs` for sharing-safe reports. |
| **`changelog.py`** | Walks consecutive snapshot tags and emits a Markdown changelog of game-side changes — added/deleted/renamed files, function-level breakdowns of every modified script. Pastes cleanly into release notes. |
| **`fetch_version.py`** | Downloads a specific historical Steam build via DepotDownloader, decompiles it with GDRE_Tools, and snapshots it — all in one shot. Backfill old game versions you missed; reproduce any past patch from a manifest ID. Subcommands: `list`, `add`, `bootstrap`, `fetch`, `backfill`. |

**Dependency tracking** — for upstream libraries your mods depend on (mod loader, config menu framework, item registry, etc.). GitHub-sourced; uses upstream's own tags directly via local mirror clones, so no parallel history repo.

| Script | What it does |
|--------|-------------|
| **`deps_fetch.py`** | Manages local mirror clones of upstream dep repos. `deps_fetch sync` clones missing ones, fetches new tags on existing ones. Other subcommands: `list`, `tags <name>`, `add`. |
| **`deps_diff.py`** | Diffs one dep between two of its tags. Reports added/removed/modified files and per-file function/signal signature changes. Same HTML rendering as `analyze_mods.py` (color-coded per-file diffs, collapsible). |
| **`deps_audit.py`** | Cross-references dep changes against your mods' call sites. Walks the dep at both tags to find removed-or-changed function names, scans every `.gd` under `mods/` for matching `.method(` calls, classifies each mod as 🟢 safe / 🟡 review / 🔴 broken. Heuristic (name match, not type-aware). |
| **`deps_changelog.py`** | Walks consecutive dep tags and emits Markdown release notes — same shape as `changelog.py` but per-dep. |

The git repos *are* the diff engine, so you can also browse changes directly with `git log`, `git diff`, or VS Code's git UI — on either the game-history folder or the dep mirror clones.

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

## Two workflows

There are two ways to populate your snapshot history:

- **Simple (manual):** decompile the game with GDRE after each patch, then run `snapshot.py`. This is what most modders will use day-to-day. **You only need Python, Git, and GDRE Tools.**
- **Advanced (automated backfill):** use `fetch_version.py` to pull *any* historical Steam build, decompile it, and snapshot it in one shot. Useful if you want to backfill old game versions you missed. Requires DepotDownloader (auto-installed) and a Steam account that owns the game.

The Quickstart below covers the simple path. Skip to the [`fetch_version.py`](#fetch_versionpy) reference if you want the automated flow.

---

## Quickstart

A typical first run takes about five minutes after you have the prerequisites.

### 1. Install and run GDRE Tools (decompile the game)

GDRE Tools is a separate project that converts Godot `.pck` files back to readable GDScript. You'll run it once per game patch.

1. Download the latest release from https://github.com/bruvzg/gdsdecomp/releases (Windows users grab the zip).
2. Extract somewhere stable, e.g. `C:\modding-tools\GDRE_tools\`.
3. Run it on the game's PCK. Either via GUI (launch `gdre_tools.exe`, point it at `RTV.pck`, click "Recover Project") or via CLI:

```bash
C:\modding-tools\GDRE_tools\gdre_tools.exe --headless ^
  --recover="C:\Program Files (x86)\Steam\steamapps\common\Road to Vostok\RTV.pck" ^
  --output="C:\my-rtv-modding\reference\RTV_decompiled" ^
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

Each time the game updates, run these four steps in order:

1. **Re-decompile** — point GDRE at the new `RTV.pck` and overwrite `reference/RTV_decompiled` (same command as Quickstart §1).
2. **Snapshot** the new state:
   ```bash
   python C:\rtv-mod-impact-tracker\snapshot.py
   ```
3. **Analyze** which of your mods are affected:
   ```bash
   python C:\rtv-mod-impact-tracker\analyze_mods.py --output report.html
   ```
4. **Generate a changelog** of game-side changes (optional but useful):
   ```bash
   python C:\rtv-mod-impact-tracker\changelog.py --output CHANGELOG.md
   ```

You now have:
- A new tagged snapshot in `reference/RTV_history/`
- An HTML report telling you which mods broke
- A Markdown changelog of every game-side change in this patch

⚠️ **The re-decompile is mandatory.** `snapshot.py` reads from `reference/RTV_decompiled`; if you skip step 1, you'll re-snapshot the previous version under a new tag.

### 6. (Optional) Track upstream mod dependencies

If your mod depends on other mods (a mod loader, a config-menu framework, an item registry, etc.) and those mods publish source on GitHub with semver tags, declare them in `mod_tracker.toml` under `[[deps]]`:

```toml
[[deps]]
name           = "metro"                                  # short id used on CLI
display_name   = "Metro Mod Loader"
repo           = "https://github.com/<owner>/<repo>"
path           = "reference/MetroModLoader_source"        # workspace-relative clone path
modworkshop_id = 55623                                    # optional cross-ref
```

Then:

```bash
python C:\rtv-mod-impact-tracker\deps_fetch.py sync       # clone everything
python C:\rtv-mod-impact-tracker\deps_diff.py --dep metro --output metro_diff.html
python C:\rtv-mod-impact-tracker\deps_audit.py --dep metro --output metro_audit.html
```

`deps_audit.py` is the headline value: it cross-references every signature change in the dep against your mods' `.method(` call sites and tells you which of your mods are broken vs. safe.

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

:: deps_fetch.bat / deps_diff.bat / deps_audit.bat / deps_changelog.bat
@python C:\rtv-mod-impact-tracker\deps_fetch.py %*
@python C:\rtv-mod-impact-tracker\deps_diff.py %*
@python C:\rtv-mod-impact-tracker\deps_audit.py %*
@python C:\rtv-mod-impact-tracker\deps_changelog.py %*
```

**macOS / Linux (`.sh`):**
```bash
#!/usr/bin/env bash
exec python ~/rtv-mod-impact-tracker/snapshot.py "$@"
```

After that, the daily commands become just `snapshot`, `analyze_mods`, `changelog`, `fetch_version`, `deps_fetch`, `deps_diff`, `deps_audit`, `deps_changelog`.

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
  🟡 MyDatabaseMod  (overrides: 1)
      - [M] res://Scripts/Database.gd  (body changed)
  🟡 MyPoliceTweak  (overrides: 1)
      - [M] res://Scripts/Police.gd  (body changed)

[SAFE]
  🟢 MyUiMod  (overrides: 0)
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

#### Steam authentication

`fetch fetch <label>` and `fetch backfill` both call DepotDownloader, which needs to log in to Steam to download paid games:

- **First run**: pass `--username <your-steam-login>`. DepotDownloader will prompt for your password and Steam Guard 2FA code in the terminal.
- **Subsequent runs**: the session token is cached in DepotDownloader's `.DepotDownloader` subdirectory (Steam keeps these alive for weeks), so re-running with the same `--username` typically skips the password and 2FA prompts.
- **Anonymous downloads**: not supported for paid games. You must own the game on the Steam account you use.

If you don't pass `--username`, DepotDownloader will fail with an authentication error.

---

### `deps_fetch.py`

Manages local mirror clones of upstream dep repos.

```
python deps_fetch.py <subcommand>
```

| Subcommand | Effect |
|-----------|--------|
| `list` | Show all registered deps and clone status (tag count, latest tag, path) |
| `sync [name]` | Clone (if missing) or `git fetch --tags --force` (if present). Pass `name` to sync one dep, omit for all |
| `tags <name>` | List every tag known on a dep clone, sorted by creation date |
| `add <name> --repo URL --path REL [...]` | Append a new `[[deps]]` entry to `mod_tracker.toml`. Optional: `--display-name`, `--modworkshop-id` |

### `deps_diff.py`

Diffs one dep between two of its tags.

```
python deps_diff.py --dep NAME [--from REF] [--to REF] [options]
```

| Option | Effect |
|--------|--------|
| `--dep NAME` | Required. Dep id from `mod_tracker.toml`'s `[[deps]]` array (e.g. `mcm`, `metro`) |
| `--from REF` | From-ref tag. Default: second-most-recent tag |
| `--to REF` | To-ref tag. Default: most-recent tag |
| `--list-tags` | List tags on the dep clone and exit |
| `--output PATH` | Write HTML report to this path |
| `--no-diffs` | Omit per-file unified diffs from HTML (lighter, no upstream source embedded) |

### `deps_audit.py`

Cross-references dep changes against your mods' call sites. Conservative heuristic: a dep function whose signature changed or was removed flags every `.func_name(` call in your mods that matches by name. False positives are expected — read each hit with that in mind.

```
python deps_audit.py --dep NAME [--from REF] [--to REF] [options]
```

| Option | Effect |
|--------|--------|
| `--dep NAME` | Required. Dep id from `[[deps]]` |
| `--from REF` / `--to REF` | Tag pair (defaults: second-most-recent and most-recent) |
| `--list-tags` | List tags on the dep clone and exit |
| `--output PATH` | Write HTML report to this path |
| `--include-added` | Also flag mods that call methods which only exist in `--to` (treat as 🟡 review). Off by default since most matches are name coincidences |

### `deps_changelog.py`

Generates a Markdown changelog for one dep, walking its tags.

```
python deps_changelog.py --dep NAME [options]
```

| Option | Effect |
|--------|--------|
| `--dep NAME` | Required. Dep id from `[[deps]]` |
| (no `--from`/`--to`) | Full changelog: every transition between consecutive tags |
| `--from REF --to REF` | Single-section changelog for one transition |
| `--since TAG` | Only include transitions after this tag |
| `--output PATH` | Write to file (also prints to stdout) |

### Dep-tracking workflow

```bash
# 1. Register the upstreams (or edit mod_tracker.toml directly)
python deps_fetch.py add metro \
  --repo https://github.com/<author>/<loader-repo> \
  --path reference/MetroModLoader_source \
  --display-name "Metro Mod Loader" --modworkshop-id 55623

# 2. Clone everything
python deps_fetch.py sync

# 3. See what tags exist
python deps_fetch.py tags mcm

# 4. After upstream releases a new version: refresh
python deps_fetch.py sync

# 5. See what changed and what it breaks
python deps_diff.py --dep mcm --output mcm_diff.html
python deps_audit.py --dep mcm --output mcm_audit.html

# 6. Generate release-note-style summary
python deps_changelog.py --dep mcm --since v2.6.0 --output mcm_changelog.md
```

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

# Optional. Only needed if you use deps_*.py. Each entry is one upstream
# dependency repo. Add as many as you have deps to track.
# [[deps]]
# name           = "metro"                                       # short id used on CLI
# display_name   = "Metro Mod Loader"                            # human label
# repo           = "https://github.com/owner/repo"               # upstream git URL
# path           = "reference/MetroModLoader_source"             # workspace-relative clone path
# modworkshop_id = 55623                                         # optional cross-ref
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
- **Mirror upstream dep source into this tool's own repo.** Dep mirror clones live in *your* workspace under `reference/<DepName>_source/`, gitignored. They're regenerable via `deps_fetch sync`.
- **Generate migration patches.** It tells you *what* changed in the game scripts (or dep APIs) your code depends on, not *how* to adapt. That's still your job.
- **Detect logic-level breakage.** A function whose signature is unchanged but whose internal logic now violates assumptions your override depends on will be flagged 🟡 review, not 🔴 broken. Read the body diff to be sure.
- **Disambiguate dep API name collisions.** `deps_audit.py` matches by method name (`.foo(`) — if your mod has a local `foo()` and the dep also has one, both will be flagged. False positives are by design (conservative); read each hit with that in mind.

---

## Legal and ethical use

This tool is community modding tooling, similar in shape to xEdit (Bethesda games), MCP (Minecraft), DayZ Tools (Bohemia), or SMAPI (Stardew Valley). It exists to help mod authors keep their work compatible with game patches and upstream library updates.

**The boundaries this tool operates within:**

- **You must own the game.** Snapshotting requires you to first decompile your own copy of the game. `fetch_version.py` calls Steam (via DepotDownloader) using your own credentials and only works for games on your account.
- **Decompilation happens via [GDRE Tools](https://github.com/bruvzg/gdsdecomp), a separate project.** This tool consumes the output; it does not perform decompilation itself, ship a decompiler, or work around any DRM.
- **No game content is bundled or distributed by this repo.** The history repo, the decompile, and the dep mirror clones all live on your local filesystem. They are gitignored by the example workspace `.gitignore` and the README explicitly warns against pushing them to public repositories.
- **No telemetry, no calls home, no third-party services.** The tool runs locally. The only network access is `git fetch`/`git clone` against the public GitHub upstream URLs you put in `mod_tracker.toml`, plus DepotDownloader against Steam (only if you opt into `fetch_version.py fetch`).
- **MIT licensed.** Use it, fork it, ship it. No restrictions beyond the standard MIT terms.

**If you're a game developer reading this:** this tool is built to help your modding community ship higher-quality, more compatible mods. It does not redistribute your code or assets. If you'd nonetheless prefer it not exist, [open an issue]() on this repo and the maintainer will work with you on a takedown — modders don't want to fight the people whose games they love.

---

## Troubleshooting

**"could not find mod_tracker.toml"** — You're running the script from a directory that has no `mod_tracker.toml` in it or any parent. Either `cd` into your workspace, or pass `--config /path/to/mod_tracker.toml` explicitly.

**"could not detect version from project.godot"** — The decompile didn't preserve `config/version` in `project.godot`, or that file doesn't exist where the config points. Pass `--label X.Y.Z` to override.

**"buildid: (not found)"** — Either the Steam app ID is wrong in your config, the appmanifest doesn't exist (game not installed via Steam?), or Steam lives somewhere non-standard. Either fix `[steam].app_id`, set `[steam].install_root`, or pass `--build NNN` explicitly. The snapshot will still work without a buildid — it just falls back to a `game-v<version>` tag.

**Unicode errors on Windows** — The scripts force UTF-8 on stdout, but if you're piping through tools that don't handle UTF-8 you may see garbled output. Redirect to a file with `--output` instead.

**"only one snapshot exists — nothing to diff against"** — You haven't taken a second snapshot yet. Run `snapshot.py` again after the next game patch.

---

## Contributing

Issues and PRs welcome. The codebase is intentionally small and dependency-free; please keep it that way. Eight scripts (four game-tracking, four dep-tracking), no plugins, no `pip install`.

If you adapt this for a different Godot game, an example config in `examples/` would be appreciated.

---

## Acknowledgements

Built collaboratively with [Claude Code](https://claude.com/claude-code) (Anthropic). The design (using git as the diff engine, the safe/review/broken classification, the `const`-resolution heuristic, the function-level changelog) emerged from a planning conversation; Claude wrote the bulk of the implementation.

The Road to Vostok modding community on [VostokMods](https://github.com/Ryhon0/VostokMods) and [ModWorkshop](https://modworkshop.net/mod/49779) provided the context that made this useful.

---

## License

[MIT](LICENSE) — do whatever you want with this, just don't blame anyone if it eats your saves.
