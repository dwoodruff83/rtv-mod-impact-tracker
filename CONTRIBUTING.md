# Contributing

Thanks for considering a contribution. The codebase is intentionally small and dependency-free; please keep it that way.

## Branch flow

```
feature/<short-name>   work branches
        |
        v
     staging            integration branch (where everything lands first)
        |
        v
       main             stable, public-facing, only updated via PR from staging
```

- Open all PRs against **`staging`** by default
- `main` is protected. PRs into `main` are only accepted from `staging` (enforced by `.github/workflows/enforce-main-source.yml` and branch protection rules)
- Force pushes and branch deletions are disabled on both `main` and `staging`

This keeps `main` always-shippable and gives `staging` room to integrate multiple feature branches before promoting.

## Local setup

1. Fork or clone the repo
2. Create a feature branch off `staging`: `git checkout -b feature/my-thing staging`
3. Make changes, commit, push the feature branch, open a PR into `staging`

## Code conventions

- **Standard library only.** No `pip` dependencies, no `requirements.txt`, no `pyproject.toml`. If a feature needs more, propose an alternative or open an issue first.
- **Python 3.11+** is the floor (for `tomllib`).
- **Plain technical voice** in code, comments, docs, and commits.
- Cross-platform: avoid OS-specific paths in code; the user's `mod_tracker.toml` is the anchor.
- Output to stdout should be UTF-8 even on Windows. User-facing scripts re-wrap `sys.stdout`/`sys.stderr` at module load if the encoding isn't UTF-8.

## Tests

There's no test suite by design — the codebase is mostly pipelines that compose around git and a small TOML config. The smoke check is "run the eight scripts against a populated workspace and verify they all complete without errors." See `CLAUDE.md` in the repo root for the full smoke test recipe.

## Reporting issues

Open an issue with:
- What you ran (exact command line)
- What you expected to happen
- What actually happened (stack trace, error message, or unexpected output)
- Your OS, Python version, and Git version

For game-developer takedown requests: see the **Legal and ethical use** section in the README. Open an issue and the maintainer will work with you.
