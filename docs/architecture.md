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

1. **Scrape** (`core/scraper.py::get_discoveries(past_days, future_days)`): iterates enabled rows of
   `custom_feeds`; each feed type has a branch (`metacritic_tv|movie`, `dvds_releases`, `tvmaze_schedule`,
   `tmdb_movies`, or a generic parser for user feeds). Each feed runs in its own try/except and records
   `last_run/last_status/last_error_message`. Feeds return plain dicts (`title`, `date_obj`, `date_str`,
   `description`, optional ids, `language`, `country`, `is_returning`, `source_feed_id`).
2. **Merge/dedupe**: `merge_movie_lists` (DVD-site movies merged into all other movie feeds) then `dedupe_movies` (any source):
   same film = shared TMDB/IMDb id, or equal `_movie_key` (slug minus a leading article) with years within 1, or
   one key being the start/end of the other (both >= 8 chars) with release dates within 30 days.
   Entries with conflicting ids never merge; the first source wins and gaps are filled from the duplicate. TV is de-duplicated by slug
   with earlier feeds winning.
3. **Enrich** (`core/enricher.py`): TV via TVmaze singlesearch (+Sonarr, Wikipedia cast fallback); movies via Radarr lookup, then TMDB
   (when a key is set; by id, else title+year search), then Wikipedia for missing cast/director/producer.
4. **Cache** (`core/db.py::add_cached_item`): upsert keyed by IMDb id, else normalized title (exact year, then +/-1 year, then any year when the
   `default_match_ignore_year` setting is on — it defaults to on).
   `core/metadata.py::evaluate_item_state_transition` proposes `is_archived` / `has_new_metadata`; `add_cached_item`
   then overrides that for manually archived rows.
5. **Serve** (`web/server.py`): `/api/discover` returns TV + movies with library status resolved against
   Radarr/Sonarr (by tmdb/tvdb/imdb id, then normalized title). The SPA filters client-side.

## Cache table (SQLite, `xarrtools.db`)

One row per movie/show: identity (`type`, `title`, `year`, `normalized_title`, `imdb_id`/`tvdb_id`/`tmdb_id`),
display (`date_str`, `date_obj`, `description`, `poster_url`, `trailer`, `genres` JSON, `cast`, `director`,
`producer`, `network`, ratings), locale (`country` ISO alpha-2, `language` English name), state
(`is_in_library`, `is_returning`, `is_archived`, `manually_archived`, `has_new_metadata`, `added_at`) and
`source_feed_id`. Other tables: `custom_feeds`, `settings` (key/value incl. one-time migration flags and the TMDB
key). Columns are added to old DBs automatically by `init_db` (`expected_cols`).

## Archiving state machine (`core/metadata.py`)

- Auto-archive when **>= 2 of** {title, network, cast, plot} are missing; un-archive (with a "New metadata"
  badge) when enrichment later fills them.
- **Manual archive wins**: the override lives in `core/db.py::add_cached_item` (not in `core/metadata.py`): when the
  existing row has `manually_archived = 1` it forces `is_archived = 1` and `has_new_metadata = 0` (until the user
  un-archives). `archive_cached_item`, `/api/archive` and `/api/archive/batch` set the flag.

## Title keys

`core.locales.slug()`: NFKD, strip accents, lowercase, `&` -> `and`, drop everything that is not a word
character. `normalize_title()` (in `core/db.py` and `core/scraper.py`) first strips format suffixes
(`[Blu-ray]`, years, season markers). `_movie_key` additionally drops a leading article for de-duplication.

## Language / country

Convention: `language` = English name (`"Korean"`), `country` = ISO 3166 alpha-2 (`"KR"`). Sources: TVmaze
(`language`, network/webChannel country), TMDB (`original_language`; country from `/movie/{id}` details only),
filled at enrichment time for Metacritic items. Filtering is a multi-select in the sidebar.

## Frontend (`web/static/src/`)

Modular frontend architecture written in TypeScript under `web/static/src/` and compiled to ES2020 native modules
in `web/static/dist/` (git-ignored, served at `/static/dist/*.js`) via `npm run build`. The web dashboard entry
point `web/templates/index.html` loads `<script type="module" src="/static/dist/main.js"></script>`.

Module responsibilities:
- `web/static/src/types.ts`: TypeScript interfaces for discoveries, settings, modals, and filters.
- `web/static/src/state.ts`: Single-page application state (`currentDiscoveries {tv, movies}` and sets `selectedGenres/Networks/Countries/Languages`).
- `web/static/src/filters.ts`: Pure filter logic (`itemPassesFilters`, `getFilteredUnarchived`, multi-select filters).
- `web/static/src/cards.ts`: Card HTML generation helpers (`escapeHtml`, `countryName`, `localeBadge`, `buildRatingBadgesHtml`, `buildMediaCardHtml`).
- `web/static/src/render.ts`: DOM rendering (`renderMediaLists`), sorting, and badge animations.
- `web/static/src/api.ts`: Typed API client covering all endpoints (`/api/discover`, `/api/add`, `/api/archive`, `/api/settings`, `/api/feeds`, etc.).
- `web/static/src/settings.ts` & `web/static/src/settings-ui.ts`: Settings form collection, preset resolution, MRU management, and feed table row HTML helpers.
- `web/static/src/modals.ts` & `web/static/src/modals-ui.ts`: Add modal builders, indexer candidate rows, global search cards, and dropdown options helpers.
- `web/static/src/main.ts`: Application bootstrap, lifecycle orchestration, and event wiring.

Single-page application state: `currentDiscoveries {tv, movies}` and sets `selectedGenres/Networks/Countries/
Languages`. `itemPassesFilters(item, type)` is the single predicate used by `renderMediaLists` and by
"Archive all filtered" (`getFilteredUnarchived` -> `POST /api/archive/batch`). Multi-selects share markup
(`btn-/content-/options-/clear-/invert-<name>-filter` ids, where `<name>` is `genres`, `networks`, `country`,
`language`).
Node-based test suites exercise compiled modules: `tests/test_frontend_filters.py`, `tests/test_frontend_api.py`,
`tests/test_frontend_cards.py`, `tests/test_frontend_settings.py`, and `tests/test_frontend_modals.py`; `tests/test_m3_static_template_challenge.py` checks HTML/JS id parity.
## Backup & Poster cache (`core/backup.py`, `core/posters.py`)

- **JSON backup** (`/api/backup/export?format=json`, `core.db.export_to_dict`): settings + basic media rows, top-level `format_version: 1`, and SHA-256 canonical JSON `checksum`. Unchecksummed legacy files are accepted; checksum mismatches are rejected with 400.
- **Full instance backup** (`/api/backup/export?format=full`, `core.backup.export_full_backup`): complete `.zip` archive holding `backup.json` (`format_version: 2`, all cache columns, custom feeds with remapped source feed IDs, canonical checksum), `manifest.json` (SHA-256 hash of all files and `{sha256(url): url}` poster index), and downloaded poster images under `posters/`.
- **Integrity & safety**: `import_full_backup` validates zip-slip/path traversal, caps entry sizes (<= 20MB) and total uncompressed size (<= 2GB), verifies manifest hashes and backup.json checksum before writing anything. Settings, custom feeds, and cache rows are restored in a single SQLite transaction with sticky manual archives and library presence preserved.
- **Poster disk cache**: `posters/` folder next to the database (`core.posters.get_posters_dir`) storing raw bytes with `.meta` sidecars keyed by URL SHA-256. `/api/poster` (`web/server.py::proxy_poster`) checks this disk cache first to avoid network roundtrips, and writes through on successful fetch with SSRF validation (private/loopback IPs blocked, server hostnames allowed) and nosniff headers.

## Background Scheduled Refreshes (`core/scheduler.py`, `web/server.py`)

- **Daemon thread**: started on server boot (`scheduler_loop`, skipped when `PYTEST_CURRENT_TEST` is set) sleeping ~30s between checks.
- **Pure scheduling math** (`core/scheduler.py`):
  - `compute_next_run(last_run, interval_hours, time_of_day, now)`: computes the next execution time (UTC-aware), respecting the configurable interval (1-168h) and optional daily `HH:MM` target interpreted in the server's local time (DST-safe; timestamps stored in UTC).
  - `is_due(...)`: returns whether a scan is due. Never-run scheduler enforces a 60-second initial startup delay. Service restarts do not immediately rescan unless execution is actually overdue (`now >= next_run`).
  - `validate_time_of_day`, `parse_time_of_day`: validates and parses 24h `HH:MM` format.
- **Scan engine** (`web/server.py::run_scan`): decoupled from Flask request context; executes discoveries scraping, metadata enrichment, library matching, and SQLite cache updates. Respects `scan_progress_lock`, raising `RuntimeError` if a scan is already in progress.
- **Endpoints**:
  - `GET /api/scheduler/status`: returns `{status, enabled, interval_hours, time_of_day, last_run, next_run, running, last_result}`.
  - `POST /api/scheduler/run-now`: API key protected manual trigger; returns 409 if a scan is running, starts `run_scheduler_job` in a background thread and returns 200 `{status: "started"}`.
## Structured Logging Architecture (`core/logging_setup.py`)

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

## Tests

`pytest tests -q --no-cov`. Many files are named after review "challenge" rounds; they are regular tests.
Shared DB access in tests uses temp DBs; a few legacy tests use the repo DB path through `core.db` — do not add more.
