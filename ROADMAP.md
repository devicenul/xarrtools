# xarrtools Roadmap 🗺️

This document tracks planned future functionality, architectural changes, and user experience enhancements for the **xarrtools** application.

---

## Planned Enhancements

### 1. Frontend Modularization & Reactive State Architecture
- **Decision**: Developers are expected to install Node and build; the compiled JS is **not** checked in (it is git-ignored under `web/static/dist/`) until GitHub CI/CD can build and publish releases. `init.*` will install the Node dependencies, and `build.py` / the `run.*` launchers will run the TypeScript compile before starting or packaging the app.
- **Goal**: Refactor the monolithic `web/templates/app.js` (~3,000 lines and growing) into modular ES6/TypeScript modules or a lightweight reactive state management framework to improve maintainability, developer ergonomics, and UI responsiveness.
- **Implementation Strategy**:
  - Break `app.js` into focused ES6 modules (`api.js`, `state.js`, `dom.js`, `modals.js`, `filters.js`, `settings.js`).
  - Introduce standardized event buses / reactive state stores for filter changes, modal workflows, and notification feeds.
  - Implement progressive hydration and virtualized grid rendering for large release libraries (>500 items).
- **Code files involved**: [web/templates/app.js](web/templates/app.js), [web/templates/index.html](web/templates/index.html), [web/server.py](web/server.py).

### 2. Dockerization for NAS/Server Hosting
- **Goal**: Allow running the application inside a lightweight container on NAS systems (Synology, Unraid, QNAP) or homelab servers.
- **Implementation Strategy**:
  - Create a `Dockerfile` based on `python:3.11-alpine` to keep the footprint small (<100MB).
  - Define `/config` as a persistent volume mapping area to hold `xarrtools.db` and optional `.env` file overrides.
  - Expose port `5000` to link the internal Flask process to host requests.
  - Create a `docker-compose.yml` template to easily stand up the tool alongside Radarr and Sonarr containers.
- **Code files involved**: [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [core/db.py](core/db.py).

### 3. Background Scheduled Refreshes
- **Goal**: Automatically scan all enabled feeds (Metacritic, DVDs, TVmaze, TMDB and custom feeds) on a daily schedule, ensuring cache records stay updated without manual user trigger clicks.
- **Implementation Strategy**:
  - Integrate a background daemon thread or Python task library (like `APScheduler`) inside `server.py` starting on Flask boot.
  - Configure scan timings (e.g., run every 24 hours or customizable in Settings).
  - Scrape calendars, enrich results, and store entries in the SQLite database cache.
  - Log scan statistics and broadcast a notification update payload to the UI sidebar.
- **Code files involved**: [web/server.py](web/server.py), [web/templates/app.js](web/templates/app.js).

### 4. GitHub Builds and Releases Setup
- **Goal**: Automate PyInstaller compilation and packaging workflows on GitHub tag triggers, distributing binary builds directly via GitHub Releases.
- **Implementation Strategy**:
  - Create GitHub Actions workflows for multi-platform matrices (Ubuntu, macOS, Windows).
  - Run `pytest` test suites across platforms before building executables (`init.*` already installs `requirements-dev.txt`; `build.py` is the single build entry point to call).
  - Generate release artifacts (`.dmg`, `Setup.exe`, standalone binaries) and attach them to GitHub Releases.
- **Code files involved**: `.github/workflows/build.yml`.

### 5. Structured Logging Architecture
- **Status**: Only `core/tmdb.py` and `core/config.py` use `logging` today; `cli/cli.py` still has ~78 `print` calls and `core/scraper.py`, `core/db.py` and `web/server.py` a few more.
- **Goal**: Implement systematic, configurable, structured logging across all core scraper classes, API wrappers, database operations, and server endpoints to facilitate easier troubleshooting and telemetry.
- **Implementation Strategy**:
  - Re-architect simple print statements and sporadic `app.logger.error` instances into a unified Python standard `logging` setup.
  - Support log level configuration (e.g., DEBUG, INFO, WARNING, ERROR) via Settings.
  - Set up rotating log file handler (`xarrtools.log`) alongside console logging.
- **Code files involved**: [core/config.py](core/config.py), [web/server.py](web/server.py), [cli/cli.py](cli/cli.py).

### 6. Standardized Code Documentation & Type Annotations
- **Status**: Partially done: about half of the functions carry return annotations (`web/server.py` is the main gap, 1 of 31), and `AGENTS.md` / `docs/` now describe the architecture.
- **Goal**: Standardize and enrich inline code documentation, block comments, and docstrings across all modules to improve code legibility and maintainability.
- **Implementation Strategy**:
  - Perform a thorough audit of the code modules, ensuring all classes, utility functions, routes, and regex matching/parsing blocks have descriptive PEP 257 compliant docstrings.
  - Add comprehensive Python type hinting (`typing` annotations) across all core and CLI modules.
  - Add context comments explaining non-trivial business logic, database queries, and test isolation design details.
- **Code files involved**: all Python files under `core/`, `web/`, and `cli/`.

### 7. Free Packaging and Distribution Pipeline
- **Goal**: Create cross-platform installation packages and setup distribution channels completely free of charge, avoiding developer registration fees.
- **Implementation Strategy**:
  - **macOS (Homebrew Tap & DMG)**: Distribute the compiled `.app` bundle inside an unsigned drag-and-drop `.dmg` using `create-dmg` or `dmgbuild`. Create a custom Homebrew Tap repository (`homebrew-xarrtools`) with a Ruby formula to distribute the pre-compiled binary seamlessly via `brew install xarrtools`. Provide clear instructions for Gatekeeper bypass (`xattr -d com.apple.quarantine`).
  - **Windows (WinGet & Inno Setup)**: Use `Inno Setup` to bundle the binary into a custom `Setup.exe` installer for free. Submit the application to the community-driven Windows Package Manager (`winget`) repository so users can install it via `winget install xarrtools`.
  - **SmartScreen Whitelisting**: Set up a workflow to submit new release binary hashes to the Microsoft Security Intelligence File Submission portal for free analysis, which builds reputation and clears false-positive SmartScreen warnings.
  - **Python Package (PyPI)**: Distribute the app as a standard package on PyPI, enabling installation via `pipx install xarrtools` to bypass OS code-signing limitations completely.
- **Code files involved**: [build.py](build.py), [build.sh](build.sh), [build.bat](build.bat), [build.ps1](build.ps1).

---

## Completed Features

### ✓ Agent Documentation (AGENTS.md and docs/)
- Added `AGENTS.md`, `docs/architecture.md` and `docs/decisions.md` describing purpose, architecture and design rationale, with a test that fails when documented paths or symbols disappear.

### ✓ Single Cross-Platform Build Script
- `build.py` now holds all PyInstaller logic; `build.sh` / `build.ps1` / `build.bat` are thin wrappers, and `init.*` install `requirements-dev.txt` (pytest, pytest-cov, pyinstaller).

### ✓ Bulk Archive and Filter Invert
- "Archive all filtered" button (`POST /api/archive/batch`) and an "Invert" button on every filter dropdown.

### ✓ Country and Language Metadata with Multi-Select Filters
- Country (ISO code) and original language are collected from TVmaze, TMDB and enrichment, stored in the cache, shown as a card badge and filterable from the sidebar.

### ✓ Movie De-duplication and Unicode-Safe Title Keys
- `dedupe_movies` merges the same film across sources (ids, equal titles, subtitle variants) without merging conflicting ids; the title key keeps non-Latin letters so Greek/Cyrillic titles no longer collapse together.

### ✓ TMDB Movie Source and TVmaze Schedule Feed
- TMDB replaces the Cloudflare-blocked Letterboxd feed (chunked 7-day discovery plus rich enrichment); TVmaze's full schedule supplies upcoming TV premieres and specials.

### ✓ Sticky Manual Archives
- Items archived by hand are never resurfaced by new metadata.

### ✓ Backup & Restore Settings and Cache (Web UI, Standalone App, and CLI)
- Export and import configuration settings and discovery cache databases with full schema validation and checksum integrity.

### ✓ Low-Metadata Auto-Archiving & Smart Unarchiving with Badging
- Automatically inspects the 4 core metadata fields (**Title**, **Studio/Network**, **Cast**, and **Plot**).
- Releases with $\ge 2$ missing/unavailable core fields are automatically marked as archived (`is_archived = 1`) to keep the discovery feed clean of low-quality entries.
- When an archived release gains newly discovered metadata on subsequent scans, background healing, or manual refresh, it is automatically unarchived (`is_archived = 0`) and tagged with `has_new_metadata = 1`.
- The Web UI displays an eye-catching `✨ New metadata` badge on the release card.
- Re-archiving an item immediately resets `has_new_metadata` back to `0`.

### ✓ Hybrid Quality Profile & Root Folder Presets (with Sonarr Language Profile Removal)
- Added a 3-tier preset hierarchy for both Radarr and Sonarr in the Add Media dialog (Web UI and CLI):
  1. **Primary**: Explicit defaults configured in Server Settings (`#panel-connections`).
  2. **Fallback**: Most-Recently-Used (MRU) profile and root folder selection from the last added item of that media type.
  3. **Safety Fallback**: Graceful fallback to index 0 if IDs/paths become invalid on the server.
- Added dropdown selectors for Radarr and Sonarr default quality profiles and root folders in the Server Settings modal.
- Completely removed deprecated Sonarr Language Profiles across the client wrapper, server API endpoints, Web UI modal, CLI workflows, and test suites.

### ✓ Core Backend Architecture & Security Overhaul
- **Security Hardening**: Fortified the poster image proxy against SSRF and Path Traversal with strict destination IP range validation (blocking IPv4/IPv6 private ranges, loopback, link-local, and AWS metadata 169.254.169.254), timeout enforcement, stream piping, and `nosniff` headers. Added strict database startup permission checks and enforced `X-API-Key` authentication on all data-modifying API routes.
- **Performance & Concurrency**: Refactored `core/config.py` to use an in-memory cached state with a `refresh()` method to eliminate N+1 DB query spikes. Tuned SQLite WAL mode with `busy_timeout = 5000` and composite indexing, and added chunked batch insertion (`add_cached_items_batch`).
- **Connection Pooling & Rate Limiting**: Added persistent `requests.Session` connection pooling with urllib3 `Retry` backoff and token-bucket `RateLimiter` classes (10/s Wikipedia, 2/s TVMaze) in `core/enricher.py`.
- **Background Library Caching**: Added a background thread to cache Sonarr/Radarr libraries locally, preventing redundant full-library REST calls on discovery scans.

### ✓ Standalone Desktop App UI (Captive Browser Window)
- Implemented `gui/gui.py` using `PyQt5.QtWebEngineWidgets` (with automatic fallback to the standard browser if PyQt5 is unavailable).
- Runs the Flask web server in a daemon background thread and renders the UI inside a native desktop application frame.

### ✓ Protocol Fallback for Server Configurations & Custom Feeds
- Automatically detects and falls back between HTTPS and HTTP protocols for scheme-less addresses configured in Sonarr/Radarr settings or custom feed URLs.

### ✓ Director and Producer Movie Metadata
- Retrieves movie directors and producers via Wikipedia and displays them inline on movie cards.

### ✓ Sorting Options for Scanned Media Lists
- Enables sorting TV shows and movies dynamically by release/premiere date, title, or studio, defaulting to chronological ascending.

### ✓ "Add Only" Option in Media Addition Modals
- Provides an "Add Only" option when adding a show/movie to download clients without triggering an immediate indexer search scan.

### ✓ Embed App Icons in Compiled Binaries & Runtime
- Embeds application icon assets (`.ico` for Windows, `.icns` for macOS, and `.png` for Linux) inside PyInstaller executable builds.

### ✓ User-Defined Custom Feeds (RSS, JSON, HTML)
Supports custom media discovery calendars/feeds beyond the built-in Metacritic and DVD release schedules. Users can define custom RSS/XML feeds, JSON API sources, or raw HTML tables with custom CSS selectors/JSONPath mapping configurations directly in the Settings GUI. Includes automated validation controls, SSRF protections, a dry-run diagnostic preview panel, and a "Restore Defaults" button to reload seeded presets.

### ✓ GPL v3.0 License Integration
Committed the standard GNU General Public License v3.0 to the repository root.


### ✓ Cross-Platform Launcher Scripts and Compilation (Windows, macOS, Linux)
Automated launcher scripts (`run.bat` / `run.sh`) handle virtual environment setup and dependency installation on Windows, macOS, and Linux. PyInstaller compilation bundles the application into standalone single-file executables via `build.bat` and `build.sh`, with `sys._MEIPASS` path resolution for compiled asset access.

### ✓ Comprehensive Unit and Coverage Testing
Designed and implemented a complete testing framework using `pytest` and `pytest-cov`, currently at **~89% statement coverage** (1,070+ tests) across `core` library logic, the Flask `web` backend, and the interactive terminal `cli`, plus Node-based behavioural tests for the sidebar filter JavaScript. Utilizes mock integrations for external REST clients (Sonarr, Radarr, TMDB, TVMaze) and isolates execution to a temporary SQLite test database to ensure completely clean, isolated, and deterministic test runs.

### ✓ Reorganized Codebase & Sensible Package Layout
Removed the redundant nested `xarrtools/xarrtools/` packaging. Reorganized the codebase into clean top-level directories: `core` (shared domain logic and database layers), `web` (Flask web server and templates), and `cli` (interactive terminal console manager). All imports have been restructured and tested successfully.

### ✓ Persistent & Strict In-Library Detection
Added a persistent `is_in_library` column inside the SQLite database cache, enabling cached status retention across reloads. Implemented strict ID-based matching (TVDB/TMDB ID or IMDb ID) against live Radarr and Sonarr libraries during scans, metadata updates, and additions. Supports unconfigured Sandbox/Demo mode additions by simulating and persisting in-library states directly within the SQLite database cache.

### ✓ Standalone Demo Mode (Run Without Configuration)
Provides an interactive sandbox flow with simulated indexer lookups, options configuration (folders and quality profiles), and global search capability when Radarr/Sonarr servers are unconfigured. Adds a glowing magenta "Demo Active" badge to the sidebar indicators.

### ✓ Auto-Open Settings on Unconfigured Launch
Detects on load if both Radarr and Sonarr are unconfigured and automatically triggers the Settings panel so the user knows where connection credentials can be input.

### ✓ Clickable Poster Art Link Navigation
Wraps card poster graphics in anchor tags that redirect to external metadata sites (IMDb for movies, TVDB/TVMaze for TV series) in a new browser tab with hover states and active scales preserved.

### ✓ Fixed Settings Modal Dialog Layout Dimensions
Sets a static size for the Settings modal card, styling form bodies with flex layouts and scroll limits to prevent vertical page resizing during settings tab transitions.

### ✓ Theme Synchronization inside Settings Tab
Adds a Theme Mode dropdown inside the Settings "View Options" tab, synchronized in real-time with the body classes, localStorage, and the header theme toggler.

### ✓ Light Mode Support with Switch Toggle
Implemented light mode styling overrides, tuned HSL color palettes, localStorage preference saving, and generated optimized light logo/favicon assets (`logo_light.png` and `favicon_light.png`).

### ✓ Non-Blocking Scan Progress Pop-Over & Startup Progress
Replaced the full-screen blocking overlay with a bottom-right floating scan status popup. Implemented thread-safe background status APIs on the server, a client-side polling interval, and a state-guard to ignore latency gaps. Configured startup cache loads to also utilize this progress card.

### ✓ Collapsible & Scrollable Recent Activity Sidebar
Restructured the Recent Activity sidebar container to be collapsed by default with rotating chevron transition states, scrolling within the sidebar boundaries rather than pushing options off-screen.

### ✓ Refresh Icon Spinner Background Fixed
Replaced standard text emoji 🔄 with a custom vector SVG circular arrow, ensuring a completely transparent background during rotation and resolving system-specific font background constraints.

### ✓ Radarr Track Collection / Box Set Exposure
Allows users to automatically track and monitor entire TMDb Movie Collections (such as trilogies or franchise box sets) in Radarr when adding individual movies. Exposes TMDb collection status as visual badges inside movie indexer results and adds config options to enable collection monitoring when adding titles.

### ✓ Global Search Relocated to Sidebar Navigation Badges Panel
Moved the Global Search control to a dedicated cyberpunk-styled navigation button next to the Radarr and Sonarr status badges in the sidebar header. When active, it displays a glowing neon-cyan outline and switches the main window to the search panel interface.

### ✓ Text Search Input Clear Option (x)
Integrated absolute-positioned clear buttons inside the text search inputs (`#search-bar` and `#global-search-input`). The clear button dynamically shows when content is typed and clears/refocuses on click.

### ✓ Stacked Genre & Studio/Network Multiselect Dropdowns
Added vertically-stacked dropdown selectors inside the sidebar `.filter-card` to filter shows and movies by genre and network/studio. Supports multiselect checkboxes, "Clear All" controls, and filters are bypassed (inactive) when empty.

### ✓ Cache Missing Data Healing on Scan/Refresh
Scans automatically identify incomplete cache records (e.g., missing poster, ratings, or IDs) and enrich them from live metadata feeds. Preserves the `is_archived` status and uses a 24-hour rate limit check to prevent redundant API queries.

### ✓ Media Rating Badges (Rotten Tomatoes / Metacritic / IMDb)
Displays IMDb, Metacritic, and Rotten Tomatoes ratings directly as styled, color-coded badges on discovery cards and global search cards. Automatically enriches TV movie ratings and stores values inside SQLite cache table schema.

### ✓ Media Poster Art & 2xn Card Layout
Queries Sonarr, Radarr, and TVMaze metadata providers to locate public image links, saves them inside local cache, and designs cards into a split-layout showcasing 2:3 vertical poster art on the left, scaling the card grid to a balanced 2xn layout.

### ✓ Global Search for Online Media Items
Allows users to query any movie or TV show title globally using Sonarr/Radarr indexer lookup APIs, view results with poster art, check library status, and add items directly.

### ✓ Load Cached Discoveries on Initial Startup
Immediately pulls and renders non-filtered, cached discoveries from the local SQLite database that match the current date filters on page load.

### ✓ Collapse Empty Sections in UI
Automatically hide the TV Shows or Movies section containers in the Web UI if active search inputs, tab selections, or filters yield zero visible cards.

### ✓ Title Matching Regardless of Year Setting
Added a user setting to match on the same title regardless of year if a unique ID is not available, resolving matching issues for returning seasons of shows.

### ✓ Brand App Icon and Favicon Creation
Designed a custom neon-cyberpunk hot-magenta/cyan logo concept, built a PowerShell resize helper script, and integrated favicons and logo elements.

### ✓ Settings Dialog Reorganization
Overhauled settings layout into a responsive tabbed interface (Servers, Scanning, View Options, System Diagnostics) with cache metrics and wipe utilities.

### ✓ Media External Links and Search Chips
Introduced collapsible source links inside media cards, including direct deep links to IMDb, TMDB, TVDB, Metacritic, and Google.
