# ModWorkshop publication notes

Internal doc — guidance for publishing this tool to ModWorkshop. The tool itself isn't a mod (no `.vmz`, no game install side); the ModWorkshop entry is essentially a pointer to the GitHub repo with a tailored description so RTV modders can find it.

## Recommended publication model

**Lightweight ModWorkshop entry that links back to GitHub.** Reasons:

- The tool runs alongside the game, not inside it — there's no `.vmz` to upload anyway
- Source is the canonical artifact; the ModWorkshop page should drive people to it
- One source of truth for releases (GitHub tags) avoids drift between the two platforms
- Issues/PRs flow naturally to GitHub

The entry mainly buys discoverability for RTV modders browsing the workshop.

## Field checklist

| Field | Value |
|---|---|
| **Category** | `Tools` (sibling to Metro Mod Loader, GDRE Tools-style utilities) |
| **Tags** | `Add-on (#13)` plus any "Modding Tool" / "Developer" tag the workshop offers |
| **License** | MIT (matches LICENSE in the repo) |
| **Dependencies** | None on the workshop side. README documents Python 3.11+ and Git as runtime requirements. |
| **GitHub URL** | The ModWorkshop description should prominently link to the public GitHub repo |
| **Updates** | Releases tracked on GitHub; ModWorkshop description's "version" field can mirror the latest GitHub tag |

## Description draft (paste into the ModWorkshop description field)

Use the following block. It's tuned for the ModWorkshop audience — assumes the reader is a mod author, foregrounds the "tells you which of your mods will break" value prop, and points at GitHub for the full README.

---

> **Tell which of your Road to Vostok mods will break before you launch the game — and track upstream library dependencies for breaking changes between releases.**
>
> A standalone CLI toolkit for RTV mod authors. It snapshots decompiled game scripts after each patch, then diffs the files your mods override and tells you what's safe / needs review / actually broken. It also tracks upstream mod-dependency repos (Metro Mod Loader, MCM, etc.) by their GitHub tags, so you can see what changed in any release before users start reporting bugs.
>
> ## What you get
>
> Eight small Python scripts, two families:
>
> **Game tracking** — `snapshot.py` captures one decompile per patch into a local git repo. `analyze_mods.py` tells you which of your mods are 🟢 safe / 🟡 review / 🔴 broken between any two snapshots, with HTML reports embedding collapsible per-file diffs. `changelog.py` emits a Markdown changelog of every game-side change. `fetch_version.py` orchestrates Steam backfill via DepotDownloader if you want to pull historical builds.
>
> **Dependency tracking** — `deps_fetch.py` maintains local mirror clones of upstream dep repos. `deps_diff.py` shows what changed between any two upstream tags. `deps_audit.py` cross-references those changes against your mods' call sites and flags broken methods. `deps_changelog.py` emits release notes per dep.
>
> ## Why this exists
>
> The game gets patched. Your override might be fine. It might be silently broken. You launch the game and find out the hard way. This tool replaces "launch and pray" with a five-second HTML report.
>
> Same problem on the dep side: a mod loader or framework you depend on cuts a new version. Did your `lib.register(...)` call still work? `deps_audit.py` answers that without you having to read every commit.
>
> ## How to use
>
> 1. Clone the GitHub repo (link below) — Python 3.11+ and Git are the only runtime requirements, no `pip install`
> 2. Drop a `mod_tracker.toml` at the root of your modding workspace (an example for RTV ships in `examples/`)
> 3. After each game patch: re-decompile (with [GDRE Tools](https://github.com/bruvzg/gdsdecomp)), then `python snapshot.py` + `python analyze_mods.py --output report.html`
> 4. After each upstream dep release: `python deps_fetch.py sync` + `python deps_audit.py --dep <name> --output audit.html`
>
> ## Licence
>
> MIT. Standard library only. No plugins, no telemetry, no calls home.
>
> ## Legal and ethical use
>
> Community modding tooling — same shape as xEdit, MCP, DayZ Tools, or SMAPI. You must own the game; decompilation happens via [GDRE Tools](https://github.com/bruvzg/gdsdecomp) (a separate project) on your own copy. No game content is bundled or distributed by this repo — everything stays on your local filesystem. No DRM bypass, no telemetry, no calls home. If the game's developer ever requests takedown, the maintainer will work with them.
>
> ## Source, issues, contributions
>
> [GitHub repo](<insert-public-repo-url-here>). README has the full quickstart, command reference, and configuration schema.
>
> Built primarily for [Road to Vostok](https://store.steampowered.com/app/1963610/) but the analysis is generic — `snapshot/analyze_mods/changelog/fetch_version` work for any Godot-on-Steam game, and the `deps_*` scripts work for any GitHub-hosted upstream with semver tags.

---

## Screenshot candidates (capture before publishing)

Three screenshots cover the value proposition cleanly. All come from real tool output — generate them once, screenshot them, then they don't need regenerating until the UI changes.

1. **`screenshots/01_analyze_html.png`** — `analyze_mods.py --output` HTML report showing 🔴 / 🟡 / 🟢 mod buckets. Open the rendered HTML in a browser, take a screenshot of the report header + first few mod blocks. This is the headline value prop.
2. **`screenshots/02_deps_audit.png`** — `deps_audit.py --output` HTML report showing the breaking-API-changes section + a flagged mod with call-site preview. Demonstrates the dep-tracking pipeline.
3. **`screenshots/03_terminal.png`** — terminal showing `analyze_mods.py` text output (the bucketed list) AND/OR `deps_changelog.py` Markdown output. Good for showing the tool runs without GUI.

Optional 4th: **`screenshots/04_html_diff_expanded.png`** — same `analyze_mods.py` HTML but with one of the collapsible per-file diffs expanded, showing the color-coded line diff. Visually striking.

Place under `screenshots/` in this repo (already gitignored from `.vmz` packaging, since this isn't a mod).

## Pre-publish checklist

- [ ] Push the repo to a public GitHub URL
- [ ] Update the `<insert-public-repo-url-here>` placeholder in the description above
- [ ] Capture the screenshots listed above
- [ ] Verify `examples/road-to-vostok.toml` has the `[[deps]]` section (done as of 2026-04-26)
- [ ] Confirm CLAUDE.md no longer mentions personal workspace paths (done)
- [ ] Confirm git history is clean of any pre-public personal references (audited 2026-04-26 — clean)
- [ ] Pick a ModWorkshop "version" string (suggest mirroring the latest GitHub tag, or `1.0.0` for first publish if no tags yet)
- [ ] First publish via ModWorkshop web form
- [ ] Post-publish: cross-link from the GitHub README to the ModWorkshop page (optional but boosts discoverability both directions)
