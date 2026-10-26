# xarrtools 🍿

An interactive web-based and CLI media discovery manager designed to scrape upcoming/recent movie and TV releases, enrich them with rich metadata (cast, genre, trailer, studio network), cache them in a local SQLite database, and add them to **Radarr** and **Sonarr** instances.

---

## Key Features

1. **Dual Themes (Dark & Light Modes)**: A modern, premium interface. Toggle between a neomorphic dark cyberpunk theme with glowing cyan/magenta accents and a sleek HSL light theme, complete with optimized light logo assets (`logo_light.png`, `favicon_light.png`). Themes can be switched instantly with a button next to settings and persist in `localStorage`.
2. **Non-Blocking Background Scanning & Detailed Progress**: Scraping and re-indexing run asynchronously. A bottom-right floating progress toast displays real-time details (e.g., `"Fetching metadata for X (3 of 15)"`) and a progress bar. Hitting scan or starting up doesn't lock the UI, letting you search or archive cached items during updates.
3. **Collapsible Recent Activity logs**: Recent logs scroll within a dedicated panel that is collapsed by default to save sidebar space, keeping configurations visible.
4. **Metadata Enrichment & Vector Spinners**: Automatically matches Metacritic and DVD release calendars with TMDB, TVDB, and IMDb IDs—fetching plots, cast, ratings, and trailers. Single card metadata can be refreshed with transparent, circular SVG vector icons that spin cleanly without background boxes.
5. **Persistent Local Database Cache**: Caches scraped discoveries in a local SQLite database (`xarrtools.db`) to ensure instant load times. Caches are automatically pruned if older than 12 months.
6. **Missing Data Healing on Scans**: During new scans, the backend automatically detects incomplete cached entries (e.g. missing posters, ratings, or IDs) and re-enriches them from live APIs. A 24-hour rate limit check prevents redundant lookups.
7. **Interactive Match Selector**: First-click on "Add" initiates a search across indexers, highlights the best matches, and lets you choose the exact movie or series to add.
8. **Radarr Movie Collection / Box Set Exposure**: Exposes whether a movie belongs to a TMDb collection (e.g., *The Matrix Collection*) with styled badges, allowing you to monitor the entire box set in Radarr via a "Track Collection" option.
9. **Dynamic & Persistent Library Checking**: Automatically matches discovery items against live Radarr/Sonarr libraries using strict ID matching (matching TVDB/TMDB ID or IMDb ID) to guarantee 100% accuracy. Library statuses are persisted in the local SQLite database cache, defaulting to the cached states when offline or running in Sandbox/Demo mode.
10. **Archive Feature**: Archive release discoveries to hide clutter without affecting your Sonarr/Radarr indexers.
11. **Global Search next to status badges**: Locate any movie or show globally using a glowing, cyan-themed navigation button next to the Radarr and Sonarr status badges in the sidebar.
12. **Interactive Filter Controls**: 
    - Text search input clear buttons `(x)` to instantly reset search fields.
    - Vertically stacked multiselect dropdowns for Genres and Studios/Networks, populated dynamically from current discovery lists, with one-click "Clear All" buttons.
13. **Robust Settings Dialog**: Update server URLs, API keys, default months, default filter behaviors, and perform database maintenance directly from the dashboard. Maintains a stable height and width during tab transitions.
14. **Rich CLI Version**: A terminal-based version of the tool with rich table layout formatting.
15. **Standalone Demo Sandbox Mode**: Fully browse, search, and configure addition settings (folders and profiles) using mock data without configuring Radarr or Sonarr servers. Automatically launches Settings modal on unconfigured startups and renders a glowing "Demo Active" badge in the header.
16. **Clickable Poster Links**: Wrap movie and series poster graphics in deep links to external resources (IMDb/TVDB) in new tabs.
17. **Interface Theme Sync dropdown**: Add a setting dropdown inside settings view tab to swap dark/light themes, fully synchronized in real-time with the header toggler.


---

## Codebase Structure

```
xarrtools/
│
├── main.py                     # Entry point. Launches Desktop GUI, Web Server, or CLI mode
├── init.sh / init.bat / init.ps1 # Cross-platform project initialization scripts
├── run.sh / run.bat / run.ps1  # Cross-platform automated startup launchers
├── build.py                         # Cross-platform PyInstaller build logic
├── build.sh / build.bat / build.ps1 # Thin wrappers: ensure the venv (init.*) then run build.py
├── requirements-dev.txt             # Test + build tooling (pytest, pytest-cov, pyinstaller)
├── requirements.txt            # Python dependencies
├── README.md                   # System documentation
├── ROADMAP.md                  # Project roadmap and completed features log
├── .gitignore                  # Git untracked pattern definitions
│
├── core/                       # Shared Domain Logic & Database layer
│   ├── __init__.py
│   ├── client.py               # Radarr & Sonarr REST API wrappers
│   ├── config.py               # Dynamic settings accessor (DB with .env fallback)
│   ├── db.py                   # SQLite Cache & Settings database manager
│   ├── enricher.py             # Metadata crawler (TVDB, TMDB, IMDb matching)
│   └── scraper.py              # Metacritic / Release calendar HTML scrapers
│
├── web/                        # Web Backend (Flask) & Frontend Assets
│   ├── __init__.py
│   ├── server.py               # Flask web server and API controllers
│   ├── static/                 # Frontend TypeScript source and compiled dist assets
│   │   └── src/                # Modular TypeScript frontend source
│   └── templates/              # Web Frontend HTML, CSS, images
│       ├── index.html          # Dashboard skeleton structure and overlays
│       ├── style.css           # Premium glassmorphism styles and transitions
│       ├── logo_light.png      # Light theme cropped logo
│       └── favicon_light.png   # Light theme cropped favicon
│
└── cli/                        # Command Line Interface (CLI) application
    ├── __init__.py
    └── cli.py                  # Rich Console terminal implementation
```

---

## Detailed Component Guide

### [main.py](file:///d:/Workspaces/Projects/xarrtools/main.py)
Determines whether to start the server or launch CLI mode based on input flags. By default, it schedules a timer to open your default browser to `http://localhost:5000` and starts the Flask server.

### [core/db.py](file:///d:/Workspaces/Projects/xarrtools/core/db.py)
Performs database initialization (`init_db`) creating the `settings` and `cache` tables. 
- If the settings table is empty, it migrates variables from `.env` to seed the database.
- Implements settings getter/setter, cache search, and archiving states.
- Automatically cleans expired cache entries older than 365 days on launch (`clean_expired_cache`).

### [core/config.py](file:///d:/Workspaces/Projects/xarrtools/core/config.py)
Provides a global configuration manager. Properties like `radarr_url` and `sonarr_api_key` retrieve settings dynamically from the SQLite `settings` table, falling back to local environment variables if settings are missing or uninitialized.

### [core/client.py](file:///d:/Workspaces/Projects/xarrtools/core/client.py)
Implements robust wrappers (`RadarrClient` and `SonarrClient`) to perform CRUD actions against Radarr and Sonarr instances. Employs `get_library()` to obtain whole libraries in single queries, accelerating status resolution. `RadarrClient.add_movie` supports collection tracking using the `"monitor": "movieAndCollection"` flag.

### [core/scraper.py](file:///d:/Workspaces/Projects/xarrtools/core/scraper.py)
Scrapes TV premiers from Metacritic's calendars and movie schedules from DVD Release calendars. Normalizes scraped titles for matching.

### [core/enricher.py](file:///d:/Workspaces/Projects/xarrtools/core/enricher.py)
Uses public metadata sources (TMDB/TVDB/Wikipedia/YouTube) to find best-fit IDs, network/studio info, cast lists, genre taggings, ratings (IMDb, Metacritic, Rotten Tomatoes), and trailer URLs.

### [web/server.py](file:///d:/Workspaces/Projects/xarrtools/web/server.py)
The web server module. Exposes:
- `GET /api/config`: Resolves target root folders and profiles from Radarr/Sonarr.
- `GET/POST /api/settings`: Manages DB configurations.
- `POST /api/archive`: Persists archiving selections.
- `GET /api/discover`: Aggregates, heals, and filters scraper outputs against DB cache records.
- `GET /api/scan/progress`: Exposes thread-safe progress metrics of running background scans.
- `POST /api/cache/refresh`: Forces live API metadata re-enrichment for a single cache item.
- `POST /api/cache/prune`: Manually triggers pruning of cache entries older than 12 months.
- `POST /api/cache/clear`: Manually wipes all cache records.
- `GET /api/lookup`: Searches indexers for a title.
- `POST /api/add`: Deploys media items (optionally collections) to Radarr or Sonarr.

### [cli/cli.py](file:///d:/Workspaces/Projects/xarrtools/cli/cli.py)
Interactive command line interface built using the `rich` library. Supports searching, listing configuration status, discovering new releases, and bulk adding items to Radarr or Sonarr directly from the terminal.

---

## Quick Start (Cross-Platform Initialization & Launch)

### 1. Initialize the Project
Run the initialization script for your platform to create the Python virtual environment (with automatic `$HOME/.cache` `ext4` fallback on Android/FUSE shared storage), install runtime, test and build dependencies (`requirements.txt` plus `requirements-dev.txt`: `pytest`, `pytest-cov`, `pyinstaller`), generate `.env` from `.env.example`, and initialize the SQLite database (`xarrtools.db`):

- **Linux / macOS / Android Linux VM (Bash)**:
  ```bash
  ./init.sh
  ```
- **Windows (Command Prompt / Batch)**:
  ```cmd
  init.bat
  ```
- **PowerShell (Windows PowerShell / Cross-Platform `pwsh`)**:
  ```powershell
  ./init.ps1
  ```

### 2. Launch the Application
Use the platform launcher script (which automatically runs initialization if needed and forwards any CLI flags to `main.py`):

- **Linux / macOS / Android Linux VM (Bash)**:
  ```bash
  ./run.sh            # Default standalone GUI (with browser fallback)
  ./run.sh --server   # Web server mode
  ./run.sh --cli      # Interactive Rich terminal CLI mode
  ```
- **Windows (Command Prompt / Batch)**:
  ```cmd
  run.bat
  ```
- **PowerShell**:
  ```powershell
  ./run.ps1
  ```

---

## Usage Modes

### Web Interface Mode
Launch the application:
```bash
python main.py --server
```
Open [http://localhost:5000](http://localhost:5000) in your browser.
- **Scanning**: Use the sliders in the left panel to configure the date ranges, and click **Scan New Releases**. Background progress displays in the pop-over toast.
- **Theme toggler**: Click the ☀️/🌙 icon in the header to switch between light mode and dark mode.
- **Settings**: Click the ⚙️ icon in the top left header to view or update settings.
- **Recent Activity**: Click the header in the sidebar panel to toggle log collapse states.
- **Global Search**: Click the 🔎 **Search** navigation badge button next to the Radarr and Sonarr status indicators in the header to search the indexers directly.
- **Filters & Search**: 
  - Clear search queries quickly with the `(x)` clear buttons inside the inputs.
  - Apply dynamic multi-select filters for Genres and Studios/Networks (stacked vertically in the sidebar) to narrow down card lists.
  - Filter using default toggles (Show Returning Seasons, Show Library Items, Show Archived Items).
- **Card Actions**: Click **Trailer** to preview, **Archive** to hide the card, refresh using the circular arrow icon, or **Add** to fetch indexer matches and open the download options modal (which defaults to "Add and Search").

### CLI Mode
Launch the CLI interface:
```bash
python main.py --cli
```
Allows searching and queueing downloads in a direct interactive command-line workflow.

---

## Running Tests 🧪

To execute the unit and integration tests with coverage:

1. **Linux / macOS / Android Linux VM**:
   ```bash
   source ./init.sh --env-only
   "$VENV_DIR/bin/pytest" --cov=core --cov=web --cov=cli tests/ --cov-report=term-missing
   ```
2. **Windows**:
   ```cmd
   .venv\Scripts\pytest --cov=core --cov=web --cov=cli tests/ --cov-report=term-missing
   ```
3. This runs the comprehensive test suite (testing all scrapers, config accessors, database helpers, Flask API controllers, and Rich CLI logic) against a temporary SQLite database with all external REST integrations mocked for clean, hermetic execution.
