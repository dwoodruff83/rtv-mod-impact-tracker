# rtv-mod-impact-tracker

A tiny Python tool that tracks decompiled Godot game scripts across patches and tells you which of your mods will break.

Built primarily for [Road to Vostok](https://store.steampowered.com/app/1963610/) modding, but the analysis is generic — it works for any Godot game that uses `take_over_path()`-style script overrides and ships via Steam.

## What it does

When the game gets a patch and you re-decompile it, the tool:

1. Snapshots the new decompiled scripts into a git history repo, tagged with the game version + Steam build id.
2. Walks your `mods/` folder, parses each mod's `take_over_path()` calls (string-literal *and* `const`-referenced paths) and `mod.txt` autoloads.
3. Diffs the overridden files between the previous snapshot and the new one.
4. Classifies each mod:
   - 🟢 **safe** — overridden files weren't touched
   - 🟡 **review** — overridden file body changed but function signatures held; the override probably still works but is worth reading
   - 🔴 **broken** — overridden file was deleted, or its function signatures, `extends`, or `class_name` lines changed; the override almost certainly needs updating

The git repo *is* the diff engine, so you can also browse changes directly with `git log`, `git diff`, or VS Code's git UI.

## Requirements

- Python 3.11 or newer (for `tomllib`)
- Git
- A decompiler that produces readable GDScript (e.g. [GDRE Tools](https://github.com/bruvzg/gdsdecomp))

## Install

Clone this repo somewhere convenient:

```bash
git clone https://github.com/<your-user>/rtv-mod-impact-tracker.git
```

No `pip install` needed — the scripts are standalone and only use the standard library.

## Setup

Drop a `mod_tracker.toml` in the root of your modding workspace. Use `examples/road-to-vostok.toml` as a starting point:

```toml
[paths]
decompiled = "reference/RTV_decompiled"
history    = "reference/RTV_history"
mods       = "mods"

[steam]
app_id = 1963610   # Road to Vostok full game

[snapshot]
exclude_toplevel = ["mods", ".godot", "gdre_export.log"]
```

All paths are relative to the directory the `mod_tracker.toml` lives in.

A typical workspace layout:

```
my-rtv-modding/
├── mod_tracker.toml             ← config you just created
├── mods/                        ← your mod source folders
│   ├── MyMod1/
│   └── MyMod2/
└── reference/
    ├── RTV_decompiled/          ← GDRE output (your working copy)
    └── RTV_history/             ← created by snapshot.py
```

## Usage

The tool finds `mod_tracker.toml` by walking up from your current working directory, so run it from anywhere inside your workspace.

### Capture a snapshot when the game gets patched

```bash
# After re-running GDRE against the new RTV.pck, capture a new snapshot:
python /path/to/rtv-mod-impact-tracker/snapshot.py
```

This auto-detects:
- The game version from `<decompiled>/project.godot` (`config/version=...`)
- The Steam build id from `appmanifest_<app_id>.acf`

It commits the new state to the history repo and tags it `game-v<version>-build<buildid>`.

### See which mods broke

```bash
python /path/to/rtv-mod-impact-tracker/analyze_mods.py \
  --from game-v0.1.0.0-build22674175 \
  --to HEAD \
  --output report.html
```

If you don't pass `--from`, the tool uses the second-most-recent tag and compares it to the most-recent. Pass `--list-tags` to see what's available.

### Useful flags

```bash
# Preview what snapshot.py would do without writing anything
python snapshot.py --dry-run

# Override version detection (e.g. when re-snapshotting an older decompile)
python snapshot.py --label 0.1.0.0 --build 22674175

# Initialize the history repo explicitly (also runs on first snapshot.py if missing)
python snapshot.py --init

# Use a config file outside the cwd hierarchy
python snapshot.py --config /path/to/some/mod_tracker.toml
```

## Convenience wrappers

If you don't want to type the full path every time, drop a one-line `.bat` (Windows) or shell script in your workspace:

```bat
:: snapshot.bat
@python F:\rtv-mod-impact-tracker\snapshot.py %*
```

```bash
# snapshot.sh
#!/usr/bin/env bash
exec python ~/rtv-mod-impact-tracker/snapshot.py "$@"
```

## How signature-change detection works

`analyze_mods.py` reads each overridden file at both refs and compares:

- Function names + argument lists (whitespace-normalized)
- `class_name` declarations
- `extends` declarations

If any of those change, the file is flagged **broken**. Body-only edits (logic changes inside functions, comment edits, formatting) are flagged **review** — the override will probably still load, but you should skim the diff to make sure the new body doesn't violate assumptions your override depends on.

This heuristic is intentionally conservative. False positives (review/broken when actually fine) are preferred over false negatives (safe when actually broken).

## What this tool does not do

- **It does not decompile the game.** Run [GDRE Tools](https://github.com/bruvzg/gdsdecomp) against your own legitimate copy of the game first, then point the tool at the output.
- **It does not ship game scripts.** The history repo is created locally on your machine from your own decompile and stays there.
- **It does not generate migration patches.** It tells you *what* changed, not *how* to adapt your override. That's still your job (for now).

## Acknowledgements

Built collaboratively with [Claude Code](https://claude.com/claude-code) (Anthropic). The design (using git as the diff engine, the safe/review/broken classification, the `const`-resolution heuristic) emerged from a planning conversation; Claude wrote the bulk of the implementation.

## License

[MIT](LICENSE)
