# xarrtools Roadmap 🗺️

This document tracks planned future functionality, architectural changes, and user experience enhancements for the **xarrtools** application.

---

## Planned Enhancements

### 2. Dockerization for NAS/Server Hosting
- **Goal**: Allow running the application inside a lightweight container on NAS systems (Synology, Unraid, QNAP) or homelab servers.
- **Implementation Strategy**:
  - Create a `Dockerfile` based on `python:3.11-alpine` to keep the footprint small (<100MB).
  - Define `/config` as a persistent volume mapping area to hold `xarrtools.db` and optional `.env` file overrides.
  - Expose port `5000` to link the internal Flask process to host requests.
  - Create a `docker-compose.yml` template to easily stand up the tool alongside Radarr and Sonarr containers.
- **Code files involved**: [Dockerfile](file:///d:/Workspaces/Projects/xarrtools/Dockerfile), [docker-compose.yml](file:///d:/Workspaces/Projects/xarrtools/docker-compose.yml), [core/db.py](file:///d:/Workspaces/Projects/xarrtools/core/db.py) (relocate database if running in Docker to `/config/xarrtools.db`).

### 3. Background Scheduled Refreshes
- **Goal**: Automatically scan Metacritic and DVD releases on a daily schedule, ensuring cache records stay updated without manual user trigger clicks.
- **Implementation Strategy**:
  - Integrate a background daemon thread or Python task library (like `APScheduler`) inside `server.py` starting on Flask boot.
  - Configure scan timings (e.g., run every 24 hours).
  - Scrape calendars, enrich results, and store entries in the SQLite database cache.
  - Log scan statistics and broadcast a notification update payload to the UI sidebar (using simple long-polling or WebSockets).
- **Code files involved**: [web/server.py](file:///d:/Workspaces/Projects/xarrtools/web/server.py), [web/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/web/templates/app.js)

### 4. Code and Agentic Review
- **Goal**: Complete a thorough security and performance review of database locks, scraper concurrency, and exception mapping layers.

### 5. GitHub Builds and Releases Setup
- **Goal**: Automate PyInstaller compilation and packaging workflows on GitHub tag triggers, distributing binary builds directly via GitHub Releases.

### 6. Standalone Desktop App UI (Captive Browser Window)
- **Goal**: Enable running the application as a standalone desktop program using a captive web-view wrapper (like `pywebview` or `PyQtWebEngine`) to run the server in the background and display the UI inside a dedicated application frame.
- **Code files involved**: [main.py](file:///d:/Workspaces/Projects/xarrtools/main.py), [gui/gui.py](file:///d:/Workspaces/Projects/xarrtools/gui/gui.py) [NEW].

### 7. Sufficient Logging
- **Goal**: Implement systematic, configurable, structured logging across all core scraper classes, API wrappers, database operations, and server endpoints to facilitate easier troubleshooting and telemetry.
- **Implementation Strategy**:
  - Re-architect simple print statements and sporadic `app.logger.error` instances into a unified Python standard `logging` setup.
  - Support log level configuration (e.g., DEBUG, INFO, WARNING, ERROR) via Settings.
  - Set up rotating log file handler (`xarrtools.log`) alongside console logging.
- **Code files involved**: [core/config.py](file:///d:/Workspaces/Projects/xarrtools/core/config.py), [web/server.py](file:///d:/Workspaces/Projects/xarrtools/web/server.py), [cli/cli.py](file:///d:/Workspaces/Projects/xarrtools/cli/cli.py).

### 8. Sufficient Comments in the Code
- **Goal**: Standardize and enrich inline code documentation, block comments, and docstrings across all modules to improve code legibility and ease codebase onboarding for external developers or automated agents.
- **Implementation Strategy**:
  - Perform a thorough audit of the code modules, ensuring all classes, utility functions, routes, and complex regex matching/parsing blocks have descriptive PEP 257 compliant docstrings.
  - Standardize docstring structure (describing arguments, return types, and potential side-effects).
  - Add context comments explaining non-trivial business logic, database queries, and test isolation design details.
- **Code files involved**: all Python files under `core/`, `web/`, and `cli/`.

### 9. Free Packaging and Distribution Pipeline
- **Goal**: Create cross-platform installation packages and setup distribution channels completely free of charge, avoiding developer registration fees.
- **Implementation Strategy**:
  - **macOS (Homebrew Tap & DMG)**: Distribute the compiled `.app` bundle inside an unsigned drag-and-drop `.dmg` using `create-dmg` or `dmgbuild`. Create a custom Homebrew Tap repository (`homebrew-xarrtools`) with a Ruby formula to distribute the pre-compiled binary seamlessly via `brew install xarrtools`. Provide clear instructions for Gatekeeper bypass (`xattr -d com.apple.quarantine`).
  - **Windows (WinGet & Inno Setup)**: Use `Inno Setup` to bundle the binary into a custom `Setup.exe` installer for free. Submit the application to the community-driven Windows Package Manager (`winget`) repository so users can install it via `winget install xarrtools`.
  - **SmartScreen Whitelisting**: Set up a workflow to submit new release binary hashes to the Microsoft Security Intelligence File Submission portal for free analysis, which builds reputation and clears false-positive SmartScreen warnings.
  - **Python Package (PyPI)**: Distribute the app as a standard package on PyPI, enabling installation via `pipx install xarrtools` to bypass OS code-signing limitations completely.
- **Code files involved**: [build.sh](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/build.sh), [build.bat](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/build.bat).

### 10. Filter Scanned Items with Missing Crucial Metadata
- **Goal**: Ignore found items that do not have a title, studio/network, cast, or plot available when scanning, keeping the discovery list clean of incomplete entries.
- **Implementation Strategy**:
  - Update scanning/enrichment loops to inspect the resolved metadata fields.
  - Exclude items that fail to resolve essential fields (title, studio, cast, or plot).
- **Code files involved**: [core/scraper.py](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/core/scraper.py), [core/enricher.py](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/core/enricher.py).

### 11. Server-Specific Default Quality Profiles
- **Goal**: Allow users to select a default quality profile for Radarr and Sonarr individually inside the Settings panel.
- **Implementation Strategy**:
  - Add database settings for default Radarr and Sonarr quality profile IDs.
  - Render dropdown selectors populated from available profiles in the Settings UI under Server configs.
  - Automatically pre-select these configured profiles when opening the media addition confirmation modals.
- **Code files involved**: [core/db.py](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/core/db.py), [web/server.py](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/web/server.py), [web/templates/app.js](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/web/templates/app.js), [web/templates/index.html](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/web/templates/index.html).

### 12. "Add Only" Option in Media Addition Modals
- **Goal**: Provide a separate "Add" button alongside the existing "Add and Search" button when queueing movie/show additions.
- **Implementation Strategy**:
  - Add a secondary submission button to the addition confirmation modal.
  - Configure the backend payload to omit the instant indexer search trigger command (`addSearch = false`) when this secondary button is clicked.
- **Code files involved**: [web/templates/index.html](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/web/templates/index.html), [web/templates/app.js](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/web/templates/app.js), [web/server.py](file:///Users/rrjefferson/Workspaces/Projects/xarrtools/web/server.py).


---

## Completed Features

### ✓ User-Defined Custom Feeds (RSS, JSON, HTML)
Supports custom media discovery calendars/feeds beyond the built-in Metacritic and DVD release schedules. Users can define custom RSS/XML feeds, JSON API sources, or raw HTML tables with custom CSS selectors/JSONPath mapping configurations directly in the Settings GUI. Includes automated validation controls, SSRF protections, a dry-run diagnostic preview panel, and a "Restore Defaults" button to reload seeded presets.

### ✓ GPL v3.0 License Integration
Committed the standard GNU General Public License v3.0 to the repository root.


### ✓ Cross-Platform Launcher Scripts and Compilation (Windows, macOS, Linux)
Automated launcher scripts (`run.bat` / `run.sh`) handle virtual environment setup and dependency installation on Windows, macOS, and Linux. PyInstaller compilation bundles the application into standalone single-file executables via `build.bat` and `build.sh`, with `sys._MEIPASS` path resolution for compiled asset access.

### ✓ Comprehensive Unit and Coverage Testing
Designed and implemented a complete testing framework using `pytest` and `pytest-cov`, reaching **100% statement coverage** across all modules including `core` library logic, the Flask `web` backend, and the interactive terminal `cli`. Utilizes mock integrations for external REST clients (Sonarr, Radarr, TMDB, TVMaze) and isolates execution to a temporary SQLite test database to ensure completely clean, isolated, and deterministic test runs.

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
