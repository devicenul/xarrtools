# AGENTS.md — guide for AI coding agents working on xarrtools

xarrtools is a Python/Flask companion for Radarr and Sonarr. It **discovers upcoming and new TV shows and
movies** from several feeds, **enriches** them with metadata, **caches** them in SQLite, and lets the user
**triage** them (archive, add to Radarr/Sonarr, see what is already in their library) from a web UI, a desktop
window (pywebview) or a CLI.

**The end goal is acquisition:** discovery exists so the user can pick what they want and *add it to their
Radarr/Sonarr servers*, which then monitor, search for and download it. Workflow: discover -> enrich (so the user
can judge it) -> triage (archive the rest, hide what is already in the library) -> **add to Radarr/Sonarr**
(`/api/add`) -> the *arr apps take over. Anything that makes that decision easier or the hand-off more reliable
(accurate library matching, correct ids, good metadata) is core to the product, not a nicety.

Read this file first, then [docs/architecture.md](docs/architecture.md) (how it fits together) and
[docs/decisions.md](docs/decisions.md) (why it is the way it is — don't undo these without a good reason).

## Philosophy

- **The cache is the product.** Scans are slow and flaky (third-party sites); the UI reads from SQLite
  (`/api/discover?skip_scrape=true`) and scans refresh it.
- **Fail soft, but never silently.** One broken feed must not stop the others (feeds are isolated), yet an
  empty scrape result is treated as an *error* (`last_status = error`), not as "nothing new".
- **The user's decisions win.** A manual archive is sticky: new metadata never resurfaces it.
- **Works offline-ish and everywhere.** Windows/macOS/Linux/Android-VM, no required API keys (TMDB is optional).
- **Small, dependency-light.** Flask + requests + BeautifulSoup + SQLite. The frontend is modular
  TypeScript (`web/static/src/*.ts`), compiled to `web/static/dist/` via `npm run build` during setup, with
  compiled output git-ignored (no checked-in generated JS) until CI/CD publishes releases.

## Repo map

| Path | Purpose |
|---|---|
| `main.py` | Entry point: `--gui` (default), `--server`, `--cli` |
| `core/scraper.py` | Feed scrapers (Metacritic, DVDs, TVmaze, TMDB), `get_discoveries`, `dedupe_movies` |
| `core/enricher.py` | `enrich_tv_show` (TVmaze, Sonarr, Wikipedia cast fallback) and `enrich_movie` (Radarr, TMDB, Wikipedia fallback) |
| `core/tmdb.py` | TMDB client: chunked discovery and per-movie enrichment |
| `core/db.py` | SQLite schema, migrations, cache CRUD, settings, backup/restore |
| `core/metadata.py` | Missing-metadata rules and the auto-archive state machine |
| `core/locales.py` | Language/country normalisation and the Unicode-aware `slug()` title key |
| `core/client.py`, `core/config.py` | Radarr/Sonarr API clients; settings/.env access |
| `web/server.py`, `web/templates/` | Flask API + single-page UI (`index.html`, `style.css`) |
| `web/static/src/` | TypeScript frontend modules (`types.ts`, `state.ts`, `render.ts`, `cards.ts`, `filters.ts`, `api.ts`, `settings.ts`, `modals.ts`, `main.ts`) |
| `cli/cli.py`, `gui/gui.py` | Terminal manager and pywebview shell |
| `build.py` (+ `build.*`), `init.*`, `run.*` | Build, environment setup and launchers (sh / ps1 / bat) |
| `tests/` | pytest suite (~1070 tests) |

## Everyday commands

```bash
./init.sh                                   # create venv, install requirements-dev.txt, create .env, init DB
.venv/bin/python -m pytest tests -q --no-cov   # ~25 s; use the venv path printed by init.sh if it differs
./build.sh                                  # PyInstaller binary via build.py (build.ps1 / build.bat on Windows)
python main.py --server                     # run the web UI on http://localhost:5000
```

On the Android/Linux-VM setup the venv lives in `~/.cache/projects/<name>-<hash>/venv` (shared storage has no
symlinks); `source init.sh --env-only` (sourced, as `build.sh` does) exports `VENV_DIR`/`PROJECT_CACHE_DIR`. Run commands from the repo root.

## Hard rules

1. **Never touch the real `xarrtools.db` from tests or scripts.** Use a temp DB: the `temp_db` fixture in `tests/test_db.py` (it is local to that
   file — copy the pattern, or point `core.db.DB_PATH` at a temp file as `tests/test_server.py` does). A few
   legacy tests still touch the repo DB; don't add more. `tests/conftest.py` blanks the TMDB key so tests stay offline.
2. **Never print, log, commit or write credentials** (TMDB token, Radarr/Sonarr keys). They live in the DB
   `settings` table / `.env`, both git-ignored. `.env.example` holds placeholders only.
3. **Titles are compared with `slug()` / `normalize_title()`**, never an ASCII-only regex — non-Latin titles
   must not collapse to an empty key.
4. **Tests must not depend on today's date.** Use dates relative to `datetime.now()`; `/api/discover` defaults to a
   `[today-30d, today+60d]` window (`past_months`/`future_months` params), so test data must fall inside it.
5. **Schema changes** go through the `CREATE TABLE` + `expected_cols` pattern in `init_db`, and one-time data
   fixes use a flag in the `settings` table (see `migrated_*`). Keep `add_cached_item` placeholders in sync.
6. **Add dependencies to `requirements.txt` (runtime) or `requirements-dev.txt` (test/build).**
7. Preserve existing comments and docstrings you are not changing; keep commit messages descriptive
   (what changed *and why*).
8. The Windows scripts (`*.ps1`, `*.bat`) cannot be run in the Linux VM — change them minimally and say so.
9. On the Android shared mount git needs `core.fileMode false` to avoid mode-change noise.

## Definition of done

Code + tests for the change, full suite green, docs updated if behaviour or architecture changed
(including this file), and nothing sensitive staged (`git diff --cached` before committing).
