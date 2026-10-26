# Decision log (why things are the way they are)

| Decision | Reason |
|---|---|
| Letterboxd feed replaced by TMDB | Letterboxd sits behind a Cloudflare challenge (403) that scripts can't pass. TMDB has an official API. |
| TMDB discovery in 7-day windows, 2 pages each | A single popularity-sorted query let blockbusters crowd out everything else. |
| TVmaze `/schedule/full` is a default TV feed | Metacritic's "new" list only has already-released shows; TVmaze lists future premieres and specials. |
| Empty Metacritic result = feed error | A blocked/changed page used to look like "no new shows". |
| Manual archives are sticky (`manually_archived`) | Users were annoyed by archived items reappearing after enrichment. Auto-archive is still reversible. |
| Auto-archive needs >= 2 missing of title/network/cast/plot | Avoids hiding items for a single missing field; badge appears when data arrives later. |
| Returning (season 2+) shows, library items and archived items hidden by default | Default view is "new things I don't have yet". Specials are not flagged as returning. |
| `slug()` is Unicode-aware | ASCII-only keys turned every Greek/Cyrillic title into `''`, making one cache row appear many times and causing false library matches. |
| `dedupe_movies` never merges conflicting TMDB/IMDb ids | "Beast" and "The Beast" are different films. Prefix/suffix merging needs >= 8 chars and dates within 30 days. |
| Country for movies only after enrichment | TMDB discover lists have no origin country; it needs a per-movie call. |
| `build.py` is the single build implementation | Three scripts had drifted; wrappers only ensure the venv. |
| No Makefile | `make` isn't available on stock Windows; per-OS differences live in `build.py`. |
| Tests blank the TMDB key (`tests/conftest.py`) | Tests must be offline and must never use the real credential. |
| Credentials only in DB/`.env` | Both git-ignored; history was audited and is clean. |
| Frontend built with TypeScript; compiled dist/ JS is not committed | Developers can install Node; checking in generated dist JS modules would create noisy, stale diffs until CI/CD builds releases. |
| Frontend behaviour tested via Node + DOM stub | No browser tooling available; keeps JS logic regression-tested without new dependencies. |
| Dependency-free daemon thread for scheduler | Avoids heavy scheduling frameworks (like APScheduler); standard library threading loop is simple, portable, and transparent. |
| Scheduler 60s startup delay on first run | Prevents heavy scrape/enrich jobs from competing with server boot and user's initial UI load. |
| Restarts do not rescan unless overdue | Preserves previous execution schedule without spamming feeds on every server/app restart. |
| Scheduler reuses scan progress lock & 409 status | Prevents race conditions and duplicate scans between background scheduled tasks and manual UI scans. |
| Capped log file rotation (max 2 files: `xarrtools.log` and `xarrtools.log.1`, ~1MB each) | Prevents runaway disk growth on resource-constrained host devices, NAS, or VM environments while preserving previous session history for diagnostics. |
| In-flight credential redaction via filter and formatter | Prevents secret API keys, tokens, query params, and Authorization headers from ever being written to console or disk, even in debug mode or crash tracebacks. |
| In-memory ZIP for log downloads with fallback README | Safe, streaming download endpoint (`GET /api/logs/download`) with zero disk-write overhead; returns informative README if logs directory is empty or missing. |
| Live log level updating without restart | Allows users to toggle DEBUG logging on-the-fly to diagnose an issue and return to INFO without stopping the Flask server or interrupting scans. |
| Tests are globally isolated from the real DB in `tests/conftest.py` | Legacy modules each patched `DB_PATH` themselves (import-time, per file), so single-file runs and early imports wiped the developer's real cache and settings. A session-wide redirect plus a hash guard makes that impossible. |
| Desktop GUI download bridge (`gui/gui.py`, `web/static/src/api.ts`) | pywebview does not handle file downloads or navigation to JSON/ZIP reliably (`window.location.href` renders JSON into the app window and drops ZIP downloads without `ALLOW_DOWNLOADS`). Registering `DesktopApi` via `js_api.save_file` opens native OS save dialogs and streams files to disk, falling back to `<a download>` in standard browsers. |
| Bounded poster download deadline & 8 Waitress worker threads (`core/backup.py`, `web/server.py`) | Full backup export separates instant disk-cached posters from uncached ones and applies a strict deadline (`max_poster_fetch_time=10.0`s) to prevent thread starvation or UI timeouts while Waitress runs with 8 threads to handle concurrent polling. |
