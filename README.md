# xarrtools 🍿

An interactive web-based and CLI media discovery manager designed to scrape upcoming/recent movie and TV releases, enrich them with rich metadata (cast, genre, trailer, studio network), cache them in a local SQLite database, and add them to **Radarr** and **Sonarr** instances.

---

## Key Features

1. **Stunning Web Dashboard**: A modern, premium dark-themed interface utilizing glassmorphism, cyan/magenta glowing themes, and subtle animations.
2. **Metadata Enrichment**: Automatically matches Metacritic and DVD release calendars with IMDb, TVDB, and TMDB IDs, fetching plots, network details, cast, ratings, and trailers.
3. **Persistent Local Database Cache**: Caches scraped discoveries in a local SQLite database (`xarrtools.db`) to ensure instant load times. Caches are automatically pruned if older than 12 months.
4. **Missing Data Healing on Scans**: During new scans, the backend automatically detects incomplete cached entries (e.g. missing posters, ratings, or IDs) and re-enriches them from live APIs. A 24-hour rate limit check prevents redundant lookups.
5. **Interactive Match Selector**: First-click on "Add" initiates a search across indexers, highlights the best matches, and lets you choose the exact movie or series to add.
6. **Radarr Movie Collection / Box Set Exposure**: Automatically exposes whether a movie belongs to a TMDb collection (e.g., *The Matrix Collection*) with styled badges in search matches, and allows monitoring the entire collection in Radarr using a "Track Collection" option.
7. **Dynamic Library Checking**: Automatically checks your existing Radarr/Sonarr libraries in batch queries to label items already in your possession.
8. **Archive Feature**: Archive release discoveries to hide clutter without affecting your Sonarr/Radarr indexers.
9. **Global Search next to status badges**: Locate any movie or show globally using a glowing, cyan-themed navigation button next to the Radarr and Sonarr status badges in the sidebar.
10. **Interactive Filter Controls**: 
    - Text search input clear buttons `(x)` to instantly reset search fields.
    - Vertically stacked multiselect dropdowns for Genres and Studios/Networks, populated dynamically from current discovery lists, with one-click "Clear All" buttons.
11. **Robust Settings Dialog**: Update server URLs, API keys, default months, default filter behaviors, and perform database maintenance directly from the dashboard.
12. **Rich CLI Version**: A terminal-based version of the tool with rich table layout formatting.

---

## Codebase Structure

```
xarrtools/
│
├── main.py                     # Entry point. Launches Web Server or CLI mode
├── run.bat                     # Windows automated setup launcher
├── requirements.txt            # Python dependencies
├── README.md                   # System documentation
├── ROADMAP.md                  # Project roadmap and completed features log
├── .gitignore                  # Git untracked pattern definitions
│
└── xarrtools/                  # Primary Python Package
    ├── __init__.py
    ├── cli.py                  # Rich Console terminal implementation
    ├── client.py               # Radarr & Sonarr REST API wrappers
    ├── config.py               # Dynamic settings accessor (DB with .env fallback)
    ├── db.py                   # SQLite Cache & Settings database manager
    ├── enricher.py             # Metadata crawler (TVDB, TMDB, IMDb matching)
    ├── scraper.py              # Metacritic / Release calendar HTML scrapers
    ├── server.py               # Flask web server and API controllers
    │
    └── templates/              # Web Frontend Assets
        ├── index.html          # Dashboard skeleton structure and overlays
        ├── style.css           # Premium glassmorphism styles and transitions
        └── app.js              # Client state, filter events, and modal controller
```

---

## Detailed Component Guide

### [main.py](file:///d:/Workspaces/Projects/xarrtools/main.py)
Determines whether to start the server or launch CLI mode based on input flags. By default, it schedules a timer to open your default browser to `http://localhost:5000` and starts the Flask server.

### [xarrtools/db.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/db.py)
Performs database initialization (`init_db`) creating the `settings` and `cache` tables. 
- If the settings table is empty, it migrates variables from `.env` to seed the database.
- Implements settings getter/setter, cache search, and archiving states.
- Automatically cleans expired cache entries older than 365 days on launch (`clean_expired_cache`).

### [xarrtools/config.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/config.py)
Provides a global configuration manager. Properties like `radarr_url` and `sonarr_api_key` retrieve settings dynamically from the SQLite `settings` table, falling back to local environment variables if settings are missing or uninitialized.

### [xarrtools/client.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/client.py)
Implements robust wrappers (`RadarrClient` and `SonarrClient`) to perform CRUD actions against Radarr and Sonarr instances. Employs `get_library()` to obtain whole libraries in single queries, accelerating status resolution. `RadarrClient.add_movie` supports collection tracking using the `"monitor": "movieAndCollection"` flag.

### [xarrtools/scraper.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/scraper.py)
Scrapes TV premiers from Metacritic's calendars and movie schedules from DVD Release calendars. Normalizes scraped titles for matching.

### [xarrtools/enricher.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/enricher.py)
Uses public metadata sources (TMDB/TVDB/Wikipedia/YouTube) to find best-fit IDs, network/studio info, cast lists, genre taggings, ratings (IMDb, Metacritic, Rotten Tomatoes), and trailer URLs.

### [xarrtools/server.py](file:///d:/Workspaces/Projects/xarrtools/xarrtools/server.py)
The web server module. Exposes:
- `GET /api/config`: Resolves target root folders and profiles from Radarr/Sonarr.
- `GET/POST /api/settings`: Manages DB configurations.
- `POST /api/archive`: Persists archiving selections.
- `GET /api/discover`: Aggregates, heals, and filters scraper outputs against DB cache records.
- `POST /api/cache/refresh`: Forces live API metadata re-enrichment for a single cache item.
- `POST /api/cache/prune`: Manually triggers pruning of cache entries older than 12 months.
- `POST /api/cache/clear`: Manually wipes all cache records.
- `GET /api/lookup`: Searches indexers for a title.
- `POST /api/add`: Deploys media items (optionally collections) to Radarr or Sonarr.

---

## Quick Start (Windows Setup)

The easiest way to configure and run the application on Windows:

1. **Auto Start**: Double-click `run.bat` in the root folder.
2. The launcher will construct a Python virtual environment (`.venv`), install dependencies, generate a `.env` configuration file from the template, and open it in Notepad.
3. Configure your URL links and API keys in the `.env` file, save, close, and re-launch `run.bat`.
4. The dashboard will automatically launch in your browser.

---

## Usage Modes

### Web Interface Mode
Launch the application:
```bash
python main.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.
- **Scanning**: Use the sliders in the left panel to configure the date ranges, and click **Scan New Releases**.
- **Settings**: Click the ⚙️ icon in the top left header to view or update your Radarr/Sonarr coordinates and default behaviors.
- **Global Search**: Click the 🔎 **Search** navigation badge button next to the Radarr and Sonarr status indicators in the header to search the indexers directly.
- **Filters & Search**: 
  - Clear search queries quickly with the `(x)` clear buttons inside the inputs.
  - Apply dynamic multi-select filters for Genres and Studios/Networks (stacked vertically in the sidebar) to narrow down card lists.
  - Filter using default toggles (Show Returning Seasons, Show Library Items, Show Archived Items).
- **Card Actions**: Click **Trailer** to preview, **Archive** to hide the card, or **Add** to fetch indexer matches.

### CLI Mode
Launch the CLI interface:
```bash
python main.py --cli
```
Allows searching and queueing downloads in a direct interactive command-line workflow.
