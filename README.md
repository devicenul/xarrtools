# xarrtools

xarrtools is a companion app for Radarr and Sonarr. It tracks upcoming and new TV shows and movies across multiple feeds, checks them against your existing library, and lets you triage the list so you can add what you want to your servers in a single click.

If you run Radarr or Sonarr at home, you know the drill: finding out about new releases usually means browsing several websites, remembering what you wanted, checking whether you already downloaded it, and manually typing names into search bars. xarrtools puts that whole discovery and intake workflow in one place.

---

## What It Does

- **Discovers upcoming and new media**: Scrapes TV premieres, DVD and streaming release dates, and optional TMDB lists into a clean, searchable feed.
- **Enriches with metadata**: Pulls in plots, cast, genres, networks, trailers, and ratings from IMDb, Metacritic, and Rotten Tomatoes.
- **Spots what you already have**: Matches incoming titles against your live Radarr and Sonarr libraries by unique IDs (TMDB, TVDB, IMDb) so your existing media stays hidden by default.
- **Filters the noise**: Hide returning seasons to focus on brand-new shows, filter by genre, network, country, or language, and archive anything you are not interested in.
- **One-click intake**: Pick your quality profile and root folder, then send titles directly to Radarr or Sonarr to start monitoring and searching right away.

---

## 1. Get It Running

You can run xarrtools as a desktop app on your computer, as a Docker container on your NAS or home server, or directly from source.

### Desktop App (macOS, Windows, Linux)

Grab the latest standalone package for your operating system from [GitHub Releases](https://github.com/devicenul/xarrtools/releases):

- **macOS (Apple Silicon)**: `xarrtools-<version>-macos-arm64.zip`
- **macOS (Intel)**: `xarrtools-<version>-macos-x64.zip`
- **Windows (x64)**: `xarrtools-<version>-windows-x64.exe`
- **Linux (x64)**: `xarrtools-<version>-linux-x64.zip`

Extract the archive and run the executable.

> [!NOTE]
> **First-Launch Notes for Unsigned Binaries**
> 
> Because release binaries are built directly on GitHub Actions without commercial code-signing certificates, your operating system may ask for confirmation on first launch:
> 
> - **macOS (Gatekeeper)**: macOS might report that the developer cannot be verified. Open Terminal, navigate to the extracted folder, and clear the quarantine attribute:
>   ```bash
>   xattr -d com.apple.quarantine xarrtools
>   chmod +x xarrtools
>   ```
> - **Windows (SmartScreen)**: Windows Defender SmartScreen may display a warning prompt. Click **More info**, then click **Run anyway**.
> - **Linux**: If your desktop has GTK and WebKit libraries installed, xarrtools opens in a dedicated app window. If those system libraries are missing, it falls back to server mode and opens the interface in your default web browser.

### Docker & Docker Compose (NAS / Homelab)

If you run a home server or NAS (such as Unraid, TrueNAS, or Synology), Docker is the easiest way to run xarrtools.

Pre-built multi-architecture images (`linux/amd64` and `linux/arm64`) are published to the GitHub Container Registry.

#### Using Docker Run

```bash
docker run -d \
  --name xarrtools \
  -p 5000:5000 \
  -v ./config:/config \
  -e XARRTOOLS_AUTH_USER="admin" \
  -e XARRTOOLS_AUTH_PASSWORD="your-strong-password" \
  ghcr.io/devicenul/xarrtools:latest
```

#### Using Docker Compose

Create a `docker-compose.yml` file (or use the one in this repository):

```yaml
services:
  xarrtools:
    image: ghcr.io/devicenul/xarrtools:latest
    container_name: xarrtools
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./config:/config
    environment:
      - XARRTOOLS_HOST=0.0.0.0
      - XARRTOOLS_PORT=5000
      - XARRTOOLS_CONFIG_DIR=/config
      - XARRTOOLS_AUTH_USER=${XARRTOOLS_AUTH_USER:-}
      - XARRTOOLS_AUTH_PASSWORD=${XARRTOOLS_AUTH_PASSWORD:-}
```

Run it with:

```bash
docker compose up -d
```

Open your browser to `http://<your-server-ip>:5000`.

**Docker configuration details:**
- **Persistent storage (`/config`)**: Maps your host storage to `/config` in the container. The database (`xarrtools.db`), custom `.env` overrides, cached posters (`/config/posters`), and logs (`/config/logs`) are preserved here.
- **Port**: Default port is `5000`. Adjust your port mapping or set `XARRTOOLS_PORT` if needed.
- **Optional Basic Authentication**: When `XARRTOOLS_AUTH_USER` and `XARRTOOLS_AUTH_PASSWORD` environment variables are set, all web pages and API routes require HTTP Basic Authentication (the container health check probe at `/api/health` stays accessible without credentials).

### Running from Source

If you want to run directly from the repository:

1. **Prerequisites**: Python 3.10+ (or 3.12) and Node.js 20+.
2. **Initialize the environment**:
   - **Linux / macOS**: `./scripts/init.sh`
   - **Windows (Command Prompt)**: `scripts\init.bat`
   - **Windows (PowerShell)**: `./scripts/init.ps1`
   This sets up the Python virtual environment, installs runtime and development dependencies, creates your `.env` configuration file if needed, initializes the database, and compiles the frontend TypeScript assets.
3. **Launch the application**:
   - **Desktop window**: `./scripts/run.sh` (or `python -m xarrtools`)
   - **Web server**: `./scripts/run.sh --server` (or `python -m xarrtools --server`)
   - **Terminal CLI**: `./scripts/run.sh --cli` (or `python -m xarrtools --cli`)

Helpful startup flags:
- `--gui` / `-g`: Launch the desktop window (default).
- `--server` / `-s`: Start the web server and open your default browser.
- `--cli` / `-c`: Start the interactive terminal manager.
- `--host <ip>`: Bind to a specific network interface (default: `127.0.0.1` or `XARRTOOLS_HOST`).
- `--port <port>` / `-p <port>`: Bind to a specific port (default: `5000` or `XARRTOOLS_PORT`).
- `--no-browser`: Start the server without automatically opening your browser.
- `--debug` / `-d`: Enable debug logging output.

---

## 2. First-Time Setup

When you first open xarrtools, click the **Settings** cog (⚙️) in the top-right corner. If servers have not been configured yet, xarrtools starts in a demo sandbox mode and will display the settings dialog automatically.

1. **Connect Radarr & Sonarr** (under the **Servers** tab):
   - Enter your **Radarr URL** (e.g. `http://192.168.1.50:7878/`) and **Radarr API Key**.
   - Enter your **Sonarr URL** (e.g. `http://192.168.1.50:8989/`) and **Sonarr API Key**.
   - You can copy your API keys from Radarr and Sonarr under **Settings → General → Security**.
2. **Set Default Paths & Profiles**:
   - Once connected, xarrtools automatically queries your servers to load your available root folders and quality profiles.
   - Choose your preferred **Default Root Folder** and **Default Quality Profile** for each application. These defaults pre-populate download options so you can add media in a single click.
3. **Optional TMDB API Key / Token**:
   - Under the same tab, you can provide a TMDB Read Access Token (or API key).
   - TMDB is completely optional. Without it, xarrtools still discovers releases from DVD release calendars, TVmaze, and Metacritic. Providing a token unlocks broader movie discovery feeds, high-resolution posters, and movie collection tracking.
4. **Save and Check Status**:
   - Click **Save Settings**. The Radarr and Sonarr connection badges in the top header will turn green once connected.

---

## 3. Find What's Coming

Once configured, discovering new releases is straightforward:

### Manual Scans

In the left panel:
1. Adjust the **Months in Past** (0 to 12) and **Months in Future** (0 to 12) sliders. A common setup is 1 month back and 2 months ahead to catch recent premieres and upcoming release dates.
2. Click **Scan New Releases**.
3. A progress card appears in the lower-right corner showing real-time status as scrapers query calendars and fetch metadata.
4. Scanning runs in the background, so you can continue browsing, searching, or archiving existing cached titles while the scan proceeds.

### Scheduled Refreshes

You can set xarrtools to keep your discoveries updated automatically:
1. Open **Settings → Scheduler**.
2. Check **Enable Automatic Background Refreshes**.
3. Set your preferred **Refresh Interval** in hours (1 to 168 hours; default is 24).
4. Optionally, specify a local **Time of Day** in 24-hour format (e.g. `03:00` for 3:00 AM).
5. Scans then run on that schedule in the background. You can also kick one off immediately with **Run Refresh Now**.

### Filter and Sort the Feed

Use the sidebar controls to narrow down the view:
- **View Tabs**: Quickly switch between **All Releases**, **TV Shows**, or **New Movies**.
- **Instant Search**: Type into the search input to filter titles, cast members, or networks on the fly. Click the `(x)` button to clear.
- **Multiselect Dropdowns**: Filter by **Genres**, **Studios/Networks**, **Country**, and **Language**. Each dropdown includes **Clear All** and **Invert** buttons so you can exclude or focus on specific items with one click.
- **Visibility Checkboxes**:
  - **Show Returning Seasons**: Unchecked by default, keeping returning season 2+ shows hidden so you can focus on brand-new series premieres.
  - **Show Library Items**: Unchecked by default to keep releases you already own out of the way.
  - **Show Archived Items**: Unchecked by default to keep discarded items hidden.
- **Sort By**: Reorder releases by Release Date (ascending or descending), Title (A-Z or Z-A), or Studio/Network.

### Rich Media Cards

Each card provides key details to help you decide whether to add a title:
- Poster art (cached locally for fast loading) with deep links to external databases (IMDb or TVDB) when clicked.
- Premiere dates, network or studio name, country and language tags, and genre pills.
- Expandable plot overviews and cast lists.
- Rating badges for IMDb, Metacritic, and Rotten Tomatoes when available.
- A **Trailer** button to watch official YouTube previews in a pop-up modal.
- A circular refresh button to re-fetch live metadata for an individual title if details change.

---

## 4. Triage Your Releases

Keep your feed clean by sorting through incoming titles:

- **Archive noise**: Click **Archive** on any card you do not want. It disappears from your active view immediately.
- **Bulk archive**: Want to skip a category? Filter your view (such as selecting a specific genre or language), then click **Archive all filtered** in the sidebar. All matching items are archived in one operation.
- **Sticky manual archives**: When you manually archive an item, that decision is permanent. Future background scans or metadata refreshes will never un-archive it. It only returns if you choose to un-archive it yourself.
- **Automatic cleanup for incomplete items**: If an incoming title is missing essential information (two or more of title, network, cast, and plot), xarrtools temporarily auto-archives it so low-quality entries do not clutter your view. When future scans find complete details, xarrtools un-archives the item and marks it with a **New metadata** badge.
- **Library matching**: xarrtools checks items against your Radarr and Sonarr libraries using strict TMDB, TVDB, or IMDb identifiers, plus title matching. If a match is found, the card is tagged as "In Library" and hidden from your triage view. If a title variation prevents an automatic match, click "Mark In Library" from the Add dialog to link it manually.

---

## 5. Add to Radarr and Sonarr

When you find something you want to download:

1. Click **Add** on the card.
2. **Select the Match**: xarrtools queries your Radarr or Sonarr search API and shows candidate matches with release years and IDs. Select the correct title.
3. **Choose Download Options**:
   - Your configured **Default Root Folder** and **Default Quality Profile** are pre-selected.
   - The app remembers your most recently used folders and profiles if you change them.
   - Leave **Monitor Release** checked so the server tracks the show or movie.
4. **Choose How to Add**:
   - **Add and Search**: Adds the media to your server and immediately commands Radarr or Sonarr to search indexers and start downloading.
   - **Add Only**: Adds the media in a monitored state without starting an immediate search, allowing your server's regular RSS sync to pick it up when available.
5. **Radarr Box Sets & Collections**:
   - When a movie is part of a known franchise (such as *The Lord of the Rings* or *John Wick*), a collection badge appears on the card.
   - In the download modal, check **Track Collection / Add Box Set** to monitor the whole movie collection in Radarr at the same time.
6. **Global Search**:
   - Need to add something that is not on the release feeds? Click the 🔎 **Search** button in the header next to the connection badges.
   - Enter any movie or series title to search your servers' indexers directly and add it through the same guided modal.

---

## 6. Keep It Healthy

The **Settings** dialog includes tools to maintain your setup over time:

### Custom Feeds (Settings → Custom Feeds)

- **Manage built-in feeds**: Toggle default feeds on or off (Metacritic TV, Metacritic Movies, DVD Releases, TVmaze Premieres & Specials, and TMDB Movies).
- **Add your own feeds**: Support for RSS/XML feeds, JSON APIs, and HTML web pages.
- **Field mapping**: Define custom HTTP headers, media types, CSS selectors, or JSON path mappings.
- **Test before saving**: Use the **Test Mappings** button to preview sample parsed output before saving changes, or click **Restore Defaults** if you want to reset to the factory configuration.

### Backup and Restore (Settings → System)

- **Export Backup (JSON)**: Creates a lightweight `.json` export of your settings, custom feeds, and cached titles, protected by a SHA-256 integrity checksum.
- **Full Backup with Posters (ZIP)**: Creates a complete `.zip` archive containing your database records, custom feeds, a verified manifest, and all downloaded poster images.
- **Moving between Docker and Desktop**: Backup files are self-contained and use portable, relative paths. You can export a backup from a desktop install and restore it into Docker on your NAS (or vice-versa) with your custom feeds, sticky archives, and cached posters intact.
- **Import Backup**: Upload either a `.json` or `.zip` backup file to restore your configuration in a clean, single-transaction database import.

### Maintenance and Diagnostics (Settings → System)

- **Prune Expired Cache**: Safely remove cached release records older than 12 months with one click.
- **Wipe Discovery Cache**: Clear all discovery cache rows if you want a clean slate.
- **Live Log Level**: Switch logging levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`) on the fly without restarting the server.
- **Download Sanitized Logs**: Click **Download logs (ZIP)** to retrieve current log files (`xarrtools.log` and `xarrtools.log.1`). API tokens, server keys, and passwords are automatically redacted by in-flight log filters before ever touching disk or console.
- **Version Display**: View the running application version under System diagnostics (and at `/api/health`).

---

## Good to Know

- **Privacy & Credentials**: xarrtools runs entirely on your own hardware. Your API keys, passwords, database, and cached media stay local. The app only communicates with your configured Radarr/Sonarr servers, TMDB (if enabled), and public release feed endpoints.
- **Network Security**: If you expose xarrtools on your home network or behind a domain, set `XARRTOOLS_AUTH_USER` and `XARRTOOLS_AUTH_PASSWORD` to enable HTTP Basic Authentication, and place the app behind a reverse proxy (such as Nginx, Caddy, or Traefik) configured with HTTPS.
- **Data Storage**:
  - In desktop and local source mode, the database (`xarrtools.db`), poster cache (`posters/`), and logs (`logs/`) reside in your project directory (or next to the frozen executable).
  - In Docker, all persistent state lives inside your mounted `/config` volume.
  - Log files automatically rotate at ~1MB with a single backup file (`xarrtools.log` and `xarrtools.log.1`), preventing unbounded disk growth.

---

## Contributing and Development

Contributions are welcome! If you want to build or modify xarrtools locally:

- Read [AGENTS.md](AGENTS.md) for project guidelines, architecture patterns, and conventions.
- Read [docs/architecture.md](docs/architecture.md) for component data flow and internal structure.
- Read [docs/decisions.md](docs/decisions.md) for architectural trade-offs and rationale behind design decisions.

### Common Developer Commands

```bash
# Setup environment and install dev dependencies
./scripts/init.sh

# Run the full test suite
.venv/bin/python -m pytest tests -q --no-cov

# Run static type checking
mypy src/xarrtools

# Compile the modular TypeScript frontend
npm --prefix src/xarrtools/web run build

# Build a standalone single-file PyInstaller binary
./scripts/build.sh
```

---

## Roadmap

Planned improvements—including easier installs (a Homebrew tap, WinGet, a macOS disk image, PyPI) and a performance check with a very large library—are tracked in [ROADMAP.md](ROADMAP.md).

---

## License

xarrtools is free and open-source software licensed under the **GNU General Public License v3.0 (GPLv3)**. See the [LICENSE](LICENSE) file for details.
