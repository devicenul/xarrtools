"""
tests/test_m2_discovery_caching_challenge.py
--------------------------------------------
Empirical Challenger Test Suite for Milestone 2:
Adversarial challenge and stress-testing of discovery scanning, caching,
and serialization endpoints in `web/server.py`.

Coverage targets:
1. GET /api/discover with skip_scrape=true and skip_scrape=false across date windows and custom feed discoveries.
2. Exact thresholding verification:
   - >= 2 missing core fields -> is_archived=True (auto-archived)
   - < 2 missing core fields -> is_archived=False (normal status retained)
3. Strict JSON boolean literal verification:
   - has_new_metadata is always present and is a strict boolean literal (true/false, not int or string).
   - is_archived is always present and is a strict boolean literal.
4. Smart auto-unarchiving on rescan/refresh with has_new_metadata=True badging.
5. Re-archiving badge reset to has_new_metadata=False.
6. Boundary date windows, extreme parameters, and custom feed isolation.
"""

import pytest
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Isolate test database before importing web.server
import xarrtools.core.db; from xarrtools import core
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

# Intercept background thread on import
with patch("threading.Thread"):
    from xarrtools.web.server import app, update_scan_progress

from xarrtools.core.db import (
    add_cached_item,
    get_cached_item,
    get_db_connection,
    set_setting,
    init_db
)
from xarrtools.core.metadata import evaluate_metadata, should_auto_archive


@pytest.fixture(autouse=True)
def clean_database():
    """Wipes test cache and settings between tests."""
    conn = get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM custom_feeds")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()

    init_db()
    set_setting("api_key", "test_api_key")
    from xarrtools.core.config import config
    config.refresh()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True

    class WrappedClient:
        def __init__(self, test_client):
            self._client = test_client

        def get(self, *args, **kwargs):
            return self._client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_api_key"
            kwargs["headers"] = headers
            return self._client.post(*args, **kwargs)

    with app.test_client() as c:
        yield WrappedClient(c)


# ==============================================================================
# 1. CORE MISSING FIELDS THRESHOLDING TESTS (>= 2 missing vs < 2 missing)
# ==============================================================================

@pytest.mark.parametrize("title,network,cast,plot,expected_missing_count,expected_archived", [
    # 0 missing fields -> is_archived = False
    ("Severance", "Apple TV+", "Adam Scott, Patricia Arquette", "Employees undergo surgical memory separation.", 0, False),
    
    # 1 missing field (Title only missing) -> is_archived = False
    ("", "Apple TV+", "Adam Scott, Patricia Arquette", "Employees undergo surgical memory separation.", 1, False),
    ("Unknown", "Apple TV+", "Adam Scott", "Great plot", 1, False),
    ("TBD", "HBO", "Cast Member", "A thrilling story", 1, False),
    ("N/A", "Netflix", "Cast Member", "A thrilling story", 1, False),
    
    # 1 missing field (Network only missing) -> is_archived = False
    ("Dark Matter", "", "Joel Edgerton", "A man is abducted into an alternate life.", 1, False),
    ("Dark Matter", "Unknown", "Joel Edgerton", "A man is abducted into an alternate life.", 1, False),
    ("Dark Matter", "unknown studio", "Joel Edgerton", "A man is abducted into an alternate life.", 1, False),
    ("Dark Matter", "N/A", "Joel Edgerton", "A man is abducted into an alternate life.", 1, False),
    
    # 1 missing field (Cast only missing) -> is_archived = False
    ("Dark Matter", "Apple TV+", "", "A man is abducted into an alternate life.", 1, False),
    ("Dark Matter", "Apple TV+", "Cast details not available.", "A man is abducted into an alternate life.", 1, False),
    ("Dark Matter", "Apple TV+", "Unknown", "A man is abducted into an alternate life.", 1, False),
    ("Dark Matter", "Apple TV+", "N/A", "A man is abducted into an alternate life.", 1, False),
    
    # 1 missing field (Plot only missing) -> is_archived = False
    ("Dark Matter", "Apple TV+", "Joel Edgerton", "", 1, False),
    ("Dark Matter", "Apple TV+", "Joel Edgerton", "No plot summary available.", 1, False),
    ("Dark Matter", "Apple TV+", "Joel Edgerton", "unknown", 1, False),
    ("Dark Matter", "Apple TV+", "Joel Edgerton", "N/A", 1, False),

    # 2 missing fields (Network + Cast) -> is_archived = True
    ("Incomplete Show A", "Unknown", "Cast details not available.", "Has a valid plot summary.", 2, True),
    ("Incomplete Show B", "", "", "Has a valid plot summary.", 2, True),
    
    # 2 missing fields (Network + Plot) -> is_archived = True
    ("Incomplete Show C", "Unknown", "Actor A, Actor B", "No plot summary available.", 2, True),
    ("Incomplete Show D", "N/A", "Actor A, Actor B", "", 2, True),
    
    # 2 missing fields (Cast + Plot) -> is_archived = True
    ("Incomplete Show E", "HBO", "Cast details not available.", "No plot summary available.", 2, True),
    ("Incomplete Show F", "Netflix", "", "", 2, True),

    # 2 missing fields (Title + Network) -> is_archived = True
    ("Unknown", "Unknown", "Actor A", "Valid plot summary.", 2, True),
    
    # 2 missing fields (Title + Cast) -> is_archived = True
    ("TBD", "HBO", "Cast details not available.", "Valid plot summary.", 2, True),

    # 2 missing fields (Title + Plot) -> is_archived = True
    ("N/A", "HBO", "Actor A", "No plot summary available.", 2, True),

    # 3 missing fields -> is_archived = True
    ("Low Show 3A", "Unknown", "Cast details not available.", "No plot summary available.", 3, True),
    ("Unknown", "HBO", "Cast details not available.", "No plot summary available.", 3, True),
    ("Unknown", "Unknown", "Cast details not available.", "Valid plot.", 3, True),

    # 4 missing fields -> is_archived = True
    ("Unknown", "Unknown", "Cast details not available.", "No plot summary available.", 4, True),
    ("", "", "", "", 4, True),
    (None, None, None, None, 4, True),
])
def test_metadata_evaluation_and_archiving_threshold_matrix(title, network, cast, plot, expected_missing_count, expected_archived):
    """Stress tests the mathematical thresholding: missing_count >= 2 => is_archived = True."""
    item = {
        "title": title,
        "network": network,
        "cast": cast,
        "plot": plot
    }
    eval_res = evaluate_metadata(item)
    assert eval_res["missing_count"] == expected_missing_count
    assert eval_res["is_low_metadata"] is expected_archived
    assert should_auto_archive(item) is expected_archived


# ==============================================================================
# 2. GET /api/discover (skip_scrape=true) STRESS TESTS & JSON SERIALIZATION
# ==============================================================================

def test_api_discover_skip_scrape_all_permutations(client):
    """Tests GET /api/discover with skip_scrape=true for TV and movies across all metadata conditions."""
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")

    # 1. TV with 0 missing fields (< 2) -> is_archived=False, has_new_metadata=False
    add_cached_item("tv", {
        "title": "Rich TV Show", "year": 2026, "plot": "Rich synopsis.", "cast": "Actor A",
        "network": "HBO", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    # 2. TV with 1 missing field (< 2) -> is_archived=False, has_new_metadata=False
    add_cached_item("tv", {
        "title": "OneMissing TV Show", "year": 2026, "plot": "No plot summary available.", "cast": "Actor B",
        "network": "NBC", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    # 3. TV with 2 missing fields (>= 2) -> is_archived=True, has_new_metadata=False
    add_cached_item("tv", {
        "title": "TwoMissing TV Show", "year": 2026, "plot": "No plot summary available.", "cast": "Cast details not available.",
        "network": "NBC", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    # 4. TV that was smart unarchived -> is_archived=False, has_new_metadata=True
    add_cached_item("tv", {
        "title": "Badged TV Show", "year": 2026, "plot": "No plot", "cast": "None", "network": "None",
        "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })
    # Rescan / enrich with complete metadata
    add_cached_item("tv", {
        "title": "Badged TV Show", "year": 2026, "plot": "Complete plot discovered!", "cast": "Actor C",
        "network": "Apple TV+", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    # 5. Movie with 0 missing fields (< 2) -> is_archived=False, has_new_metadata=False
    add_cached_item("movie", {
        "title": "Rich Movie", "year": 2026, "plot": "Rich synopsis.", "cast": "Actor D",
        "network": "Paramount", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    # 6. Movie with 2 missing fields (>= 2) -> is_archived=True, has_new_metadata=False
    add_cached_item("movie", {
        "title": "Low Movie", "year": 2026, "plot": "", "cast": "Unknown",
        "network": "Universal", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    # 7. Movie that was smart unarchived -> is_archived=False, has_new_metadata=True
    add_cached_item("movie", {
        "title": "Badged Movie", "year": 2026, "plot": "", "cast": "", "network": "",
        "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })
    add_cached_item("movie", {
        "title": "Badged Movie", "year": 2026, "plot": "Full plot!", "cast": "Star Actor",
        "network": "A24", "is_in_library": False, "date_str": date_str, "date_obj": date_str
    })

    with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
        res = client.get("/api/discover?skip_scrape=true&past_months=1&future_months=1")
        assert res.status_code == 200
        
        # Verify JSON payload string contains boolean literal keywords (true / false)
        raw_json_str = res.data.decode("utf-8")
        assert '"has_new_metadata": true' in raw_json_str or '"has_new_metadata":true' in raw_json_str
        assert '"has_new_metadata": false' in raw_json_str or '"has_new_metadata":false' in raw_json_str
        assert '"is_archived": true' in raw_json_str or '"is_archived":true' in raw_json_str
        assert '"is_archived": false' in raw_json_str or '"is_archived":false' in raw_json_str

        data = json.loads(raw_json_str)
        assert data["status"] == "success"

        tv_by_title = {item["title"]: item for item in data["tv"]}
        movie_by_title = {item["title"]: item for item in data["movies"]}

        # TV Assertions
        assert tv_by_title["Rich TV Show"]["is_archived"] is False
        assert tv_by_title["Rich TV Show"]["has_new_metadata"] is False
        assert type(tv_by_title["Rich TV Show"]["is_archived"]) is bool
        assert type(tv_by_title["Rich TV Show"]["has_new_metadata"]) is bool

        assert tv_by_title["OneMissing TV Show"]["is_archived"] is False
        assert tv_by_title["OneMissing TV Show"]["has_new_metadata"] is False
        assert type(tv_by_title["OneMissing TV Show"]["is_archived"]) is bool
        assert type(tv_by_title["OneMissing TV Show"]["has_new_metadata"]) is bool

        assert tv_by_title["TwoMissing TV Show"]["is_archived"] is True
        assert tv_by_title["TwoMissing TV Show"]["has_new_metadata"] is False
        assert type(tv_by_title["TwoMissing TV Show"]["is_archived"]) is bool
        assert type(tv_by_title["TwoMissing TV Show"]["has_new_metadata"]) is bool

        assert tv_by_title["Badged TV Show"]["is_archived"] is False
        assert tv_by_title["Badged TV Show"]["has_new_metadata"] is True
        assert type(tv_by_title["Badged TV Show"]["is_archived"]) is bool
        assert type(tv_by_title["Badged TV Show"]["has_new_metadata"]) is bool

        # Movie Assertions
        assert movie_by_title["Rich Movie"]["is_archived"] is False
        assert movie_by_title["Rich Movie"]["has_new_metadata"] is False
        assert type(movie_by_title["Rich Movie"]["is_archived"]) is bool
        assert type(movie_by_title["Rich Movie"]["has_new_metadata"]) is bool

        assert movie_by_title["Low Movie"]["is_archived"] is True
        assert movie_by_title["Low Movie"]["has_new_metadata"] is False
        assert type(movie_by_title["Low Movie"]["is_archived"]) is bool
        assert type(movie_by_title["Low Movie"]["has_new_metadata"]) is bool

        assert movie_by_title["Badged Movie"]["is_archived"] is False
        assert movie_by_title["Badged Movie"]["has_new_metadata"] is True
        assert type(movie_by_title["Badged Movie"]["is_archived"]) is bool
        assert type(movie_by_title["Badged Movie"]["has_new_metadata"]) is bool


# ==============================================================================
# 3. GET /api/discover (skip_scrape=false) LIVE SCRAPE AUTO-ARCHIVING & BADGES
# ==============================================================================

def test_api_discover_live_scrape_auto_archiving_and_badging(client):
    """Tests GET /api/discover with skip_scrape=false auto-evaluating metadata and assigning archive flags."""
    now = datetime.now()
    
    tv_raw = [
        {"title": "Live Rich TV", "date_obj": now, "description": "Scraped TV Desc", "date_str": "2026-06-01", "is_returning": False},
        {"title": "Live Low TV", "date_obj": now, "description": "No plot summary available.", "date_str": "2026-06-01", "is_returning": False},
        {"title": "Live Unarchive TV", "date_obj": now, "description": "Scraped TV Desc", "date_str": "2026-06-01", "is_returning": False}
    ]
    movie_raw = [
        {"title": "Live Rich Movie", "date_obj": now, "description": "Scraped Movie Desc", "date_str": "2026-06-01", "imdbId": "tt801"},
        {"title": "Live Low Movie", "date_obj": now, "description": "No plot summary available.", "date_str": "2026-06-01", "imdbId": "tt802"},
        {"title": "Live Unarchive Movie", "date_obj": now, "description": "Scraped Movie Desc", "date_str": "2026-06-01", "imdbId": "tt803"}
    ]

    # Pre-seed "Live Unarchive TV" and "Live Unarchive Movie" as archived in database
    add_cached_item("tv", {
        "title": "Live Unarchive TV", "year": now.year, "plot": "No plot summary available.",
        "cast": "Cast details not available.", "network": "Unknown", "is_in_library": False,
        "date_str": "2026-06-01", "date_obj": "2026-06-01"
    })
    add_cached_item("movie", {
        "title": "Live Unarchive Movie", "year": now.year, "plot": "No plot summary available.",
        "cast": "Cast details not available.", "network": "Unknown", "is_in_library": False,
        "date_str": "2026-06-01", "date_obj": "2026-06-01", "imdbId": "tt803"
    })

    # Verify initial DB state is archived
    c_tv = get_cached_item("tv", "Live Unarchive TV", now.year)
    c_mov = get_cached_item("movie", "Live Unarchive Movie", now.year, "tt803")
    assert c_tv["is_archived"] == 1
    assert c_mov["is_archived"] == 1

    def mock_tv_enricher(title, year, client_instance):
        if title == "Live Rich TV":
            return {
                "title": "Live Rich TV", "year": year, "plot": "Complete rich series synopsis.",
                "cast": "Lead Star, Support Star", "genres": ["Drama"], "trailer": "http://trailer",
                "poster_url": "http://poster.jpg", "tvdbId": 901, "imdbId": "tt901", "network": "HBO"
            }
        elif title == "Live Low TV":
            return {
                "title": "Live Low TV", "year": year, "plot": "No plot summary available.",
                "cast": "Cast details not available.", "genres": [], "trailer": "",
                "poster_url": "", "tvdbId": None, "imdbId": None, "network": "Unknown"
            }
        elif title == "Live Unarchive TV":
            return {
                "title": "Live Unarchive TV", "year": year, "plot": "Discovered complete plot details!",
                "cast": "Lead Star", "genres": ["Sci-Fi"], "trailer": "http://trailer",
                "poster_url": "http://poster.jpg", "tvdbId": 903, "imdbId": "tt903", "network": "Apple TV+"
            }
        raise ValueError(f"Unexpected title: {title}")

    def mock_movie_enricher(title, year, client_instance, imdb_id=None):
        if title == "Live Rich Movie":
            return {
                "title": "Live Rich Movie", "year": year, "plot": "Complete rich movie synopsis.",
                "cast": "Star A, Star B", "genres": ["Action"], "trailer": "http://trailer",
                "poster_url": "http://poster.jpg", "tmdbId": 911, "imdbId": imdb_id, "network": "Paramount"
            }
        elif title == "Live Low Movie":
            return {
                "title": "Live Low Movie", "year": year, "plot": "No plot summary available.",
                "cast": "Cast details not available.", "genres": [], "trailer": "",
                "poster_url": "", "tmdbId": None, "imdbId": imdb_id, "network": "N/A"
            }
        elif title == "Live Unarchive Movie":
            return {
                "title": "Live Unarchive Movie", "year": year, "plot": "Discovered complete movie plot!",
                "cast": "Star Actor", "genres": ["Thriller"], "trailer": "http://trailer",
                "poster_url": "http://poster.jpg", "tmdbId": 913, "imdbId": imdb_id, "network": "Universal"
            }
        raise ValueError(f"Unexpected title: {title}")

    with patch("xarrtools.web.server.get_clients", return_value=(None, None)), \
         patch("xarrtools.web.server.get_discoveries", return_value=(tv_raw, movie_raw)), \
         patch("xarrtools.web.server.enrich_tv_show", side_effect=mock_tv_enricher), \
         patch("xarrtools.web.server.enrich_movie", side_effect=mock_movie_enricher):

        res = client.get("/api/discover?skip_scrape=false")
        assert res.status_code == 200
        
        # Verify JSON boolean literals directly
        raw_json_str = res.data.decode("utf-8")
        data = json.loads(raw_json_str)
        assert data["status"] == "success"

        tv_items = {item["title"]: item for item in data["tv"]}
        movie_items = {item["title"]: item for item in data["movies"]}

        # 1. Rich items (< 2 missing fields) -> is_archived=False, has_new_metadata=False
        assert tv_items["Live Rich TV"]["is_archived"] is False
        assert tv_items["Live Rich TV"]["has_new_metadata"] is False
        assert isinstance(tv_items["Live Rich TV"]["has_new_metadata"], bool)
        assert isinstance(tv_items["Live Rich TV"]["is_archived"], bool)

        assert movie_items["Live Rich Movie"]["is_archived"] is False
        assert movie_items["Live Rich Movie"]["has_new_metadata"] is False
        assert isinstance(movie_items["Live Rich Movie"]["has_new_metadata"], bool)
        assert isinstance(movie_items["Live Rich Movie"]["is_archived"], bool)

        # 2. Low metadata items (>= 2 missing fields) -> is_archived=True, has_new_metadata=False
        assert tv_items["Live Low TV"]["is_archived"] is True
        assert tv_items["Live Low TV"]["has_new_metadata"] is False
        assert isinstance(tv_items["Live Low TV"]["has_new_metadata"], bool)
        assert isinstance(tv_items["Live Low TV"]["is_archived"], bool)

        assert movie_items["Live Low Movie"]["is_archived"] is True
        assert movie_items["Live Low Movie"]["has_new_metadata"] is False
        assert isinstance(movie_items["Live Low Movie"]["has_new_metadata"], bool)
        assert isinstance(movie_items["Live Low Movie"]["is_archived"], bool)

        # 3. Smart Unarchived items (was archived -> new metadata discovered) -> is_archived=False, has_new_metadata=True
        assert tv_items["Live Unarchive TV"]["is_archived"] is False
        assert tv_items["Live Unarchive TV"]["has_new_metadata"] is True
        assert isinstance(tv_items["Live Unarchive TV"]["has_new_metadata"], bool)
        assert isinstance(tv_items["Live Unarchive TV"]["is_archived"], bool)

        assert movie_items["Live Unarchive Movie"]["is_archived"] is False
        assert movie_items["Live Unarchive Movie"]["has_new_metadata"] is True
        assert isinstance(movie_items["Live Unarchive Movie"]["has_new_metadata"], bool)
        assert isinstance(movie_items["Live Unarchive Movie"]["is_archived"], bool)


# ==============================================================================
# 4. DATE WINDOWS & PARAMETER BOUNDARY TESTS
# ==============================================================================

@pytest.mark.parametrize("past_months,future_months", [
    (0, 0),       # Clamped to 0 days (today only)
    (-5, -10),    # Negative values clamped to 0
    (1, 2),       # Standard default (30 past days, 60 future days)
    (6, 12),      # Medium window (180 past days, 360 future days)
    (100, 200),   # Clamped to max 365 days
])
def test_api_discover_date_windows_clamping(client, past_months, future_months):
    """Tests GET /api/discover across extreme, negative, zero, and maximum date windows."""
    today = datetime.now()
    
    # Add items at various date offsets
    today_str = today.strftime("%Y-%m-%d")
    old_date = (today - timedelta(days=200)).strftime("%Y-%m-%d")
    ancient_date = (today - timedelta(days=500)).strftime("%Y-%m-%d")
    far_future_date = (today + timedelta(days=200)).strftime("%Y-%m-%d")
    extreme_future_date = (today + timedelta(days=500)).strftime("%Y-%m-%d")

    add_cached_item("tv", {
        "title": "Today TV", "year": today.year, "plot": "Desc", "cast": "Cast", "network": "Net",
        "is_in_library": False, "date_str": today_str, "date_obj": today_str
    })
    add_cached_item("tv", {
        "title": "Old TV", "year": today.year, "plot": "Desc", "cast": "Cast", "network": "Net",
        "is_in_library": False, "date_str": old_date, "date_obj": old_date
    })
    add_cached_item("tv", {
        "title": "Ancient TV", "year": today.year, "plot": "Desc", "cast": "Cast", "network": "Net",
        "is_in_library": False, "date_str": ancient_date, "date_obj": ancient_date
    })
    add_cached_item("movie", {
        "title": "Far Future Movie", "year": today.year, "plot": "Desc", "cast": "Cast", "network": "Net",
        "is_in_library": False, "date_str": far_future_date, "date_obj": far_future_date
    })
    add_cached_item("movie", {
        "title": "Extreme Future Movie", "year": today.year, "plot": "Desc", "cast": "Cast", "network": "Net",
        "is_in_library": False, "date_str": extreme_future_date, "date_obj": extreme_future_date
    })

    with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
        res = client.get(f"/api/discover?skip_scrape=true&past_months={past_months}&future_months={future_months}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"

        tv_titles = [item["title"] for item in data["tv"]]
        movie_titles = [item["title"] for item in data["movies"]]

        # "Today TV" should always be within window
        assert "Today TV" in tv_titles

        # Ancient and Extreme Future (500 days away) should never be in window because max clamp is 365 days
        assert "Ancient TV" not in tv_titles
        assert "Extreme Future Movie" not in movie_titles

        if past_months >= 7: # > 200 days
            assert "Old TV" in tv_titles
        else:
            assert "Old TV" not in tv_titles

        if future_months >= 7: # > 200 days
            assert "Far Future Movie" in movie_titles
        else:
            assert "Far Future Movie" not in movie_titles


# ==============================================================================
# 5. CUSTOM FEED DISCOVERIES & ATTRIBUTION INTEGRATION
# ==============================================================================

def test_api_discover_custom_feed_discoveries(client):
    """Tests custom feed items scraped and ingested through discovery pipeline."""
    # Wipe custom_feeds to ensure no live built-in feeds run network fetches
    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_feeds")
    cursor.execute("""
        INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "Custom Feed Challenger",
        "https://example.com/custom_feed.json",
        "json",
        "movie",
        1,
        "{}",
        json.dumps({
            "item_selector": "items",
            "mappings": {
                "title": {"selector": "title"},
                "year": {"selector": "year"},
                "description": {"selector": "overview"},
                "network": {"selector": "studio"},
                "cast": {"selector": "actors"}
            }
        })
    ))
    feed_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # 2. Mock network payload for custom feed
    mock_payload = json.dumps({
        "items": [
            {
                "title": "Custom Feed Rich Movie",
                "year": "2026",
                "overview": "Exciting custom movie plot.",
                "studio": "Neon",
                "actors": "Actor Alpha"
            },
            {
                "title": "Custom Feed Low Movie",
                "year": "2026",
                "overview": "No plot summary available.",
                "studio": "Unknown",
                "actors": "Cast details not available."
            }
        ]
    })

    def mock_enrich_movie(title, year, client_instance, imdb_id=None):
        if title == "Custom Feed Rich Movie":
            return {
                "title": "Custom Feed Rich Movie", "year": 2026, "plot": "Exciting custom movie plot.",
                "cast": "Actor Alpha", "network": "Neon", "genres": ["Drama"], "poster_url": "http://poster.jpg",
                "tmdbId": 1234, "imdbId": "tt1234"
            }
        elif title == "Custom Feed Low Movie":
            return {
                "title": "Custom Feed Low Movie", "year": 2026, "plot": "No plot summary available.",
                "cast": "Cast details not available.", "network": "Unknown", "genres": [],
                "poster_url": "", "tmdbId": None, "imdbId": None
            }
        raise ValueError(f"Unexpected title: {title}")

    with patch("xarrtools.web.server.get_clients", return_value=(None, None)), \
         patch("xarrtools.core.scraper.safe_fetch_feed", return_value=mock_payload), \
         patch("xarrtools.web.server.enrich_movie", side_effect=mock_enrich_movie):

        res = client.get("/api/discover?skip_scrape=false")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"

        movie_items = {item["title"]: item for item in data["movies"]}
        assert "Custom Feed Rich Movie" in movie_items
        assert "Custom Feed Low Movie" in movie_items

        # Verify auto-archiving behavior on custom feed items
        assert movie_items["Custom Feed Rich Movie"]["is_archived"] is False
        assert movie_items["Custom Feed Rich Movie"]["has_new_metadata"] is False
        assert type(movie_items["Custom Feed Rich Movie"]["has_new_metadata"]) is bool

        assert movie_items["Custom Feed Low Movie"]["is_archived"] is True
        assert movie_items["Custom Feed Low Movie"]["has_new_metadata"] is False
        assert type(movie_items["Custom Feed Low Movie"]["has_new_metadata"]) is bool


# ==============================================================================
# 6. RE-ARCHIVING FLAG RESET & STATE TRANSITIONS
# ==============================================================================

def test_api_archive_rearchiving_badge_reset_full_cycle(client):
    """Verifies full lifecycle: low metadata -> archived -> metadata discovered -> unarchived (badge=True) -> re-archived -> (badge=False)."""
    # Step 1: Initial Discovery (Low metadata -> auto-archived)
    add_cached_item("tv", {
        "title": "Lifecycle Show", "year": 2026, "plot": "No plot summary available.",
        "cast": "Cast details not available.", "network": "Unknown", "is_in_library": False,
        "date_str": "2026-06-01", "date_obj": "2026-06-01"
    })
    
    item = get_cached_item("tv", "Lifecycle Show", 2026)
    assert item["is_archived"] == 1
    assert item["has_new_metadata"] == 0

    # Step 2: Metadata Refresh discovers complete metadata (Auto-unarchived with badge)
    with patch("xarrtools.web.server.get_clients", return_value=(None, None)), \
         patch("xarrtools.web.server.enrich_tv_show") as mock_enrich:
        
        mock_enrich.return_value = {
            "title": "Lifecycle Show", "year": 2026, "plot": "Newly discovered full series plot!",
            "cast": "Star Actor", "genres": ["Drama"], "trailer": "http://trailer",
            "poster_url": "http://poster.jpg", "tvdbId": 777, "imdbId": "tt777", "network": "HBO"
        }
        res_refresh = client.post("/api/cache/refresh", json={"type": "tv", "title": "Lifecycle Show", "year": 2026})
        assert res_refresh.status_code == 200
        refreshed_item = res_refresh.get_json()["item"]
        assert refreshed_item["is_archived"] is False
        assert refreshed_item["has_new_metadata"] is True
        assert type(refreshed_item["has_new_metadata"]) is bool

    # Check database state after unarchiving
    item_after_refresh = get_cached_item("tv", "Lifecycle Show", 2026)
    assert item_after_refresh["is_archived"] == 0
    assert item_after_refresh["has_new_metadata"] == 1

    # Verify discovery API reflects unarchived and badged state
    with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
        res_discover = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
        assert res_discover.status_code == 200
        tv_list = res_discover.get_json()["tv"]
        found = next(t for t in tv_list if t["title"] == "Lifecycle Show")
        assert found["is_archived"] is False
        assert found["has_new_metadata"] is True
        assert type(found["has_new_metadata"]) is bool

    # Step 3: Re-archiving the item via POST /api/archive
    res_archive = client.post("/api/archive", json={"type": "tv", "title": "Lifecycle Show", "year": 2026, "archive": True})
    assert res_archive.status_code == 200
    assert res_archive.get_json()["status"] == "success"

    # Verify database state has reset has_new_metadata back to 0
    item_after_rearchive = get_cached_item("tv", "Lifecycle Show", 2026)
    assert item_after_rearchive["is_archived"] == 1
    assert item_after_rearchive["has_new_metadata"] == 0

    # Verify discovery API reflects re-archived and unbadged state
    with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
        res_discover_after = client.get("/api/discover?skip_scrape=true&past_months=12&future_months=12")
        assert res_discover_after.status_code == 200
        tv_list_after = res_discover_after.get_json()["tv"]
        found_after = next(t for t in tv_list_after if t["title"] == "Lifecycle Show")
        assert found_after["is_archived"] is True
        assert found_after["has_new_metadata"] is False
        assert type(found_after["has_new_metadata"]) is bool


# ==============================================================================
# 7. CONCURRENCY & SCAN LOCK DEFENSE TESTS
# ==============================================================================

def test_api_discover_concurrent_scan_lock(client):
    """Verifies that initiating a scan while another scan is in progress returns HTTP 409 Conflict."""
    update_scan_progress("scraping", "In progress...", 1, 10)
    try:
        res = client.get("/api/discover?skip_scrape=false")
        assert res.status_code == 409
        data = res.get_json()
        assert data["status"] == "error"
        assert "scan is already in progress" in data["message"]
    finally:
        update_scan_progress("idle", "Idle", 0, 0)
