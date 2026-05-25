# xarrtools Roadmap 🗺️

This document tracks planned future functionality, architectural changes, and user experience enhancements for the **xarrtools** application.

---

## 1. Application Icon (Favicon & Brand Identity)
- **Goal**: Create a recognizable visual identity for the browser tabs, desktop shortcuts, and compiled binary windows.
- **Implementation Strategy**:
  - Design a custom logo asset using an HSL color palette (neon magenta and cyan) matching the dashboard's glassmorphism style.
  - Render multiple icon variations:
    - `favicon.ico` / `favicon.png` for web browser display.
    - `logo.svg` for the UI header logo area.
    - `app.ico` for packaging binaries on Windows.
  - **Code files involved**: [templates/index.html](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/index.html) (add `<link rel="icon">`), [templates/style.css](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/style.css) (replace text emoji logo with SVG).

## 2. Settings Dialog Reorganization
- **Goal**: Transition from a single long scrollable settings layout to a clean, sectioned, tabbed interface to manage settings scale.
- **Proposed Tab Structure**:
  1. **🔌 Connections**: URL fields, API keys, and dedicated **"Test Connection"** status buttons for Radarr and Sonarr.
  2. **📅 Scan Configuration**: Default past/future month sliders/inputs, and parameters for ignoring/including returning seasons.
  3. **👁️ View Preferences**: Default values for sidebar filters (Show Library, Show Archived, Default Category Tab).
  4. **⚙️ System & Cache**: Stats on cache table size, manual cache prune trigger, and a button to wipe cached entries entirely.
- **Code files involved**: [templates/index.html](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/index.html), [templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js) (tab layout switching state), [templates/style.css](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/style.css).

## 3. Python Compilation to Binary (.exe)
- **Goal**: Enable users to run the web server and CLI directly on Windows without installing Python, setting up virtual environments, or managing dependencies manually.
- **Implementation Strategy**:
  - Configure `PyInstaller` to bundle the workspace:
    ```bash
    pyinstaller --onefile --add-data "xarrtools/templates;xarrtools/templates" main.py
    ```
  - Modify file path references (e.g., database path, templates folder) to check for `sys._MEIPASS` (temp folder extraction path used by PyInstaller) when running compiled.
  - Incorporate the compiled binary output workflow into an automated build pipeline script (e.g., `build.bat`).
- **Code files involved**: [main.py](file:///d:/Workspaces/Projects/xarrtools/main.py), [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py).

## 4. Dockerization for NAS/Server Hosting
- **Goal**: Allow running the application inside a lightweight container on NAS systems (Synology, Unraid, QNAP) or homelab servers.
- **Implementation Strategy**:
  - Create a `Dockerfile` based on `python:3.11-alpine` to keep the footprint small (<100MB).
  - Define `/config` as a persistent volume mapping area to hold `xarrtools.db` and optional `.env` file overrides.
  - Expose port `5000` to link the internal Flask process to host requests.
  - Create a `docker-compose.yml` template to easily stand up the tool alongside Radarr and Sonarr containers.
- **Code files involved**: [Dockerfile](file:///d:/Workspaces/Projects/xarrtools/Dockerfile) [NEW], [docker-compose.yml](file:///d:/Workspaces/Projects/xarrtools/docker-compose.yml) [NEW], [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py) (relocate database if running in Docker to `/config/xarrtools.db`).

## 5. Background Scheduled Refreshes
- **Goal**: Automatically scan Metacritic and DVD releases on a daily schedule, ensuring cache records stay updated without manual user trigger clicks.
- **Implementation Strategy**:
  - Integrate a background daemon thread or Python task library (like `APScheduler`) inside `server.py` starting on Flask boot.
  - Configure scan timings (e.g., run every 24 hours).
  - Scrape calendars, enrich results, and store entries in the SQLite database cache.
  - Log scan statistics and broadcast a notification update payload to the UI sidebar (using simple long-polling or WebSockets).
- **Code files involved**: [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

## 6. Media Poster Art/Images on Cards
- **Goal**: Elevate grid visualization by loading official movie and series poster images on each discovery card.
- **Implementation Strategy**:
  - Update [xarrtools/enricher.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/enricher.py) to save TMDB `poster_path` and TVDB `image` URLs during the metadata matching stage.
  - Add a `poster_url` field to the SQLite cache table schema.
  - Render the poster image on the left/top side of the card, incorporating a fallback loading gradient or card placeholder overlay if the image URL fails.
- **Code files involved**: [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py) (schema migration), [xarrtools/enricher.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/enricher.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

## 7. Media Source External Links
- **Goal**: Make it easy for users to check reviews or details by linking directly to the source database pages.
- **Implementation Strategy**:
  - Parse and store direct source URLs during metadata matching:
    - **IMDb Link**: `https://www.imdb.com/title/<imdb_id>/`
    - **TMDB Link**: `https://www.themoviedb.org/movie/<tmdb_id>` or `/tv/<tvdb_id>`
    - **TVDB Link**: `https://thetvdb.com/dereferrer/series/<tvdb_id>`
    - **Metacritic Link**: Store the origin release calendar page or item link.
  - Render small branded shortcut icon links (IMDb yellow icon, TMDB green pill, etc.) adjacent to the card titles.
- **Code files involved**: [xarrtools/enricher.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/enricher.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

## 8. Radarr Track Collection / Box Set Exposure
- **Goal**: Support checking and monitoring TMDB Movie Collections (e.g. *The Matrix Trilogy*, *The Lord of the Rings Collection*) when adding a movie.
- **Implementation Strategy**:
  - When looking up metadata for a movie, check TMDB database returns for associated `belongs_to_collection` information.
  - If a collection is found, display it in the match selector modal.
  - Add a **"Track Collection / Add Box Set"** checkbox options flag in the add form.
  - Pass the tracking parameters to `RadarrClient.add_movie` to leverage Radarr's collections mapping rules.
- **Code files involved**: [xarrtools/client.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/client.py), [xarrtools/enricher.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/enricher.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

## 9. In-Library Detection Improvements
- **Goal**: Ensure 100% accuracy for automatically tagging items already present in Sonarr/Radarr, even when explicit TVDB/TMDB IDs are missing or mismatched.
- **Implementation Strategy**:
  - Enhance status checking functions to compare normalized titles, release years (allowing ±1 year margin), and clean punctuation.
  - Query alternative metadata sites to resolve ID mismatches if the primary calendar crawler lacks TVDB/TMDB links.
- **Code files involved**: [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/client.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/client.py).

## 10. Collapse Empty Sections in UI
- **Goal**: Automatically hide the TV Shows or Movies section containers in the Web UI if active search inputs, tab selections, or filters yield zero visible cards.
- **Implementation Strategy**:
  - Modify `renderMediaLists` in the UI frontend application script.
  - When list matches for either TV or Movies is empty, apply the `.hidden` helper class to the container wrappers `#section-tv` or `#section-movies` rather than just printing an empty text state.
- **Code files involved**: [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/app.js), [xarrtools/templates/index.html](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/index.html).

## 11. Load Cached Discoveries on Initial Startup
- **Goal**: Instead of greeting the user with a blank welcome panel on browser load, immediately pull and render non-filtered, cached discoveries from the local SQLite database that match the current date filters.
- **Implementation Strategy**:
  - Expose a parameter like `skip_scrape=true` on `/api/discover` or create a new endpoint `/api/cache/list`.
  - On page load (`DOMContentLoaded`), run a fast API request to retrieve cached items within the selected past/future window from `xarrtools.db`.
  - Render the cache hits immediately, transitioning the UI out of the welcome state automatically.
  - The "Scan New Releases" button can then be used explicitly to force-pull fresh scraper indexes and sync updates.
- **Code files involved**: [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

## 12. Media Rating Badges (Rotten Tomatoes / Metacritic / IMDb)
- **Goal**: Scrape and display aggregate critics and user score ratings directly on the discovery cards.
- **Implementation Strategy**:
  - Update `enricher.py` to extract Metacritic score values (often available in the scraped calendar feeds) or leverage API sources (like OMDb or TMDB) to pull Rotten Tomatoes percentage ratings and IMDb ratings.
  - Add rating fields to the SQLite cache table schema and store these scores.
  - Render visually styled rating pills (e.g. green tomato/red tomato icons, or color-coded numeric badges) inside the card badges container.
- **Code files involved**: [xarrtools/enricher.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/enricher.py), [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).

## 13. Global Search for Online Media Items
- **Goal**: Allow users to query and look up any arbitrary movie or TV show globally (beyond Metacritic or DVD calendars) directly from the Web dashboard to queue it, matching the manual search features of the CLI.
- **Implementation Strategy**:
  - Add a persistent search/lookup bar in the dashboard top header.
  - When a query is executed, call the Sonarr/Radarr indexer search APIs via `/api/lookup` and display matched search items in a temporary search result overlay grid.
  - Show quick indicators detailing if the movie/show is already in library, and let users configure quality/paths and add it directly.
- **Code files involved**: [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py), [xarrtools/templates/index.html](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/index.html), [xarrtools/templates/app.js](file:///d:/Workspaces/Projects/xarrtools/xarrtools/templates/app.js).
