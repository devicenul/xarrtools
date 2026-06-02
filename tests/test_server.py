import pytest
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# 1. Isolate the database path BEFORE importing web.server
# This prevents initialization/modification of the production database during imports or test runs.
import core.db
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)

# Initialize database schemas
core.db.init_db()

# 2. Intercept and mock the background Thread start so it does not run continuously in tests
with patch("threading.Thread") as mock_thread:
    from web.server import (
        app,
        scan_progress,
        scan_progress_lock,
        update_scan_progress,
        get_clients,
        background_poster_healer,
        start_server
    )

from core.client import ArrAPIError

@pytest.fixture(autouse=True)
def cleanup_db():
    """Wipes the test database tables between test cases."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    
    # Reset default settings
    core.db.init_db()
    yield
    # Clean up temp file at the very end of the test suite if needed,
    # but since it's used globally, we'll keep it until program exits.

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_index_endpoint(client):
    with patch("web.server.render_template") as mock_render:
        mock_render.return_value = "Mock Index HTML"
        res = client.get("/")
        assert res.status_code == 200
        assert res.data == b"Mock Index HTML"
        mock_render.assert_called_once_with("index.html")

def test_get_server_config_endpoint_configured(client):
    mock_radarr = MagicMock()
    mock_radarr.get_root_folders.return_value = [{"path": "/movies"}]
    mock_radarr.get_quality_profiles.return_value = [{"id": 1, "name": "1080p"}]
    
    mock_sonarr = MagicMock()
    mock_sonarr.get_root_folders.return_value = [{"path": "/tv"}]
    mock_sonarr.get_quality_profiles.return_value = [{"id": 2, "name": "720p"}]
    mock_sonarr.get_language_profiles.return_value = [{"id": 1, "name": "English"}]

    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        res = client.get("/api/config")
        assert res.status_code == 200
        data = res.get_json()
        assert data["radarr"]["configured"] is True
        assert data["radarr"]["folders"] == [{"path": "/movies"}]
        assert data["radarr"]["profiles"] == [{"id": 1, "name": "1080p"}]
        assert data["sonarr"]["configured"] is True
        assert data["sonarr"]["folders"] == [{"path": "/tv"}]
        assert data["sonarr"]["profiles"] == [{"id": 2, "name": "720p"}]
        assert data["sonarr"]["language_profiles"] == [{"id": 1, "name": "English"}]

def test_get_server_config_endpoint_not_configured_or_errors(client):
    mock_radarr_err = MagicMock()
    mock_radarr_err.get_root_folders.side_effect = Exception("Radarr offline")
    
    mock_sonarr_err = MagicMock()
    mock_sonarr_err.get_root_folders.side_effect = Exception("Sonarr offline")

    with patch("web.server.get_clients", return_value=(mock_radarr_err, mock_sonarr_err)):
        res = client.get("/api/config")
        assert res.status_code == 200
        data = res.get_json()
        assert data["radarr"]["configured"] is False
        assert data["sonarr"]["configured"] is False

    with patch("web.server.get_clients", return_value=(None, None)):
        res = client.get("/api/config")
        assert res.status_code == 200
        data = res.get_json()
        assert data["radarr"]["configured"] is False
        assert data["sonarr"]["configured"] is False

def test_manage_settings_endpoint_get(client):
    with patch("web.server.get_all_settings", return_value={"test_key": "test_val"}):
        res = client.get("/api/settings")
        assert res.status_code == 200
        assert res.get_json() == {"test_key": "test_val"}

def test_manage_settings_endpoint_post(client):
    with patch("web.server.set_setting") as mock_set:
        res = client.post("/api/settings", json={"key1": "val1", "key2": "val2"})
        assert res.status_code == 200
        assert res.get_json() == {"status": "success", "message": "Settings saved successfully."}
        assert mock_set.call_count == 2
        mock_set.assert_any_call("key1", "val1")
        mock_set.assert_any_call("key2", "val2")

def test_archive_media_endpoint_missing_params(client):
    res = client.post("/api/archive", json={})
    assert res.status_code == 400
    assert "Missing type or title" in res.get_json()["message"]

    res = client.post("/api/archive", json={"type": "movie"})
    assert res.status_code == 400

def test_archive_media_endpoint_success(client):
    with patch("web.server.archive_cached_item") as mock_archive:
        res = client.post("/api/archive", json={
            "type": "movie",
            "title": "Inception",
            "year": 2010,
            "archive": True,
            "raw_item": {"meta": "data"}
        })
        assert res.status_code == 200
        assert res.get_json()["status"] == "success"
        mock_archive.assert_called_once_with("movie", "Inception", 2010, True, {"meta": "data"})

def test_archive_media_endpoint_error(client):
    with patch("web.server.archive_cached_item", side_effect=Exception("DB connection error")):
        res = client.post("/api/archive", json={"type": "movie", "title": "Inception"})
        assert res.status_code == 500
        assert "DB connection error" in res.get_json()["message"]

def test_cache_stats_endpoint(client):
    with patch("web.server.get_cache_stats", return_value={"total_rows": 42}):
        res = client.get("/api/cache/stats")
        assert res.status_code == 200
        assert res.get_json() == {"total_rows": 42}

    with patch("web.server.get_cache_stats", side_effect=Exception("Failed")):
        res = client.get("/api/cache/stats")
        assert res.status_code == 500

def test_cache_prune_endpoint(client):
    with patch("web.server.clean_expired_cache") as mock_prune:
        res = client.post("/api/cache/prune")
        assert res.status_code == 200
        assert "Manual cache pruning completed" in res.get_json()["message"]
        mock_prune.assert_called_once()

    with patch("web.server.clean_expired_cache", side_effect=Exception("Failed")):
        res = client.post("/api/cache/prune")
        assert res.status_code == 500

def test_cache_clear_endpoint(client):
    with patch("web.server.clear_all_cache") as mock_clear:
        res = client.post("/api/cache/clear")
        assert res.status_code == 200
        assert "All cached discoveries wiped" in res.get_json()["message"]
        mock_clear.assert_called_once()

    with patch("web.server.clear_all_cache", side_effect=Exception("Failed")):
        res = client.post("/api/cache/clear")
        assert res.status_code == 500

def test_get_scan_progress_endpoint(client):
    res = client.get("/api/scan/progress")
    assert res.status_code == 200
    data = res.get_json()
    assert "status" in data
    assert "current" in data

def test_discover_releases_already_running(client):
    # Set progress to scanning/enriching
    update_scan_progress("scraping", "Working...", 1, 10)
    try:
        res = client.get("/api/discover")
        assert res.status_code == 409
        assert "already in progress" in res.get_json()["message"]
    finally:
        update_scan_progress("idle", "Idle", 0, 0)

def test_discover_releases_scrape_failure(client):
    with patch("web.server.get_discoveries", side_effect=Exception("Scraper timed out")):
        res = client.get("/api/discover")
        assert res.status_code == 500
        assert "Failed to scrape releases" in res.get_json()["message"]

def test_discover_releases_skip_scrape_no_clients(client):
    # Populate cache table with items
    from core.db import add_cached_item
    tv_date = datetime.now().strftime("%Y-%m-%d")
    movie_date = datetime.now().strftime("%Y-%m-%d")
    item_tv = {
        "title": "Show A", "year": 2025, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date
    }
    item_movie = {
        "title": "Movie A", "year": 2024, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 22, "imdbId": "tt22", "network": "Paramount", "is_in_library": False,
        "is_archived": True, "date_str": movie_date, "date_obj": movie_date
    }
    add_cached_item("tv", item_tv)
    add_cached_item("movie", item_movie)

    # When no clients are configured, it should return cached status directly
    with patch("web.server.get_clients", return_value=(None, None)):
        res = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
        assert res.status_code == 200
        data = res.get_json()
        assert len(data["tv"]) == 1
        assert len(data["movies"]) == 1
        assert data["tv"][0]["title"] == "Show A"
        assert data["tv"][0]["is_in_library"] is False
        assert data["movies"][0]["is_in_library"] is False
        assert data["movies"][0]["is_archived"] is True

def test_discover_releases_skip_scrape_with_clients_sync(client):
    # Setup cache
    from core.db import add_cached_item
    tv_date = datetime.now().strftime("%Y-%m-%d")
    movie_date = datetime.now().strftime("%Y-%m-%d")
    item_tv = {
        "title": "Show B", "year": 2025, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date
    }
    item_movie = {
        "title": "Movie B", "year": 2024, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 22, "imdbId": "tt22", "network": "Paramount", "is_in_library": False,
        "is_archived": False, "date_str": movie_date, "date_obj": movie_date
    }
    add_cached_item("tv", item_tv)
    add_cached_item("movie", item_movie)

    # Mock Sonarr/Radarr clients where shows/movies are in the library
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": 22, "imdbId": "tt22", "title": "Movie B", "year": 2024}]
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": 11, "imdbId": "tt11", "title": "Show B", "year": 2025}]

    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        # Run discover with skip_scrape
        res = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
        assert res.status_code == 200
        data = res.get_json()
        assert data["tv"][0]["is_in_library"] is True
        assert data["movies"][0]["is_in_library"] is True

        # Check that cache was updated/synced to in_library=True
        conn = core.db.get_db_connection()
        tv_row = conn.execute("SELECT is_in_library FROM cache WHERE type='tv'").fetchone()
        movie_row = conn.execute("SELECT is_in_library FROM cache WHERE type='movie'").fetchone()
        conn.close()
        assert tv_row["is_in_library"] == 1
        assert movie_row["is_in_library"] == 1

def test_discover_releases_live_scrape_and_enrich(client):
    # TV scraper output has date_obj as datetime object
    tv_raw = [{
        "title": "Show Live", "date_obj": datetime.now(), "description": "Scraped TV Plot", "date_str": "2026-05-30", "is_returning": False
    }]
    movie_raw = [{
        "title": "Movie Live", "date_obj": datetime.now(), "description": "Scraped Movie Plot", "date_str": "2026-05-30", "imdbId": "tt999"
    }]

    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = []
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = []

    # Mock get_discoveries
    with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
        # Mock enrichment calls
        with patch("web.server.enrich_tv_show") as mock_enrich_tv, \
             patch("web.server.enrich_movie") as mock_enrich_movie:
             
            mock_enrich_tv.return_value = {
                "title": "Show Live", "year": 2026, "plot": "Enriched TV Plot", "cast": "Cast TV",
                "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
                "tvdbId": 12, "imdbId": "tt12", "network": "HBO", "is_in_library": False, "is_archived": False
            }
            mock_enrich_movie.return_value = {
                "title": "Movie Live", "year": 2026, "plot": "Enriched Movie Plot", "cast": "Cast Movie",
                "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
                "tmdbId": 34, "imdbId": "tt999", "network": "Paramount", "is_in_library": False, "is_archived": False
            }

            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            assert data["tv"][0]["title"] == "Show Live"
            assert data["movies"][0]["title"] == "Movie Live"
            
            # Check cache is written
            conn = core.db.get_db_connection()
            rows = conn.execute("SELECT title, type, poster_url FROM cache").fetchall()
            conn.close()
            assert len(rows) == 2

def test_discover_releases_live_scrape_valid_cache_hit(client):
    # If the item is already in the cache database and cache is complete, it shouldn't enrich again
    from core.db import add_cached_item
    tv_date = datetime.now().strftime("%Y-%m-%d")
    item_tv = {
        "title": "Show Hits", "year": datetime.now().year, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": "8.0"
    }
    add_cached_item("tv", item_tv)
    
    # Touch the added_at to be current so it counts as recently updated
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()
    conn.close()

    tv_raw = [{
        "title": "Show Hits", "date_obj": datetime.now(), "description": "Scraped TV Plot", "date_str": tv_date, "is_returning": False
    }]
    movie_raw = []

    with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
        with patch("core.enricher.enrich_tv_show") as mock_enrich_tv:
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            assert len(data["tv"]) == 1
            assert data["tv"][0]["title"] == "Show Hits"
            mock_enrich_tv.assert_not_called()

def test_discover_releases_live_scrape_enrich_exception_fallback(client):
    tv_raw = [{
        "title": "Show Fails", "date_obj": datetime.now(), "description": "Scraped TV Plot", "date_str": "2026-05-30", "is_returning": False
    }]
    movie_raw = [{
        "title": "Movie Fails", "date_obj": datetime.now(), "description": "Scraped Movie Plot", "date_str": "2026-05-30"
    }]

    with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
        with patch("web.server.enrich_tv_show", side_effect=Exception("Enrichment failed")), \
             patch("web.server.enrich_movie", side_effect=Exception("Enrichment failed")):
             
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            # TV show should fall back to basic values
            assert data["tv"][0]["title"] == "Show Fails"
            assert data["tv"][0]["plot"] == "Scraped TV Plot"
            assert data["movies"][0]["title"] == "Movie Fails"
            assert data["movies"][0]["plot"] == "Scraped Movie Plot"

def test_cache_refresh_item_endpoint_missing_params(client):
    res = client.post("/api/cache/refresh", json={})
    assert res.status_code == 400

    res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show"})
    assert res.status_code == 400

def test_cache_refresh_item_endpoint_invalid_type(client):
    res = client.post("/api/cache/refresh", json={"type": "music", "title": "Show", "year": 2026})
    assert res.status_code == 400

def test_cache_refresh_item_endpoint_tv_success(client):
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": 123, "imdbId": "tt123", "title": "Refreshed Show", "year": 2026}]
    
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)), \
         patch("web.server.enrich_tv_show") as mock_enrich_tv:
         
        mock_enrich_tv.return_value = {
            "title": "Refreshed Show", "year": 2026, "plot": "New Plot", "cast": "Cast",
            "genres": ["Drama"], "trailer": "Trailer", "poster_url": "http://poster.jpg",
            "tvdbId": 123, "imdbId": "tt123", "network": "HBO"
        }
        
        # Inject existing cached row to check if is_archived and other attributes are preserved
        from core.db import add_cached_item
        add_cached_item("tv", {
            "title": "Refreshed Show", "year": 2026, "plot": "Old Plot", "cast": "Cast",
            "genres": ["Drama"], "trailer": "Trailer", "poster_url": "http://poster.jpg",
            "tvdbId": 123, "imdbId": "tt123", "network": "HBO", "is_in_library": False,
            "is_archived": True, "date_str": "2026-05-30"
        })

        res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Refreshed Show", "year": 2026})
        assert res.status_code == 200
        data = res.get_json()["item"]
        assert data["is_in_library"] is True
        assert data["is_archived"] is True
        assert data["plot"] == "New Plot"

def test_cache_refresh_item_endpoint_movie_success(client):
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": 456, "imdbId": "tt456", "title": "Refreshed Movie", "year": 2026}]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)), \
         patch("web.server.enrich_movie") as mock_enrich_movie:
         
        mock_enrich_movie.return_value = {
            "title": "Refreshed Movie", "year": 2026, "plot": "New Plot", "cast": "Cast",
            "genres": ["Action"], "trailer": "Trailer", "poster_url": "http://poster.jpg",
            "tmdbId": 456, "imdbId": "tt456", "network": "Studio"
        }

        res = client.post("/api/cache/refresh", json={"type": "movie", "title": "Refreshed Movie", "year": 2026})
        assert res.status_code == 200
        data = res.get_json()["item"]
        assert data["is_in_library"] is True
        assert data["plot"] == "New Plot"

def test_cache_refresh_item_endpoint_failure(client):
    with patch("web.server.enrich_tv_show", side_effect=Exception("Offline")):
        res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Fail Show", "year": 2026})
        assert res.status_code == 500

def test_lookup_media_endpoint_missing_params(client):
    res = client.get("/api/lookup")
    assert res.status_code == 400

    res = client.get("/api/lookup?type=tv")
    assert res.status_code == 400

def test_lookup_media_endpoint_invalid_type(client):
    res = client.get("/api/lookup?type=music&title=test")
    assert res.status_code == 400

def test_lookup_media_endpoint_not_configured(client):
    with patch("web.server.get_clients", return_value=(None, None)):
        res = client.get("/api/lookup?type=tv&title=test")
        assert res.status_code == 400
        assert "Sonarr server is not configured" in res.get_json()["message"]

        res = client.get("/api/lookup?type=movie&title=test")
        assert res.status_code == 400
        assert "Radarr server is not configured" in res.get_json()["message"]

def test_lookup_media_endpoint_success(client):
    mock_radarr = MagicMock()
    mock_radarr.lookup_movie.return_value = [{"title": "Found Movie"}]
    mock_sonarr = MagicMock()
    mock_sonarr.lookup_series.return_value = [{"title": "Found Series"}]

    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        res = client.get("/api/lookup?type=tv&title=test")
        assert res.status_code == 200
        assert res.get_json()["results"] == [{"title": "Found Series"}]

        res = client.get("/api/lookup?type=movie&title=test")
        assert res.status_code == 200
        assert res.get_json()["results"] == [{"title": "Found Movie"}]

def test_lookup_media_endpoint_failure(client):
    mock_sonarr = MagicMock()
    mock_sonarr.lookup_series.side_effect = Exception("Lookup failed")
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        res = client.get("/api/lookup?type=tv&title=test")
        assert res.status_code == 500

def test_add_media_endpoint_missing_params(client):
    res = client.post("/api/add", json={})
    assert res.status_code == 400

def test_add_media_endpoint_demo_sandbox(client):
    # TV Demo Sandbox
    res = client.post("/api/add", json={
        "type": "tv", "raw_metadata": {"title": "Demo Show", "year": 2026, "imdbId": "tt123"},
        "folder": "/tv", "profile_id": 1, "demo": True
    })
    assert res.status_code == 200
    assert "Sandbox" in res.get_json()["message"]
    
    conn = core.db.get_db_connection()
    tv_row = conn.execute("SELECT is_in_library FROM cache WHERE title='Demo Show'").fetchone()
    conn.close()
    assert tv_row["is_in_library"] == 1

    # Movie Demo Sandbox
    res = client.post("/api/add", json={
        "type": "movie", "raw_metadata": {"title": "Demo Movie", "year": 2026, "imdbId": "tt456"},
        "folder": "/movies", "profile_id": 1, "is_demo": True
    })
    assert res.status_code == 200
    assert "Sandbox" in res.get_json()["message"]
    
    conn = core.db.get_db_connection()
    movie_row = conn.execute("SELECT is_in_library FROM cache WHERE title='Demo Movie'").fetchone()
    conn.close()
    assert movie_row["is_in_library"] == 1

def test_add_media_endpoint_live_errors_not_configured(client):
    with patch("web.server.get_clients", return_value=(None, None)):
        res = client.post("/api/add", json={
            "type": "tv", "raw_metadata": {"title": "Show"}, "folder": "/tv", "profile_id": 1
        })
        assert res.status_code == 400
        assert "Sonarr server is not configured" in res.get_json()["message"]

        res = client.post("/api/add", json={
            "type": "movie", "raw_metadata": {"title": "Movie"}, "folder": "/movies", "profile_id": 1
        })
        assert res.status_code == 400
        assert "Radarr server is not configured" in res.get_json()["message"]

def test_add_media_endpoint_live_success(client):
    mock_radarr = MagicMock()
    mock_radarr.add_movie.return_value = {"title": "Live Movie", "year": 2026, "imdbId": "tt456"}
    
    mock_sonarr = MagicMock()
    mock_sonarr.add_series.return_value = {"title": "Live Series", "year": 2026, "imdbId": "tt123"}

    # Insert cache row for movie and show to test update_cached_library_status inside add_media
    from core.db import add_cached_item
    add_cached_item("tv", {"title": "Live Series", "year": 2026, "imdbId": "tt123", "plot": "Plot", "is_in_library": False, "is_archived": False})
    add_cached_item("movie", {"title": "Live Movie", "year": 2026, "imdbId": "tt456", "plot": "Plot", "is_in_library": False, "is_archived": False})

    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        # Add TV Show
        res = client.post("/api/add", json={
            "type": "tv", "raw_metadata": {"title": "Live Series", "year": 2026},
            "folder": "/tv", "profile_id": 2, "lang_profile_id": 1
        })
        assert res.status_code == 200
        assert "Successfully added TV Show" in res.get_json()["message"]
        
        # Add Movie
        res = client.post("/api/add", json={
            "type": "movie", "raw_metadata": {"title": "Live Movie", "year": 2026},
            "folder": "/movies", "profile_id": 2
        })
        assert res.status_code == 200
        assert "Successfully added Movie" in res.get_json()["message"]

        # Verify cached library status synced to True
        conn = core.db.get_db_connection()
        tv_row = conn.execute("SELECT is_in_library FROM cache WHERE type='tv'").fetchone()
        movie_row = conn.execute("SELECT is_in_library FROM cache WHERE type='movie'").fetchone()
        conn.close()
        assert tv_row["is_in_library"] == 1
        assert movie_row["is_in_library"] == 1

def test_add_media_endpoint_arr_api_error(client):
    mock_radarr = MagicMock()
    mock_radarr.add_movie.side_effect = ArrAPIError("API Error adding movie")
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        res = client.post("/api/add", json={
            "type": "movie", "raw_metadata": {"title": "Live Movie", "year": 2026},
            "folder": "/movies", "profile_id": 2
        })
        assert res.status_code == 500
        assert "API Error adding movie" in res.get_json()["message"]

@patch("web.server.time.sleep")
def test_background_poster_healer_no_rows(mock_sleep):
    # With no rows in the database cache, it will break immediately
    background_poster_healer()

@patch("web.server.time.sleep")
@patch("core.enricher.enrich_tv_show")
@patch("core.enricher.enrich_movie")
def test_background_poster_healer_with_rows(mock_enrich_movie, mock_enrich_tv, mock_sleep):
    # Insert a TV show row with null poster URL
    from core.db import get_db_connection
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO cache (type, title, year, imdb_id, poster_url, description, cast, genres, trailer, network, is_in_library, is_archived, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("tv", "Show Title", 2024, "tt123", None, "Desc", "Cast", "[]", "Trailer", "Net", 0, 0, "2026-05-30 00:00:00")
    )
    conn.commit()
    conn.close()

    mock_enrich_tv.return_value = {
        "title": "Show Title",
        "year": 2024,
        "imdbId": "tt123",
        "poster_url": "http://new-poster.jpg",
        "plot": "Desc",
        "cast": "Cast",
        "genres": [],
        "trailer": "Trailer",
        "network": "Net",
        "is_in_library": False,
        "is_archived": False
    }

    # Run healer
    background_poster_healer()

    # Check that it updated the poster URL
    conn = get_db_connection()
    row = conn.execute("SELECT poster_url FROM cache WHERE title='Show Title'").fetchone()
    conn.close()
    assert row["poster_url"] == "http://new-poster.jpg"

@patch("web.server.time.sleep")
@patch("core.enricher.enrich_movie")
def test_background_poster_healer_movie(mock_enrich_movie, mock_sleep):
    from core.db import get_db_connection
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO cache (type, title, year, imdb_id, poster_url, description, cast, genres, trailer, network, is_in_library, is_archived, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("movie", "Movie Title", 2024, "tt456", None, "Desc", "Cast", "[]", "Trailer", "Net", 0, 1, "2026-05-30 00:00:00")
    )
    conn.commit()
    conn.close()

    mock_enrich_movie.return_value = {
        "title": "Movie Title",
        "year": 2024,
        "imdbId": "tt456",
        "poster_url": "http://movie-poster.jpg",
        "plot": "Desc",
        "cast": "Cast",
        "genres": [],
        "trailer": "Trailer",
        "network": "Net",
        "is_in_library": False,
        "is_archived": True
    }

    background_poster_healer()

    conn = get_db_connection()
    row = conn.execute("SELECT poster_url FROM cache WHERE title='Movie Title'").fetchone()
    conn.close()
    assert row["poster_url"] == "http://movie-poster.jpg"

@patch("web.server.time.sleep")
@patch("web.server.get_clients")
def test_background_poster_healer_exception(mock_get_clients, mock_sleep):
    # Mock get_clients to return None clients to prevent config DB queries at the start
    mock_get_clients.return_value = (None, None)

    # Mock get_db_connection to raise an exception once, then return a mock connection
    # whose fetchone() returns None to break the loop immediately.
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.fetchone.return_value = None
    
    calls = 0
    def side_effect():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Exception("DB Error")
        return mock_conn
    
    with patch("core.db.get_db_connection", side_effect=side_effect):
        background_poster_healer()
    
    assert calls == 2



@patch("web.server.app.run")
@patch("waitress.serve")
def test_start_server_production(mock_serve, mock_run):
    start_server(1234, debug=False)
    mock_serve.assert_called_once_with(app, host="127.0.0.1", port=1234)
    mock_run.assert_not_called()

@patch("web.server.app.run")
@patch("waitress.serve", side_effect=ImportError("No waitress"))
def test_start_server_fallback(mock_serve, mock_run):
    start_server(1234, debug=False)
    mock_run.assert_called_once_with(host="127.0.0.1", port=1234, debug=False)

@patch("web.server.app.run")
def test_start_server_debug(mock_run):
    start_server(1234, debug=True)
    mock_run.assert_called_once_with(host="127.0.0.1", port=1234, debug=True)

@patch("web.server.config")
@patch("web.server.RadarrClient")
@patch("web.server.SonarrClient")
def test_get_clients_both_configured(mock_sonarr, mock_radarr, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    mock_config.radarr_url = "http://radarr"
    mock_config.radarr_api_key = "key1"
    mock_config.sonarr_url = "http://sonarr"
    mock_config.sonarr_api_key = "key2"
    
    radarr, sonarr = get_clients()
    assert radarr is not None
    assert sonarr is not None
    mock_radarr.assert_called_once_with("http://radarr", "key1")
    mock_sonarr.assert_called_once_with("http://sonarr", "key2")

@patch("web.server.config")
def test_get_clients_various_configurations(mock_config):
    # 1. Radarr unconfigured, Sonarr unconfigured
    mock_config.validate_radarr.return_value = False
    mock_config.validate_sonarr.return_value = False
    radarr, sonarr = get_clients()
    assert radarr is None
    assert sonarr is None
    
    # 2. Radarr configured, Sonarr unconfigured
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = False
    mock_config.radarr_url = "http://radarr"
    mock_config.radarr_api_key = "key1"
    radarr, sonarr = get_clients()
    assert radarr is not None
    assert sonarr is None
    
    # 3. Radarr unconfigured, Sonarr configured
    mock_config.validate_radarr.return_value = False
    mock_config.validate_sonarr.return_value = True
    mock_config.sonarr_url = "http://sonarr"
    mock_config.sonarr_api_key = "key2"
    radarr, sonarr = get_clients()
    assert radarr is None
    assert sonarr is not None

def test_get_clients_library_fetch_exceptions(client):
    # Mock clients where library fetch throws exception
    mock_radarr = MagicMock()
    mock_radarr.get_library.side_effect = Exception("Radarr fail")
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.side_effect = Exception("Sonarr fail")
    
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        res = client.get("/api/discover?skip_scrape=true")
        assert res.status_code == 200

def test_get_clients_library_fetch_missing_fields(client):
    # Mock clients returning items with missing/empty fields
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [
        {"tmdbId": None, "imdbId": "   ", "title": "", "year": None},
        {"tmdbId": 101, "imdbId": "tt101", "title": "Movie duplicate", "year": 2024},
        {"tmdbId": 102, "imdbId": "tt102", "title": "Movie duplicate", "year": 2025},
        {"tmdbId": 103, "imdbId": None, "title": "No imdb Movie", "year": 2026},
    ]
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [
        {"tvdbId": None, "imdbId": "   ", "title": "", "year": None},
        {"tvdbId": 201, "imdbId": "tt201", "title": "Show duplicate", "year": 2024},
        {"tvdbId": 202, "imdbId": "tt202", "title": "Show duplicate", "year": 2025},
        {"tvdbId": 203, "imdbId": None, "title": "No imdb Show", "year": 2026},
    ]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        res = client.get("/api/discover?skip_scrape=true")
        assert res.status_code == 200

def test_api_discover_caching_and_sync_edge_cases(client):
    # Set default match ignore year = False (0) to hit year difference logic
    from core.db import add_cached_item, set_setting
    set_setting("default_match_ignore_year", "0")
    
    # 1. Incomplete TV show (added 2 days ago, missing poster/ratings/ids)
    two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    item_tv = {
        "title": "Show Incomplete", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": None,
        "tvdbId": None, "imdbId": None, "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30"
    }
    add_cached_item("tv", item_tv)
    
    # Update added_at for Show Incomplete
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = ? WHERE title = 'Show Incomplete'", (two_days_ago,))
    conn.commit()
    
    # 2. Incomplete Movie (added 1 hour ago, but recently updated is True, missing poster)
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    item_movie = {
        "title": "Movie Incomplete", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": None,
        "tmdbId": 300, "imdbId": "tt300", "network": "Paramount", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30"
    }
    add_cached_item("movie", item_movie)
    conn.execute("UPDATE cache SET added_at = ? WHERE title = 'Movie Incomplete'", (one_hour_ago,))
    conn.commit()
    conn.close()

    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": 300, "imdbId": "tt300", "title": "Movie Incomplete", "year": 2026}]
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": 400, "imdbId": "tt400", "title": "Show Incomplete", "year": 2026}]
    
    tv_raw = [
        {"title": "Show Incomplete", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False}
    ]
    movie_raw = [
        {"title": "Movie Incomplete", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}
    ]
    
    # Mock discoveries and enrichments (which run because caches are incomplete)
    with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
        with patch("web.server.enrich_tv_show") as mock_enrich_tv, \
             patch("web.server.enrich_movie") as mock_enrich_movie:
             
            mock_enrich_tv.return_value = {
                "title": "Show Incomplete", "year": 2026, "plot": "", "cast": "TV Cast",
                "genres": [], "trailer": "", "tvdbId": 400, "imdbId": "tt400", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            mock_enrich_movie.return_value = {
                "title": "Movie Incomplete", "year": 2026, "plot": "", "cast": "Movie Cast",
                "genres": [], "trailer": "", "tmdbId": 300, "imdbId": "tt300", "network": "Paramount",
                "is_in_library": False, "is_archived": False
            }
            
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200

def test_api_discover_skip_scrape_complete_cache_sync(client):
    from core.db import add_cached_item, set_setting
    
    # Add complete items in cache with is_in_library = False
    item_tv = {
        "title": "Show Complete Skip", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 550, "imdbId": "tt550", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    item_movie = {
        "title": "Movie Complete Skip", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 650, "imdbId": "tt650", "network": "Paramount", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    item_tv_not_in_lib = {
        "title": "Show Not In Library Skip", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 551, "imdbId": "tt551", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    item_movie_not_in_lib = {
        "title": "Movie Not In Library Skip", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 651, "imdbId": "tt651", "network": "Paramount", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    add_cached_item("tv", item_tv)
    add_cached_item("movie", item_movie)
    add_cached_item("tv", item_tv_not_in_lib)
    add_cached_item("movie", item_movie_not_in_lib)

    # Mock clients where only some are in library
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": 550, "imdbId": "tt550", "title": "Show Complete Skip", "year": 2026}]
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": 650, "imdbId": "tt650", "title": "Movie Complete Skip", "year": 2026}]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        # 1. ignore_year = True
        set_setting("default_match_ignore_year", "1")
        res = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
        assert res.status_code == 200
        
        # 2. ignore_year = False
        set_setting("default_match_ignore_year", "0")
        res = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
        assert res.status_code == 200

def test_api_discover_complete_cache_library_sync(client):
    from core.db import add_cached_item, set_setting
    # 1. ignore_year = False
    set_setting("default_match_ignore_year", "0")
    
    # Add complete items in cache with is_in_library = False
    item_tv = {
        "title": "Show Complete", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 500, "imdbId": "tt500", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    item_movie = {
        "title": "Movie Complete", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 600, "imdbId": "tt600", "network": "Paramount", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    add_cached_item("tv", item_tv)
    add_cached_item("movie", item_movie)
    
    # Touch added_at so it's recently updated
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()
    conn.close()
    
    # Mock clients where these items are in the library
    # TV Show matched by title automatch within 1 year
    # Movie matched by TMDB ID
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": 500, "imdbId": "tt500", "title": "Show Complete", "year": 2025}]
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": 600, "imdbId": "tt600", "title": "Movie Complete", "year": 2026}]
    
    tv_raw = [{"title": "Show Complete", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False}]
    movie_raw = [{"title": "Movie Complete", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            assert data["tv"][0]["is_in_library"] is True
            assert data["movies"][0]["is_in_library"] is True
            
    # 2. Test with ignore_year = True
    set_setting("default_match_ignore_year", "1")
    # TV Show matched by title ignoring year
    mock_sonarr.get_library.return_value = [{"tvdbId": None, "imdbId": None, "title": "Show Complete", "year": 2020}]
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200

def test_api_cache_refresh_exceptions_and_edge_cases(client):
    # 1. Missing required fields
    res = client.post("/api/cache/refresh", json={})
    assert res.status_code == 400
    
    # 2. Invalid type
    res = client.post("/api/cache/refresh", json={"type": "invalid", "title": "Test", "year": 2024})
    assert res.status_code == 400
    
    # 3. TV show - get_library throws Exception (cover try-except block)
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.side_effect = Exception("Sonarr library error")
    
    # Seed cache with existing
    from core.db import add_cached_item
    add_cached_item("tv", {
        "title": "Show Ref", "year": 2025, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": True
    })
    
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        with patch("web.server.enrich_tv_show") as mock_enrich_tv:
            mock_enrich_tv.return_value = {
                "title": "Show Ref", "year": 2025, "plot": "Enriched plot", "cast": "Cast",
                "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show Ref", "year": 2025})
            assert res.status_code == 200
            # Library sync should fall back to cached since sonarr library check threw exception
            data = res.get_json()
            assert data["item"]["is_in_library"] is False
            
    # 4. Movie - get_library throws Exception
    mock_radarr = MagicMock()
    mock_radarr.get_library.side_effect = Exception("Radarr library error")
    add_cached_item("movie", {
        "title": "Movie Ref", "year": 2025, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 22, "imdbId": "tt22", "network": "Paramount", "is_in_library": False,
        "is_archived": True
    })
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.enrich_movie") as mock_enrich_movie:
            mock_enrich_movie.return_value = {
                "title": "Movie Ref", "year": 2025, "plot": "Enriched plot", "cast": "Cast",
                "genres": [], "trailer": "", "tmdbId": 22, "imdbId": "tt22", "network": "Paramount",
                "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "movie", "title": "Movie Ref", "year": 2025})
            assert res.status_code == 200

    # 4.5 Refresh item that does NOT exist in cache (covers existing is None branches)
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.enrich_tv_show") as mock_enrich_tv:
            mock_enrich_tv.return_value = {
                "title": "New TV Show Ref", "year": 2025, "plot": "Enriched plot", "cast": "Cast",
                "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "New TV Show Ref", "year": 2025})
            assert res.status_code == 200
            
    # 5. Top-level Exception returns 500
    with patch("web.server.get_clients", side_effect=Exception("Top level fail")):
        old_propagate = app.config.get("PROPAGATE_EXCEPTIONS")
        app.config["PROPAGATE_EXCEPTIONS"] = False
        try:
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show Ref", "year": 2025})
            assert res.status_code == 500
        finally:
            if old_propagate is not None:
                app.config["PROPAGATE_EXCEPTIONS"] = old_propagate
            else:
                del app.config["PROPAGATE_EXCEPTIONS"]

def test_api_cache_refresh_successful_library_sync(client):
    from core.db import add_cached_item, set_setting
    
    # TV show refresh
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": 700, "imdbId": "tt700", "title": "Show Refresh Sync", "year": 2026}]
    
    add_cached_item("tv", {
        "title": "Show Refresh Sync", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 700, "imdbId": "tt700", "network": "Hulu", "is_in_library": False,
        "is_archived": False
    })
    
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        with patch("web.server.enrich_tv_show") as mock_enrich_tv:
            mock_enrich_tv.return_value = {
                "title": "Show Refresh Sync", "year": 2026, "plot": "Enriched", "cast": "Cast",
                "genres": [], "trailer": "", "tvdbId": 700, "imdbId": "tt700", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            # 1. ignore_year = True
            set_setting("default_match_ignore_year", "1")
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show Refresh Sync", "year": 2026})
            assert res.status_code == 200
            assert res.get_json()["item"]["is_in_library"] is True
            
            # 2. ignore_year = False
            set_setting("default_match_ignore_year", "0")
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show Refresh Sync", "year": 2026})
            assert res.status_code == 200
            
    # Movie refresh
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": 800, "imdbId": "tt800", "title": "Movie Refresh Sync", "year": 2026}]
    
    add_cached_item("movie", {
        "title": "Movie Refresh Sync", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 800, "imdbId": "tt800", "network": "Paramount", "is_in_library": False,
        "is_archived": False
    })
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.enrich_movie") as mock_enrich_movie:
            mock_enrich_movie.return_value = {
                "title": "Movie Refresh Sync", "year": 2026, "plot": "Enriched", "cast": "Cast",
                "genres": [], "trailer": "", "tmdbId": 800, "imdbId": "tt800", "network": "Paramount",
                "is_in_library": False, "is_archived": False
            }
            # 1. ignore_year = True
            set_setting("default_match_ignore_year", "1")
            res = client.post("/api/cache/refresh", json={"type": "movie", "title": "Movie Refresh Sync", "year": 2026})
            assert res.status_code == 200
            assert res.get_json()["item"]["is_in_library"] is True
            
            # 2. ignore_year = False
            set_setting("default_match_ignore_year", "0")
            res = client.post("/api/cache/refresh", json={"type": "movie", "title": "Movie Refresh Sync", "year": 2026})
            assert res.status_code == 200

def test_api_add_edge_cases(client):
    # 1. Missing fields
    res = client.post("/api/add", json={})
    assert res.status_code == 400
    
    # 2. Demo mode - item NOT in cache
    res = client.post("/api/add", json={
        "type": "tv",
        "raw_metadata": {"title": "Demo Show New", "year": 2026, "imdbId": "tt99"},
        "folder": "/tv",
        "profile_id": 1,
        "demo": True
    })
    assert res.status_code == 200
    assert "Successfully added" in res.get_json()["message"]
    
    # 2.5 Demo mode - item DOES exist in cache (covers existing True branch)
    from core.db import add_cached_item
    add_cached_item("tv", {
        "title": "Demo Show Existing", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": False
    })
    res = client.post("/api/add", json={
        "type": "tv",
        "raw_metadata": {"title": "Demo Show Existing", "year": 2026, "imdbId": "tt11"},
        "folder": "/tv",
        "profile_id": 1,
        "demo": True
    })
    assert res.status_code == 200
    
    # 3. Demo mode - exception block
    with patch("web.server.get_cached_item", side_effect=Exception("Database locked")):
        res = client.post("/api/add", json={
            "type": "tv",
            "raw_metadata": {"title": "Demo Show New", "year": 2026, "imdbId": "tt99"},
            "folder": "/tv",
            "profile_id": 1,
            "demo": True
        })
        assert res.status_code == 500
        
    # 4. Standard mode - tv item NOT in cache
    mock_sonarr = MagicMock()
    mock_sonarr.add_series.return_value = {"title": "TV Series New", "year": 2026, "imdbId": "tt10"}
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        res = client.post("/api/add", json={
            "type": "tv",
            "raw_metadata": {"title": "TV Series New", "year": 2026, "imdbId": "tt10"},
            "folder": "/tv",
            "profile_id": 1
        })
        assert res.status_code == 200
        
    # 5. Standard mode - movie item NOT in cache
    mock_radarr = MagicMock()
    mock_radarr.add_movie.return_value = {"title": "Movie New", "year": 2026, "imdbId": "tt20"}
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        res = client.post("/api/add", json={
            "type": "movie",
            "raw_metadata": {"title": "Movie New", "year": 2026, "imdbId": "tt20"},
            "folder": "/movies",
            "profile_id": 1
        })
        assert res.status_code == 200

def test_background_poster_healer_pytest_env_reload():
    # Verify reloading web.server starts the healer thread when PYTEST_CURRENT_TEST is absent.
    import importlib
    import os
    import web.server
    
    old_env = os.environ.get("PYTEST_CURRENT_TEST")
    if "PYTEST_CURRENT_TEST" in os.environ:
        del os.environ["PYTEST_CURRENT_TEST"]
        
    try:
        with patch("threading.Thread") as mock_thread:
            importlib.reload(web.server)
            mock_thread.assert_called_once()
            # Verify it targets background_poster_healer
            assert mock_thread.call_args[1]["target"] == web.server.background_poster_healer
    finally:
        if old_env is not None:
            os.environ["PYTEST_CURRENT_TEST"] = old_env

def test_api_discover_various_sync_and_incomplete_cases(client):
    from core.db import add_cached_item, set_setting
    
    # 1. TV show incomplete cache missing added_at
    item_tv_no_added_at = {
        "title": "Show No Added At", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 901, "imdbId": "tt901", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30"
    }
    add_cached_item("tv", item_tv_no_added_at)
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = NULL WHERE title = 'Show No Added At'")
    conn.commit()
    
    # 2. TV show incomplete cache invalid added_at format
    item_tv_bad_added_at = {
        "title": "Show Bad Added At", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 902, "imdbId": "tt902", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30"
    }
    add_cached_item("tv", item_tv_bad_added_at)
    conn.execute("UPDATE cache SET added_at = 'bad date' WHERE title = 'Show Bad Added At'")
    conn.commit()
    conn.close()

    # 3. Cache complete but clients None to hit else branch in library checks
    item_tv_complete = {
        "title": "Show Complete None Client", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 903, "imdbId": "tt903", "network": "Hulu", "is_in_library": True,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    item_movie_complete = {
        "title": "Movie Complete None Client", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Action"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 904, "imdbId": "tt904", "network": "Paramount", "is_in_library": True,
        "is_archived": False, "date_str": "May 30", "date_obj": "2026-05-30", "rating_imdb": "8.0"
    }
    add_cached_item("tv", item_tv_complete)
    add_cached_item("movie", item_movie_complete)
    
    # Touch added_at so they are recently updated
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = ? WHERE title IN ('Show Complete None Client', 'Movie Complete None Client')", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()
    conn.close()

    tv_raw = [
        {"title": "Show No Added At", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False},
        {"title": "Show Bad Added At", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False},
        {"title": "Show Complete None Client", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False}
    ]
    movie_raw = [
        {"title": "Movie Complete None Client", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"},
        {"title": "Movie Live Fail", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}
    ]

    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = []
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = []

    # 4. We will run skip_scrape = False with clients = (None, None) to hit lines 403, 525, 449, 572
    # And we'll mock enrichment functions
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv, \
                 patch("web.server.enrich_movie") as mock_enrich_movie:
                 
                mock_enrich_tv.return_value = {
                    "title": "Show No Added At", "year": 2026, "plot": "", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 901, "imdbId": "tt901", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                # movie enrichment returns missing imdbId to hit line 550 and 584 fallback checks
                # and covers movie enrichment exception fallback
                mock_enrich_movie.side_effect = [
                    Exception("Enrich movie exception")
                ]
                
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200

    # 5. Test with ignore_year = False for TV show / movie library sync under live scrape (lines 442-445, 565-568)
    # We set default_match_ignore_year = False (0)
    set_setting("default_match_ignore_year", "0")
    
    tv_raw_2 = [{"title": "Show Live Sync", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False}]
    movie_raw_2 = [{"title": "Movie Live Sync", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    
    # Mock clients where they match by title but different year
    mock_sonarr.get_library.return_value = [{"tvdbId": None, "imdbId": None, "title": "Show Live Sync", "year": 2025}]
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "Movie Live Sync", "year": 2025}]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw_2, movie_raw_2)):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv, \
                 patch("web.server.enrich_movie") as mock_enrich_movie:
                 
                mock_enrich_tv.return_value = {
                    "title": "Show Live Sync", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 910, "imdbId": "tt910", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                # returns missing imdbId to hit line 550, 584
                mock_enrich_movie.return_value = {
                    "title": "Movie Live Sync", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tmdbId": 920, "imdbId": "", "network": "Paramount",
                    "is_in_library": False, "is_archived": False
                }
                
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200

def test_api_cache_refresh_existing_returning_none(client):
    from core.db import add_cached_item
    # Seed cache TV show without is_returning
    add_cached_item("tv", {
        "title": "Show No Returning", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": False
    })
    
    # Manually remove is_returning from cache table row
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET is_returning = NULL WHERE title = 'Show No Returning'")
    conn.commit()
    conn.close()
    
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.enrich_tv_show") as mock_enrich_tv:
            mock_enrich_tv.return_value = {
                "title": "Show No Returning", "year": 2026, "plot": "Enriched plot", "cast": "Cast",
                "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show No Returning", "year": 2026})
            assert res.status_code == 200


def test_discover_recently_updated_branch_coverage(client):
    # Tests lines 367-368 and 489-490 (recently_updated = True)
    # We need a cached item that has a poster but is incomplete (missing rating/ids),
    # and has a recent added_at timestamp.
    from core.db import add_cached_item, get_cached_item
    from datetime import datetime, timedelta
    
    tv_date = datetime.now().strftime("%Y-%m-%d")
    item_tv = {
        "title": "Recently TV", "year": datetime.now().year, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": None, "imdbId": None, "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": None
    }
    add_cached_item("tv", item_tv)
    
    item_movie = {
        "title": "Recently Movie", "year": datetime.now().year, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": None, "imdbId": None, "network": "HBO", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": None
    }
    add_cached_item("movie", item_movie)
    
    # Update added_at for both to be 1 hour ago
    recent_time = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = ?", (recent_time,))
    conn.commit()
    conn.close()
    
    # Print cached items to verify they exist and have added_at
    c_tv = get_cached_item("tv", "Recently TV", datetime.now().year)
    c_movie = get_cached_item("movie", "Recently Movie", datetime.now().year)
    print("DEBUG: c_tv =", c_tv)
    print("DEBUG: c_movie =", c_movie)
    
    tv_raw = [{"title": "Recently TV", "date_obj": datetime.now(), "description": "Scraped TV Plot", "date_str": tv_date, "is_returning": False}]
    movie_raw = [{"title": "Recently Movie", "date_obj": datetime.now(), "description": "Scraped Movie Plot", "date_str": tv_date}]
    
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = []
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = []
    
    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv, \
                 patch("web.server.enrich_movie") as mock_enrich_movie:
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                print("DEBUG: data =", data)
                assert len(data["tv"]) == 1
                assert len(data["movies"]) == 1
                # Because recently_updated and has_poster, it is considered complete and enrichment is skipped
                mock_enrich_tv.assert_not_called()
                mock_enrich_movie.assert_not_called()


def test_discover_cached_no_added_at_movie(client):
    # Tests line 486->494: cached item has no added_at (or is None)
    from core.db import add_cached_item
    tv_date = datetime.now().strftime("%Y-%m-%d")
    item_movie = {
        "title": "NoAddedAt Movie", "year": datetime.now().year, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 33, "imdbId": "tt33", "network": "HBO", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": "8.0"
    }
    add_cached_item("movie", item_movie)
    
    # Set added_at to NULL
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = NULL")
    conn.commit()
    conn.close()
    
    movie_raw = [{"title": "NoAddedAt Movie", "date_obj": datetime.now(), "description": "Scraped Movie Plot", "date_str": tv_date}]
    
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = []
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            with patch("core.enricher.enrich_movie") as mock_enrich_movie:
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                mock_enrich_movie.assert_not_called()


def test_discover_cached_movie_title_library_match(client):
    # Tests line 513->519 (title library match for cached movies with ignore_year = True and False)
    from core.db import add_cached_item
    from core.db import set_setting
    tv_date = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Test ignore_year = True
    set_setting("default_match_ignore_year", "1")
    item_movie = {
        "title": "MatchTitle Movie", "year": 2024, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 33, "imdbId": "tt33", "network": "HBO", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": "8.0"
    }
    add_cached_item("movie", item_movie)
    
    movie_raw = [{"title": "MatchTitle Movie", "date_obj": datetime(2024, 1, 1), "description": "Scraped Movie Plot", "date_str": tv_date}]
    
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "MatchTitle Movie", "year": 2020}]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            assert data["movies"][0]["is_in_library"] is True

    # 2. Test ignore_year = False (with difference <= 1 and > 1)
    set_setting("default_match_ignore_year", "0")
    # Year difference <= 1
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "MatchTitle Movie", "year": 2025}]
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            assert data["movies"][0]["is_in_library"] is True

    # Year difference > 1
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "MatchTitle Movie", "year": 2020}]
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            res = client.get("/api/discover?skip_scrape=false")
            assert res.status_code == 200
            data = res.get_json()
            assert data["movies"][0]["is_in_library"] is False


def test_discover_unconfigured_cache_exists_and_fallback(client):
    # Tests line 572: movie live enrichment with no radarr client but cached item exists
    from core.db import add_cached_item
    tv_date = datetime.now().strftime("%Y-%m-%d")
    
    # We create an incomplete cache item (missing poster_url) so it triggers live enrichment
    item_movie = {
        "title": "Unconfigured Movie", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": None,
        "tmdbId": 33, "imdbId": "tt33", "network": "HBO", "is_in_library": True,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": "8.0"
    }
    add_cached_item("movie", item_movie)
    
    movie_raw = [{"title": "Unconfigured Movie", "date_obj": datetime(2026, 1, 1), "description": "Scraped Movie Plot", "date_str": tv_date}]
    
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            with patch("core.enricher.enrich_movie") as mock_enrich_movie:
                mock_enrich_movie.return_value = {
                    "title": "Unconfigured Movie", "year": 2026, "plot": "Enriched Movie Plot", "cast": "Cast Movie",
                    "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
                    "tmdbId": 33, "imdbId": "tt33", "network": "HBO", "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                # Should fall back to caching library status from cached["is_in_library"]
                assert data["movies"][0]["is_in_library"] is True


def test_discover_movies_enrichment_exception_imdb_branches(client):
    # Tests line 594->596: exceptions during enrichment of movies with different imdbId status
    tv_date = datetime.now().strftime("%Y-%m-%d")
    
    movie_raw = [
        {"title": "Fail1 Movie", "date_obj": datetime(2026, 1, 1), "description": "Desc 1", "date_str": tv_date},
        {"title": "Fail2 Movie", "date_obj": datetime(2026, 1, 1), "description": "Desc 2", "date_str": tv_date, "imdbId": "tt123"},
        {"title": "Fail3 Movie", "date_obj": datetime(2026, 1, 1), "description": "Desc 3", "date_str": tv_date, "imdbId": ""}
    ]
    
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            with patch("core.enricher.enrich_movie", side_effect=Exception("Failed")):
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert len(data["movies"]) == 3
                assert data["movies"][0]["imdbId"] is None
                assert data["movies"][1]["imdbId"] == "tt123"
                assert data["movies"][2]["imdbId"] == ""


def test_cache_refresh_existing_returning_missing_key(client):
    # Tests line 633->637: existing dict doesn't have the key "is_returning"
    from core.db import add_cached_item
    
    # We mock get_cached_item to return a dictionary without "is_returning" key
    mock_existing = {
        "title": "Show No Key", "year": 2026, "plot": "Plot", "cast": "Cast",
        "genres": "[]", "trailer": "", "tvdb_id": 11, "imdb_id": "tt11", "network": "Hulu",
        "is_in_library": False, "is_archived": False
    }
    
    with patch("web.server.get_cached_item", return_value=mock_existing):
        with patch("web.server.get_clients", return_value=(None, None)):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv:
                mock_enrich_tv.return_value = {
                    "title": "Show No Key", "year": 2026, "plot": "Enriched plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show No Key", "year": 2026})
                assert res.status_code == 200
                data = res.get_json()
                assert "is_returning" not in data["item"]


def test_cache_refresh_tv_library_sync_edge_cases(client):
    # Tests lines 660->658, 661->663, 663->658, 666->672 in web/server.py
    # We mock get_clients to return a sonarr client whose get_library returns:
    # 1. A show with empty/no title (hits 660->658 False)
    # 2. Duplicate titles (hits 661->663 False)
    # 3. A show with no year (hits 663->658 False)
    # 4. A list of shows not matching (hits 666->672 False)
    from core.db import set_setting
    set_setting("default_match_ignore_year", "1")
    
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [
        {"tvdbId": None, "imdbId": None, "title": ""}, # hits 660->658 False
        {"tvdbId": None, "imdbId": None, "title": "Dupe TV", "year": 2020},
        {"tvdbId": None, "imdbId": None, "title": "Dupe TV", "year": 2021}, # hits 661->663 False
        {"tvdbId": None, "imdbId": None, "title": "NoYear TV", "year": None}, # hits 663->658 False
        {"tvdbId": None, "imdbId": None, "title": "NotMatching TV", "year": 2026} # hits 666->672 False
    ]
    
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        with patch("web.server.enrich_tv_show") as mock_enrich_tv:
            mock_enrich_tv.return_value = {
                "title": "Show Match", "year": 2026, "plot": "Enriched plot", "cast": "Cast",
                "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "tv", "title": "Show Match", "year": 2026})
            assert res.status_code == 200
            data = res.get_json()
            assert data["item"]["is_in_library"] is False


def test_cache_refresh_movie_library_sync_edge_cases_and_fallback(client):
    # Tests lines 712->710, 713->715, 715->710, 718->724, 728 in web/server.py
    # We mock get_clients to return:
    # - A radarr client whose get_library returns:
    #   1. A movie with empty/no title (hits 712->710 False)
    #   2. Duplicate titles (hits 713->715 False)
    #   3. A movie with no year (hits 715->710 False)
    #   4. A list of movies not matching (hits 718->724 False)
    # - And radarr_client is None to test line 728 fallback
    from core.db import set_setting
    from core.db import add_cached_item
    set_setting("default_match_ignore_year", "1")
    
    # 1. Test library sync edge cases
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [
        {"tmdbId": None, "imdbId": None, "title": ""}, # hits 712->710 False
        {"tmdbId": None, "imdbId": None, "title": "Dupe Movie", "year": 2020},
        {"tmdbId": None, "imdbId": None, "title": "Dupe Movie", "year": 2021}, # hits 713->715 False
        {"tmdbId": None, "imdbId": None, "title": "NoYear Movie", "year": None}, # hits 715->710 False
        {"tmdbId": None, "imdbId": None, "title": "NotMatching Movie", "year": 2026} # hits 718->724 False
    ]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.enrich_movie") as mock_enrich_movie:
            mock_enrich_movie.return_value = {
                "title": "Movie Match", "year": 2026, "plot": "Enriched plot", "cast": "Cast",
                "genres": [], "trailer": "", "tmdbId": 11, "imdbId": "tt11", "network": "Hulu",
                "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "movie", "title": "Movie Match", "year": 2026})
            assert res.status_code == 200
            data = res.get_json()
            assert data["item"]["is_in_library"] is False

    # 2. Test line 728 fallback (radarr_client is None)
    add_cached_item("movie", {
        "title": "Fallback Movie", "year": 2026, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": 33, "imdbId": "tt33", "network": "HBO", "is_in_library": True,
        "is_archived": False
    })
    
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.enrich_movie") as mock_enrich_movie:
            mock_enrich_movie.return_value = {
                "title": "Fallback Movie", "year": 2026, "plot": "Enriched Movie Plot", "cast": "Cast Movie",
                "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
                "tmdbId": 33, "imdbId": "tt33", "network": "HBO", "is_in_library": False, "is_archived": False
            }
            res = client.post("/api/cache/refresh", json={"type": "movie", "title": "Fallback Movie", "year": 2026})
            assert res.status_code == 200
            data = res.get_json()
            # Should fallback to existing["is_in_library"] which is True
            assert data["item"]["is_in_library"] is True


def test_discover_live_scrape_tv_title_library_match(client):
    # Tests line 443: TV title library match during live scrape with ignore_year = True and False
    from core.db import set_setting
    
    tv_raw = [{"title": "MatchTitle TV", "date_obj": datetime(2026, 1, 1), "description": "Scraped TV Plot", "date_str": "May 30", "is_returning": False}]
    
    # 1. ignore_year = True
    set_setting("default_match_ignore_year", "1")
    mock_sonarr = MagicMock()
    mock_sonarr.get_library.return_value = [{"tvdbId": None, "imdbId": None, "title": "MatchTitle TV", "year": 2020}]
    
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, ())):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv:
                mock_enrich_tv.return_value = {
                    "title": "MatchTitle TV", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert data["tv"][0]["is_in_library"] is True

    # 2. ignore_year = False
    set_setting("default_match_ignore_year", "0")
    # Year difference <= 1
    mock_sonarr.get_library.return_value = [{"tvdbId": None, "imdbId": None, "title": "MatchTitle TV", "year": 2025}]
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, ())):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv:
                mock_enrich_tv.return_value = {
                    "title": "MatchTitle TV", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert data["tv"][0]["is_in_library"] is True

    # Year difference > 1
    mock_sonarr.get_library.return_value = [{"tvdbId": None, "imdbId": None, "title": "MatchTitle TV", "year": 2020}]
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, ())):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv:
                mock_enrich_tv.return_value = {
                    "title": "MatchTitle TV", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert data["tv"][0]["is_in_library"] is False


def test_discover_live_scrape_movie_title_library_match(client):
    # Tests line 566: Movie title library match during live scrape with ignore_year = True and False
    from core.db import set_setting
    
    movie_raw = [{"title": "MatchTitle Movie", "date_obj": datetime(2026, 1, 1), "description": "Scraped Movie Plot", "date_str": "May 30"}]
    
    # 1. ignore_year = True
    set_setting("default_match_ignore_year", "1")
    mock_radarr = MagicMock()
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "MatchTitle Movie", "year": 2020}]
    
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            with patch("web.server.enrich_movie") as mock_enrich_movie:
                mock_enrich_movie.return_value = {
                    "title": "MatchTitle Movie", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tmdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert data["movies"][0]["is_in_library"] is True

    # 2. ignore_year = False
    set_setting("default_match_ignore_year", "0")
    # Year difference <= 1
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "MatchTitle Movie", "year": 2025}]
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            with patch("web.server.enrich_movie") as mock_enrich_movie:
                mock_enrich_movie.return_value = {
                    "title": "MatchTitle Movie", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tmdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert data["movies"][0]["is_in_library"] is True

    # Year difference > 1
    mock_radarr.get_library.return_value = [{"tmdbId": None, "imdbId": None, "title": "MatchTitle Movie", "year": 2020}]
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        with patch("web.server.get_discoveries", return_value=((), movie_raw)):
            with patch("web.server.enrich_movie") as mock_enrich_movie:
                mock_enrich_movie.return_value = {
                    "title": "MatchTitle Movie", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tmdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                data = res.get_json()
                assert data["movies"][0]["is_in_library"] is False


def test_start_background_healer_thread():
    # Remove PYTEST_CURRENT_TEST from os.environ, then reload web.server to trigger thread start
    import importlib
    import os
    from unittest.mock import patch
    
    env_copy = os.environ.copy()
    if "PYTEST_CURRENT_TEST" in os.environ:
        del os.environ["PYTEST_CURRENT_TEST"]
    try:
        with patch("threading.Thread") as mock_thread:
            import web.server
            importlib.reload(web.server)
            mock_thread.assert_called_once()
    finally:
        os.environ.update(env_copy)


def test_discover_recently_updated_false_branch(client):
    # Tests lines 368 (False branch) and 488 (False branch) (recently_updated = False)
    # We need a cached item that has a poster but is incomplete (missing rating/ids),
    # and has a database entry older than 24 hours (e.g. 48 hours ago).
    from core.db import add_cached_item
    from datetime import datetime, timedelta
    
    tv_date = datetime.now().strftime("%Y-%m-%d")
    item_tv = {
        "title": "Old TV", "year": datetime.now().year, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": None, "imdbId": None, "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": None
    }
    add_cached_item("tv", item_tv)
    
    item_movie = {
        "title": "Old Movie", "year": datetime.now().year, "plot": "Movie Desc", "cast": "Movie Cast",
        "genres": ["Drama"], "trailer": "Movie Trailer", "poster_url": "http://movie/poster.jpg",
        "tmdbId": None, "imdbId": None, "network": "HBO", "is_in_library": False,
        "is_archived": False, "date_str": tv_date, "date_obj": tv_date, "rating_imdb": None
    }
    add_cached_item("movie", item_movie)
    
    # Update added_at for both to be 48 hours ago
    old_time = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    conn = core.db.get_db_connection()
    conn.execute("UPDATE cache SET added_at = ?", (old_time,))
    conn.commit()
    conn.close()
    
    tv_raw = [{"title": "Old TV", "date_obj": datetime.now(), "description": "Scraped TV Plot", "date_str": tv_date, "is_returning": False}]
    movie_raw = [{"title": "Old Movie", "date_obj": datetime.now(), "description": "Scraped Movie Plot", "date_str": tv_date}]
    
    with patch("web.server.get_clients", return_value=(None, None)):
        with patch("web.server.get_discoveries", return_value=(tv_raw, movie_raw)):
            with patch("web.server.enrich_tv_show") as mock_enrich_tv, \
                 patch("web.server.enrich_movie") as mock_enrich_movie:
                 
                mock_enrich_tv.return_value = {
                    "title": "Old TV", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tvdbId": 11, "imdbId": "tt11", "network": "Hulu",
                    "is_in_library": False, "is_archived": False
                }
                mock_enrich_movie.return_value = {
                    "title": "Old Movie", "year": 2026, "plot": "Plot", "cast": "Cast",
                    "genres": [], "trailer": "", "tmdbId": 11, "imdbId": "tt11", "network": "HBO",
                    "is_in_library": False, "is_archived": False
                }
                res = client.get("/api/discover?skip_scrape=false")
                assert res.status_code == 200
                # Both should be enriched because they are incomplete and NOT recently updated!
                mock_enrich_tv.assert_called_once()
                mock_enrich_movie.assert_called_once()


def test_custom_feed_endpoints(client):
    # Ensure custom_feeds is clean
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM custom_feeds")
    conn.commit()
    conn.close()

    # 1. GET /api/feeds (should be empty initially)
    response = client.get("/api/feeds")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert len(data["feeds"]) == 0

    # 2. POST /api/feeds (create new feed)
    feed_payload = {
        "name": "Test Watchlist",
        "url": "https://example.com/watchlist",
        "feed_type": "json",
        "default_media_type": "movie",
        "enabled": 1,
        "http_headers": {"User-Agent": "TestAgent"},
        "parser_config": {
            "item_selector": "results",
            "mappings": {
                "title": {"selector": "title"},
                "year": {"selector": "release_year", "transforms": [{"type": "regex_search", "pattern": "\\d{4}"}]}
            }
        }
    }
    response = client.post("/api/feeds", json=feed_payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "feed_id" in data
    feed_id = data["feed_id"]

    # 3. GET /api/feeds again (should contain the new feed)
    response = client.get("/api/feeds")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["feeds"]) == 1
    feed = data["feeds"][0]
    assert feed["name"] == "Test Watchlist"
    assert feed["feed_type"] == "json"
    assert feed["enabled"] == 1
    assert "results" in feed["parser_config"]

    # 4. POST /api/feeds (update existing feed)
    feed_payload["id"] = feed_id
    feed_payload["name"] = "Updated Watchlist"
    feed_payload["enabled"] = 0
    response = client.post("/api/feeds", json=feed_payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"

    # Check updated feed
    response = client.get("/api/feeds")
    data = response.get_json()
    assert len(data["feeds"]) == 1
    assert data["feeds"][0]["name"] == "Updated Watchlist"
    assert data["feeds"][0]["enabled"] == 0

    # 5. POST /api/feeds/test (dry-run preview test with mocked network response)
    test_payload = {
        "url": "https://example.com/watchlist",
        "feed_type": "json",
        "default_media_type": "movie",
        "http_headers": {"User-Agent": "TestAgent"},
        "parser_config": {
            "item_selector": "results",
            "mappings": {
                "title": {"selector": "title"},
                "year": {"selector": "release_year", "transforms": [{"type": "regex_search", "pattern": "\\d{4}"}]}
            }
        }
    }

    mock_json = '{"results": [{"title": "Inception", "release_year": "2010"}, {"title": "Interstellar", "release_year": "2014"}]}'
    with patch("web.server.safe_fetch_feed", return_value=mock_json) as mock_fetch:
        response = client.post("/api/feeds/test", json=test_payload)
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["parsed_items_count"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["title"] == "Inception"
        assert data["results"][0]["year"] == 2010
        mock_fetch.assert_called_once_with("https://example.com/watchlist", headers={"User-Agent": "TestAgent"})

    # 6. POST /api/feeds/delete (remove the feed)
    response = client.post("/api/feeds/delete", json={"id": feed_id})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"

    # GET /api/feeds (should be empty again)
    response = client.get("/api/feeds")
    data = response.get_json()
    assert len(data["feeds"]) == 0

    # 7. POST /api/feeds validation errors (missing fields)
    response = client.post("/api/feeds", json={"name": "Bad Feed"})
    assert response.status_code == 400
    
    # 8. POST /api/feeds validation errors (invalid http_headers JSON)
    response = client.post("/api/feeds", json={"name": "Bad Feed", "url": "http://x", "feed_type": "json", "http_headers": "invalid-json", "parser_config": {}})
    assert response.status_code == 400

    # 9. POST /api/feeds validation errors (missing 'title' in mappings)
    response = client.post("/api/feeds", json={"name": "Bad Feed", "url": "http://x", "feed_type": "json", "parser_config": {"item_selector": "x", "mappings": {}}})
    assert response.status_code == 400

    # 10. POST /api/feeds validation errors (unsafe regex pattern)
    unsafe_payload = {
        "name": "Unsafe Regex Feed",
        "url": "http://example.com",
        "feed_type": "json",
        "parser_config": {
            "item_selector": "items",
            "mappings": {
                "title": {"selector": "title"},
                "year": {"selector": "year", "transforms": [{"type": "regex_search", "pattern": "(a+)+"}]}
            }
        }
    }
    response = client.post("/api/feeds", json=unsafe_payload)
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"
    assert "unsafe nested quantifiers" in data["message"]

    # 11. POST /api/feeds/restore
    response = client.post("/api/feeds/restore")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"

    # Verify feeds are restored (5 default feeds)
    response = client.get("/api/feeds")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["feeds"]) == 5
    names = [f["name"] for f in data["feeds"]]
    assert "Metacritic - New TV Shows" in names
    assert "Metacritic - New Movies" in names
    assert "DVDs Release Dates" in names
    assert "Letterboxd - Popular Weekly Movies" in names
    assert "Wikipedia - 2026 American Films" in names

    # 12. POST /api/feeds (saving built-in feed type with empty config should succeed)
    built_in_payload = {
        "name": "Custom Metacritic TV",
        "url": "https://www.metacritic.com/browse/tv/all/all/all-time/new/",
        "feed_type": "metacritic_tv",
        "default_media_type": "tv",
        "enabled": 1,
        "http_headers": {},
        "parser_config": {}
    }
    response = client.post("/api/feeds", json=built_in_payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"

def test_discover_returns_date_obj_and_add_only(client):
    # Setup cache
    from core.db import add_cached_item
    tv_date = "2026-06-01"
    item_tv = {
        "title": "Show C", "year": 2026, "plot": "TV Desc", "cast": "TV Cast",
        "genres": ["Drama"], "trailer": "TV Trailer", "poster_url": "http://tv/poster.jpg",
        "tvdbId": 11, "imdbId": "tt11", "network": "Hulu", "is_in_library": False,
        "is_archived": False, "date_str": "Jun 1, 2026", "date_obj": tv_date
    }
    add_cached_item("tv", item_tv)

    res = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["tv"]) >= 1
    assert data["tv"][0]["date_obj"] == "2026-06-01"

    # Test api/add with search_now=False
    mock_sonarr = MagicMock()
    mock_sonarr.add_series.return_value = {"title": "Live Series", "year": 2026, "imdbId": "tt123"}
    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        res_add = client.post("/api/add", json={
            "type": "tv",
            "raw_metadata": {"title": "Live Series", "year": 2026},
            "folder": "/tv",
            "profile_id": 2,
            "search_now": False
        })
        assert res_add.status_code == 200
        mock_sonarr.add_series.assert_called_once_with(
            series_data={"title": "Live Series", "year": 2026, "is_in_library": True},
            quality_profile_id=2,
            root_folder_path="/tv",
            monitored=True,
            search_now=False,
            language_profile_id=1
        )

def test_is_incomplete_metadata_and_suppression(client):
    from web.server import is_incomplete_metadata
    
    # 1. Test helper logic
    assert not is_incomplete_metadata({"title": "Gladiator II", "cast": "Cast details not available.", "plot": "No plot summary available."})
    assert not is_incomplete_metadata({"title": "Unknown", "cast": "Cast details not available.", "plot": "Some cool plot"})
    assert not is_incomplete_metadata({"title": "Unknown", "cast": "Paul Mescal", "plot": "No plot summary available."})
    
    assert is_incomplete_metadata({"title": "Unknown", "cast": "Cast details not available.", "plot": "No plot summary available."})
    assert is_incomplete_metadata({"title": "", "cast": "", "description": ""})
    assert is_incomplete_metadata({"title": "None", "cast": "None", "overview": "None"})

    # 2. Test lookup endpoint suppression filtering
    mock_radarr = MagicMock()
    mock_radarr.lookup_movie.return_value = [
        {"title": "Valid Movie", "overview": "Plot summary is here.", "imdbId": "tt111"},
        {"title": "Unknown", "overview": "No plot summary available.", "imdbId": ""}
    ]
    with patch("web.server.get_clients", return_value=(mock_radarr, None)):
        res = client.get("/api/lookup?type=movie&title=test")
        assert res.status_code == 200
        results = res.get_json()["results"]
        assert len(results) == 1
        assert results[0]["title"] == "Valid Movie"



