# xarrtools Roadmap 🗺️

This document tracks planned future functionality, architectural changes, and user experience enhancements for the **xarrtools** application.

---

## Planned Enhancements

### 1. Python Compilation to Binary (Windows, macOS, Linux)
- **Goal**: Enable users to run the web server and CLI directly on Windows, macOS, and Linux without installing Python, setting up virtual environments, or managing dependencies manually.
- **Implementation Strategy**:
  - Configure `PyInstaller` to bundle the workspace on each respective operating system:
    ```bash
    pyinstaller --onefile --add-data "xarrtools/templates:xarrtools/templates" main.py  # macOS/Linux
    pyinstaller --onefile --add-data "xarrtools/templates;xarrtools/templates" main.py  # Windows
    ```
  - Modify file path references (e.g., database path, templates folder) to check for `sys._MEIPASS` when running compiled.
  - Incorporate the compiled binary output workflow into automated build pipeline scripts (e.g., `build.bat`, `build.sh`).
- **Code files involved**: [main.py](file:///d:/Workspaces/Projects/xarrtools/main.py), [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py).

### 2. Dockerization for NAS/Server Hosting
- **Goal**: Allow running the application inside a lightweight container on NAS systems (Synology, Unraid, QNAP) or homelab servers.
- **Implementation Strategy**:
  - Create a `Dockerfile` based on `python:3.11-alpine` to keep the footprint small (<100MB).
  - Define `/config` as a persistent volume mapping area to hold `xarrtools.db` and optional `.env` file overrides.
  - Expose port `5000` to link the internal Flask process to host requests.
  - Create a `docker-compose.yml` template to easily stand up the tool alongside Radarr and Sonarr containers.
- **Code files involved**: [Dockerfile](file:///d:/Workspaces/Projects/xarrtools/Dockerfile), [docker-compose.yml](file:///d:/Workspaces/Projects/xarrtools/docker-compose.yml), [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py) (relocate database if running in Docker to `/config/xarrtools.db`).

### 3. Background Scheduled Refreshes
- **Goal**: Automatically scan Metacritic and DVD releases on a daily schedule, ensuring cache records stay updated without manual user trigger clicks.
- **Implementation Strategy**:
  - Integrate a background daemon thread or Python task library (like `APScheduler`) inside `server.py` starting on Flask boot.
  - Configure scan timings (e.g., run every 24 hours).
  - Scrape calendars, enrich results, and store entries in the SQLite database cache.
  - Log scan statistics and broadcast a notification update payload to the UI sidebar (using simple long-polling or WebSockets).
- **Code files involved**: [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

### 4. macOS and Linux Launch Scripts
- **Goal**: Create automated bash setup launcher scripts (`run.sh`) mirroring `run.bat` to handle venv creation, package installation, environment variables setup, and server execution seamlessly on Unix-based systems.
- **Code files involved**: [run.sh](file:///d:/Workspaces/Projects/xarrtools/run.sh) [NEW].

### 5. In-Library Detection Improvements
- **Goal**: Ensure 100% accuracy for automatically tagging items already present in Sonarr/Radarr, even when explicit TVDB/TMDB IDs are missing or mismatched.
- **Implementation Strategy**:
  - Enhance status checking functions to compare normalized titles, release years (allowing ±1 year margin), and clean punctuation.
  - Query alternative metadata sites to resolve ID mismatches if the primary calendar crawler lacks TVDB/TMDB links.
- **Code files involved**: [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/client.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/client.py).

### 6. Clean up Directory Structure
- **Goal**: Clean up project assets, configuration locations, and temporary folders to prepare the codebase for formal Python packaging and distributing.
- **Implementation Strategy**:
  - Move template assets to standard location hierarchies, organize dev scratch scripts, and ensure proper packaging standards.

### 7. Unit Tests
- **Goal**: Implement a robust suite of unit and integration tests to ensure logic stability and prevent regressions during updates.
- **Implementation Strategy**:
  - Set up a test framework (using `unittest` or `pytest`).
  - Mock Radarr/Sonarr client API calls, SQLite DB connection tables, and HTML scraper inputs to validate data parsing.
- **Code files involved**: [tests/](file:///d:/Workspaces/Projects/xarrtools/tests) [NEW].

### 8. User-Defined Media Feeds
- **Goal**: Support custom media discovery calendars/feeds beyond the pre-configured Metacritic and DVD calendar schedules.
- **Implementation Strategy**:
  - Allow users to enter custom feed URLs (RSS feeds, JSON feeds, or scrape-able HTML) in Settings.
  - Support setting a basic schema mapping or custom parsing regex pattern to ingest titles, dates, descriptions, and IDs.
- **Code files involved**: [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py), [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

### 9. Code and Agentic Review
- **Goal**: Complete a thorough security and performance review of database locks, scraper concurrency, and exception mapping layers.

### 10. GitHub Builds and Releases Setup
- **Goal**: Automate PyInstaller compilation and packaging workflows on GitHub tag triggers, distributing binary builds directly via GitHub Releases.

### 11. GPL v3 License Integration
- **Goal**: Commit a standard GPL v3.0 license file to the repository.
- **Code files involved**: [LICENSE](file:///d:/Workspaces/Projects/xarrtools/LICENSE) [NEW].

### 12. Standalone Desktop App UI (Captive Browser Window)
- **Goal**: Enable running the application as a standalone desktop program using a captive web-view wrapper (like `pywebview` or `PyQtWebEngine`) to run the server in the background and display the UI inside a dedicated application frame.
- **Code files involved**: [main.py](file:///d:/Workspaces/Projects/xarrtools/main.py), [xarrtools/gui.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/gui.py) [NEW].

---

## Completed Features

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
