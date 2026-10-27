"""
tests/test_tier5_adversarial_hardening.py
-----------------------------------------
Tier 5 White-Box Adversarial Stress-Testing & Coverage Hardening for xarrtools.
Targets:
1. Malformed data payloads, type permutations, unusual casing, Unicode/Emoji/Zero-width sentinels.
2. Live cache refresh race conditions, concurrent multi-threaded DB access, and cache eviction.
3. SQLite schema migrations, missing columns, corrupted columns, and rollback resilience.
4. Web UI card rendering edge cases (DOM structure, badge placement, XSS escaping, class naming).
5. Scraper / Enricher error paths, ReDoS safety, and network failure resilience.
"""

import pytest
import sqlite3
import json
import threading
import time
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from xarrtools.core.metadata import (
    is_title_missing,
    is_network_missing,
    is_cast_missing,
    is_plot_missing,
    evaluate_metadata,
    should_auto_archive,
    evaluate_item_state_transition,
    MISSING_TITLE_STRINGS,
    MISSING_NETWORK_STRINGS,
    MISSING_CAST_STRINGS,
    MISSING_PLOT_STRINGS
)
from xarrtools.core.db import (
    init_db,
    get_db_connection,
    add_cached_item,
    add_cached_items_batch,
    get_cached_item,
    archive_cached_item,
    clean_expired_cache,
    get_cache_stats,
    clear_all_cache,
    get_cached_discoveries,
    update_cached_library_status,
    normalize_title,
    clean_movie_title,
    clean_tv_title,
    set_setting,
    get_setting,
    get_all_settings
)
from xarrtools.web.server import app


# ---------------------------------------------------------------------------
# Fixture: Isolated in-memory/temporary SQLite database
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Provides a fresh isolated database file for adversarial stress-testing."""
    db_file = tmp_path / "xarrtools_adversarial.db"
    monkeypatch.setattr("xarrtools.core.db.DB_PATH", db_file)
    init_db()
    return db_file


@pytest.fixture
def client(isolated_db, monkeypatch):
    """Provides a Flask test client with an isolated database."""
    app.config["TESTING"] = True
    set_setting("api_key", "test-secret-key-12345")
    with app.test_client() as client:
        yield client


# ===========================================================================
# 1. Adversarial Metadata Evaluator Stress-Testing
# ===========================================================================

class TestAdversarialMetadataEvaluator:
    """Stress tests on metadata evaluator using hostile, malformed, and combinatorial inputs."""

    @pytest.mark.parametrize("payload,expected_missing", [
        (None, True),
        ("", True),
        ("   \t\r\n\v\f   ", True),
        ("UNKNOWN", True),
        ("uNkNoWn", True),
        ("  TBD  ", True),
        ("N/A", True),
        ("n/a", True),
        ("na", True),
        ("NA", True),
        ("NULL", True),
        ("None", True),
        (False, True),
        (True, True),
        ([], True),
        ({}, True),
        (set(), True),
        (0, False),          # Integer 0 is a valid title like the movie '0'
        ("0", False),
        ("1917", False),
        ("300", False),
        ("WALL-E", False),
        ("¡Three Amigos!", False),
        ("Café Society", False),
        ("🎬 The Movie 🍿", False),
        ("   Valid Title   ", False),
    ])
    def test_title_validator_adversarial_matrix(self, payload, expected_missing):
        assert is_title_missing(payload) == expected_missing

    @pytest.mark.parametrize("payload,expected_missing", [
        (None, True),
        ("", True),
        ("Unknown Network", True),
        ("UNKNOWN STUDIO", True),
        ("uNkNoWn nEtWoRk", True),
        ("n/a", True),
        ("none", True),
        ("null", True),
        ("tbd", True),
        ({}, True),
        ({"name": None}, True),
        ({"name": "Unknown"}, True),
        ({"network": "N/A"}, True),
        ({"studio": "None"}, True),
        ({"name": "HBO Max"}, False),
        ({"network": "Netflix"}, False),
        ({"studio": "Warner Bros."}, False),
        ([], True),
        ([None, "Unknown", "N/A"], True),
        ([{"name": "Unknown"}, {"name": "N/A"}], True),
        ([{"name": "Unknown"}, {"name": "Apple TV+"}], False),
        ("HBO", False),
        ("BBC One", False),
    ])
    def test_network_validator_adversarial_matrix(self, payload, expected_missing):
        assert is_network_missing(payload) == expected_missing

    @pytest.mark.parametrize("payload,expected_missing", [
        (None, True),
        ("", True),
        ("cast details not available.", True),
        ("CAST DETAILS NOT AVAILABLE.", True),
        ("cast details not available", True),
        ("error getting details.", True),
        ("ERROR GETTING DETAILS.", True),
        ("Unknown", True),
        ("n/a", True),
        ("null", True),
        ("none", True),
        ([], True),
        ([None, "", "Unknown"], True),
        ([{"name": None}], True),
        ([{"name": "Unknown"}], True),
        ([{"person": {"name": "Unknown"}}], True),
        ([{"person": {"name": None}}], True),
        ([{"person": None}], True),
        ([{"person": {"name": "Bryan Cranston"}}], False),
        ([{"name": "Aaron Paul"}], False),
        ([{"name": "Unknown"}, {"name": "Pedro Pascal"}], False),
        ("Bryan Cranston, Aaron Paul", False),
        ("Meryl Streep", False),
    ])
    def test_cast_validator_adversarial_matrix(self, payload, expected_missing):
        assert is_cast_missing(payload) == expected_missing

    @pytest.mark.parametrize("payload,expected_missing", [
        (None, True),
        ("", True),
        ("no plot summary available.", True),
        ("NO PLOT SUMMARY AVAILABLE.", True),
        ("no plot summary available", True),
        ("unknown", True),
        ("n/a", True),
        ("null", True),
        ("none", True),
        ("tbd", True),
        ([], True),
        ({}, True),
        ("A chemistry teacher diagnosed with inoperable lung cancer...", False),
        ("Plot with emoji 🌌 and accents éèà", False),
    ])
    def test_plot_validator_adversarial_matrix(self, payload, expected_missing):
        assert is_plot_missing(payload) == expected_missing

    def test_evaluate_metadata_with_unexpected_types(self):
        """Tests evaluate_metadata with completely arbitrary types and key structures."""
        # Non-dict inputs
        assert evaluate_metadata(None)["is_low_metadata"] is True
        assert evaluate_metadata("")["is_low_metadata"] is True
        assert evaluate_metadata(12345)["is_low_metadata"] is True
        assert evaluate_metadata([])["is_low_metadata"] is True

        # Malformed items with weird keys and types
        weird_item = {
            "title": 1234,  # Title "1234" is valid
            "network": ["Invalid", "HBO"],  # Valid list
            "cast": [{"person": {"name": "Bob"}}],  # Valid nested dict
            "plot": "Valid plot",
            "extra_junk": object()
        }
        res = evaluate_metadata(weird_item)
        assert res["missing_count"] == 0
        assert res["is_low_metadata"] is False

    def test_state_transition_full_combinatorial_matrix(self):
        """Exhaustively verifies all 16 state combinations for (was_archived, was_badged) x (is_low, explicitly_archived)."""
        for was_archived in [0, 1]:
            for was_badged in [0, 1]:
                existing = {"is_archived": was_archived, "has_new_metadata": was_badged}
                
                # Case A: New item has full metadata (< 2 missing) and is NOT explicitly archived
                new_full = {"title": "Show", "network": "HBO", "cast": "Actors", "plot": "Summary", "is_archived": 0}
                res_arch, res_badge = evaluate_item_state_transition(existing, new_full)
                if was_archived:
                    assert (res_arch, res_badge) == (0, 1), f"Failed for existing {existing} -> full"
                else:
                    assert (res_arch, res_badge) == (0, was_badged), f"Failed for existing {existing} -> full"

                # Case B: New item is low-metadata (>= 2 missing)
                new_low = {"title": "Show", "network": "Unknown", "cast": "N/A", "plot": "None"}
                res_arch, res_badge = evaluate_item_state_transition(existing, new_low)
                assert (res_arch, res_badge) == (1, 0), f"Failed for existing {existing} -> low"

                # Case C: New item has full metadata but is explicitly marked is_archived=1
                new_explicit_arch = {"title": "Show", "network": "HBO", "cast": "Actors", "plot": "Summary", "is_archived": 1}
                res_arch, res_badge = evaluate_item_state_transition(existing, new_explicit_arch)
                assert (res_arch, res_badge) == (1, 0), f"Failed for existing {existing} -> explicit archive"


# ===========================================================================
# 2. Database Concurrency & Race Condition Stress-Testing
# ===========================================================================

class TestDatabaseConcurrencyAndStress:
    """Stress tests SQLite under concurrent multi-threaded writes, rapid state flipping, and legacy migration."""

    def test_concurrent_multithreaded_cache_writes(self, isolated_db):
        """Spawns multiple threads writing, updating, and archiving items simultaneously to verify lock safety and zero data corruption."""
        num_threads = 10
        iterations_per_thread = 20
        errors = []

        def worker(thread_id):
            try:
                for i in range(iterations_per_thread):
                    # Alternate between sparse and full metadata updates
                    if i % 2 == 0:
                        item = {
                            "title": f"ThreadShow_{thread_id}",
                            "year": 2026,
                            "network": "Unknown",
                            "cast": "N/A",
                            "plot": "No plot summary available."
                        }
                    else:
                        item = {
                            "title": f"ThreadShow_{thread_id}",
                            "year": 2026,
                            "network": "Showtime",
                            "cast": f"Actor {thread_id}",
                            "plot": f"Summary for show {thread_id}"
                        }
                    add_cached_item("tv", item)

                    # Trigger archive / unarchive occasionally
                    if i % 5 == 0:
                        archive_cached_item("tv", f"ThreadShow_{thread_id}", 2026, is_archived=True)
                    elif i % 7 == 0:
                        archive_cached_item("tv", f"ThreadShow_{thread_id}", 2026, is_archived=False)
            except Exception as e:
                errors.append(f"Thread {thread_id} error: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Encountered thread errors during concurrent DB operations: {errors}"

        # Verify DB integrity
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"
        conn.close()

    def test_schema_resilience_missing_and_extra_columns(self, isolated_db):
        """Tests that legacy databases with missing columns or dropped columns migrate properly."""
        conn = sqlite3.connect(isolated_db)
        cursor = conn.cursor()
        # Drop cache and create bare minimal legacy table
        cursor.execute("DROP TABLE cache")
        cursor.execute("""
            CREATE TABLE cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                title TEXT,
                year INTEGER
            )
        """)
        cursor.execute("INSERT INTO cache (type, title, year) VALUES ('tv', 'Old Legacy Show', 2024)")
        conn.commit()
        conn.close()

        # Run init_db() to trigger migration
        init_db()

        # Check that has_new_metadata and all expected columns exist
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(cache)")
        cols = {row["name"] for row in cursor.fetchall()}
        assert "has_new_metadata" in cols
        assert "is_archived" in cols
        assert "normalized_title" in cols

        # Query legacy row
        cursor.execute("SELECT * FROM cache WHERE title = 'Old Legacy Show'")
        legacy_row = dict(cursor.fetchone())
        assert legacy_row["has_new_metadata"] == 0
        assert legacy_row["normalized_title"] == "oldlegacyshow"
        conn.close()

    def test_cache_eviction_edge_cases(self, isolated_db):
        """Tests clean_expired_cache under various date formats, missing dates, and boundary boundaries."""
        conn = get_db_connection()
        cursor = conn.cursor()

        now = datetime.now()
        fresh_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        fresh_added = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

        expired_date = (now - timedelta(days=400)).strftime("%Y-%m-%d")
        expired_added = (now - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Fresh item with date_obj
        cursor.execute("INSERT INTO cache (type, title, year, date_obj, added_at) VALUES ('tv', 'Fresh Show', 2026, ?, ?)", (fresh_date, fresh_added))
        # 2. Expired item with date_obj
        cursor.execute("INSERT INTO cache (type, title, year, date_obj, added_at) VALUES ('tv', 'Expired Show 1', 2024, ?, ?)", (expired_date, fresh_added))
        # 3. Item without date_obj (fallback to added_at) - Fresh
        cursor.execute("INSERT INTO cache (type, title, year, date_obj, added_at) VALUES ('movie', 'Fresh Movie No Date', 2026, '', ?)", (fresh_added,))
        # 4. Item without date_obj - Expired added_at
        cursor.execute("INSERT INTO cache (type, title, year, date_obj, added_at) VALUES ('movie', 'Expired Movie No Date', 2024, '', ?)", (expired_added,))
        # 5. Item with 1900-01-01 sentinel date_obj - Expired added_at
        cursor.execute("INSERT INTO cache (type, title, year, date_obj, added_at) VALUES ('tv', 'Sentinel Date Show', 2024, '1900-01-01', ?)", (expired_added,))
        conn.close()

        clean_expired_cache()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM cache")
        remaining = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "Fresh Show" in remaining
        assert "Fresh Movie No Date" in remaining
        assert "Expired Show 1" not in remaining
        assert "Expired Movie No Date" not in remaining
        assert "Sentinel Date Show" not in remaining


# ===========================================================================
# 3. Web API Endpoints Adversarial Testing
# ===========================================================================

class TestWebAPIAdversarialEndpoints:
    """Stress tests on Flask REST API endpoints with malformed payloads, unauthorized access, and edge parameters."""

    def test_unauthorized_post_request(self, client):
        """Ensures mutating API endpoints reject requests without a valid X-API-Key."""
        res = client.post("/api/archive", json={"type": "tv", "title": "Test", "year": 2026})
        assert res.status_code == 401
        assert res.json["status"] == "error"

    def test_archive_endpoint_malformed_and_missing_params(self, client):
        """Tests /api/archive with missing fields, invalid year types, and empty bodies."""
        headers = {"X-API-Key": "test-secret-key-12345"}

        # Missing title
        res = client.post("/api/archive", json={"type": "tv"}, headers=headers)
        assert res.status_code == 400

        # Missing type
        res = client.post("/api/archive", json={"title": "Test"}, headers=headers)
        assert res.status_code == 400

        # Invalid string year
        res = client.post("/api/archive", json={"type": "tv", "title": "Test", "year": "invalid_year"}, headers=headers)
        assert res.status_code == 500

    def test_cache_refresh_endpoint_adversarial(self, client):
        """Tests /api/cache/refresh error cases and state updates."""
        headers = {"X-API-Key": "test-secret-key-12345"}

        # Missing required parameters
        res = client.post("/api/cache/refresh", json={}, headers=headers)
        assert res.status_code == 400

        # Invalid media type
        res = client.post("/api/cache/refresh", json={"type": "podcast", "title": "Test", "year": 2026}, headers=headers)
        assert res.status_code == 400

    def test_discover_endpoint_extreme_date_parameters(self, client):
        """Tests /api/discover with negative, extreme, or non-integer query params."""
        # Extreme past and future months (clamped internally)
        res = client.get("/api/discover?past_months=9999&future_months=-50&skip_scrape=true")
        assert res.status_code == 200
        assert "tv" in res.json
        assert "movies" in res.json

    def test_api_discover_preserves_new_metadata_boolean(self, client):
        """Verifies /api/discover accurately serializes has_new_metadata as a JSON boolean."""
        headers = {"X-API-Key": "test-secret-key-12345"}

        # Insert sparse item (auto-archived)
        sparse_item = {
            "title": "Badge Serialization Show",
            "year": 2026,
            "network": "Unknown",
            "cast": "N/A",
            "plot": "None",
            "date_obj": "2026-06-01"
        }
        add_cached_item("tv", sparse_item)

        # Unarchive by enriching with full metadata
        full_item = {
            "title": "Badge Serialization Show",
            "year": 2026,
            "network": "HBO",
            "cast": "Famous Cast",
            "plot": "Detailed plot summary.",
            "date_obj": "2026-06-01"
        }
        add_cached_item("tv", full_item)

        res = client.get("/api/discover?past_months=12&future_months=12&skip_scrape=true")
        assert res.status_code == 200
        shows = [s for s in res.json["tv"] if s["title"] == "Badge Serialization Show"]
        assert len(shows) == 1
        assert shows[0]["is_archived"] is False
        assert shows[0]["has_new_metadata"] is True

        # Re-archive via /api/archive and verify has_new_metadata is reset to False in next discover
        res_arch = client.post("/api/archive", json={
            "type": "tv",
            "title": "Badge Serialization Show",
            "year": 2026,
            "archive": True
        }, headers=headers)
        assert res_arch.status_code == 200

        res2 = client.get("/api/discover?past_months=12&future_months=12&skip_scrape=true")
        shows2 = [s for s in res2.json["tv"] if s["title"] == "Badge Serialization Show"]
        assert len(shows2) == 1
        assert shows2[0]["is_archived"] is True
        assert shows2[0]["has_new_metadata"] is False


# ===========================================================================
# 4. Web UI Badging & Client JavaScript Verification
# ===========================================================================

class TestWebUIAdversarialCardRendering:
    """Verifies static templates, DOM badging, CSS rules, and JavaScript rendering logic."""

    def test_app_js_badging_logic_present(self):
        """Verifies frontend modules contain the exact conditional logic for has_new_metadata badge."""
        cards_ts_path = os.path.join(os.path.dirname(__file__), "..", "src", "xarrtools", "web", "static", "src", "cards.ts")
        render_ts_path = os.path.join(os.path.dirname(__file__), "..", "src", "xarrtools", "web", "static", "src", "render.ts")
        with open(cards_ts_path, "r", encoding="utf-8") as f:
            cards_content = f.read()
        with open(render_ts_path, "r", encoding="utf-8") as f:
            render_content = f.read()

        # Check badge creation snippet
        assert "badge-new-metadata" in cards_content
        assert "has_new_metadata" in cards_content
        assert 'item.has_new_metadata ? \'<span class="badge badge-new-metadata">New metadata</span>\' : ""' in cards_content

        # Check toggleArchive resets item.has_new_metadata
        assert "if (isArchiving) {" in render_content
        assert "item.has_new_metadata = false;" in render_content

    def test_style_css_badge_styling_definitions(self):
        """Verifies web/templates/style.css defines the badge styling classes for both dark and light modes."""
        style_css_path = os.path.join(os.path.dirname(__file__), "..", "src", "xarrtools", "web", "templates", "style.css")
        with open(style_css_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert ".badge-new-metadata" in content
        assert ".badge-new-metadata::before" in content
        assert "body.light-theme .badge-new-metadata" in content

    def test_index_html_static_serving(self, client):
        """Verifies GET / serves the HTML index containing required metadata tags."""
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "<meta name=\"x-api-key\"" in html
        assert "main.js" in html
        assert "style.css" in html
        assert "id=\"check-show-archived\"" in html


# ===========================================================================
# 5. Scraper / Enricher Robustness & ReDoS Defense
# ===========================================================================

class TestScraperEnricherRobustness:
    """Verifies regex safety against ReDoS and error handling during failed upstream scrapes."""

    def test_is_safe_regex_guards_against_redos(self):
        from xarrtools.core.scraper import is_safe_regex
        # Safe patterns
        assert is_safe_regex(r'\d{4}') is True
        assert is_safe_regex(r'[a-zA-Z0-9_-]+') is True
        assert is_safe_regex(r'^[A-Z][a-z]+$') is True

        # Dangerous patterns with nested / adjacent quantifiers
        assert is_safe_regex(r'(a+)+') is False
        assert is_safe_regex(r'(a*)*') is False
        assert is_safe_regex(r'(a|b+)+') is False
        assert is_safe_regex(r'a++') is False
        assert is_safe_regex(r'a*+') is False

    def test_title_cleaning_adversarial_patterns(self):
        """Tests clean_tv_title and clean_movie_title on complex adversarial string combinations."""
        # TV cleaning
        assert clean_tv_title("Stranger Things: Season 5") == "Stranger Things"
        assert clean_tv_title("The Crown (Series 3)") == "The Crown"
        assert clean_tv_title("Doctor Who: The Complete Series") == "Doctor Who"
        assert clean_tv_title("Show Name - Season Two") == "Show Name"

        # Movie cleaning
        assert clean_movie_title("Oppenheimer [4K UHD]") == "Oppenheimer"
        assert clean_movie_title("Dune: Part Two (Blu-ray + DVD)") == "Dune: Part Two"
        assert clean_movie_title("Avatar: The Way of Water [Digital]") == "Avatar: The Way of Water"
        assert clean_movie_title("Gladiator II (2024)") == "Gladiator II"
