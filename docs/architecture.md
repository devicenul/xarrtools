# Architecture

## Purpose in the Radarr/Sonarr workflow

xarrtools sits *in front of* the *arr servers: it finds new releases, shows what is already in the library
(matched by tmdb/tvdb/imdb id, then normalized title), and lets the user add the wanted ones to Radarr/Sonarr
(`/api/add`, with lookup via `/api/lookup`) so those servers can search for and download them. Everything below
serves that hand-off.

## Data flow

```
feeds (custom_feeds table)                      user clicks "Scan New Releases"
  Metacritic TV/Movies ─┐                                  │
  DVDs release dates ───┤                                  ▼
  TVmaze /schedule/full ┼─► core.scraper.get_discoveries ─► web/server.py /api/discover
  TMDB /discover/movie ─┤        (merge + dedupe)              │ for each item:
  Wikipedia / custom ───┘                                      │  cache hit & complete? use it
                                                               │  else core.enricher.enrich_*  ──► TVmaze / Radarr / TMDB / Wikipedia
                                                               ▼
                                              core.db.add_cached_item  (SQLite `cache` table)
                                                               │
                      /api/discover?skip_scrape=true  ◄────────┘  (UI normally reads this)
```

1. **Scrape** (`src/xarrtools/core/scraper.py::get_discoveries(past_days, future_days)`): iterates enabled rows of
   `custom_feeds`; each feed type has a branch (`metacritic_tv|movie`, `dvds_releases`, `tvmaze_schedule`,
   `tmdb_movies`, or a generic parser for user feeds). Each feed runs in its own try/except and records
   `last_run/last_status/last_error_message`. Feeds return plain dicts (`title`, `date_obj`, `date_str`,
   `description`, optional ids, `language`, `country`, `is_returning`, `source_feed_id`).
2. **Merge/dedupe**: `merge_movie_lists` (DVD-site movies merged into all other movie feeds) then `dedupe_movies` (any source):
   same film = shared TMDB/IMDb id, or equal `_movie_key` (slug minus a leading article) with years within 1, or
   one key being the start/end of the other (both >= 8 chars) with release dates within 30 days.
   Entries with conflicting ids never merge; the first source wins and gaps are filled from the duplicate. TV is de-duplicated by slug
   with earlier feeds winning.
3. **Enrich** (`src/xarrtools/core/enricher.py`): TV via TVmaze singlesearch (+Sonarr, Wikipedia cast fallback); movies via Radarr lookup, then TMDB
   (when a key is set; by id, else title+year search), then Wikipedia for missing cast/director/producer.
4. **Cache** (`src/xarrtools/core/db.py::add_cached_item`): upsert keyed by IMDb id, else normalized title (exact year, then +/-1 year, then any year when the
   `default_match_ignore_year` setting is on — it defaults to on).
   `src/xarrtools/core/metadata.py::evaluate_item_state_transition` proposes `is_archived` / `has_new_metadata`; `add_cached_item`
   then overrides that for manually archived rows.
5. **Serve** (`src/xarrtools/web/server.py`): `/api/discover` returns TV + movies with library status resolved against
   Radarr/Sonarr (by tmdb/tvdb/imdb id, then normalized title). The SPA filters client-side.

## Cache table (SQLite, `xarrtools.db`)

One row per movie/show: identity (`type`, `title`, `year`, `normalized_title`, `imdb_id`/`tvdb_id`/`tmdb_id`),
display (`date_str`, `date_obj`, `description`, `poster_url`, `trailer`, `genres` JSON, `cast`, `director`,
`producer`, `network`, ratings), locale (`country` ISO alpha-2, `language` English name), state
(`is_in_library`, `is_returning`, `is_archived`, `manually_archived`, `has_new_metadata`, `added_at`) and
`source_feed_id`. Other tables: `custom_feeds`, `settings` (key/value incl. one-time migration flags and the TMDB
key). Columns are added to old DBs automatically by `init_db` (`expected_cols`).

## Archiving state machine (`src/xarrtools/core/metadata.py`)

- Auto-archive when **>= 2 of** {title, network, cast, plot} are missing; un-archive (with a "New metadata"
  badge) when enrichment later fills them.
- **Manual archive wins**: the override lives in `src/xarrtools/core/db.py::add_cached_item` (not in `src/xarrtools/core/metadata.py`): when the
  existing row has `manually_archived = 1` it forces `is_archived = 1` and `has_new_metadata = 0` (until the user
  un-archives). `archive_cached_item`, `/api/archive` and `/api/archive/batch` set the flag.

## Title keys

`core.locales.slug()`: NFKD, strip accents, lowercase, `&` -> `and`, drop everything that is not a word
character. `normalize_title()` (in `src/xarrtools/core/db.py` and `src/xarrtools/core/scraper.py`) first strips format suffixes
(`[Blu-ray]`, years, season markers). `_movie_key` additionally drops a leading article for de-duplication.

## Language / country

Convention: `language` = English name (`"Korean"`), `country` = ISO 3166 alpha-2 (`"KR"`). Sources: TVmaze
(`language`, network/webChannel country), TMDB (`original_language`; country from `/movie/{id}` details only),
filled at enrichment time for Metacritic items. Filtering is a multi-select in the sidebar.

## Frontend (`src/xarrtools/web/static/src/`)

Modular frontend architecture written in TypeScript under `src/xarrtools/web/static/src/` and compiled to ES2020 native modules
in `src/xarrtools/web/static/dist/` (git-ignored, served at `/static/dist/*.js`) via `npm run build`. The web dashboard entry
point `src/xarrtools/web/templates/index.html` loads `<script type="module" src="/static/dist/main.js"></script>`.

Module responsibilities:
- `src/xarrtools/web/static/src/types.ts`: TypeScript interfaces for discoveries, settings, modals, and filters.
- `src/xarrtools/web/static/src/state.ts`: Single-page application state (`currentDiscoveries {tv, movies}` and sets `selectedGenres/Networks/Countries/Languages`).
- `src/xarrtools/web/static/src/filters.ts`: Pure filter logic (`itemPassesFilters`, `getFilteredUnarchived`, multi-select filters).
- `src/xarrtools/web/static/src/cards.ts`: Card HTML generation helpers (`escapeHtml`, `countryName`, `localeBadge`, `buildRatingBadgesHtml`, `buildMediaCardHtml`).
- `src/xarrtools/web/static/src/render.ts`: DOM rendering (`renderMediaLists`), sorting, and badge animations.
- `src/xarrtools/web/static/src/api.ts`: Typed API client covering all endpoints (`/api/discover`, `/api/add`, `/api/archive`, `/api/settings`, `/api/feeds`, etc.).
- `src/xarrtools/web/static/src/settings.ts` & `src/xarrtools/web/static/src/settings-ui.ts`: Settings form collection, preset resolution, MRU management, and feed table row HTML helpers.
- `src/xarrtools/web/static/src/modals.ts` & `src/xarrtools/web/static/src/modals-ui.ts`: Add modal builders, indexer candidate rows, global search cards, and dropdown options helpers.
- `src/xarrtools/web/static/src/main.ts`: Application bootstrap, lifecycle orchestration, and event wiring.

Single-page application state: `currentDiscoveries {tv, movies}` and sets `selectedGenres/Networks/Countries/
Languages`. `itemPassesFilters(item, type)` is the single predicate used by `renderMediaLists` and by
"Archive all filtered" (`getFilteredUnarchived` -> `POST /api/archive/batch`). Multi-selects share markup
(`btn-/content-/options-/clear-/invert-<name>-filter` ids, where `<name>` is `genres`, `networks`, `country`,
`language`).
Node-based test suites exercise compiled modules: `tests/test_frontend_filters.py`, `tests/test_frontend_api.py`,
`tests/test_frontend_cards.py`, `tests/test_frontend_settings.py`, and `tests/test_frontend_modals.py`; `tests/test_m3_static_template_challenge.py` checks HTML/JS id parity.
## Backup & Poster cache (`src/xarrtools/core/backup.py`, `src/xarrtools/core/posters.py`)

- **JSON backup** (`/api/backup/export?format=json`, `core.db.export_to_dict`): settings + basic media rows, top-level `format_version: 1`, and SHA-256 canonical JSON `checksum`. Unchecksummed legacy files are accepted; checksum mismatches are rejected with 400.
- **Full instance backup** (`/api/backup/export?format=full`, `core.backup.export_full_backup`): complete `.zip` archive holding `backup.json` (`format_version: 2`, all cache columns, custom feeds with remapped source feed IDs, canonical checksum), `manifest.json` (SHA-256 hash of all files and `{sha256(url): url}` poster index), and downloaded poster images under `posters/`. Cached posters are included immediately; uncached poster fetching runs concurrently with a bounded deadline (`max_poster_fetch_time=10.0`s) to prevent thread starvation or stalled exports.
- **Integrity & safety**: `import_full_backup` validates zip-slip/path traversal, caps entry sizes (<= 20MB) and total uncompressed size (<= 2GB), verifies manifest hashes and backup.json checksum before writing anything. Settings, custom feeds, and cache rows are restored in a single SQLite transaction with sticky manual archives and library presence preserved.
- **Poster disk cache**: `posters/` folder next to the database (`core.posters.get_posters_dir`) storing raw bytes with `.meta` sidecars keyed by URL SHA-256. `/api/poster` (`src/xarrtools/web/server.py::proxy_poster`) checks this disk cache first to avoid network roundtrips, and writes through on successful fetch with SSRF validation (private/loopback IPs blocked, server hostnames allowed) and nosniff headers.
- **Desktop GUI & Browser Downloads**: In standalone desktop mode (`src/xarrtools/gui/gui.py`), pywebview enables `ALLOW_DOWNLOADS` and registers `DesktopApi` via `js_api.save_file` to open native OS file dialogs and stream downloads directly to the chosen path without page reload or rendering raw JSON. In browser mode, frontend `triggerFileDownload` transparently falls back to `<a download>` synthetic anchor clicks. Waitress runs with 8 worker threads (`threads=8`) to handle concurrent polling and downloads.

## Background Scheduled Refreshes (`src/xarrtools/core/scheduler.py`, `src/xarrtools/web/server.py`)

- **Daemon thread**: started on server boot (`scheduler_loop`, skipped when `PYTEST_CURRENT_TEST` is set) sleeping ~30s between checks.
- **Pure scheduling math** (`src/xarrtools/core/scheduler.py`):
  - `compute_next_run(last_run, interval_hours, time_of_day, now)`: computes the next execution time (UTC-aware), respecting the configurable interval (1-168h) and optional daily `HH:MM` target interpreted in the server's local time (DST-safe; timestamps stored in UTC).
  - `is_due(...)`: returns whether a scan is due. Never-run scheduler enforces a 60-second initial startup delay. Service restarts do not immediately rescan unless execution is actually overdue (`now >= next_run`).
  - `validate_time_of_day`, `parse_time_of_day`: validates and parses 24h `HH:MM` format.
- **Scan engine** (`src/xarrtools/web/server.py::run_scan`): decoupled from Flask request context; executes discoveries scraping, metadata enrichment, library matching, and SQLite cache updates. Respects `scan_progress_lock`, raising `RuntimeError` if a scan is already in progress.
- **Endpoints**:
  - `GET /api/scheduler/status`: returns `{status, enabled, interval_hours, time_of_day, last_run, next_run, running, last_result}`.
  - `POST /api/scheduler/run-now`: API key protected manual trigger; returns 409 if a scan is running, starts `run_scheduler_job` in a background thread and returns 200 `{status: "started"}`.
## Structured Logging Architecture (`src/xarrtools/core/logging_setup.py`)

- **Hierarchy**: All loggers sit under the `xarrtools` namespace (`xarrtools.scraper`, `xarrtools.db`, `xarrtools.enricher`, `xarrtools.client`, `xarrtools.server`, `xarrtools.scheduler`, `xarrtools.posters`, `xarrtools.backup`, etc.). The root `xarrtools` logger has `propagate = False` to prevent double-logging in parent processes.
- **Handlers**:
  - `StreamHandler(sys.stdout)` with formatted, structured plain text logs (`%(asctime)s [%(levelname)s] %(name)s: %(message)s`).
  - `RotatingFileHandler(xarrtools.log)` located under `logs/` adjacent to `xarrtools.db` (configurable via `LOG_DIR` or `XARRTOOLS_LOG_DIR`), capped at ~1MB (`maxBytes=1048576`) and `backupCount=1` (strictly max 2 log files: `xarrtools.log` and `xarrtools.log.1`).
- **Security & Redaction**:
  - `RedactingFilter` and `RedactingFormatter` automatically redact credentials, API keys, tokens, query parameters (`?apikey=...`, `?token=...`, etc.), headers (`X-Api-Key`, `Bearer <token>`, `Authorization`), configured service keys (Radarr, Sonarr, TMDB, server API key), and exception tracebacks before records hit stdout or disk.
- **Dynamic Configuration**:
  - Log level is stored in settings (`log_level`, default `INFO`, allowed `DEBUG`, `INFO`, `WARNING`, `ERROR`).
  - Updates via `POST /api/settings` validate the level (400 on invalid) and call `setup_logging(level=...)` to update root and handler levels live without requiring server restarts.
- **Log Export**:
  - `GET /api/logs/download` streams an in-memory ZIP archive of pre-redacted logs (`xarrtools.log` and `xarrtools.log.1`). If no logs are present, it gracefully returns a ZIP containing an explanatory README.txt file.

## Container Architecture & Deployment (`Dockerfile`, `docker-compose.yml`)

- **Multi-stage build**:
  - Stage 1 (`node:20-alpine`): installs frontend dependencies (`npm ci`) and compiles TypeScript sources (`npm run build`) into `src/xarrtools/web/static/dist/`.
  - Stage 2 (`python:3.12-slim`): installs runtime dependencies from `requirements.txt` (excluding GUI libraries), copies application modules (`src/xarrtools/`), and imports compiled frontend assets from Stage 1.
- **Config directory isolation**:
  - Uses `XARRTOOLS_CONFIG_DIR=/config` mapped as a persistent volume.
  - SQLite database (`xarrtools.db`), environment overrides (`.env`), cached posters (`/config/posters`), and logs (`/config/logs`) all reside within this single directory.
- **Security & Least Privilege**:
  - Runs under an unprivileged user (`appuser`, UID/GID 1000).
  - Optional HTTP Basic Authentication (`XARRTOOLS_AUTH_USER` / `XARRTOOLS_AUTH_PASSWORD`) protects all endpoints (`/` and `/api/*`) using constant-time comparison (`hmac.compare_digest`).
  - Credentials and tokens are redacted from logging and never exported in backups or saved into container images.
- **Health monitoring**:
  - Built-in Python-based `HEALTHCHECK` queries unauthenticated `GET /api/health` (`SELECT 1` database query probe) without needing external utilities like curl or wget.
- **Cross-environment backup portability**:
  - Backups (both full ZIP and JSON) store purely relative references without environment-specific paths or host credentials, enabling seamless migration between Docker and standalone desktop/server installations.

## CI/CD Pipeline & Distribution Architecture

- **Continuous Integration (`.github/workflows/ci.yml`)**:
  - Triggers on pushes and pull requests to `main` (skipping docs-only markdown changes via `paths-ignore`).
  - Cross-platform test matrix spanning Ubuntu (Python 3.10 and 3.12), macOS (Python 3.12), and Windows (Python 3.12).
  - TypeScript compilation (`npm ci && npm run build`), static type verification (`mypy`), and full test suite execution (`pytest`).
  - Docker container smoke testing: builds the local image, runs an unprivileged container with `/config` volume mapping, and verifies unauthenticated `GET /api/health` probes.
- **Automated Releases (`.github/workflows/release.yml`)**:
  - Triggers on tag pushes (`v*`) and manual dry-run workflow dispatch.
  - Gated by full test execution on Ubuntu.
  - Multi-platform binary matrix compiles standalone PyInstaller executables for macOS (Apple Silicon `macos-arm64` and Intel `macos-x64`), Windows (`windows-x64`), and Linux (`linux-x64`).
  - Binary smoke verification: tests `--help` and live `--server --no-browser` startup with `/api/health` polling.
  - Standalone archives packaged with SHA256 checksums (`.zip` on macOS/Linux to preserve permissions, `.exe` on Windows).
  - Multi-architecture Docker publishing (`linux/amd64` and `linux/arm64`) to GitHub Container Registry (`ghcr.io/devicenul/xarrtools`).
  - GitHub Release creation (`gh release create`) publishing binaries, checksums, and auto-generated release notes (flagged as prerelease if version contains a hyphen).

## Tests

`pytest tests -q --no-cov`. Many files are named after review "challenge" rounds; they are regular tests.
`tests/conftest.py` redirects `xarrtools.core.db.DB_PATH` and the log dir to a session temp dir before any test module is imported, redirects any test that resolves to the real DB, and fails the run if the real `xarrtools.db` changes. Individual test modules may still use their own temp DB.
