import os
import sys
import json
import threading
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from datetime import datetime, timedelta

from core.config import config
from core.client import RadarrClient, SonarrClient, ArrAPIError
from core.scraper import get_discoveries
from core.enricher import enrich_tv_show, enrich_movie
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
    get_setting
)

# Initialize Database and Prune Expired cache entries
init_db()
clean_expired_cache()

# Resolve template directory path inside the package folder
templates_dir = Path(__file__).resolve().parent / "templates"

app = Flask(
    __name__,
    template_folder=str(templates_dir),
    static_folder=str(templates_dir),
    static_url_path="/static"
)

# Thread-safe global scan progress
scan_progress = {
    "status": "idle",
    "message": "",
    "current": 0,
    "total": 0
}
scan_progress_lock = threading.Lock()

def update_scan_progress(status, message, current=0, total=0):
    with scan_progress_lock:
        scan_progress["status"] = status
        scan_progress["message"] = message
        scan_progress["current"] = current
        scan_progress["total"] = total


# Initialize Radarr / Sonarr Clients
def get_clients():
    radarr_client = None
    if config.validate_radarr():
        radarr_client = RadarrClient(config.radarr_url, config.radarr_api_key)
        
    sonarr_client = None
    if config.validate_sonarr():
        sonarr_client = SonarrClient(config.sonarr_url, config.sonarr_api_key)
        
    return radarr_client, sonarr_client

@app.route("/")
def index():
    """Serves the primary UI page."""
    return render_template("index.html")

@app.route("/api/config", methods=["GET"])
def get_server_config():
    """Returns Root Paths and Quality Profiles from Sonarr and Radarr."""
    radarr_client, sonarr_client = get_clients()
    
    response_data = {
        "radarr": {"configured": False, "folders": [], "profiles": []},
        "sonarr": {"configured": False, "folders": [], "profiles": [], "language_profiles": []}
    }
    
    if radarr_client:
        try:
            response_data["radarr"]["folders"] = radarr_client.get_root_folders()
            response_data["radarr"]["profiles"] = radarr_client.get_quality_profiles()
            response_data["radarr"]["configured"] = True
        except Exception as e:
            app.logger.error(f"Error fetching Radarr config: {e}")
            
    if sonarr_client:
        try:
            response_data["sonarr"]["folders"] = sonarr_client.get_root_folders()
            response_data["sonarr"]["profiles"] = sonarr_client.get_quality_profiles()
            response_data["sonarr"]["language_profiles"] = sonarr_client.get_language_profiles()
            response_data["sonarr"]["configured"] = True
        except Exception as e:
            app.logger.error(f"Error fetching Sonarr config: {e}")
            
    return jsonify(response_data)

@app.route("/api/settings", methods=["GET", "POST"])
def manage_settings():
    """Reads or updates configuration settings."""
    if request.method == "POST":
        data = request.json or {}
        for key, val in data.items():
            set_setting(key, str(val))
        return jsonify({"status": "success", "message": "Settings saved successfully."})
    else:
        return jsonify(get_all_settings())

@app.route("/api/archive", methods=["POST"])
def archive_media():
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

@app.route("/api/cache/stats", methods=["GET"])
def cache_stats():
    """Returns row counts and database size diagnostics."""
    try:
        return jsonify(get_cache_stats())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/cache/prune", methods=["POST"])
def cache_prune():
    """Manually triggers pruning of cache entries older than 12 months."""
    try:
        clean_expired_cache()
        return jsonify({"status": "success", "message": "Manual cache pruning completed."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    """Manually wipes all discoveries from the cache table."""
    try:
        clear_all_cache()
        return jsonify({"status": "success", "message": "All cached discoveries wiped successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/scan/progress", methods=["GET"])
def get_scan_progress():
    with scan_progress_lock:
        return jsonify(scan_progress)

@app.route("/api/discover", methods=["GET"])
def discover_releases():
    """Scrapes, caches, enriches, and resolves releases for TV and Movies."""
    past_months = request.args.get("past_months", default=1, type=int)
    future_months = request.args.get("future_months", default=2, type=int)
    skip_scrape = request.args.get("skip_scrape", default="false").lower() == "true"
    
    past_days = max(0, min(365, past_months * 30))
    future_days = max(0, min(365, future_months * 30))
    
    if not skip_scrape:
        with scan_progress_lock:
            if scan_progress["status"] != "idle":
                return jsonify({"status": "error", "message": "A scan is already in progress."}), 409
    
    ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
    radarr_client, sonarr_client = get_clients()
    
    # 1. Fetch libraries in single queries to optimize check (collecting TVDB/TMDB and IMDb sets, and normalized titles for automatch)
    radarr_tmdb_ids = set()
    radarr_imdb_ids = set()
    radarr_titles = {}
    sonarr_tvdb_ids = set()
    sonarr_imdb_ids = set()
    sonarr_titles = {}
    
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
                title_norm = normalize_title(movie.get("title", ""))
                if title_norm:
                    if title_norm not in radarr_titles:
                        radarr_titles[title_norm] = []
                    if movie.get("year"):
                        radarr_titles[title_norm].append(int(movie["year"]))
        except Exception as e:
            app.logger.error(f"Error fetching Radarr library: {e}")
            
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
                title_norm = normalize_title(show.get("title", ""))
                if title_norm:
                    if title_norm not in sonarr_titles:
                        sonarr_titles[title_norm] = []
                    if show.get("year"):
                        sonarr_titles[title_norm].append(int(show["year"]))
        except Exception as e:
            app.logger.error(f"Error fetching Sonarr library: {e}")
            
    enriched_tv = []
    enriched_movies = []
    
    if skip_scrape:
        # Load directly from database cache
        from datetime import datetime, timedelta
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
                title_norm = normalize_title(row["title"])
                if title_norm in sonarr_titles:
                    if ignore_year:
                        has_title_match = True
                    else:
                        row_year = row["year"]
                        has_title_match = any(abs(y - row_year) <= 1 for y in sonarr_titles[title_norm])
                        
                in_library = has_tvdb_match or has_imdb_match or has_title_match
                
                # Sync status if changed
                if in_library != bool(row["is_in_library"]):
                    update_cached_library_status("tv", row["title"], row["year"], in_library, imdb_id)
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
                "is_returning": bool(row["is_returning"]),
                "date_str": row["date_str"],
                "raw_metadata": None,
                "rating_imdb": row.get("rating_imdb", "") or "",
                "rating_metacritic": row.get("rating_metacritic", "") or "",
                "rating_rt": row.get("rating_rt", "") or ""
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
                title_norm = normalize_title(row["title"])
                if title_norm in radarr_titles:
                    if ignore_year:
                        has_title_match = True
                    else:
                        row_year = row["year"]
                        has_title_match = any(abs(y - row_year) <= 1 for y in radarr_titles[title_norm])
                        
                in_library = has_tmdb_match or has_imdb_match or has_title_match
                
                # Sync status if changed
                if in_library != bool(row["is_in_library"]):
                    update_cached_library_status("movie", row["title"], row["year"], in_library, imdb_id)
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
                "date_str": row["date_str"],
                "raw_metadata": None,
                "rating_imdb": row.get("rating_imdb", "") or "",
                "rating_metacritic": row.get("rating_metacritic", "") or "",
                "rating_rt": row.get("rating_rt", "") or ""
            }
            enriched_movies.append(data)
            
        return jsonify({
            "status": "success",
            "tv": enriched_tv,
            "movies": enriched_movies
        })
        
    try:
        if not skip_scrape:
            update_scan_progress("scraping", "Scraping Metacritic and DVD release calendars...", 0, 0)
            
        try:
            tv_raw, movie_raw = get_discoveries(past_days, future_days)
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to scrape releases: {e}"}), 500
            
        # 2. Enrich TV shows (using database cache optimization)
        total_items = len(tv_raw) + len(movie_raw)
        for idx, item in enumerate(tv_raw):
            try:
                if not skip_scrape:
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
                        title_norm = normalize_title(cached["title"])
                        if title_norm in sonarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - cached["year"]) <= 1 for y in sonarr_titles[title_norm])
                                
                        in_library = has_tvdb_match or has_imdb_match or has_title_match
                        
                        # Sync status if changed
                        if in_library != bool(cached["is_in_library"]):
                            update_cached_library_status("tv", cached["title"], cached["year"], in_library, imdb_val)
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
                        "raw_metadata": None,
                        "rating_imdb": cached.get("rating_imdb", "") or "",
                        "rating_metacritic": cached.get("rating_metacritic", "") or "",
                        "rating_rt": cached.get("rating_rt", "") or ""
                    }
                else:
                    data = enrich_tv_show(item["title"], item["date_obj"].year, sonarr_client)
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    data["is_returning"] = item.get("is_returning", False)
                    data["is_archived"] = bool(cached["is_archived"]) if cached else False
                    
                    # Resolve library status
                    in_library = False
                    tvdb_val = data.get("tvdbId")
                    imdb_val = data.get("imdbId")
                    if sonarr_client:
                        has_tvdb_match = (tvdb_val and int(tvdb_val) in sonarr_tvdb_ids)
                        clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                        has_imdb_match = (clean_imdb and clean_imdb in sonarr_imdb_ids)
                        
                        has_title_match = False
                        title_norm = normalize_title(data["title"])
                        if title_norm in sonarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - data["year"]) <= 1 for y in sonarr_titles[title_norm])
                                
                        in_library = has_tvdb_match or has_imdb_match or has_title_match
                    else:
                        in_library = bool(cached["is_in_library"]) if cached else False
                        
                    data["is_in_library"] = in_library
                    data["date_str"] = item.get("date_str", "")
                    data["date_obj"] = item.get("date_obj")
                    data["href"] = item.get("href", "")
                        
                    # Cache newly fetched details
                    add_cached_item("tv", data)
                    
                data["date_str"] = item["date_str"]
                data["is_returning"] = item.get("is_returning", False)
                enriched_tv.append(data)
            except Exception as e:
                app.logger.error(f"Error enriching TV show '{item['title']}': {e}")
                item["plot"] = item["description"]
                item["cast"] = "Cast details not available."
                item["genres"] = []
                item["tvdbId"] = None
                item["imdbId"] = None
                item["is_in_library"] = False
                item["is_archived"] = False
                item["raw_metadata"] = None
                item["is_returning"] = item.get("is_returning", False)
                enriched_tv.append(item)
                
        # 3. Enrich Movies (using database cache optimization)
        for idx, item in enumerate(movie_raw):
            try:
                if not skip_scrape:
                    current_idx = len(tv_raw) + idx + 1
                    update_scan_progress("enriching", f"Getting metadata for {item['title']}", current_idx, total_items)
                cached = get_cached_item("movie", item["title"], item["date_obj"].year, item.get("imdbId"))
                
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
                        title_norm = normalize_title(cached["title"])
                        if title_norm in radarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - cached["year"]) <= 1 for y in radarr_titles[title_norm])
                                
                        in_library = has_tmdb_match or has_imdb_match or has_title_match
                        
                        # Sync status if changed
                        if in_library != bool(cached["is_in_library"]):
                            update_cached_library_status("movie", cached["title"], cached["year"], in_library, imdb_val)
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
                        "raw_metadata": None,
                        "rating_imdb": cached.get("rating_imdb", "") or "",
                        "rating_metacritic": cached.get("rating_metacritic", "") or "",
                        "rating_rt": cached.get("rating_rt", "") or ""
                    }
                else:
                    data = enrich_movie(item["title"], item["date_obj"].year, radarr_client, item.get("imdbId"))
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    if "imdbId" not in data or not data["imdbId"]:
                        data["imdbId"] = item.get("imdbId")
                    data["is_archived"] = bool(cached["is_archived"]) if cached else False
                    
                    # Resolve library status
                    in_library = False
                    tmdb_val = data.get("tmdbId")
                    imdb_val = data.get("imdbId")
                    if radarr_client:
                        has_tmdb_match = (tmdb_val and int(tmdb_val) in radarr_tmdb_ids)
                        clean_imdb = str(imdb_val).strip().lower() if imdb_val else ""
                        has_imdb_match = (clean_imdb and clean_imdb in radarr_imdb_ids)
                        
                        has_title_match = False
                        title_norm = normalize_title(data["title"])
                        if title_norm in radarr_titles:
                            if ignore_year:
                                has_title_match = True
                            else:
                                has_title_match = any(abs(y - data["year"]) <= 1 for y in radarr_titles[title_norm])
                                
                        in_library = has_tmdb_match or has_imdb_match or has_title_match
                    else:
                        in_library = bool(cached["is_in_library"]) if cached else False
                        
                    data["is_in_library"] = in_library
                    data["date_str"] = item.get("date_str", "")
                    data["date_obj"] = item.get("date_obj")
                    data["href"] = item.get("href", "")
                        
                    # Cache newly fetched details
                    add_cached_item("movie", data)
                    
                data["date_str"] = item["date_str"]
                if "imdbId" not in data or not data["imdbId"]:
                    data["imdbId"] = item.get("imdbId")
                enriched_movies.append(data)
            except Exception as e:
                app.logger.error(f"Error enriching movie '{item['title']}': {e}")
                item["plot"] = item["description"]
                item["cast"] = "Cast details not available."
                item["genres"] = []
                item["tmdbId"] = None
                item["is_in_library"] = False
                item["is_archived"] = False
                item["raw_metadata"] = None
                if "imdbId" not in item or not item["imdbId"]:
                    item["imdbId"] = item.get("imdbId")
                enriched_movies.append(item)
                
        return jsonify({
            "status": "success",
            "tv": enriched_tv,
            "movies": enriched_movies
        })
    finally:
        if not skip_scrape:
            update_scan_progress("idle", "Idle", 0, 0)

@app.route("/api/cache/refresh", methods=["POST"])
def cache_refresh_item():
    """Forces metadata enrichment from live APIs for a single movie or show and updates cache."""
    data = request.json or {}
    type_ = data.get("type")
    title = data.get("title")
    year = data.get("year")
    imdb_id = data.get("imdbId")
    
    if not type_ or not title or not year:
        return jsonify({"status": "error", "message": "Missing required fields (type, title, year)"}), 400
        
    radarr_client, sonarr_client = get_clients()
    
    try:
        # Check if currently marked as archived in cache to preserve it
        existing = get_cached_item(type_, title, int(year), imdb_id)
        is_archived = bool(existing["is_archived"]) if existing else False
        
        if type_ == "tv":
            refreshed = enrich_tv_show(title, int(year), sonarr_client)
            refreshed["is_archived"] = is_archived
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
                    title_norm = normalize_title(title_val)
                    ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
                    sonarr_titles_local = {}
                    for show in series:
                        t_norm = normalize_title(show.get("title", ""))
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
                            
                    in_library = has_tvdb_match or has_imdb_match or has_title_match
                except Exception:
                    pass
            else:
                in_library = bool(existing["is_in_library"]) if existing else False
                
            refreshed["is_in_library"] = in_library
            add_cached_item("tv", refreshed)
        elif type_ == "movie":
            refreshed = enrich_movie(title, int(year), radarr_client, imdb_id)
            refreshed["is_archived"] = is_archived
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
                    title_norm = normalize_title(title_val)
                    ignore_year = (get_setting("default_match_ignore_year", "1") == "1")
                    radarr_titles_local = {}
                    for movie in movies:
                        t_norm = normalize_title(movie.get("title", ""))
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
                            
                    in_library = has_tmdb_match or has_imdb_match or has_title_match
                except Exception:
                    pass
            else:
                in_library = bool(existing["is_in_library"]) if existing else False
                
            refreshed["is_in_library"] = in_library
            add_cached_item("movie", refreshed)
        else:
            return jsonify({"status": "error", "message": "Invalid media type"}), 400
            
        return jsonify({"status": "success", "item": refreshed})
    except Exception as e:
        app.logger.error(f"Error refreshing cache item '{title}': {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/lookup", methods=["GET"])
def lookup_media():
    """Performs a live lookup on Sonarr/Radarr indexers for a title."""
    type_ = request.args.get("type")
    title = request.args.get("title")
    
    if not type_ or not title:
        return jsonify({"status": "error", "message": "Missing type or title parameters"}), 400
        
    radarr_client, sonarr_client = get_clients()
    
    try:
        if type_ == "tv":
            if not sonarr_client:
                return jsonify({"status": "error", "message": "Sonarr server is not configured."}), 400
            results = sonarr_client.lookup_series(title)
            return jsonify({"status": "success", "results": results})
        elif type_ == "movie":
            if not radarr_client:
                return jsonify({"status": "error", "message": "Radarr server is not configured."}), 400
            results = radarr_client.lookup_movie(title)
            return jsonify({"status": "success", "results": results})
        else:
            return jsonify({"status": "error", "message": "Invalid type parameter"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/add", methods=["POST"])
def add_media():
    """Adds a movie or TV show to Radarr/Sonarr library."""
    req_data = request.json or {}
    type_ = req_data.get("type")
    raw_meta = req_data.get("raw_metadata")
    folder = req_data.get("folder")
    profile_id = req_data.get("profile_id")
    lang_profile_id = req_data.get("lang_profile_id", 1)
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
            res = sonarr_client.add_series(
                series_data=raw_meta,
                quality_profile_id=int(profile_id),
                root_folder_path=folder,
                monitored=monitored,
                search_now=search_now,
                language_profile_id=int(lang_profile_id) if lang_profile_id else None
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
            return jsonify({"status": "success", "message": f"Successfully added TV Show '{res.get('title')}'!"})
        else:
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
            return jsonify({"status": "success", "message": f"Successfully added Movie '{res.get('title')}'!"})
    except ArrAPIError as e:
        return jsonify({"status": "error", "message": str(e)}), 500


import threading
import time

def background_poster_healer():
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
            # Silently catch and retry after a delay to avoid crashing the background thread
            time.sleep(5)

# Start background healer thread
threading.Thread(target=background_poster_healer, daemon=True).start()

def start_server(port=5000):
    """Starts the Flask web server."""
    print(f"Starting xarrtools server at http://localhost:{port}...")
    app.run(host="127.0.0.1", port=port, debug=False)
