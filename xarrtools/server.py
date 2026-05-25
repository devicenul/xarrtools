import os
import sys
import json
from pathlib import Path
from flask import Flask, jsonify, request, render_template

from xarrtools.config import config
from xarrtools.client import RadarrClient, SonarrClient, ArrAPIError
from xarrtools.scraper import get_discoveries
from xarrtools.enricher import enrich_tv_show, enrich_movie
from xarrtools.db import (
    init_db,
    clean_expired_cache,
    get_cached_item,
    add_cached_item,
    archive_cached_item,
    get_all_settings,
    set_setting,
    get_cache_stats,
    clear_all_cache
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

@app.route("/api/discover", methods=["GET"])
def discover_releases():
    """Scrapes, caches, enriches, and resolves releases for TV and Movies."""
    past_months = request.args.get("past_months", default=1, type=int)
    future_months = request.args.get("future_months", default=2, type=int)
    
    past_days = max(0, min(365, past_months * 30))
    future_days = max(0, min(365, future_months * 30))
    
    radarr_client, sonarr_client = get_clients()
    
    # 1. Fetch libraries in single queries to optimize check
    radarr_library_ids = set()
    sonarr_library_ids = set()
    
    if radarr_client:
        try:
            radarr_lib = radarr_client.get_library()
            for movie in radarr_lib:
                if movie.get("tmdbId"):
                    radarr_library_ids.add(movie["tmdbId"])
        except Exception as e:
            app.logger.error(f"Error fetching Radarr library: {e}")
            
    if sonarr_client:
        try:
            sonarr_lib = sonarr_client.get_library()
            for show in sonarr_lib:
                if show.get("tvdbId"):
                    sonarr_library_ids.add(show["tvdbId"])
        except Exception as e:
            app.logger.error(f"Error fetching Sonarr library: {e}")
            
    try:
        tv_raw, movie_raw = get_discoveries(past_days, future_days)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to scrape releases: {e}"}), 500
        
    enriched_tv = []
    enriched_movies = []
    
    # 2. Enrich TV shows (using database cache optimization)
    for item in tv_raw:
        try:
            cached = get_cached_item("tv", item["title"], item["date_obj"].year)
            if cached:
                data = {
                    "title": cached["title"],
                    "year": cached["year"],
                    "plot": cached["description"] or item["description"],
                    "cast": cached["cast"],
                    "genres": json.loads(cached["genres"]) if cached["genres"] else [],
                    "trailer": cached["trailer"],
                    "tvdbId": cached["tvdb_id"],
                    "imdbId": cached["imdb_id"],
                    "network": cached["network"],
                    "is_in_library": False,
                    "is_archived": bool(cached["is_archived"]),
                    "raw_metadata": None
                }
                # Check library
                if data["tvdbId"] and data["tvdbId"] in sonarr_library_ids:
                    data["is_in_library"] = True
            else:
                data = enrich_tv_show(item["title"], item["date_obj"].year, sonarr_client)
                if not data["plot"] or data["plot"] == "No plot summary available.":
                    data["plot"] = item["description"]
                data["is_returning"] = item.get("is_returning", False)
                data["is_archived"] = False
                
                # Check library
                if data.get("tvdbId") and data["tvdbId"] in sonarr_library_ids:
                    data["is_in_library"] = True
                    
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
    for item in movie_raw:
        try:
            cached = get_cached_item("movie", item["title"], item["date_obj"].year, item.get("imdbId"))
            if cached:
                data = {
                    "title": cached["title"],
                    "year": cached["year"],
                    "plot": cached["description"] or item["description"],
                    "cast": cached["cast"],
                    "genres": json.loads(cached["genres"]) if cached["genres"] else [],
                    "trailer": cached["trailer"],
                    "tmdbId": cached["tmdb_id"],
                    "imdbId": cached["imdb_id"],
                    "network": cached["network"],
                    "is_in_library": False,
                    "is_archived": bool(cached["is_archived"]),
                    "raw_metadata": None
                }
                # Check library
                if data["tmdbId"] and data["tmdbId"] in radarr_library_ids:
                    data["is_in_library"] = True
            else:
                data = enrich_movie(item["title"], item["date_obj"].year, radarr_client, item.get("imdbId"))
                if not data["plot"] or data["plot"] == "No plot summary available.":
                    data["plot"] = item["description"]
                if "imdbId" not in data or not data["imdbId"]:
                    data["imdbId"] = item.get("imdbId")
                data["is_archived"] = False
                
                # Check library
                if data.get("tmdbId") and data["tmdbId"] in radarr_library_ids:
                    data["is_in_library"] = True
                    
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
    
    if not type_ or not raw_meta or not folder or not profile_id:
        return jsonify({"status": "error", "message": "Missing required fields (type, raw_metadata, folder, profile_id)"}), 400
        
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
            return jsonify({"status": "success", "message": f"Successfully added TV Show '{res.get('title')}'!"})
        else:
            res = radarr_client.add_movie(
                movie_data=raw_meta,
                quality_profile_id=int(profile_id),
                root_folder_path=folder,
                monitored=monitored,
                search_now=search_now
            )
            return jsonify({"status": "success", "message": f"Successfully added Movie '{res.get('title')}'!"})
    except ArrAPIError as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def start_server(port=5000):
    """Starts the Flask web server."""
    print(f"Starting xarrtools server at http://localhost:{port}...")
    app.run(host="127.0.0.1", port=port, debug=False)
