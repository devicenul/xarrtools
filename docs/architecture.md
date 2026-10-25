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

## Frontend (`web/templates/app.js`)

Plain JS single page. State: `currentDiscoveries {tv, movies}` and sets `selectedGenres/Networks/Countries/
Languages`. `itemPassesFilters(item, type)` is the single predicate used by `renderMediaLists` and by
"Archive all filtered" (`getFilteredUnarchived` -> `POST /api/archive/batch`). Multi-selects share markup
(`btn-/content-/options-/clear-/invert-<name>-filter` ids, where `<name>` is `genres`, `networks`, `country`,
`language`). `tests/test_frontend_filters.py` runs these functions
under Node with a DOM stub; `tests/test_m3_static_template_challenge.py` checks HTML/JS id parity.
Build tooling for the TypeScript migration is defined in `package.json` and `tsconfig.json`. When
sources exist under `web/static/src`, the build step compiles to output web/static/dist (git-ignored,
nothing compiled yet; runtime currently serves directly from `web/templates/app.js`).

## Tests

`pytest tests -q --no-cov`. Many files are named after review "challenge" rounds; they are regular tests.
Shared DB access in tests uses temp DBs; a few legacy tests use the repo DB path through `core.db` — do not add more.
