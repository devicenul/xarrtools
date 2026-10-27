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
| `scripts/build.py` is the single build implementation | Three scripts had drifted; wrappers only ensure the venv. |
| No Makefile | `make` isn't available on stock Windows; per-OS differences live in `scripts/build.py`. |
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
| `python:3.12-slim` base image for Docker | Avoids musl libc compatibility and wheel compilation issues inherent to Alpine while remaining lean (~150MB). |
| Multi-stage Docker build with `node:20-alpine` | Builds compiled TypeScript assets during docker build without requiring checked-in generated JS in the repository. |
| Separation of `pywebview` into `requirements-gui.txt` | Keeps runtime `requirements.txt` headless-clean for Docker and server environments while `requirements-dev.txt` installs it for desktop development and PyInstaller builds. |
| Non-root container user (`appuser`) | Follows container security best practices and least privilege principles. |
| Python standard-library HEALTHCHECK probe | Queries `/api/health` using `urllib.request` directly, avoiding the need for `curl` or `wget` inside the container image. |
| Optional HTTP Basic Auth (`XARRTOOLS_AUTH_USER` / `XARRTOOLS_AUTH_PASSWORD`) | Provides security when exposing the web interface and REST APIs on local networks or behind basic reverse proxies, while remaining optional so desktop usage is unaffected. |
| Free CI matrix on GitHub Actions (`.github/workflows/ci.yml`) | devicenul/xarrtools is a public repository, making standard Actions runner minutes (Ubuntu, macOS, Windows) and GHCR package storage free and unlimited. Matrix tests Python 3.10/3.12 across OSs with cancel-in-progress concurrency. |
| macOS arm64 + Intel binary builds (`.github/workflows/release.yml`) | Uses `macos-latest` (Apple Silicon) and `macos-15-intel` (Intel x86_64) runners to produce standalone executables for both modern and legacy Mac hardware. |
| Linux binary captive window fallback | PyInstaller packages Python and application modules but not GTK/WebKit system libraries. If present on the host, the native captive window opens; otherwise, `main.py` falls back seamlessly to server mode (`--server`) and the user's default browser. |
| Unsigned binary distribution with bypass guidance | Standalone release binaries avoid commercial code-signing fees. Documentation provides Gatekeeper attribute removal (`xattr -d com.apple.quarantine`) and Windows Defender SmartScreen ("Run anyway") guidance until packaging tools (Homebrew, WinGet) are set up. |
| Stamped binary versioning (`core/version.py`, `scripts/build.py`) | Release workflows pass `--version` to `scripts/build.py`, which generates a stamped version file imported by `core/version.py` before PyInstaller compilation. This guarantees frozen executables report their version in `/api/health` and Settings without requiring environment variables. |
