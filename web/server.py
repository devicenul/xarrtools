"""Flask web application and REST API server for xarrtools."""
import os
import sys
import json
import threading
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, TypedDict
from flask import Flask, jsonify, request, render_template, send_from_directory, Response
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("xarrtools.server")

from core.config import config
from core.client import RadarrClient, SonarrClient, ArrAPIError
from core.scraper import get_discoveries, safe_fetch_feed, parse_custom_feed, is_safe_regex
from core.enricher import enrich_tv_show, enrich_movie
from core.scheduler import validate_time_of_day, compute_next_run, is_due
from core.db import (
    init_db,
    clean_expired_cache,
    get_cached_item,
    add_cached_item,
    archive_cached_item,
    get_all_settings,
    set_setting,
    get_cache_stats,
    clear_all_cache,
    get_cached_discoveries,
    update_cached_library_status,
    normalize_title,
    get_setting,
    get_db_connection,
    export_to_dict,
    import_from_dict
)

# Initialize Database and Prune Expired cache entries
init_db()
clean_expired_cache()

# Resolve template directory path inside the package folder
templates_dir = Path(__file__).resolve().parent / "templates"
dist_dir = Path(__file__).resolve().parent / "static" / "dist"

def is_dist_built() -> bool:
    """Checks whether compiled frontend modules exist in web/static/dist."""
    return dist_dir.is_dir() and any(dist_dir.glob("*.js"))

app = Flask(
    __name__,
    template_folder=str(templates_dir),
    static_folder=str(templates_dir),
    static_url_path="/static"
)

RouteResponse = Union[Response, str, Tuple[Any, int], Tuple[str, int, Dict[str, str]]]

@app.route("/static/dist/<path:filename>")
def serve_dist(filename: str) -> RouteResponse:
    """Serves compiled frontend TypeScript/ES modules."""
    if not is_dist_built():
        print(f"[xarrtools] WARNING: Frontend dist directory not found at {dist_dir}. Run 'npm run build'.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Frontend assets in /static/dist/ have not been built. Run 'npm run build'."}), 404
    return send_from_directory(dist_dir, filename)

# Thread-safe global scan progress
scan_progress: Dict[str, Any] = {
    "status": "idle",
    "message": "",
    "current": 0,
    "total": 0
}
# scan_progress_lock guards concurrent mutations to scan_progress and prevents overlapping manual scans.
scan_progress_lock = threading.Lock()
# scheduler_job_lock prevents concurrent scheduled scans from firing while another scheduled scan is running.
scheduler_job_lock = threading.Lock()
_scheduler_startup_time = datetime.now(timezone.utc)

class LibraryCache(TypedDict):
    """In-memory cache for Radarr and Sonarr libraries to speed up match detection."""
    radarr_tmdb_ids: Set[int]
    radarr_imdb_ids: Set[str]
    radarr_titles: Dict[str, List[int]]
    sonarr_tvdb_ids: Set[int]
    sonarr_imdb_ids: Set[str]
    sonarr_titles: Dict[str, List[int]]
    last_updated: Optional[datetime]

# library_cache_lock protects reading and swapping the in-memory Radarr/Sonarr library ID cache.
library_cache: LibraryCache = {
    "radarr_tmdb_ids": set(),
    "radarr_imdb_ids": set(),
    "radarr_titles": {},
    "sonarr_tvdb_ids": set(),
    "sonarr_imdb_ids": set(),
    "sonarr_titles": {},
    "last_updated": None
}
library_cache_lock = threading.Lock()

def update_scan_progress(status: str, message: str, current: int = 0, total: int = 0) -> None:
    """Updates global scan progress state safely under scan_progress_lock."""
    with scan_progress_lock:
        scan_progress["status"] = status
        scan_progress["message"] = message
        scan_progress["current"] = current
        scan_progress["total"] = total


# Initialize Radarr / Sonarr Clients
def get_clients() -> Tuple[Optional[RadarrClient], Optional[SonarrClient]]:
    """Initializes and returns Radarr and Sonarr API clients if configured."""
    radarr_client = None
    if config.validate_radarr():
        radarr_client = RadarrClient(config.radarr_url, config.radarr_api_key)
        
    sonarr_client = None
    if config.validate_sonarr():
        sonarr_client = SonarrClient(config.sonarr_url, config.sonarr_api_key)
        
    return radarr_client, sonarr_client

def is_incomplete_metadata(item: Dict[str, Any]) -> bool:
    """Checks if an item has invalid or missing values for title, cast, and plot (description) all combined."""
    title = item.get("title")
    is_title_missing = not title or str(title).strip() in ("", "Unknown", "None")
    
    cast = item.get("cast")
    is_cast_missing = not cast or str(cast).strip() in ("", "Cast details not available.", "None")
    
    plot = item.get("plot") or item.get("description") or item.get("overview")
    is_plot_missing = not plot or str(plot).strip() in ("", "No plot summary available.", "None")
    
    return is_title_missing and is_cast_missing and is_plot_missing

@app.before_request
def enforce_api_key() -> Optional[RouteResponse]:
    """Validates X-API-Key header for state-mutating API requests."""
    if request.method in ["POST", "PUT", "DELETE"] and request.path.startswith("/api/"):
        api_key = request.headers.get("X-API-Key")
        server_api_key = config._get_setting("api_key")
        if not server_api_key:
            import secrets
            server_api_key = secrets.token_hex(16)
            set_setting("api_key", server_api_key)
            config.refresh()
            
        if not api_key or api_key != server_api_key:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None

@app.route("/")
def index() -> str:
    """Serves the primary UI page."""
    server_api_key = config._get_setting("api_key")
    if not server_api_key:
        import secrets
        server_api_key = secrets.token_hex(16)
        set_setting("api_key", server_api_key)
        config.refresh()
    dist_built = is_dist_built()
    if not dist_built:
        print("[xarrtools] WARNING: Frontend dist directory is missing or unbuilt. Run 'npm install && npm run build'.", file=sys.stderr)
    return render_template("index.html", api_key=server_api_key, dist_built=dist_built)

def sync_library_cache() -> None:
    """Fetches Radarr and Sonarr libraries to refresh in-memory ID and title cache."""
    try:
        radarr_client, sonarr_client = get_clients()
        radarr_tmdb_ids: Set[int] = set()
        radarr_imdb_ids: Set[str] = set()
        radarr_titles: Dict[str, List[int]] = {}
        sonarr_tvdb_ids: Set[int] = set()
        sonarr_imdb_ids: Set[str] = set()
        sonarr_titles: Dict[str, List[int]] = {}
        
        if radarr_client:
            try:
                radarr_lib = radarr_client.get_library()
                for movie in radarr_lib:
                    if movie.get("tmdbId"):
                        radarr_tmdb_ids.add(int(movie["tmdbId"]))
                    if movie.get("imdbId"):
                        imdb = str(movie["imdbId"]).strip().lower()
                        if imdb:
                            radarr_imdb_ids.add(imdb)
                    title_norm = normalize_title(movie.get("title", ""), is_tv=False)
                    if title_norm:
                        if title_norm not in radarr_titles:
                            radarr_titles[title_norm] = []
                        if movie.get("year"):
                            radarr_titles[title_norm].append(int(movie["year"]))
            except Exception as e:
                logger.error(f"Error fetching Radarr library for cache: {e}")
                
        if sonarr_client:
            try:
                sonarr_lib = sonarr_client.get_library()
                for show in sonarr_lib:
                    if show.get("tvdbId"):
                        sonarr_tvdb_ids.add(int(show["tvdbId"]))
                    if show.get("imdbId"):
                        imdb = str(show["imdbId"]).strip().lower()
                        if imdb:
                            sonarr_imdb_ids.add(imdb)
                    title_norm = normalize_title(show.get("title", ""), is_tv=True)
                    if title_norm:
                        if title_norm not in sonarr_titles:
                            sonarr_titles[title_norm] = []
                        if show.get("year"):
                            sonarr_titles[title_norm].append(int(show["year"]))
            except Exception as e:
                logger.error(f"Error fetching Sonarr library for cache: {e}")
                
        with library_cache_lock:
            library_cache["radarr_tmdb_ids"] = radarr_tmdb_ids
            library_cache["radarr_imdb_ids"] = radarr_imdb_ids
            library_cache["radarr_titles"] = radarr_titles
            library_cache["sonarr_tvdb_ids"] = sonarr_tvdb_ids
            library_cache["sonarr_imdb_ids"] = sonarr_imdb_ids
            library_cache["sonarr_titles"] = sonarr_titles
            library_cache["last_updated"] = datetime.now()
    except Exception as e:
        logger.error(f"Library cache thread error: {e}")

def update_library_cache_loop() -> None:
    """Daemon loop that periodically refreshes the in-memory library cache every 5 minutes."""
    while True:
        sync_library_cache()
        import time
        time.sleep(300)

# Background library cache refresh daemon. Disabled during tests for isolation.
if "PYTEST_CURRENT_TEST" not in os.environ:
    threading.Thread(target=update_library_cache_loop, daemon=True).start()

@app.route("/api/config", methods=["GET"])
def get_server_config() -> RouteResponse:
    """Returns Root Paths and Quality Profiles from Sonarr and Radarr."""
    radarr_client, sonarr_client = get_clients()
    
    response_data = {
        "radarr": {"configured": False, "folders": [], "profiles": []},
        "sonarr": {"configured": False, "folders": [], "profiles": []}
    }
    
    if radarr_client:
        try:
            response_data["radarr"]["folders"] = radarr_client.get_root_folders()
            response_data["radarr"]["profiles"] = radarr_client.get_quality_profiles()
            response_data["radarr"]["configured"] = True
        except Exception as e:
            logger.error(f"Error fetching Radarr config: {e}")
            response_data["radarr"]["error"] = str(e)
            
    if sonarr_client:
        try:
            response_data["sonarr"]["folders"] = sonarr_client.get_root_folders()
            response_data["sonarr"]["profiles"] = sonarr_client.get_quality_profiles()
            response_data["sonarr"]["configured"] = True
        except Exception as e:
            logger.error(f"Error fetching Sonarr config: {e}")
            response_data["sonarr"]["error"] = str(e)
            
    return jsonify(response_data)

@app.route("/api/settings", methods=["GET", "POST"])
def manage_settings() -> RouteResponse:
    """Reads or updates configuration settings."""
    if request.method == "POST":
        data = request.json or {}

        # Validate scheduler_* values
        if "scheduler_enabled" in data:
            val = data["scheduler_enabled"]
            if isinstance(val, bool):
                pass
            elif str(val).strip().lower() in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                pass
            else:
                return jsonify({"status": "error", "message": "Invalid value for scheduler_enabled."}), 400

        if "scheduler_interval_hours" in data:
            val = data["scheduler_interval_hours"]
            try:
                h = int(val)
                if h < 1 or h > 168:
                    return jsonify({"status": "error", "message": "scheduler_interval_hours must be between 1 and 168."}), 400
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "scheduler_interval_hours must be an integer."}), 400

        if "scheduler_time_of_day" in data:
            val = data["scheduler_time_of_day"]
            if val is not None and str(val).strip() != "":
                if not validate_time_of_day(str(val)):
                    return jsonify({"status": "error", "message": "scheduler_time_of_day must be in 'HH:MM' format."}), 400

        if "scheduler_last_run" in data:
            val = data["scheduler_last_run"]
            if val is not None and str(val).strip() != "":
                try:
                    datetime.fromisoformat(str(val).strip().replace("Z", "+00:00"))
                except Exception:
                    return jsonify({"status": "error", "message": "scheduler_last_run must be a valid ISO datetime."}), 400

        if "scheduler_last_result" in data:
            val = data["scheduler_last_result"]
            if val is not None and str(val).strip() != "":
                if isinstance(val, dict):
                    data["scheduler_last_result"] = json.dumps(val)
                else:
                    try:
                        json.loads(str(val))
                    except Exception:
                        return jsonify({"status": "error", "message": "scheduler_last_result must be valid JSON."}), 400

        if "log_level" in data:
            val = str(data["log_level"]).strip().upper()
            if val not in ("DEBUG", "INFO", "WARNING", "ERROR"):
                return jsonify({"status": "error", "message": "Invalid value for log_level. Must be DEBUG, INFO, WARNING, or ERROR."}), 400
            data["log_level"] = val

        for key, val in data.items():
            set_setting(key, str(val))
        config.refresh()
        if "log_level" in data:
            from core.logging_setup import setup_logging
            setup_logging(level=data["log_level"])
        with library_cache_lock:
            library_cache["last_updated"] = None
        return jsonify({"status": "success", "message": "Settings saved successfully."})
    else:
        return jsonify(get_all_settings())

@app.route("/api/backup/export", methods=["GET"])
def backup_export() -> RouteResponse:
    """Exports settings and optionally cached media data as a JSON file or full ZIP archive attachment."""
    include_media = request.args.get("include_media", "true").lower() == "true"
    fmt = request.args.get("format", "json").lower()
    try:
        if fmt == "full":
            from core.backup import export_full_backup
            import io
            bio = io.BytesIO()
            export_full_backup(bio, include_media=include_media)
            return Response(
                bio.getvalue(),
                mimetype="application/zip",
                headers={
                    "Content-Type": "application/zip",
                    "Content-Disposition": "attachment; filename=xarrtools_full_backup.zip"
                }
            )
        data = export_to_dict(include_media=include_media)
        import json
        json_data = json.dumps(data, indent=2)
        return json_data, 200, {
            "Content-Type": "application/json",
            "Content-Disposition": "attachment; filename=xarrtools_backup.json"
        }
    except Exception as e:
        logger.error(f"Error exporting backup: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/logs/download", methods=["GET"])
def download_logs() -> Response:
    """Downloads application log files (xarrtools.log, xarrtools.log.1) packaged in a ZIP archive.
    
    Returns a ZIP containing existing log files, or a README note if no logs are present.
    """
    from core.logging_setup import get_log_dir
    import io
    import zipfile

    log_dir = get_log_dir()
    log_files = [log_dir / "xarrtools.log", log_dir / "xarrtools.log.1"]
    existing_files = [p for p in log_files if p.is_file() and p.stat().st_size > 0]

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        if not existing_files:
            zf.writestr("README.txt", "No log files currently exist or logs are empty.\n")
        else:
            for p in existing_files:
                zf.write(p, arcname=p.name)

    bio.seek(0)
    return Response(
        bio.getvalue(),
        mimetype="application/zip",
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": "attachment; filename=xarrtools_logs.zip"
        }
    )

@app.route("/api/backup/import", methods=["POST"])
def backup_import() -> RouteResponse:
    """Imports settings and cached media data from an uploaded JSON or ZIP file."""
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded."}), 400
        
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "No file selected."}), 400
        
    try:
        content = file.read()
        
        # Detect ZIP by magic bytes: PK
        if content.startswith(b"PK"):
            from core.backup import import_full_backup
            import io
            bio = io.BytesIO(content)
            res = import_full_backup(bio)
            return jsonify({
                "status": "success",
                "message": "Full backup imported successfully.",
                "settings_count": res.get("settings_count", 0),
                "media_count": res.get("media_count", 0),
                "posters_count": res.get("posters_count", 0),
                "custom_feeds_count": res.get("custom_feeds_count", 0)
            })
            
        import json
        data = json.loads(content.decode("utf-8"))
        
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid backup file structure."}), 400
            
        from core.db import verify_backup_checksum
        check = verify_backup_checksum(data)
        if check is False:
            return jsonify({"status": "error", "message": "Backup checksum verification failed (file corrupted or tampered)."}), 400
            
        settings_count, media_count = import_from_dict(data)
        
        return jsonify({
            "status": "success",
            "message": "Backup imported successfully.",
            "settings_count": settings_count,
            "media_count": media_count,
            "posters_count": 0
        })
    except ValueError as ve:
        logger.error(f"Validation error importing backup: {ve}")
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error importing backup: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

import re
from flask import Response
@app.route("/api/poster", methods=["GET"])
def proxy_poster() -> RouteResponse:
    """Proxies poster images safely to prevent mixed content and SSRF/path traversal, with disk cache."""
    from core.posters import validate_poster_url, get_cached_poster, store_poster, MAX_POSTER_SIZE
    url = request.args.get("url")
    if not url:
        return "Missing URL", 400
        
    if not re.match(r"^https?://", url):
        return "Invalid URL scheme", 400

    cached = get_cached_poster(url)
    if cached:
        data, content_type = cached
        r = Response(data, mimetype=content_type)
        r.headers["X-Content-Type-Options"] = "nosniff"
        return r

    valid, err, code = validate_poster_url(url)
    if not valid:
        return err, code

    try:
        import requests
        resp = requests.get(url, stream=True, timeout=5)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        
        chunks = []
        total_size = 0
        for chunk in resp.iter_content(chunk_size=4096):
            chunks.append(chunk)
            total_size += len(chunk)
            if total_size > MAX_POSTER_SIZE:
                break
                
        data = b"".join(chunks)
        ct = content_type.lower().split(";")[0].strip()
        if total_size <= MAX_POSTER_SIZE and ct.startswith("image/"):
            store_poster(url, data, ct)
            
        r = Response(data, mimetype=content_type)
        r.headers["X-Content-Type-Options"] = "nosniff"
        return r
    except Exception as e:
        return "Error fetching image", 500

@app.route("/api/archive", methods=["POST"])
def archive_media() -> RouteResponse:
    """Updates the archived status of an item."""
    data = request.json or {}
    type_ = data.get("type")
    title = data.get("title")
    year = data.get("year", 0)
    archive = data.get("archive", True)
    raw_item = data.get("raw_item")
    
    if not type_ or not title:
        return jsonify({"status": "error", "message": "Missing type or title parameters"}), 400
        
    try:
        archive_cached_item(type_, title, int(year), archive, raw_item)
        return jsonify({"status": "success", "message": f"Successfully updated archive status."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/archive/batch", methods=["POST"])
def archive_media_batch() -> RouteResponse:
    """Archives (or unarchives) many items at once: {"archive": bool, "items": [{type, title, year, raw_item}]}."""
    data = request.json or {}
    items = data.get("items")
    archive = data.get("archive", True)
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "Missing items list"}), 400

    done, failed = 0, []
    for entry in items:
        try:
            if not isinstance(entry, dict) or not entry.get("type") or not entry.get("title"):
                raise ValueError("Missing type or title")
            archive_cached_item(entry["type"], entry["title"], int(entry.get("year") or 0), archive,
                                entry.get("raw_item"))
            done += 1
        except Exception as e:
            failed.append({"title": entry.get("title") if isinstance(entry, dict) else None, "message": str(e)})
    status = "success" if not failed else ("partial" if done else "error")
    return jsonify({"status": status, "archived": done, "failed": failed}), (200 if done or not failed else 500)

@app.route("/api/cache/stats", methods=["GET"])
def cache_stats() -> RouteResponse:
    """Returns row counts and database size diagnostics."""
    try:
        return jsonify(get_cache_stats())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/cache/prune", methods=["POST"])
def cache_prune() -> RouteResponse:
    """Manually triggers pruning of cache entries older than 12 months."""
    try:
        clean_expired_cache()
        return jsonify({"status": "success", "message": "Manual cache pruning completed."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/cache/clear", methods=["POST"])
def cache_clear() -> RouteResponse:
    """Manually wipes all discoveries from the cache table."""
    try:
        clear_all_cache()
        return jsonify({"status": "success", "message": "All cached discoveries wiped successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/scan/progress", methods=["GET"])
def get_scan_progress() -> RouteResponse:
    """Returns the current scan status and progress counter."""
    with scan_progress_lock:
        return jsonify(scan_progress)

def run_scan(past_months: int = 1, future_months: int = 2) -> Dict[str, Any]:
    """Scrapes external release feeds, enriches items, updates the SQLite cache,
    and returns a dict with 'tv' and 'movies' lists of enriched items.
    Works outside of Flask request context.
    """
    # scan_progress_lock ensures only one scan or scheduled run executes at any time.
    with scan_progress_lock:
        if scan_progress["status"] != "idle":
            raise RuntimeError("A scan is already in progress.")

    past_days = max(0, min(365, past_months * 30))
    future_days = max(0, min(365, future_months * 30))

    ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
    radarr_client, sonarr_client = get_clients()

    # Force synchronous library cache sync in pytest to avoid stale cache or missing client mocks.
    if "PYTEST_CURRENT_TEST" in os.environ or library_cache.get("last_updated") is None:
        sync_library_cache()

    # 1. Fetch libraries (using background cache)
    with library_cache_lock:
        radarr_tmdb_ids = set(library_cache["radarr_tmdb_ids"])
        radarr_imdb_ids = set(library_cache["radarr_imdb_ids"])
        radarr_titles = dict(library_cache["radarr_titles"])
        sonarr_tvdb_ids = set(library_cache["sonarr_tvdb_ids"])
        sonarr_imdb_ids = set(library_cache["sonarr_imdb_ids"])
        sonarr_titles = dict(library_cache["sonarr_titles"])

    enriched_tv = []
    enriched_movies = []

    try:
        update_scan_progress("scraping", "Scraping Metacritic and DVD release calendars...", 0, 0)
        tv_raw, movie_raw = get_discoveries(past_days, future_days)

        # 2. Enrich TV shows (using database cache optimization)
        total_items = len(tv_raw) + len(movie_raw)
        for idx, item in enumerate(tv_raw):
            try:
                update_scan_progress("enriching", f"Fetching metadata for {item['title']}", idx + 1, total_items)
                cached = get_cached_item("tv", item["title"], item["date_obj"].year)

                # Check if cache is incomplete
                is_incomplete = True
                if cached:
                    recently_updated = False
                    if cached.get("added_at"):
                        try:
                            added_dt = datetime.strptime(cached["added_at"], "%Y-%m-%d %H:%M:%S")
                            if datetime.now() - added_dt < timedelta(hours=24):
                                recently_updated = True
                        except Exception:
                            pass

                    has_poster = bool(cached.get("poster_url"))
                    has_ratings = bool(cached.get("rating_imdb") or cached.get("rating_metacritic") or cached.get("rating_rt"))
                    has_ids = bool(cached.get("imdb_id") and cached.get("tvdb_id"))

                    if (has_poster and has_ratings and has_ids) or (recently_updated and has_poster):
                        is_incomplete = False

                if cached and not is_incomplete:
                    # Check library
                    in_library = False
                    tvdb_val = cached["tvdb_id"]
                    imdb_val = cached["imdb_id"]
                    if sonarr_client:
                        has_tvdb_match = (tvdb_val and int(tvdb_val) in sonarr_tvdb_ids)
                        clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                        has_imdb_match = (clean_imdb and clean_imdb in sonarr_imdb_ids)

                        has_title_match = False
                        title_norm = normalize_title(cached["title"], is_tv=True)
                        if title_norm in sonarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - cached["year"]) <= 1 for y in sonarr_titles[title_norm])

                        in_library = has_tvdb_match or has_imdb_match or has_title_match or bool(cached["is_in_library"])

                        # Sync status if changed
                        if in_library and not bool(cached["is_in_library"]):
                            update_cached_library_status("tv", cached["title"], cached["year"], True, imdb_val)
                    else:
                        in_library = bool(cached["is_in_library"])

                    data = {
                        "title": cached["title"],
                        "year": cached["year"],
                        "plot": cached["description"] or item["description"],
                        "cast": cached["cast"],
                        "genres": json.loads(cached["genres"]) if cached["genres"] else [],
                        "trailer": cached["trailer"],
                        "poster_url": cached["poster_url"] or "",
                        "tvdbId": tvdb_val,
                        "imdbId": imdb_val,
                        "network": cached["network"],
                        "is_in_library": in_library,
                        "is_archived": bool(cached["is_archived"]),
                        "date_obj": cached["date_obj"] or "",
                        "has_new_metadata": bool(cached.get("has_new_metadata", 0)),
                        "raw_metadata": None,
                        "rating_imdb": cached.get("rating_imdb", "") or "",
                        "rating_metacritic": cached.get("rating_metacritic", "") or "",
                        "rating_rt": cached.get("rating_rt", "") or "",
                        "country": cached.get("country", "") or "",
                        "language": cached.get("language", "") or ""
                    }
                else:
                    data = enrich_tv_show(item["title"], item["date_obj"].year, sonarr_client)
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    data["is_returning"] = item.get("is_returning", False)
                    data["country"] = data.get("country") or item.get("country", "")
                    data["language"] = data.get("language") or item.get("language", "")

                    # Resolve library status
                    in_library = False
                    tvdb_val = data.get("tvdbId")
                    imdb_val = data.get("imdbId")
                    if sonarr_client:
                        has_tvdb_match = (tvdb_val and int(tvdb_val) in sonarr_tvdb_ids)
                        clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                        has_imdb_match = (clean_imdb and clean_imdb in sonarr_imdb_ids)

                        has_title_match = False
                        title_norm = normalize_title(data["title"], is_tv=True)
                        if title_norm in sonarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - data["year"]) <= 1 for y in sonarr_titles[title_norm])

                        in_library = has_tvdb_match or has_imdb_match or has_title_match or (bool(cached["is_in_library"]) if cached else False)
                    else:
                        in_library = bool(cached["is_in_library"]) if cached else False

                    data["is_in_library"] = in_library
                    data["date_str"] = item.get("date_str", "")
                    raw_dt = item.get("date_obj")
                    data["date_obj"] = raw_dt.strftime("%Y-%m-%d") if isinstance(raw_dt, datetime) else (str(raw_dt) if raw_dt else "")
                    data["href"] = item.get("href", "")

                    # Cache newly fetched details
                    add_cached_item("tv", data)
                    cached_after = get_cached_item("tv", data["title"], data.get("year", item["date_obj"].year), data.get("imdbId"))  # type: ignore[arg-type]  # core.db.get_cached_item accepts Optional[str] at runtime
                    if cached_after:
                        data["is_archived"] = bool(cached_after["is_archived"])
                        data["has_new_metadata"] = bool(cached_after.get("has_new_metadata", 0))
                    else:
                        data["is_archived"] = bool(data.get("is_archived", False))
                        data["has_new_metadata"] = bool(data.get("has_new_metadata", False))

                data["date_str"] = item["date_str"]
                raw_dt = item.get("date_obj")
                data["date_obj"] = data.get("date_obj") or (raw_dt.strftime("%Y-%m-%d") if isinstance(raw_dt, datetime) else (str(raw_dt) if raw_dt else ""))
                data["is_returning"] = item.get("is_returning", False)
                enriched_tv.append(data)
            except Exception as e:
                logger.error(f"Error enriching TV show '{item['title']}': {e}")
                raw_dt = item.get("date_obj")
                if raw_dt:
                    item["date_obj"] = raw_dt.strftime("%Y-%m-%d") if isinstance(raw_dt, datetime) else str(raw_dt)
                item["plot"] = item["description"]
                item["cast"] = "Cast details not available."
                item["genres"] = []
                item["tvdbId"] = None
                item["imdbId"] = None
                item["is_in_library"] = False
                item["is_archived"] = False
                item["has_new_metadata"] = False
                item["raw_metadata"] = None
                item["is_returning"] = item.get("is_returning", False)
                enriched_tv.append(item)

        # 3. Enrich Movies (using database cache optimization)
        for idx, item in enumerate(movie_raw):
            try:
                current_idx = len(tv_raw) + idx + 1
                update_scan_progress("enriching", f"Getting metadata for {item['title']}", current_idx, total_items)
                cached = get_cached_item("movie", item["title"], item["date_obj"].year, item.get("imdbId"))  # type: ignore[arg-type]  # core.db.get_cached_item accepts Optional[str] at runtime

                # Check if cache is incomplete
                is_incomplete = True
                if cached:
                    recently_updated = False
                    if cached.get("added_at"):
                        try:
                            added_dt = datetime.strptime(cached["added_at"], "%Y-%m-%d %H:%M:%S")
                            if datetime.now() - added_dt < timedelta(hours=24):
                                recently_updated = True
                        except Exception:
                            pass

                    has_poster = bool(cached.get("poster_url"))
                    has_ratings = bool(cached.get("rating_imdb") or cached.get("rating_metacritic") or cached.get("rating_rt"))
                    has_ids = bool(cached.get("imdb_id") and cached.get("tmdb_id"))

                    if (has_poster and has_ratings and has_ids) or (recently_updated and has_poster):
                        is_incomplete = False

                if cached and not is_incomplete:
                    # Check library
                    in_library = False
                    tmdb_val = cached["tmdb_id"]
                    imdb_val = cached["imdb_id"]
                    if radarr_client:
                        has_tmdb_match = (tmdb_val and int(tmdb_val) in radarr_tmdb_ids)
                        clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                        has_imdb_match = (clean_imdb and clean_imdb in radarr_imdb_ids)

                        has_title_match = False
                        title_norm = normalize_title(cached["title"], is_tv=False)
                        if title_norm in radarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - cached["year"]) <= 1 for y in radarr_titles[title_norm])

                        in_library = has_tmdb_match or has_imdb_match or has_title_match or bool(cached["is_in_library"])

                        # Sync status if changed
                        if in_library and not bool(cached["is_in_library"]):
                            update_cached_library_status("movie", cached["title"], cached["year"], True, imdb_val)
                    else:
                        in_library = bool(cached["is_in_library"])

                    data = {
                        "title": cached["title"],
                        "year": cached["year"],
                        "plot": cached["description"] or item["description"],
                        "cast": cached["cast"],
                        "genres": json.loads(cached["genres"]) if cached["genres"] else [],
                        "trailer": cached["trailer"],
                        "poster_url": cached["poster_url"] or "",
                        "tmdbId": tmdb_val,
                        "imdbId": imdb_val,
                        "network": cached["network"],
                        "is_in_library": in_library,
                        "is_archived": bool(cached["is_archived"]),
                        "date_obj": cached["date_obj"] or "",
                        "has_new_metadata": bool(cached.get("has_new_metadata", 0)),
                        "raw_metadata": None,
                        "rating_imdb": cached.get("rating_imdb", "") or "",
                        "rating_metacritic": cached.get("rating_metacritic", "") or "",
                        "rating_rt": cached.get("rating_rt", "") or "",
                        "director": cached.get("director", "") or "",
                        "producer": cached.get("producer", "") or "",
                        "country": cached.get("country", "") or "",
                        "language": cached.get("language", "") or ""
                    }
                else:
                    extra = {"tmdb_id": item["tmdbId"]} if item.get("tmdbId") else {}
                    data = enrich_movie(item["title"], item["date_obj"].year, radarr_client, item.get("imdbId"), **extra)
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    if "imdbId" not in data or not data["imdbId"]:
                        data["imdbId"] = item.get("imdbId")
                    data["country"] = data.get("country") or item.get("country", "")
                    data["language"] = data.get("language") or item.get("language", "")

                    # Resolve library status
                    in_library = False
                    tmdb_val = data.get("tmdbId")
                    imdb_val = data.get("imdbId")
                    if radarr_client:
                        has_tmdb_match = (tmdb_val and int(tmdb_val) in radarr_tmdb_ids)
                        clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                        has_imdb_match = (clean_imdb and clean_imdb in radarr_imdb_ids)

                        has_title_match = False
                        title_norm = normalize_title(data["title"], is_tv=False)
                        if title_norm in radarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - data["year"]) <= 1 for y in radarr_titles[title_norm])

                        in_library = has_tmdb_match or has_imdb_match or has_title_match or (bool(cached["is_in_library"]) if cached else False)
                    else:
                        in_library = bool(cached["is_in_library"]) if cached else False

                    data["is_in_library"] = in_library
                    data["date_str"] = item.get("date_str", "")
                    raw_dt = item.get("date_obj")
                    data["date_obj"] = raw_dt.strftime("%Y-%m-%d") if isinstance(raw_dt, datetime) else (str(raw_dt) if raw_dt else "")
                    data["href"] = item.get("href", "")

                    # Cache newly fetched details
                    add_cached_item("movie", data)
                    cached_after = get_cached_item("movie", data["title"], data.get("year", item["date_obj"].year), data.get("imdbId"))  # type: ignore[arg-type]  # core.db.get_cached_item accepts Optional[str] at runtime
                    if cached_after:
                        data["is_archived"] = bool(cached_after["is_archived"])
                        data["has_new_metadata"] = bool(cached_after.get("has_new_metadata", 0))
                    else:
                        data["is_archived"] = bool(data.get("is_archived", False))
                        data["has_new_metadata"] = bool(data.get("has_new_metadata", False))

                data["date_str"] = item["date_str"]
                raw_dt = item.get("date_obj")
                data["date_obj"] = data.get("date_obj") or (raw_dt.strftime("%Y-%m-%d") if isinstance(raw_dt, datetime) else (str(raw_dt) if raw_dt else ""))
                if "imdbId" not in data or not data["imdbId"]:
                    data["imdbId"] = item.get("imdbId")
                enriched_movies.append(data)
            except Exception as e:
                logger.error(f"Error enriching movie '{item['title']}': {e}")
                raw_dt = item.get("date_obj")
                if raw_dt:
                    item["date_obj"] = raw_dt.strftime("%Y-%m-%d") if isinstance(raw_dt, datetime) else str(raw_dt)
                item["plot"] = item["description"]
                item["cast"] = "Cast details not available."
                item["genres"] = []
                item["tmdbId"] = None
                item["is_in_library"] = False
                item["is_archived"] = False
                item["has_new_metadata"] = False
                item["raw_metadata"] = None
                if "imdbId" not in item or not item["imdbId"]:
                    item["imdbId"] = item.get("imdbId")
                enriched_movies.append(item)

        return {
            "tv": [item for item in enriched_tv if not is_incomplete_metadata(item)],
            "movies": [item for item in enriched_movies if not is_incomplete_metadata(item)]
        }
    finally:
        update_scan_progress("idle", "Idle", 0, 0)

@app.route("/api/discover", methods=["GET"])
def discover_releases() -> RouteResponse:
    """Scrapes, caches, enriches, and resolves releases for TV and Movies."""
    past_months = request.args.get("past_months", default=1, type=int)
    future_months = request.args.get("future_months", default=2, type=int)
    skip_scrape = request.args.get("skip_scrape", default="false").lower() == "true"

    past_days = max(0, min(365, past_months * 30))
    future_days = max(0, min(365, future_months * 30))

    if skip_scrape:
        ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
        radarr_client, sonarr_client = get_clients()

        if "PYTEST_CURRENT_TEST" in os.environ or library_cache.get("last_updated") is None:
            sync_library_cache()

        # 1. Fetch libraries (using background cache)
        with library_cache_lock:
            radarr_tmdb_ids = set(library_cache["radarr_tmdb_ids"])
            radarr_imdb_ids = set(library_cache["radarr_imdb_ids"])
            radarr_titles = dict(library_cache["radarr_titles"])
            sonarr_tvdb_ids = set(library_cache["sonarr_tvdb_ids"])
            sonarr_imdb_ids = set(library_cache["sonarr_imdb_ids"])
            sonarr_titles = dict(library_cache["sonarr_titles"])

        enriched_tv = []
        enriched_movies = []

        # Load directly from database cache
        start_date = (datetime.now() - timedelta(days=past_days)).strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=future_days)).strftime("%Y-%m-%d")

        tv_rows, movie_rows = get_cached_discoveries(start_date, end_date)

        for row in tv_rows:
            tvdb_id = row["tvdb_id"]
            imdb_id = row["imdb_id"]

            in_library = False
            if sonarr_client:
                has_tvdb_match = (tvdb_id and int(tvdb_id) in sonarr_tvdb_ids)
                clean_imdb = str(imdb_id).strip().lower() if imdb_id else ""
                has_imdb_match = (clean_imdb and clean_imdb in sonarr_imdb_ids)

                has_title_match = False
                title_norm = normalize_title(row["title"], is_tv=True)
                if title_norm in sonarr_titles:
                    if ignore_year:
                        has_title_match = True
                    else:
                        row_year = row["year"]
                        has_title_match = any(abs(y - row_year) <= 1 for y in sonarr_titles[title_norm])

                in_library = has_tvdb_match or has_imdb_match or has_title_match or bool(row["is_in_library"])

                # Sync status if changed
                if in_library and not bool(row["is_in_library"]):
                    update_cached_library_status("tv", row["title"], row["year"], True, imdb_id)
            else:
                in_library = bool(row["is_in_library"])

            data = {
                "title": row["title"],
                "year": row["year"],
                "plot": row["description"],
                "cast": row["cast"],
                "genres": json.loads(row["genres"]) if row["genres"] else [],
                "trailer": row["trailer"],
                "poster_url": row["poster_url"] or "",
                "tvdbId": tvdb_id,
                "imdbId": imdb_id,
                "network": row["network"],
                "is_in_library": in_library,
                "is_archived": bool(row["is_archived"]),
                "has_new_metadata": bool(row.get("has_new_metadata", 0)),
                "is_returning": bool(row["is_returning"]),
                "date_str": row["date_str"],
                "date_obj": row["date_obj"] or "",
                "raw_metadata": None,
                "rating_imdb": row.get("rating_imdb", "") or "",
                "rating_metacritic": row.get("rating_metacritic", "") or "",
                "rating_rt": row.get("rating_rt", "") or "",
                "country": row.get("country", "") or "",
                "language": row.get("language", "") or ""
            }
            enriched_tv.append(data)

        for row in movie_rows:
            tmdb_id = row["tmdb_id"]
            imdb_id = row["imdb_id"]

            in_library = False
            if radarr_client:
                has_tmdb_match = (tmdb_id and int(tmdb_id) in radarr_tmdb_ids)
                clean_imdb = str(imdb_id).strip().lower() if imdb_id else ""
                has_imdb_match = (clean_imdb and clean_imdb in radarr_imdb_ids)

                has_title_match = False
                title_norm = normalize_title(row["title"], is_tv=False)
                if title_norm in radarr_titles:
                    if ignore_year:
                        has_title_match = True
                    else:
                        row_year = row["year"]
                        has_title_match = any(abs(y - row_year) <= 1 for y in radarr_titles[title_norm])

                in_library = has_tmdb_match or has_imdb_match or has_title_match or bool(row["is_in_library"])

                # Sync status if changed
                if in_library and not bool(row["is_in_library"]):
                    update_cached_library_status("movie", row["title"], row["year"], True, imdb_id)
            else:
                in_library = bool(row["is_in_library"])

            data = {
                "title": row["title"],
                "year": row["year"],
                "plot": row["description"],
                "cast": row["cast"],
                "genres": json.loads(row["genres"]) if row["genres"] else [],
                "trailer": row["trailer"],
                "poster_url": row["poster_url"] or "",
                "tmdbId": tmdb_id,
                "imdbId": imdb_id,
                "network": row["network"],
                "is_in_library": in_library,
                "is_archived": bool(row["is_archived"]),
                "has_new_metadata": bool(row.get("has_new_metadata", 0)),
                "date_str": row["date_str"],
                "date_obj": row["date_obj"] or "",
                "raw_metadata": None,
                "rating_imdb": row.get("rating_imdb", "") or "",
                "rating_metacritic": row.get("rating_metacritic", "") or "",
                "rating_rt": row.get("rating_rt", "") or "",
                "director": row.get("director", "") or "",
                "producer": row.get("producer", "") or "",
                "country": row.get("country", "") or "",
                "language": row.get("language", "") or ""
            }
            enriched_movies.append(data)

        return jsonify({
            "status": "success",
            "tv": [item for item in enriched_tv if not is_incomplete_metadata(item)],
            "movies": [item for item in enriched_movies if not is_incomplete_metadata(item)]
        })

    with scan_progress_lock:
        if scan_progress["status"] != "idle":
            return jsonify({"status": "error", "message": "A scan is already in progress."}), 409

    try:
        results = run_scan(past_months, future_months)
        return jsonify({
            "status": "success",
            "tv": results["tv"],
            "movies": results["movies"]
        })
    except RuntimeError as e:
        if "already in progress" in str(e):
            return jsonify({"status": "error", "message": str(e)}), 409
        return jsonify({"status": "error", "message": f"Failed to scrape releases: {e}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to scrape releases: {e}"}), 500

def run_scheduler_job() -> Dict[str, Any]:
    """Executes a scheduled refresh scan, updates last_run and last_result in settings,
    and catches all exceptions so it never crashes the background worker.
    """
    if not scheduler_job_lock.acquire(blocking=False):
        logger.warning("Scheduler job already in progress, skipping.")
        return {"status": "error", "error": "Scheduler job already running"}

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        with scan_progress_lock:
            if scan_progress["status"] != "idle":
                logger.warning("Scan already in progress, skipping scheduled job.")
                return {"status": "error", "error": "A scan is already in progress"}

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        cache_before = cursor.fetchone()[0]
        conn.close()

        past_months = int(get_setting("default_past_months", "1") or 1)
        future_months = int(get_setting("default_future_months", "2") or 2)

        results = run_scan(past_months, future_months)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        cache_after = cursor.fetchone()[0]
        conn.close()

        new_items = max(0, cache_after - cache_before)
        finished_at = datetime.now(timezone.utc).isoformat()
        tv_count = len(results.get("tv", []))
        movie_count = len(results.get("movies", []))

        result_payload = {
            "started_at": started_at,
            "finished_at": finished_at,
            "status": "ok",
            "tv_count": tv_count,
            "movie_count": movie_count,
            "new_items": new_items,
            "error": None
        }

        set_setting("scheduler_last_run", finished_at)
        set_setting("scheduler_last_result", json.dumps(result_payload))
        config.refresh()
        return result_payload
    except Exception as e:
        logger.error(f"Scheduled refresh failed: {e}", exc_info=True)
        finished_at = datetime.now(timezone.utc).isoformat()
        result_payload = {
            "started_at": started_at,
            "finished_at": finished_at,
            "status": "error",
            "tv_count": 0,
            "movie_count": 0,
            "new_items": 0,
            "error": str(e)
        }
        set_setting("scheduler_last_result", json.dumps(result_payload))
        config.refresh()
        return result_payload
    finally:
        scheduler_job_lock.release()

def scheduler_loop() -> None:
    """Background daemon thread loop for scheduled refreshes."""
    import time
    while True:
        try:
            time.sleep(30)
            config.refresh()
            if not config.scheduler_enabled:
                continue

            last_run_str = config.scheduler_last_run
            last_run = None
            if last_run_str:
                try:
                    last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
                except Exception:
                    last_run = None

            interval_hours = config.scheduler_interval_hours
            time_of_day = config.scheduler_time_of_day
            now = datetime.now(timezone.utc)

            if is_due(last_run, interval_hours, time_of_day, now, startup_time=_scheduler_startup_time, startup_delay_seconds=60):
                with scan_progress_lock:
                    if scan_progress["status"] != "idle":
                        continue
                run_scheduler_job()
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}", exc_info=True)

# Background daemon thread for scheduled refreshes. Disabled in tests for determinism.
if "PYTEST_CURRENT_TEST" not in os.environ:
    threading.Thread(target=scheduler_loop, daemon=True).start()

@app.route("/api/scheduler/status", methods=["GET"])
def get_scheduler_status() -> RouteResponse:
    """Returns the current state and execution history of the background scheduler."""
    enabled = config.scheduler_enabled
    interval_hours = config.scheduler_interval_hours
    tod_str = (config.scheduler_time_of_day or "").strip()
    time_of_day = tod_str if tod_str else None
    last_run_str = config.scheduler_last_run or None
    now = datetime.now(timezone.utc)
    try:
        next_run = compute_next_run(last_run_str, interval_hours, time_of_day, now)
        next_run_str = next_run.isoformat()
    except Exception:
        next_run_str = None

    last_result_str = config.scheduler_last_result
    last_result = None
    if last_result_str:
        try:
            last_result = json.loads(last_result_str)
        except Exception:
            last_result = None

    with scan_progress_lock:
        is_busy = (scan_progress["status"] != "idle") or scheduler_job_lock.locked()

    return jsonify({
        "status": "success",
        "enabled": enabled,
        "interval_hours": interval_hours,
        "time_of_day": time_of_day,
        "last_run": last_run_str,
        "next_run": next_run_str,
        "running": is_busy,
        "last_result": last_result
    })

@app.route("/api/scheduler/run-now", methods=["POST"])
def scheduler_run_now() -> RouteResponse:
    """Triggers an immediate background scheduled refresh scan."""
    with scan_progress_lock:
        if scan_progress["status"] != "idle":
            return jsonify({"status": "busy", "message": "A scan is already in progress."}), 409
    if scheduler_job_lock.locked():
        return jsonify({"status": "busy", "message": "A scheduler run is already in progress."}), 409

    threading.Thread(target=run_scheduler_job, daemon=True).start()
    return jsonify({"status": "started", "message": "Scheduled refresh triggered."})

@app.route("/api/cache/refresh", methods=["POST"])
def cache_refresh_item() -> RouteResponse:
    """Forces metadata enrichment from live APIs for a single movie or show and updates cache."""
    data = request.json or {}
    type_ = data.get("type")
    title = data.get("title")
    year = data.get("year")
    imdb_id = data.get("imdbId")
    
    if not type_ or not title or not year:
        return jsonify({"status": "error", "message": "Missing required fields (type, title, year)"}), 400
        
    try:
        radarr_client, sonarr_client = get_clients()
        existing = get_cached_item(type_, title, int(year), imdb_id)
        
        if type_ == "tv":
            refreshed = enrich_tv_show(title, int(year), sonarr_client)
            if existing:
                refreshed["date_str"] = existing.get("date_str")
                refreshed["date_obj"] = existing.get("date_obj")
                refreshed["href"] = existing.get("href")
                if "is_returning" in existing:
                    refreshed["is_returning"] = bool(existing["is_returning"])
                    
            # Resolve library status strictly
            in_library = False
            if sonarr_client:
                try:
                    series = sonarr_client.get_library()
                    tvdb_set = {int(s["tvdbId"]) for s in series if s.get("tvdbId")}
                    imdb_set = {str(s["imdbId"]).strip().lower() for s in series if s.get("imdbId")}
                    
                    tvdb_val = refreshed.get("tvdbId")
                    imdb_val = refreshed.get("imdbId")
                    title_val = refreshed.get("title")
                    year_val = refreshed.get("year", 0)
                    
                    has_tvdb_match = (tvdb_val and int(tvdb_val) in tvdb_set)
                    clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                    has_imdb_match = (clean_imdb and clean_imdb in imdb_set)
                    
                    # Automatch title fallback
                    has_title_match = False
                    title_norm = normalize_title(title_val or "", is_tv=True)
                    ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
                    sonarr_titles_local: Dict[str, List[int]] = {}
                    for show in series:
                        t_norm = normalize_title(show.get("title", ""), is_tv=True)
                        if t_norm:
                            if t_norm not in sonarr_titles_local:
                                sonarr_titles_local[t_norm] = []
                            if show.get("year"):
                                sonarr_titles_local[t_norm].append(int(show["year"]))
                                
                    if title_norm in sonarr_titles_local:
                        if ignore_year:
                            has_title_match = True
                        else:
                            has_title_match = any(abs(y - year_val) <= 1 for y in sonarr_titles_local[title_norm])
                            
                    in_library = has_tvdb_match or has_imdb_match or has_title_match or (bool(existing["is_in_library"]) if existing else False)
                except Exception:
                    pass
            else:
                in_library = bool(existing["is_in_library"]) if existing else False
                
            refreshed["is_in_library"] = in_library
            add_cached_item("tv", refreshed)
            cached_after = get_cached_item("tv", refreshed.get("title", title), int(refreshed.get("year", year)), refreshed.get("imdbId", imdb_id))
            if cached_after:
                refreshed["is_archived"] = bool(cached_after["is_archived"])
                refreshed["has_new_metadata"] = bool(cached_after.get("has_new_metadata", 0))
            else:
                refreshed["is_archived"] = bool(refreshed.get("is_archived", False))
                refreshed["has_new_metadata"] = bool(refreshed.get("has_new_metadata", False))
        elif type_ == "movie":
            refreshed = enrich_movie(title, int(year), radarr_client, imdb_id)
            if existing:
                refreshed["date_str"] = existing.get("date_str")
                refreshed["date_obj"] = existing.get("date_obj")
                refreshed["href"] = existing.get("href")
                
            # Resolve library status strictly
            in_library = False
            if radarr_client:
                try:
                    movies = radarr_client.get_library()
                    tmdb_set = {int(m["tmdbId"]) for m in movies if m.get("tmdbId")}
                    imdb_set = {str(m["imdbId"]).strip().lower() for m in movies if m.get("imdbId")}
                    
                    tmdb_val = refreshed.get("tmdbId")
                    imdb_val = refreshed.get("imdbId")
                    title_val = refreshed.get("title")
                    year_val = refreshed.get("year", 0)
                    
                    has_tmdb_match = (tmdb_val and int(tmdb_val) in tmdb_set)
                    clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                    has_imdb_match = (clean_imdb and clean_imdb in imdb_set)
                    
                    # Automatch title fallback
                    has_title_match = False
                    title_norm = normalize_title(title_val or "", is_tv=False)
                    ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
                    radarr_titles_local: Dict[str, List[int]] = {}
                    for movie in movies:
                        t_norm = normalize_title(movie.get("title", ""), is_tv=False)
                        if t_norm:
                            if t_norm not in radarr_titles_local:
                                radarr_titles_local[t_norm] = []
                            if movie.get("year"):
                                radarr_titles_local[t_norm].append(int(movie["year"]))
                                
                    if title_norm in radarr_titles_local:
                        if ignore_year:
                            has_title_match = True
                        else:
                            has_title_match = any(abs(y - year_val) <= 1 for y in radarr_titles_local[title_norm])
                            
                    in_library = has_tmdb_match or has_imdb_match or has_title_match or (bool(existing["is_in_library"]) if existing else False)
                except Exception:
                    pass
            else:
                in_library = bool(existing["is_in_library"]) if existing else False
                
            refreshed["is_in_library"] = in_library
            add_cached_item("movie", refreshed)
            cached_after = get_cached_item("movie", refreshed.get("title", title), int(refreshed.get("year", year)), refreshed.get("imdbId", imdb_id))
            if cached_after:
                refreshed["is_archived"] = bool(cached_after["is_archived"])
                refreshed["has_new_metadata"] = bool(cached_after.get("has_new_metadata", 0))
            else:
                refreshed["is_archived"] = bool(refreshed.get("is_archived", False))
                refreshed["has_new_metadata"] = bool(refreshed.get("has_new_metadata", False))
        else:
            return jsonify({"status": "error", "message": "Invalid media type"}), 400
            
        return jsonify({"status": "success", "item": refreshed})
    except Exception as e:
        logger.error(f"Error refreshing cache item '{title}': {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/lookup", methods=["GET"])
def lookup_media() -> RouteResponse:
    """Performs a live lookup on Sonarr/Radarr indexers for a title."""
    type_ = request.args.get("type")
    title = request.args.get("title")
    
    if not type_ or not title:
        return jsonify({"status": "error", "message": "Missing type or title parameters"}), 400
        
    radarr_client, sonarr_client = get_clients()
    
    # Repair truncated trailing year parenthesis like "Carrie (2026" -> "Carrie (2026)"
    search_title = re.sub(r'\((\d{4})$', r'(\1)', title.strip())
    base_title = re.sub(r'\s*[\(\[]\d{4}[\)\]]?$', '', search_title).strip()
    
    def _merge_unique_results(
        primary_list: List[Dict[str, Any]],
        secondary_list: List[Dict[str, Any]],
        id_key: str
    ) -> List[Dict[str, Any]]:
        """Merges secondary search results into primary list deduplicating by ID or title/year."""
        merged = list(primary_list)
        seen = set()
        for item in merged:
            key = item.get(id_key) or item.get("imdbId") or (str(item.get("title", "")).lower(), item.get("year"))
            seen.add(key)
        for item in secondary_list:
            key = item.get(id_key) or item.get("imdbId") or (str(item.get("title", "")).lower(), item.get("year"))
            if key not in seen:
                seen.add(key)
                merged.append(item)
        return merged

    try:
        if type_ == "tv":
            if not sonarr_client:
                return jsonify({"status": "error", "message": "Sonarr server is not configured."}), 400
            results = sonarr_client.lookup_series(search_title)
            if base_title and base_title != search_title:
                try:
                    base_results = sonarr_client.lookup_series(base_title)
                    results = _merge_unique_results(results, base_results, "tvdbId")
                except Exception:
                    pass
            filtered = [item for item in results if not is_incomplete_metadata(item)]
            return jsonify({"status": "success", "results": filtered})
        elif type_ == "movie":
            if not radarr_client:
                return jsonify({"status": "error", "message": "Radarr server is not configured."}), 400
            results = radarr_client.lookup_movie(search_title)
            if base_title and base_title != search_title:
                try:
                    base_results = radarr_client.lookup_movie(base_title)
                    results = _merge_unique_results(results, base_results, "tmdbId")
                except Exception:
                    pass
            filtered = [item for item in results if not is_incomplete_metadata(item)]
            return jsonify({"status": "success", "results": filtered})
        else:
            return jsonify({"status": "error", "message": "Invalid type parameter"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/add", methods=["POST"])
def add_media() -> RouteResponse:
    """Adds a movie or TV show to Radarr/Sonarr library."""
    req_data = request.json or {}
    type_ = req_data.get("type")
    raw_meta = req_data.get("raw_metadata")
    folder = req_data.get("folder")
    profile_id = req_data.get("profile_id")
    monitored = req_data.get("monitored", True)
    search_now = req_data.get("search_now", True)
    add_collection = req_data.get("add_collection", False)
    
    if not type_ or not raw_meta or not folder or not profile_id:
        return jsonify({"status": "error", "message": "Missing required fields (type, raw_metadata, folder, profile_id)"}), 400
        
    is_demo = bool(req_data.get("demo") or req_data.get("is_demo"))
    
    if is_demo:
        # Simulate addition in sandbox mode by updating cache table directly
        try:
            title = raw_meta.get("title")
            year = int(raw_meta.get("year", 0))
            imdb_id = raw_meta.get("imdbId") or raw_meta.get("imdb_id")
            existing = get_cached_item(type_, title, year, imdb_id)
            if existing:
                update_cached_library_status(type_, title, year, True, imdb_id)
            else:
                raw_meta["is_in_library"] = True
                add_cached_item(type_, raw_meta)

            # Persist MRU quality profile and root folder
            if type_ == "tv":
                set_setting("sonarr_mru_quality_profile", str(profile_id))
                set_setting("sonarr_mru_profile_id", str(profile_id))
                set_setting("sonarr_mru_root_folder", str(folder))
            else:
                set_setting("radarr_mru_quality_profile", str(profile_id))
                set_setting("radarr_mru_profile_id", str(profile_id))
                set_setting("radarr_mru_root_folder", str(folder))
            config.refresh()

            return jsonify({"status": "success", "message": f"[Demo Sandbox] Successfully added { 'TV Show' if type_ == 'tv' else 'Movie' } '{title}' to sandbox library!"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    radarr_client, sonarr_client = get_clients()
    
    if type_ == "tv" and not sonarr_client:
        return jsonify({"status": "error", "message": "Sonarr server is not configured."}), 400
    if type_ == "movie" and not radarr_client:
        return jsonify({"status": "error", "message": "Radarr server is not configured."}), 400
        
    try:
        if type_ == "tv":
            assert sonarr_client is not None
            res = sonarr_client.add_series(
                series_data=raw_meta,
                quality_profile_id=int(profile_id),
                root_folder_path=folder,
                monitored=monitored,
                search_now=search_now
            )
            # Update cache table immediately
            title = res.get("title") or raw_meta.get("title")
            year = res.get("year") or raw_meta.get("year", 0)
            imdb_id = res.get("imdbId") or raw_meta.get("imdbId")
            existing = get_cached_item("tv", title, year, imdb_id)
            if existing:
                update_cached_library_status("tv", title, year, True, imdb_id)
            else:
                raw_meta["is_in_library"] = True
                add_cached_item("tv", raw_meta)

            # Persist MRU quality profile and root folder
            set_setting("sonarr_mru_quality_profile", str(profile_id))
            set_setting("sonarr_mru_profile_id", str(profile_id))
            set_setting("sonarr_mru_root_folder", str(folder))
            config.refresh()

            return jsonify({"status": "success", "message": f"Successfully added TV Show '{res.get('title')}'!"})
        else:
            assert radarr_client is not None
            res = radarr_client.add_movie(
                movie_data=raw_meta,
                quality_profile_id=int(profile_id),
                root_folder_path=folder,
                monitored=monitored,
                search_now=search_now,
                add_collection=bool(add_collection)
            )
            # Update cache table immediately
            title = res.get("title") or raw_meta.get("title")
            year = res.get("year") or raw_meta.get("year", 0)
            imdb_id = res.get("imdbId") or raw_meta.get("imdbId")
            existing = get_cached_item("movie", title, year, imdb_id)
            if existing:
                update_cached_library_status("movie", title, year, True, imdb_id)
            else:
                raw_meta["is_in_library"] = True
                add_cached_item("movie", raw_meta)

            # Persist MRU quality profile and root folder
            set_setting("radarr_mru_quality_profile", str(profile_id))
            set_setting("radarr_mru_profile_id", str(profile_id))
            set_setting("radarr_mru_root_folder", str(folder))
            config.refresh()

            return jsonify({"status": "success", "message": f"Successfully added Movie '{res.get('title')}'!"})
    except ArrAPIError as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/link_library", methods=["POST"])
def link_library() -> RouteResponse:
    """Manually link a discovery item to an existing Sonarr/Radarr library match and mark it in-library."""
    req_data = request.json or {}
    type_ = req_data.get("type")
    title = req_data.get("title")
    year = req_data.get("year")
    imdb_id = req_data.get("imdbId")
    link_metadata = req_data.get("link_metadata") or {}
    
    if not type_ or not title or not year:
        return jsonify({"status": "error", "message": "Missing required fields (type, title, year)"}), 400
        
    try:
        from core.db import get_db_connection, get_cached_item
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Look up existing cached item
            existing = get_cached_item(type_, title, int(year), imdb_id, conn=conn)
            
            # Extract IDs from link_metadata
            tvdb_val = link_metadata.get("tvdbId")
            tmdb_val = link_metadata.get("tmdbId")
            imdb_val = link_metadata.get("imdbId")
            
            if existing:
                cursor = conn.cursor()
                # Update existing cache item, setting is_in_library = 1 and copying IDs
                cursor.execute('''
                    UPDATE cache SET
                        is_in_library = 1,
                        tvdb_id = COALESCE(?, tvdb_id),
                        tmdb_id = COALESCE(?, tmdb_id),
                        imdb_id = COALESCE(?, imdb_id)
                    WHERE id = ?
                ''', (tvdb_val, tmdb_val, imdb_val, existing["id"]))
                conn.commit()
            else:
                cursor = conn.cursor()
                normalized_title = normalize_title(title, is_tv=(type_ == "tv"))
                cursor.execute('''
                    INSERT INTO cache (
                        type, title, year, is_in_library, tvdb_id, tmdb_id, imdb_id, normalized_title, added_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                ''', (type_, title, int(year), tvdb_val, tmdb_val, imdb_val, normalized_title, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            
        return jsonify({"status": "success", "message": f"Successfully linked '{title}' and marked In Library."})
    except Exception as e:
        logger.error(f"Error linking library item '{title}': {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



import threading
import time

def background_poster_healer() -> None:
    """Background thread that populates missing poster URLs in the cache database."""
    # Give the server some time to start up and allow connections to initialize
    time.sleep(5)
    
    try:
        radarr_client, sonarr_client = get_clients()
    except Exception:
        radarr_client, sonarr_client = None, None
        
    while True:
        try:
            from core.db import get_db_connection, add_cached_item
            from core.enricher import enrich_tv_show, enrich_movie
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT type, title, year, imdb_id, is_archived FROM cache WHERE poster_url IS NULL LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                # No more items to heal, terminate thread
                break
                
            type_ = row["type"]
            title = row["title"]
            year = row["year"]
            imdb_id = row["imdb_id"]
            is_archived = bool(row["is_archived"])
            
            # Enrich and store
            if type_ == "tv":
                data = enrich_tv_show(title, year, sonarr_client)
            else:
                data = enrich_movie(title, year, radarr_client, imdb_id)
                
            # Preserve archive status
            data["is_archived"] = is_archived
            
            # Save it back to cache (which will populate poster_url)
            add_cached_item(type_, data)
            
            # Sleep to avoid rate limiting
            time.sleep(2)
            
        except Exception as e:
            logger.warning(f"Background poster healer error: {e}", exc_info=True)
            time.sleep(5)

# Start background healer thread. Disabled in test suites to prevent background DB contention.
if "PYTEST_CURRENT_TEST" not in os.environ:
    threading.Thread(target=background_poster_healer, daemon=True).start()

@app.route("/api/feeds", methods=["GET"])
def get_custom_feeds() -> RouteResponse:
    """Retrieve all configured custom feeds."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM custom_feeds")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"status": "success", "feeds": rows})

@app.route("/api/feeds", methods=["POST"])
def save_custom_feed() -> RouteResponse:
    """Create or update a custom feed with strict schema and regex safety validation."""
    data = request.json or {}
    id_ = data.get("id")
    name = data.get("name")
    url = data.get("url")
    feed_type = data.get("feed_type")
    default_media_type = data.get("default_media_type", "movie")
    enabled = data.get("enabled", 1)
    
    if not name or not url or not feed_type:
        return jsonify({"status": "error", "message": "Missing required fields (name, url, feed_type)"}), 400
        
    http_headers = data.get("http_headers")
    if isinstance(http_headers, dict):
        headers_str = json.dumps(http_headers)
    elif isinstance(http_headers, str):
        headers_str = http_headers
    else:
        headers_str = "{}"
        
    # Validate http_headers is valid JSON
    try:
        json.loads(headers_str)
    except ValueError:
        return jsonify({"status": "error", "message": "HTTP headers must be a valid JSON dictionary"}), 400
        
    parser_config = data.get("parser_config")
    if isinstance(parser_config, dict):
        parser_cfg_str = json.dumps(parser_config)
        parser_cfg_dict = parser_config
    elif isinstance(parser_config, str):
        parser_cfg_str = parser_config
        try:
            parser_cfg_dict = json.loads(parser_config)
        except ValueError:
            return jsonify({"status": "error", "message": "Parser config must be a valid JSON dictionary"}), 400
    else:
        return jsonify({"status": "error", "message": "Parser config must be a valid JSON object"}), 400
        
    # Validate required mapping elements in parser config
    if feed_type not in ("metacritic_tv", "metacritic_movie", "dvds_releases", "tvmaze_schedule", "tmdb_movies"):
        mappings = parser_cfg_dict.get("mappings", {})
        if "title" not in mappings:
            return jsonify({"status": "error", "message": "Parser config mappings must contain at least a 'title' selector rule"}), 400
            
        # Validate regex transforms safety (ReDoS defense)
        for field, rules in mappings.items():
            for t in rules.get("transforms", []):
                if t.get("type") in ("regex_search", "regex_replace"):
                    pattern = t.get("pattern", "")
                    if not is_safe_regex(pattern):
                        return jsonify({"status": "error", "message": f"Regular expression pattern '{pattern}' in transform mapping for '{field}' contains unsafe nested quantifiers and was rejected."}), 400

    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.cursor()
        if id_ is not None:
            cursor.execute('''
                UPDATE custom_feeds SET
                    name = ?, url = ?, feed_type = ?, default_media_type = ?,
                    enabled = ?, http_headers = ?, parser_config = ?
                WHERE id = ?
            ''', (name, url, feed_type, default_media_type, int(enabled), headers_str, parser_cfg_str, id_))
            feed_id = id_
        else:
            cursor.execute('''
                INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, url, feed_type, default_media_type, int(enabled), headers_str, parser_cfg_str))
            feed_id = cursor.lastrowid
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        
    return jsonify({"status": "success", "message": "Feed saved successfully", "feed_id": feed_id})

@app.route("/api/feeds/test", methods=["POST"])
def test_custom_feed() -> RouteResponse:
    """Dry-run mapping configurations against target feeds returning parsed previews."""
    data = request.json or {}
    url = data.get("url")
    feed_type = data.get("feed_type")
    default_media_type = data.get("default_media_type", "movie")
    http_headers = data.get("http_headers") or {}
    parser_config = data.get("parser_config") or {}
    
    if not url or not feed_type:
        return jsonify({"status": "error", "message": "Missing required fields (url, feed_type)"}), 400
        
    # Validate regex transforms safety
    mappings = parser_config.get("mappings", {})
    for field, rules in mappings.items():
        for t in rules.get("transforms", []):
            if t.get("type") in ("regex_search", "regex_replace"):
                pattern = t.get("pattern", "")
                if not is_safe_regex(pattern):
                    return jsonify({"status": "error", "message": f"Unsafe regex '{pattern}' detected"}), 400

    try:
        import time
        start_time = time.time()
        
        if not (url.startswith("http://") or url.startswith("https://")):
            import requests
            from core.scraper import HEADERS
            https_url = f"https://{url}"
            http_url = f"http://{url}"
            discovered_url = http_url
            for test_url in (https_url, http_url):
                try:
                    if feed_type in ("metacritic_tv", "metacritic_movie", "dvds_releases", "tvmaze_schedule", "tmdb_movies"):
                        requests.get(test_url, headers=HEADERS, timeout=5)
                    else:
                        safe_fetch_feed(test_url, headers=http_headers, timeout=5)
                    discovered_url = test_url
                    break
                except Exception:
                    continue
            url = discovered_url
            
        raw_payload = safe_fetch_feed(url, headers=http_headers)
        
        # Inject details into parser config for standardize_item
        parser_config["url"] = url
        parser_config["default_media_type"] = default_media_type
        parser_config["feed_type"] = feed_type
        
        items = parse_custom_feed(parser_config, raw_payload)
        fetch_time = int((time.time() - start_time) * 1000)
        
        # Return preview serialization
        preview_items = []
        for item in items[:15]:  # Clamp preview to top 15 results
            preview_items.append({
                "title": item["title"],
                "year": item["year"],
                "type": item["type"],
                "date_str": item["date_str"],
                "href": item["href"],
                "imdb_id": item["imdb_id"],
                "tvdb_id": item["tvdb_id"],
                "tmdb_id": item["tmdb_id"],
                "description": item["description"][:120] + "..." if len(item["description"]) > 120 else item["description"]
            })
            
        return jsonify({
            "status": "success",
            "fetch_time_ms": fetch_time,
            "parsed_items_count": len(items),
            "results": preview_items,
            "errors": []
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Test scan failed: {e}"
        }), 500

@app.route("/api/feeds/delete", methods=["POST"])
def delete_custom_feed() -> RouteResponse:
    """Wipes a configured custom feed registry from the database."""
    data = request.json or {}
    id_ = data.get("id")
    if id_ is None:
        return jsonify({"status": "error", "message": "Missing feed id"}), 400
        
    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_feeds WHERE id = ?", (id_,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        
    return jsonify({"status": "success", "message": "Feed deleted successfully"})

@app.route("/api/feeds/restore", methods=["POST"])
def restore_default_feeds_route() -> RouteResponse:
    """Wipes the custom feeds registry and restores standard default configurations."""
    from core.db import restore_default_feeds
    try:
        restore_default_feeds()
        return jsonify({"status": "success", "message": "Default feeds restored successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def start_server(port: int = 5000, debug: bool = False) -> None:
    """Starts the Flask web server."""
    from core.logging_setup import setup_logging
    setup_logging(level="DEBUG" if debug else None)
    if debug:
        logger.info(f"Starting xarrtools server in DEBUG mode at http://localhost:{port}...")
        app.run(host="127.0.0.1", port=port, debug=True)
    else:
        logger.info(f"Starting xarrtools production server at http://localhost:{port}...")
        try:
            from waitress import serve
            serve(app, host="127.0.0.1", port=port)
        except ImportError:
            app.run(host="127.0.0.1", port=port, debug=False)
