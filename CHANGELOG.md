# Changelog

All notable changes to rtv-mod-impact-tracker are documented here. Dates are
YYYY-MM-DD.

## 1.0.0 — 2026-04-26

First public release. Eight Python scripts split into two pipelines —
game-tracking (Steam-sourced) and dep-tracking (GitHub-sourced) — that
together tell modders which of their mods will break when the host game
patches or an upstream library updates.

**Game tracking** — for the host game you're modding:

- **`snapshot.py`** — capture a decompiled-script snapshot of the current
  Steam build into a parallel `*_history` git repo, one commit per game
  version. Auto-detects version + buildid from `project.godot` and the Steam
  ACF manifest; tags as `game-v<version>-build<buildid>`.
- **`analyze_mods.py`** — diff two snapshot tags and classify each mod's
  impact (🔴 broken / 🟡 review / 🟢 safe). Renders an HTML report with
  inline syntax-highlighted diffs, side-by-side override-vs-vanilla
  comparison, and a per-mod summary table.
- **`changelog.py`** — render a Markdown changelog of game-side script
  changes between any two snapshot tags. Useful for release-notes posts and
  for understanding what shipped in a given patch.
- **`fetch_version.py`** — pull a historical Steam build via DepotDownloader
  using a manifest registry, decompile it, and commit it as a snapshot.
  Required only for backfilling old versions; day-to-day tracking uses
  `snapshot.py` against the live install.

**Dep tracking** — for upstream mod loaders, config-menu frameworks, and
content registries hosted on GitHub:

- **`deps_fetch.py`** — sync local mirror clones of every upstream declared
  in `[[deps]]` of `mod_tracker.toml`. Mirrors are gitignored; regenerable
  on demand.
- **`deps_diff.py`** — file-level + GDScript signature diff between two
  upstream tags. Highlights added / removed / renamed / signature-changed
  functions so the breaking-change surface is obvious at a glance.
- **`deps_audit.py`** — scan your own mods' call sites against a dep diff
  and flag anything that touches a changed API. Outputs a punch list of
  mod files + line numbers worth reviewing before bumping the upstream
  version requirement.
- **`deps_changelog.py`** — Markdown release notes summarising upstream
  changes between two tags. Drop-in for the dep's own release post or for
  internal "what's new" briefings.

**Configuration & infrastructure**:

- **TOML-driven** — single `mod_tracker.toml` declares game paths, Steam
  app id, and the list of upstream `[[deps]]`. All scripts read from it,
  so adding a new dep is a one-block config change.
- **HTML reports** with inline syntax highlighting (Pygments-via-stdlib
  fallback) — no external CSS hosting, runs offline.
- **Stdlib-only Python (3.11+).** No `pip install` required for normal
  use; DepotDownloader is the only external binary, and only `fetch_version.py`
  needs it.
- **MIT licensed.** Use it, fork it, ship it.
