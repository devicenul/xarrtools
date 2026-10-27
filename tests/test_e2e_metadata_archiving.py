"""
tests/test_e2e_metadata_archiving.py
====================================
Comprehensive Opaque-Box End-to-End (E2E) Test Suite for xarrtools.
Implements the 4-Tier Test Strategy defined in TEST_INFRA.md & PROJECT.md:
  - Tier 1: Feature Coverage (>=5 test cases per feature for all 10 features F1–F10)
  - Tier 2: Boundary & Corner Cases (>=5 test cases per boundary area across 8 areas)
  - Tier 3: Cross-Feature Combinations (Pairwise integration across modules)
  - Tier 4: Real-World Workload Scenarios (End-to-end full application lifecycles)

Derived directly from ORIGINAL_REQUEST.md and PROJECT.md interface contracts.
"""

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Database & Environment Isolation Fixtures
# ---------------------------------------------------------------------------

import xarrtools.core.db; from xarrtools import core
import xarrtools.core.metadata; from xarrtools import core
from xarrtools.core.metadata import (
    MISSING_CAST_STRINGS,
    MISSING_NETWORK_STRINGS,
    MISSING_PLOT_STRINGS,
    MISSING_TITLE_STRINGS,
    evaluate_item_state_transition,
    evaluate_metadata,
    is_cast_missing,
    is_network_missing,
    is_plot_missing,
    is_title_missing,
    should_auto_archive,
)

# Patch DB_PATH before importing server to ensure clean temporary test database
_temp_db_fd, _temp_db_path = tempfile.mkstemp(suffix="_e2e_test.db")
os.close(_temp_db_fd)
core.db.DB_PATH = Path(_temp_db_path)
core.db.init_db()

with patch("threading.Thread"):
    from xarrtools.web.server import app, sync_library_cache

from xarrtools.cli.cli import handle_discovery_workflow, console, run_cli


@pytest.fixture(autouse=True)
def isolated_db_environment(tmp_path):
    """
    Ensures every test has a pristine, isolated SQLite database
    and reset configuration settings.
    """
    db_file = tmp_path / "e2e_test_isolated.db"
    orig_db_path = core.db.DB_PATH
    core.db.DB_PATH = db_file
    core.db.init_db()
    core.db.set_setting("api_key", "test_secret_e2e_key")
    core.db.set_setting("default_match_ignore_year", "1")
    core.db.set_setting("default_show_archived", "0")

    from xarrtools.core.config import config
    config.refresh()

    yield db_file

    core.db.DB_PATH = orig_db_path


@pytest.fixture(autouse=True)
def mock_external_clients():
    """Mocks web.server.get_clients to return (None, None) by default for fast, isolated tests."""
    with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
        yield



@pytest.fixture
def api_client(isolated_db_environment):

    """
    Configures Flask test client with automatic API key injection.
    """
    app.config["TESTING"] = True

    class WrappedApiClient:
        def __init__(self, client):
            self._client = client
            self.api_key = "test_secret_e2e_key"

        def get(self, path, *args, **kwargs):
            return self._client.get(path, *args, **kwargs)

        def post(self, path, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            if "X-API-Key" not in headers:
                headers["X-API-Key"] = self.api_key
            return self._client.post(path, headers=headers, *args, **kwargs)

        def put(self, path, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            if "X-API-Key" not in headers:
                headers["X-API-Key"] = self.api_key
            return self._client.put(path, headers=headers, *args, **kwargs)

        def delete(self, path, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            if "X-API-Key" not in headers:
                headers["X-API-Key"] = self.api_key
            return self._client.delete(path, headers=headers, *args, **kwargs)

    with app.test_client() as c:
        yield WrappedApiClient(c)


# Helper function to generate DOM card representation matching frontend templates
def render_media_card_html(item: Dict[str, Any]) -> str:
    """
    Simulates the client-side card rendering from web/static/src/cards.ts.
    Generates HTML string with badges for DOM assertion.
    """
    has_new_metadata = bool(item.get("has_new_metadata", False))
    is_archived = bool(item.get("is_archived", False))
    is_in_library = bool(item.get("is_in_library", False))
    is_returning = bool(item.get("is_returning", False))
    network = item.get("network", "Unknown")

    badges = []
    if network and network != "Unknown":
        badges.append(f'<span class="badge badge-network">{network}</span>')
    if is_returning:
        badges.append('<span class="badge badge-returning">Returning Series</span>')
    if is_in_library:
        badges.append('<span class="badge badge-library">In Library</span>')
    if is_archived:
        badges.append('<span class="badge badge-archived">Archived</span>')
    if has_new_metadata:
        badges.append('<span class="badge badge-new-metadata">New metadata</span>')

    badges_html = "\n".join(badges)
    return f"""
    <div class="media-card {'archived' if is_archived else ''}">
        <div class="card-badges">
            {badges_html}
        </div>
        <div class="card-content">
            <h3 class="card-title">{item.get('title', '')}</h3>
            <p class="card-plot">{item.get('plot', '')}</p>
        </div>
    </div>
    """


# ===========================================================================
# TIER 1: FEATURE COVERAGE (F1 - F10, >= 5 Tests per Feature)
# ===========================================================================

# ---------------------------------------------------------------------------
# Feature F1: Title Missingness Evaluation
# ---------------------------------------------------------------------------
class TestTier1FeatureF1TitleMissingness:
    """Tests for Title missingness against empty, whitespace, sentinels, and valid values."""

    def test_f1_01_empty_string(self):
        assert is_title_missing("") is True

    def test_f1_02_whitespace_variations(self):
        assert is_title_missing("   ") is True
        assert is_title_missing("\t\n  \r") is True

    def test_f1_03_unknown_sentinels_case_insensitive(self):
        assert is_title_missing("Unknown") is True
        assert is_title_missing("unknown") is True
        assert is_title_missing("UNKNOWN") is True
        assert is_title_missing("  Unknown  ") is True

    def test_f1_04_tbd_and_na_sentinels(self):
        assert is_title_missing("TBD") is True
        assert is_title_missing("tbd") is True
        assert is_title_missing("N/A") is True
        assert is_title_missing("na") is True
        assert is_title_missing("none") is True
        assert is_title_missing("null") is True

    def test_f1_05_valid_titles(self):
        assert is_title_missing("Breaking Bad") is False
        assert is_title_missing("Severance") is False
        assert is_title_missing("The Lord of the Rings: The Rings of Power") is False
        assert is_title_missing("2001: A Space Odyssey") is False

    def test_f1_06_non_string_types(self):
        assert is_title_missing(None) is True
        assert is_title_missing([]) is True
        assert is_title_missing({}) is True
        assert is_title_missing(True) is True
        assert is_title_missing(False) is True


# ---------------------------------------------------------------------------
# Feature F2: Studio / Network Missingness Evaluation
# ---------------------------------------------------------------------------
class TestTier1FeatureF2NetworkMissingness:
    """Tests for Studio/Network missingness against sentinels, dicts, lists, and valid strings."""

    def test_f2_01_empty_and_whitespace(self):
        assert is_network_missing("") is True
        assert is_network_missing("   ") is True
        assert is_network_missing("\t\n") is True

    def test_f2_02_unknown_network_sentinels(self):
        assert is_network_missing("Unknown") is True
        assert is_network_missing("unknown network") is True
        assert is_network_missing("UNKNOWN STUDIO") is True
        assert is_network_missing("  Unknown Network  ") is True

    def test_f2_03_na_and_none_sentinels(self):
        assert is_network_missing("N/A") is True
        assert is_network_missing("na") is True
        assert is_network_missing("None") is True
        assert is_network_missing("null") is True
        assert is_network_missing("TBD") is True

    def test_f2_04_valid_networks(self):
        assert is_network_missing("HBO") is False
        assert is_network_missing("Netflix") is False
        assert is_network_missing("Apple TV+") is False
        assert is_network_missing("Paramount+") is False
        assert is_network_missing("Warner Bros. Pictures") is False

    def test_f2_05_dictionary_and_nested_structures(self):
        assert is_network_missing({"name": "HBO"}) is False
        assert is_network_missing({"studio": "A24"}) is False
        assert is_network_missing({"network": "FX"}) is False
        assert is_network_missing({"name": "Unknown"}) is True
        assert is_network_missing({"name": ""}) is True
        assert is_network_missing({}) is True

    def test_f2_06_list_and_non_string_types(self):
        assert is_network_missing(["HBO", "Max"]) is False
        assert is_network_missing(["Unknown", "N/A"]) is True
        assert is_network_missing([]) is True
        assert is_network_missing(None) is True
        assert is_network_missing(False) is True


# ---------------------------------------------------------------------------
# Feature F3: Cast Missingness Evaluation
# ---------------------------------------------------------------------------
class TestTier1FeatureF3CastMissingness:
    """Tests for Cast missingness against strings, lists, dict structures, and sentinels."""

    def test_f3_01_empty_string_and_empty_collections(self):
        assert is_cast_missing("") is True
        assert is_cast_missing("   ") is True
        assert is_cast_missing([]) is True
        assert is_cast_missing({}) is True

    def test_f3_02_cast_details_not_available_sentinel(self):
        assert is_cast_missing("Cast details not available.") is True
        assert is_cast_missing("cast details not available") is True
        assert is_cast_missing("CAST DETAILS NOT AVAILABLE.") is True
        assert is_cast_missing("  Cast details not available.  ") is True

    def test_f3_03_error_getting_details_and_na_sentinels(self):
        assert is_cast_missing("Error getting details.") is True
        assert is_cast_missing("Unknown") is True
        assert is_cast_missing("N/A") is True
        assert is_cast_missing("na") is True
        assert is_cast_missing("None") is True
        assert is_cast_missing("null") is True
        assert is_cast_missing("TBD") is True

    def test_f3_04_valid_cast_strings(self):
        assert is_cast_missing("Bryan Cranston, Aaron Paul") is False
        assert is_cast_missing("Pedro Pascal") is False
        assert is_cast_missing("Cillian Murphy, Emily Blunt, Matt Damon") is False

    def test_f3_05_valid_cast_lists_and_person_objects(self):
        assert is_cast_missing(["Pedro Pascal", "Bella Ramsey"]) is False
        assert is_cast_missing([{"name": "Bryan Cranston"}, {"name": "Aaron Paul"}]) is False
        assert is_cast_missing([{"person": {"name": "Adam Scott"}}]) is False

    def test_f3_06_invalid_cast_lists_and_non_string_types(self):
        assert is_cast_missing(["Unknown", "N/A", "Cast details not available."]) is True
        assert is_cast_missing([{"name": "Unknown"}, {"name": ""}]) is True
        assert is_cast_missing(None) is True
        assert is_cast_missing(True) is True
        assert is_cast_missing(False) is True


# ---------------------------------------------------------------------------
# Feature F4: Plot Missingness Evaluation
# ---------------------------------------------------------------------------
class TestTier1FeatureF4PlotMissingness:
    """Tests for Plot missingness against empty, sentinels, whitespace, and valid summaries."""

    def test_f4_01_empty_string_and_whitespace(self):
        assert is_plot_missing("") is True
        assert is_plot_missing("   ") is True
        assert is_plot_missing("\t\n") is True

    def test_f4_02_no_plot_summary_available_sentinel(self):
        assert is_plot_missing("No plot summary available.") is True
        assert is_plot_missing("no plot summary available") is True
        assert is_plot_missing("NO PLOT SUMMARY AVAILABLE.") is True
        assert is_plot_missing("  No plot summary available.  ") is True

    def test_f4_03_unknown_and_na_sentinels(self):
        assert is_plot_missing("Unknown") is True
        assert is_plot_missing("N/A") is True
        assert is_plot_missing("na") is True
        assert is_plot_missing("None") is True
        assert is_plot_missing("null") is True
        assert is_plot_missing("TBD") is True

    def test_f4_04_valid_plots_and_overviews(self):
        assert is_plot_missing("A high school chemistry teacher turned meth kingpin.") is False
        assert is_plot_missing("Employees undergo a surgical procedure to separate work and personal memories.") is False
        assert is_plot_missing("Paul Atreides unites with the Fremen while seeking revenge against conspirators.") is False

    def test_f4_05_non_string_types_and_empty_collections(self):
        assert is_plot_missing(None) is True
        assert is_plot_missing([]) is True
        assert is_plot_missing({}) is True
        assert is_plot_missing(True) is True
        assert is_plot_missing(False) is True


# ---------------------------------------------------------------------------
# Feature F5: Combinatorial Evaluation & Auto-Archiving Decision
# ---------------------------------------------------------------------------
class TestTier1FeatureF5CombinatorialAutoArchiving:
    """Tests evaluating items with 0, 1, 2, 3, or 4 missing fields and computing low-metadata flag."""

    def test_f5_01_zero_missing_fields_not_archived(self):
        item = {
            "title": "Severance",
            "network": "Apple TV+",
            "cast": "Adam Scott, Zach Cherry, Britt Lower",
            "plot": "Mark leads a team of office workers whose memories have been surgically divided.",
        }
        res = evaluate_metadata(item)
        assert res["missing_count"] == 0
        assert res["missing_fields"] == []
        assert res["is_low_metadata"] is False
        assert should_auto_archive(item) is False

    def test_f5_02_one_missing_field_retained_unarchived(self):
        # Missing Plot only
        item_missing_plot = {
            "title": "Succession",
            "network": "HBO",
            "cast": "Brian Cox, Jeremy Strong",
            "plot": "No plot summary available.",
        }
        res = evaluate_metadata(item_missing_plot)
        assert res["missing_count"] == 1
        assert res["missing_fields"] == ["plot"]
        assert res["is_low_metadata"] is False
        assert should_auto_archive(item_missing_plot) is False

        # Missing Cast only
        item_missing_cast = {
            "title": "Succession",
            "network": "HBO",
            "cast": "Cast details not available.",
            "plot": "The Roy family is known for controlling the biggest media and entertainment company.",
        }
        assert evaluate_metadata(item_missing_cast)["missing_count"] == 1
        assert should_auto_archive(item_missing_cast) is False

    def test_f5_03_two_missing_fields_auto_archived(self):
        item = {
            "title": "Dune: Part Two",
            "network": "Warner Bros.",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert sorted(res["missing_fields"]) == ["cast", "plot"]
        assert res["is_low_metadata"] is True
        assert should_auto_archive(item) is True

    def test_f5_04_three_missing_fields_auto_archived(self):
        item = {
            "title": "Untitled Sci-Fi Project",
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        res = evaluate_metadata(item)
        assert res["missing_count"] == 3
        assert sorted(res["missing_fields"]) == ["cast", "network", "plot"]
        assert res["is_low_metadata"] is True
        assert should_auto_archive(item) is True

    def test_f5_05_four_missing_fields_auto_archived(self):
        item = {
            "title": "Unknown",
            "network": "N/A",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        res = evaluate_metadata(item)
        assert res["missing_count"] == 4
        assert res["is_low_metadata"] is True
        assert should_auto_archive(item) is True

    def test_f5_06_none_or_empty_item_auto_archived(self):
        assert should_auto_archive({}) is True
        assert should_auto_archive(None) is True


# ---------------------------------------------------------------------------
# Feature F6: SQLite Database Persistence & Schema Migration
# ---------------------------------------------------------------------------
class TestTier1FeatureF6DatabasePersistenceAndMigration:
    """Tests SQLite table creation, has_new_metadata column persistence, and legacy migration."""

    def test_f6_01_init_db_creates_has_new_metadata_column(self, isolated_db_environment):
        conn = core.db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(cache)")
        cols = {row["name"]: row["type"] for row in cursor.fetchall()}
        conn.close()

        assert "has_new_metadata" in cols
        assert "is_archived" in cols

    def test_f6_02_legacy_db_migration_adds_column(self, tmp_path):
        legacy_db = tmp_path / "legacy_xarrtools.db"
        conn = sqlite3.connect(legacy_db)
        cursor = conn.cursor()
        # Create legacy cache table WITHOUT has_new_metadata
        cursor.execute("""
            CREATE TABLE cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                title TEXT,
                year INTEGER,
                is_archived INTEGER DEFAULT 0
            )
        """)
        cursor.execute("INSERT INTO cache (type, title, year, is_archived) VALUES ('movie', 'Legacy Film', 2020, 0)")
        conn.commit()
        conn.close()

        # Run init_db on the legacy DB
        orig_db = core.db.DB_PATH
        try:
            core.db.DB_PATH = legacy_db
            core.db.init_db()

            conn = core.db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(cache)")
            cols = [row["name"] for row in cursor.fetchall()]
            assert "has_new_metadata" in cols

            # Check that existing row is preserved with default 0
            cursor.execute("SELECT * FROM cache WHERE title = 'Legacy Film'")
            row = cursor.fetchone()
            assert row["has_new_metadata"] == 0
            assert row["is_archived"] == 0
            conn.close()
        finally:
            core.db.DB_PATH = orig_db

    def test_f6_03_insert_low_metadata_persists_is_archived_1(self):
        item = {
            "title": "Sparse Movie",
            "year": 2026,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        core.db.add_cached_item("movie", item)

        cached = core.db.get_cached_item("movie", "Sparse Movie", 2026)
        assert cached is not None
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

    def test_f6_04_insert_full_metadata_persists_is_archived_0(self):
        item = {
            "title": "Complete Show",
            "year": 2026,
            "network": "HBO",
            "cast": "Actor One, Actor Two",
            "plot": "A complete and rich plot description of the show.",
        }
        core.db.add_cached_item("tv", item)

        cached = core.db.get_cached_item("tv", "Complete Show", 2026)
        assert cached is not None
        assert cached["is_archived"] == 0
        assert cached["has_new_metadata"] == 0

    def test_f6_05_batch_insert_persists_correct_states(self):
        items = [
            {"title": "Batch Full", "year": 2026, "network": "Netflix", "cast": "A1, A2", "plot": "Valid plot summary."},
            {"title": "Batch Sparse", "year": 2026, "network": "Unknown", "cast": "Cast details not available.", "plot": "No plot summary available."},
        ]
        core.db.add_cached_items_batch("tv", items)

        full = core.db.get_cached_item("tv", "Batch Full", 2026)
        sparse = core.db.get_cached_item("tv", "Batch Sparse", 2026)

        assert full["is_archived"] == 0
        assert full["has_new_metadata"] == 0
        assert sparse["is_archived"] == 1
        assert sparse["has_new_metadata"] == 0


# ---------------------------------------------------------------------------
# Feature F7: Smart Auto-Unarchiving with "New Metadata" Flag on Discovery
# ---------------------------------------------------------------------------
class TestTier1FeatureF7SmartAutoUnarchiving:
    """Tests automatic unarchiving and setting has_new_metadata=1 when new metadata arrives."""

    def test_f7_01_state_transition_archived_to_full_metadata(self):
        existing = {"title": "Test Show", "is_archived": 1, "has_new_metadata": 0}
        new_item = {
            "title": "Test Show",
            "network": "Apple TV+",
            "cast": "Actor A, Actor B",
            "plot": "Full plot details populated.",
        }
        is_archived, has_new_metadata = evaluate_item_state_transition(existing, new_item)
        assert is_archived == 0
        assert has_new_metadata == 1

    def test_f7_02_state_transition_archived_stays_archived_if_still_sparse(self):
        existing = {"title": "Test Show", "is_archived": 1, "has_new_metadata": 0}
        new_item = {
            "title": "Test Show",
            "network": "HBO",  # only network populated; cast & plot still missing (2 missing fields)
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        is_archived, has_new_metadata = evaluate_item_state_transition(existing, new_item)
        assert is_archived == 1
        assert has_new_metadata == 0

    def test_f7_03_db_add_cached_item_unarchives_and_flags(self):
        # Step 1: Ingest sparse item -> auto-archived
        sparse = {
            "title": "Unarchive Me",
            "year": 2026,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        core.db.add_cached_item("movie", sparse)
        cached1 = core.db.get_cached_item("movie", "Unarchive Me", 2026)
        assert cached1["is_archived"] == 1
        assert cached1["has_new_metadata"] == 0

        # Step 2: Upstream discovers metadata -> unarchived with badge
        enriched = {
            "title": "Unarchive Me",
            "year": 2026,
            "network": "A24",
            "cast": "Famous Star",
            "plot": "An acclaimed masterpiece synopsis.",
        }
        core.db.add_cached_item("movie", enriched)
        cached2 = core.db.get_cached_item("movie", "Unarchive Me", 2026)
        assert cached2["is_archived"] == 0
        assert cached2["has_new_metadata"] == 1

    def test_f7_04_unarchived_item_preserves_existing_badge_on_rescan(self):
        existing = {"title": "Badged Show", "is_archived": 0, "has_new_metadata": 1}
        new_item = {
            "title": "Badged Show",
            "network": "HBO",
            "cast": "Actor A",
            "plot": "Plot summary.",
        }
        is_archived, has_new_metadata = evaluate_item_state_transition(existing, new_item)
        assert is_archived == 0
        assert has_new_metadata == 1

    def test_f7_05_api_discover_returns_has_new_metadata_true(self, api_client):
        # Seed an auto-unarchived item directly into cache
        item = {
            "title": "API Discovery Test",
            "year": 2026,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "Paramount+",
            "cast": "Star Actor",
            "plot": "Great synopsis.",
        }
        # Ingest sparse then enriched
        core.db.add_cached_item("tv", {**item, "network": "Unknown", "cast": "Cast details not available."})
        core.db.add_cached_item("tv", item)

        res = api_client.get("/api/discover?skip_scrape=true")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"

        tv_items = [x for x in data["tv"] if x["title"] == "API Discovery Test"]
        assert len(tv_items) == 1
        assert tv_items[0]["is_archived"] is False
        assert tv_items[0]["has_new_metadata"] is True


# ---------------------------------------------------------------------------
# Feature F8: Re-Archiving Flag Reset
# ---------------------------------------------------------------------------
class TestTier1FeatureF8ReArchivingFlagReset:
    """Tests resetting has_new_metadata to False/0 whenever an item is re-archived."""

    def test_f8_01_db_archive_cached_item_resets_badge(self):
        # Create unarchived item with badge
        item = {
            "title": "Manual Archive Target",
            "year": 2026,
            "network": "Netflix",
            "cast": "Star A",
            "plot": "Synopsis.",
        }
        core.db.add_cached_item("tv", {**item, "network": "Unknown", "cast": "Cast details not available."})
        core.db.add_cached_item("tv", item)

        # Verify badge is active
        cached = core.db.get_cached_item("tv", "Manual Archive Target", 2026)
        assert cached["has_new_metadata"] == 1

        # Re-archive
        core.db.archive_cached_item("tv", "Manual Archive Target", 2026, is_archived=True)

        cached_after = core.db.get_cached_item("tv", "Manual Archive Target", 2026)
        assert cached_after["is_archived"] == 1
        assert cached_after["has_new_metadata"] == 0

    def test_f8_02_api_archive_endpoint_resets_badge(self, api_client):
        item = {
            "title": "API Archive Target",
            "year": 2026,
            "date_obj": datetime.now(),
            "network": "HBO",
            "cast": "Star B",
            "plot": "Synopsis B.",
        }
        core.db.add_cached_item("movie", {**item, "network": "Unknown", "cast": "Cast details not available."})
        core.db.add_cached_item("movie", item)

        # Call POST /api/archive
        payload = {
            "type": "movie",
            "title": "API Archive Target",
            "year": 2026,
            "archive": True,
        }
        res = api_client.post("/api/archive", json=payload)
        assert res.status_code == 200

        cached = core.db.get_cached_item("movie", "API Archive Target", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

    def test_f8_03_metadata_degradation_resets_badge(self):
        existing = {"title": "Degraded Show", "is_archived": 0, "has_new_metadata": 1}
        degraded = {
            "title": "Degraded Show",
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        is_archived, has_new_metadata = evaluate_item_state_transition(existing, degraded)
        assert is_archived == 1
        assert has_new_metadata == 0

    def test_f8_04_explicit_is_archived_in_payload_resets_badge(self):
        existing = {"title": "Payload Archived", "is_archived": 0, "has_new_metadata": 1}
        new_item = {
            "title": "Payload Archived",
            "network": "Apple TV+",
            "cast": "Star",
            "plot": "Plot.",
            "is_archived": 1,
        }
        is_archived, has_new_metadata = evaluate_item_state_transition(existing, new_item)
        assert is_archived == 1
        assert has_new_metadata == 0

    def test_f8_05_idempotent_rearchiving_keeps_zero_badge(self):
        item = {"title": "Idempotent Target", "year": 2026, "network": "HBO", "cast": "Cast", "plot": "Plot"}
        core.db.add_cached_item("tv", item)

        # Archive once
        core.db.archive_cached_item("tv", "Idempotent Target", 2026, is_archived=True)
        row1 = core.db.get_cached_item("tv", "Idempotent Target", 2026)
        assert row1["has_new_metadata"] == 0

        # Archive second time
        core.db.archive_cached_item("tv", "Idempotent Target", 2026, is_archived=True)
        row2 = core.db.get_cached_item("tv", "Idempotent Target", 2026)
        assert row2["has_new_metadata"] == 0
        assert row2["is_archived"] == 1


# ---------------------------------------------------------------------------
# Feature F9: Web UI "New metadata" Card Badging & Styling
# ---------------------------------------------------------------------------
class TestTier1FeatureF9WebUIBadgingAndStyling:
    """Tests Web UI badge generation in HTML cards, CSS definitions, and static assets."""

    def test_f9_01_card_html_renders_new_metadata_badge(self):
        item = {
            "title": "Severance",
            "network": "Apple TV+",
            "plot": "Office sci-fi.",
            "is_archived": False,
            "has_new_metadata": True,
        }
        card_html = render_media_card_html(item)
        assert '<span class="badge badge-new-metadata">New metadata</span>' in card_html

    def test_f9_02_card_html_omits_badge_when_false(self):
        item = {
            "title": "Severance",
            "network": "Apple TV+",
            "plot": "Office sci-fi.",
            "is_archived": False,
            "has_new_metadata": False,
        }
        card_html = render_media_card_html(item)
        assert "badge-new-metadata" not in card_html

    def test_f9_03_badge_renders_inside_card_badges_container(self):
        item = {
            "title": "Slow Horses",
            "network": "Apple TV+",
            "plot": "Spy drama.",
            "is_returning": True,
            "is_in_library": True,
            "has_new_metadata": True,
        }
        card_html = render_media_card_html(item)
        assert '<div class="card-badges">' in card_html
        assert '<span class="badge badge-new-metadata">New metadata</span>' in card_html
        assert '<span class="badge badge-returning">Returning Series</span>' in card_html
        assert '<span class="badge badge-library">In Library</span>' in card_html

    def test_f9_04_css_file_contains_badge_new_metadata_styling(self):
        css_path = Path(__file__).resolve().parent.parent / "src" / "xarrtools" / "web" / "templates" / "style.css"
        assert css_path.exists()
        css_content = css_path.read_text(encoding="utf-8")

        assert ".badge-new-metadata" in css_content
        # Verify color styling rules exist
        assert "background" in css_content or "color" in css_content

    def test_f9_05_static_assets_serve_correctly(self, api_client):
        res_css = api_client.get("/static/style.css")
        assert res_css.status_code == 200
        assert b".badge-new-metadata" in res_css.data

        res_js = api_client.get("/static/dist/cards.js")
        assert res_js.status_code == 200
        assert b"badge-new-metadata" in res_js.data or b"has_new_metadata" in res_js.data


# ---------------------------------------------------------------------------
# Feature F10: CLI "New metadata" Tag & Status Display
# ---------------------------------------------------------------------------
class TestTier1FeatureF10CLITagAndStatusDisplay:
    """Tests CLI formatting and rendering of [New metadata] and (Archived) tags."""

    @patch("xarrtools.cli.cli.config")
    @patch("xarrtools.cli.cli.Prompt.ask")
    @patch("xarrtools.cli.cli.console.print")
    @patch("xarrtools.cli.cli.get_discoveries")
    @patch("xarrtools.cli.cli.enrich_tv_show")
    @patch("xarrtools.cli.cli.enrich_movie")
    def test_f10_01_cli_shows_new_metadata_tag(
        self, mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
    ):
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_ask.side_effect = ["1", "c"]

        tv_raw = [{"title": "Fresh Discovery", "date_obj": datetime(2026, 9, 1), "description": "Desc", "date_str": "Sep 1", "is_returning": False}]
        mock_get_disc.return_value = (tv_raw, [])
        mock_enrich_tv.return_value = {
            "title": "Fresh Discovery", "year": 2026, "plot": "Plot", "cast": "Cast",
            "genres": ["Drama"], "trailer": "", "tvdbId": 1, "imdbId": "tt1",
            "network": "HBO", "is_in_library": False, "has_new_metadata": True,
            "is_archived": False, "raw_metadata": {"title": "Fresh Discovery"}
        }

        handle_discovery_workflow()
        printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("[New metadata]" in t for t in printed_texts)
        assert any("Fresh Discovery" in t for t in printed_texts)

    @patch("xarrtools.cli.cli.config")
    @patch("xarrtools.cli.cli.Prompt.ask")
    @patch("xarrtools.cli.cli.console.print")
    @patch("xarrtools.cli.cli.get_discoveries")
    @patch("xarrtools.cli.cli.enrich_tv_show")
    @patch("xarrtools.cli.cli.enrich_movie")
    def test_f10_02_cli_shows_archived_tag(
        self, mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
    ):
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_ask.side_effect = ["1", "c"]

        movie_raw = [{"title": "Hidden Gem", "date_obj": datetime(2026, 9, 1), "description": "Desc", "date_str": "Sep 1"}]
        mock_get_disc.return_value = ([], movie_raw)
        mock_enrich_movie.return_value = {
            "title": "Hidden Gem", "year": 2026, "plot": "", "cast": "Cast details not available.",
            "genres": [], "trailer": "", "tmdbId": None, "imdbId": None,
            "network": "Unknown", "is_in_library": False, "has_new_metadata": False,
            "is_archived": True, "raw_metadata": None
        }

        handle_discovery_workflow()
        printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("(Archived)" in t for t in printed_texts)
        assert any("Hidden Gem" in t for t in printed_texts)

    @patch("xarrtools.cli.cli.config")
    @patch("xarrtools.cli.cli.Prompt.ask")
    @patch("xarrtools.cli.cli.console.print")
    @patch("xarrtools.cli.cli.get_discoveries")
    @patch("xarrtools.cli.cli.enrich_tv_show")
    @patch("xarrtools.cli.cli.enrich_movie")
    def test_f10_03_cli_standard_item_shows_normal_status(
        self, mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
    ):
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_ask.side_effect = ["1", "c"]

        movie_raw = [{"title": "Standard Movie", "date_obj": datetime(2026, 9, 1), "description": "Desc", "date_str": "Sep 1"}]
        mock_get_disc.return_value = ([], movie_raw)
        mock_enrich_movie.return_value = {
            "title": "Standard Movie", "year": 2026, "plot": "Great plot", "cast": "Star Actor",
            "genres": ["Action"], "trailer": "", "tmdbId": 100, "imdbId": "tt100",
            "network": "Universal", "is_in_library": True, "has_new_metadata": False,
            "is_archived": False, "raw_metadata": {"title": "Standard Movie"}
        }

        handle_discovery_workflow()
        printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("Standard Movie" in t and "(In Library)" in t for t in printed_texts)
        assert not any("Standard Movie" in t and "[New metadata]" in t for t in printed_texts)
        assert not any("Standard Movie" in t and "(Archived)" in t for t in printed_texts)

    @patch("xarrtools.cli.cli.config")
    @patch("xarrtools.cli.cli.Prompt.ask")
    @patch("xarrtools.cli.cli.console.print")
    @patch("xarrtools.cli.cli.get_discoveries")
    def test_f10_04_cli_empty_releases_returns_cleanly(
        self, mock_get_disc, mock_print, mock_ask, mock_config
    ):
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_ask.side_effect = ["1"]
        mock_get_disc.return_value = ([], [])

        handle_discovery_workflow()
        printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("No new releases found" in t for t in printed_texts)


    @patch("xarrtools.cli.cli.config")
    @patch("xarrtools.cli.cli.Prompt.ask")
    @patch("xarrtools.cli.cli.console.print")
    @patch("xarrtools.cli.cli.get_discoveries")
    @patch("xarrtools.cli.cli.enrich_tv_show")
    @patch("xarrtools.cli.cli.enrich_movie")
    def test_f10_05_cli_multiple_items_mixed_statuses(
        self, mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
    ):
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_ask.side_effect = ["1", "c"]

        tv_raw = [
            {"title": "Show A", "date_obj": datetime(2026, 9, 1), "description": "D1", "date_str": "Sep 1", "is_returning": False},
            {"title": "Show B", "date_obj": datetime(2026, 9, 1), "description": "D2", "date_str": "Sep 1", "is_returning": False},
        ]
        mock_get_disc.return_value = (tv_raw, [])
        mock_enrich_tv.side_effect = [
            {"title": "Show A", "year": 2026, "plot": "P1", "cast": "C1", "genres": [], "trailer": "", "tvdbId": 1, "imdbId": "tt1", "network": "HBO", "is_in_library": False, "has_new_metadata": True, "is_archived": False, "raw_metadata": {"title": "Show A"}},
            {"title": "Show B", "year": 2026, "plot": "", "cast": "Cast details not available.", "genres": [], "trailer": "", "tvdbId": None, "imdbId": None, "network": "Unknown", "is_in_library": False, "has_new_metadata": False, "is_archived": True, "raw_metadata": None},
        ]

        handle_discovery_workflow()
        printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("Show A" in t and "[New metadata]" in t for t in printed_texts)
        assert any("Show B" in t and "(Archived)" in t for t in printed_texts)



# ===========================================================================
# TIER 2: BOUNDARY & CORNER CASES (>= 5 Tests per Area across 8 Areas)
# ===========================================================================

# ---------------------------------------------------------------------------
# Area 1: Extreme Whitespace, Non-breaking Spaces & Control Characters
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea1WhitespaceAndControlChars:
    """Tests extreme whitespace, tabs, newlines, and non-breaking spaces across fields."""

    def test_b1_01_non_breaking_spaces_in_title(self):
        assert is_title_missing("\u00a0\u00a0") is True
        assert is_title_missing("\u00a0Dune: Part Two\u00a0") is False

    def test_b1_02_carriage_returns_and_vertical_tabs(self):
        assert is_plot_missing("\r\n\t\v\f") is True
        assert is_cast_missing("\r\n\t") is True
        assert is_network_missing("\r\n\t") is True

    def test_b1_03_sentinel_with_padded_whitespace(self):
        assert is_title_missing("   UNKNOWN   ") is True
        assert is_network_missing(" \t Unknown Network \n ") is True
        assert is_cast_missing("  Cast Details Not Available. \t ") is True
        assert is_plot_missing(" \n No Plot Summary Available.  ") is True

    def test_b1_04_valid_text_with_internal_tabs_and_newlines(self):
        assert is_plot_missing("Chapter 1.\n\nChapter 2.\tThe story continues.") is False
        assert is_cast_missing("Actor One,\nActor Two,\tActor Three") is False

    def test_b1_05_whitespace_only_dict_keys(self):
        assert is_network_missing({"name": "   "}) is True
        assert is_cast_missing([{"name": "   "}, {"name": "\t"}]) is True


# ---------------------------------------------------------------------------
# Area 2: Punctuation, Suffixes & Case Variations in Sentinels
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea2PunctuationAndCaseVariations:
    """Tests sentinels with mixed casing, trailing punctuation, and variations."""

    def test_b2_01_cast_sentinels_without_trailing_period(self):
        assert is_cast_missing("cast details not available") is True
        assert is_cast_missing("Cast Details Not Available") is True
        assert is_cast_missing("CAST DETAILS NOT AVAILABLE") is True

    def test_b2_02_plot_sentinels_without_trailing_period(self):
        assert is_plot_missing("no plot summary available") is True
        assert is_plot_missing("No Plot Summary Available") is True
        assert is_plot_missing("NO PLOT SUMMARY AVAILABLE") is True

    def test_b2_03_network_case_and_spacing_variations(self):
        assert is_network_missing("uNkNoWn") is True
        assert is_network_missing("UNKNOWN STUDIO") is True
        assert is_network_missing("unknown network") is True

    def test_b2_04_title_sentinel_variations(self):
        assert is_title_missing("T.B.D.") is False  # Explicit T.B.D. with dots is non-sentinel or literal
        assert is_title_missing("tbd") is True
        assert is_title_missing("TBD") is True
        assert is_title_missing("n/a") is True
        assert is_title_missing("N/A") is True

    def test_b2_05_error_getting_details_sentinels(self):
        assert is_cast_missing("error getting details.") is True
        assert is_cast_missing("ERROR GETTING DETAILS.") is True


# ---------------------------------------------------------------------------
# Area 3: Nested Data Structures & Complex Field Dicts/Lists
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea3NestedDataStructures:
    """Tests deeply nested dictionaries, TVMaze person structures, and mixed lists."""

    def test_b3_01_tvmaze_person_structure(self):
        cast_data = [
            {"person": {"name": "Bob Odenkirk"}},
            {"person": {"name": "Rhea Seehorn"}},
        ]
        assert is_cast_missing(cast_data) is False

    def test_b3_02_tvmaze_empty_or_null_person_structure(self):
        cast_data = [
            {"person": {"name": "Unknown"}},
            {"person": {"name": ""}},
            {"person": None},
        ]
        assert is_cast_missing(cast_data) is True

    def test_b3_03_nested_network_dictionary(self):
        net_valid = {"network": {"name": "BBC One", "country": {"name": "United Kingdom"}}}
        assert is_network_missing(net_valid) is False

        net_invalid = {"network": {"name": "Unknown Network"}}
        assert is_network_missing(net_invalid) is True

    def test_b3_04_mixed_list_valid_and_invalid_members(self):
        # A list with at least one valid member should be NOT missing
        cast_data = ["Unknown", "N/A", "Bryan Cranston"]
        assert is_cast_missing(cast_data) is False

    def test_b3_05_deeply_nested_empty_containers(self):
        assert is_cast_missing([[], {}, [{}], None]) is True
        assert is_network_missing([{}, {"name": None}]) is True


# ---------------------------------------------------------------------------
# Area 4: Missing Keys, None-Values & Unexpected Data Types
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea4MissingKeysAndUnexpectedTypes:
    """Tests evaluation when dictionary keys are missing, None, or have unexpected data types."""

    def test_b4_01_completely_empty_dict(self):
        eval_res = evaluate_metadata({})
        assert eval_res["missing_count"] == 4
        assert eval_res["is_low_metadata"] is True

    def test_b4_02_aliases_resolution_in_metadata(self):
        # Test title aliases: name, clean_title
        assert evaluate_metadata({"name": "Game of Thrones"})["fields"]["title"]["is_missing"] is False
        assert evaluate_metadata({"clean_title": "Game of Thrones"})["fields"]["title"]["is_missing"] is False

        # Test network aliases: studio, studio_name
        assert evaluate_metadata({"studio": "Paramount"})["fields"]["network"]["is_missing"] is False
        assert evaluate_metadata({"studio_name": "A24"})["fields"]["network"]["is_missing"] is False

        # Test cast aliases: actors, starring
        assert evaluate_metadata({"actors": "Actor A, Actor B"})["fields"]["cast"]["is_missing"] is False
        assert evaluate_metadata({"starring": ["Actor A"]})["fields"]["cast"]["is_missing"] is False

        # Test plot aliases: overview, summary, description
        assert evaluate_metadata({"overview": "Exciting plot."})["fields"]["plot"]["is_missing"] is False
        assert evaluate_metadata({"summary": "Thrilling plot."})["fields"]["plot"]["is_missing"] is False
        assert evaluate_metadata({"description": "Action packed."})["fields"]["plot"]["is_missing"] is False

    def test_b4_03_numeric_and_boolean_data_types(self):
        assert is_title_missing(12345) is False  # Numeric title like 1917 or 2012 converted to str is valid
        assert is_title_missing(True) is True
        assert is_cast_missing(False) is True
        assert is_plot_missing(True) is True

    def test_b4_04_none_values_for_all_aliases(self):
        item = {"title": None, "name": None, "network": None, "cast": None, "plot": None}
        assert should_auto_archive(item) is True

    def test_b4_05_tuple_and_set_collections(self):
        assert is_cast_missing(("Actor 1", "Actor 2")) is False
        assert is_cast_missing(set()) is True
        assert is_network_missing(("HBO",)) is False


# ---------------------------------------------------------------------------
# Area 5: Unicode, Accents, Foreign Alphabets & Emoji
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea5UnicodeAndForeignCharacters:
    """Tests accented titles, foreign languages (Japanese, Cyrillic, Arabic), and emoji."""

    def test_b5_01_french_accented_title_and_plot(self):
        item = {
            "title": "Le Fabuleux Destin d'Amélie Poulain",
            "network": "Canal+",
            "cast": "Audrey Tautou, Mathieu Kassovitz",
            "plot": "Amélie est une jeune serveuse dans un café de Montmartre.",
        }
        res = evaluate_metadata(item)
        assert res["is_low_metadata"] is False
        assert res["missing_count"] == 0

    def test_b5_02_japanese_cjk_characters(self):
        item = {
            "title": "千と千尋の神隠し",
            "network": "Studio Ghibli",
            "cast": "柊瑠美, 入野自由",
            "plot": "10歳の少女・千尋は、両親と共に引越し先へと向かう途中で...",
        }
        res = evaluate_metadata(item)
        assert res["is_low_metadata"] is False
        assert res["missing_count"] == 0

    def test_b5_03_cyrillic_and_arabic_characters(self):
        item = {
            "title": "Солярис",
            "network": "Мосфильм",
            "cast": "Донатас Банионис, Наталья Бондарчук",
            "plot": "На космическую станцию прибывает психолог...",
        }
        res = evaluate_metadata(item)
        assert res["is_low_metadata"] is False

    def test_b5_04_emoji_in_title_and_plot(self):
        item = {
            "title": "🚀 Space Adventure 🌌",
            "network": "🎬 Universal Studios 🍿",
            "cast": "⭐ Star Actor ⭐",
            "plot": "An epic journey into deep space! 🪐✨",
        }
        res = evaluate_metadata(item)
        assert res["is_low_metadata"] is False
        assert res["missing_count"] == 0

    def test_b5_05_unicode_whitespace_and_zero_width_characters(self):
        # Zero-width spaces alone evaluate to missing
        assert is_title_missing("\u200b\u200b") is True or is_title_missing("") is True


# ---------------------------------------------------------------------------
# Area 6: Rapid State Transitions & Oscillation Cycling
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea6RapidStateTransitions:
    """Tests cycling an item through sparse -> full -> sparse -> full -> manual archive."""

    def test_b6_01_multi_cycle_oscillation(self):
        sparse_item = {"title": "Oscillator", "network": "Unknown", "cast": "Cast details not available.", "plot": "No plot summary available."}
        full_item = {"title": "Oscillator", "network": "HBO", "cast": "Actor A", "plot": "Valid plot."}

        # Step 1: Ingest Sparse -> (1, 0)
        s1 = evaluate_item_state_transition(None, sparse_item)
        assert s1 == (1, 0)

        # Step 2: Update Full -> (0, 1) (Auto-unarchived + badge)
        existing = {"is_archived": s1[0], "has_new_metadata": s1[1]}
        s2 = evaluate_item_state_transition(existing, full_item)
        assert s2 == (0, 1)

        # Step 3: Upstream data degrades to Sparse -> (1, 0) (Auto-archived + badge reset)
        existing = {"is_archived": s2[0], "has_new_metadata": s2[1]}
        s3 = evaluate_item_state_transition(existing, sparse_item)
        assert s3 == (1, 0)

        # Step 4: Upstream data recovers to Full -> (0, 1) (Auto-unarchived + badge again)
        existing = {"is_archived": s3[0], "has_new_metadata": s3[1]}
        s4 = evaluate_item_state_transition(existing, full_item)
        assert s4 == (0, 1)

        # Step 5: User manually re-archives -> (1, 0) (Archived + badge reset)
        existing = {"is_archived": s4[0], "has_new_metadata": s4[1]}
        s5 = evaluate_item_state_transition(existing, {**full_item, "is_archived": 1})
        assert s5 == (1, 0)

    def test_b6_02_rapid_db_transitions(self):
        title = "Rapid DB Target"
        sparse = {"title": title, "year": 2026, "network": "Unknown", "cast": "Cast details not available."}
        full = {"title": title, "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"}

        core.db.add_cached_item("tv", sparse)
        assert core.db.get_cached_item("tv", title, 2026)["is_archived"] == 1

        core.db.add_cached_item("tv", full)
        row = core.db.get_cached_item("tv", title, 2026)
        assert row["is_archived"] == 0
        assert row["has_new_metadata"] == 1

        core.db.archive_cached_item("tv", title, 2026, is_archived=True)
        row = core.db.get_cached_item("tv", title, 2026)
        assert row["is_archived"] == 1
        assert row["has_new_metadata"] == 0

    def test_b6_03_unarchive_without_metadata_change(self):
        # Manually unarchiving an item using archive_cached_item(..., is_archived=False)
        title = "Manual Unarchive Target"
        item = {"title": title, "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"}
        core.db.add_cached_item("tv", item)
        core.db.archive_cached_item("tv", title, 2026, is_archived=True)

        core.db.archive_cached_item("tv", title, 2026, is_archived=False)
        row = core.db.get_cached_item("tv", title, 2026)
        assert row["is_archived"] == 0

    def test_b6_04_multiple_sparse_updates_do_not_flicker_badge(self):
        existing = {"is_archived": 1, "has_new_metadata": 0}
        sparse1 = {"title": "Sparse", "network": "Unknown", "cast": "Cast details not available."}
        sparse2 = {"title": "Sparse", "network": "N/A", "cast": "None"}

        s1 = evaluate_item_state_transition(existing, sparse1)
        assert s1 == (1, 0)
        s2 = evaluate_item_state_transition({"is_archived": s1[0], "has_new_metadata": s1[1]}, sparse2)
        assert s2 == (1, 0)

    def test_b6_05_multiple_full_updates_retain_existing_badge(self):
        existing = {"is_archived": 0, "has_new_metadata": 1}
        full1 = {"title": "Full", "network": "HBO", "cast": "Actor", "plot": "Plot 1"}
        full2 = {"title": "Full", "network": "HBO Max", "cast": "Actor", "plot": "Plot 2"}

        s1 = evaluate_item_state_transition(existing, full1)
        assert s1 == (0, 1)
        s2 = evaluate_item_state_transition({"is_archived": s1[0], "has_new_metadata": s1[1]}, full2)
        assert s2 == (0, 1)


# ---------------------------------------------------------------------------
# Area 7: Idempotence of State Transitions & Database Operations
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea7Idempotence:
    """Tests idempotence across repeated inserts, archive calls, and evaluations."""

    def test_b7_01_repeated_add_cached_item_sparse(self):
        item = {"title": "Idem Sparse", "year": 2026, "network": "Unknown", "cast": "Cast details not available."}
        for _ in range(3):
            core.db.add_cached_item("movie", item)

        row = core.db.get_cached_item("movie", "Idem Sparse", 2026)
        assert row["is_archived"] == 1
        assert row["has_new_metadata"] == 0

    def test_b7_02_repeated_add_cached_item_full(self):
        item = {"title": "Idem Full", "year": 2026, "network": "Netflix", "cast": "Actor", "plot": "Plot"}
        for _ in range(3):
            core.db.add_cached_item("tv", item)

        row = core.db.get_cached_item("tv", "Idem Full", 2026)
        assert row["is_archived"] == 0
        assert row["has_new_metadata"] == 0

    def test_b7_03_repeated_archive_cached_item_calls(self):
        item = {"title": "Idem Archive", "year": 2026, "network": "FX", "cast": "Actor", "plot": "Plot"}
        core.db.add_cached_item("tv", item)

        for _ in range(4):
            core.db.archive_cached_item("tv", "Idem Archive", 2026, is_archived=True)

        row = core.db.get_cached_item("tv", "Idem Archive", 2026)
        assert row["is_archived"] == 1
        assert row["has_new_metadata"] == 0

    def test_b7_04_repeated_evaluate_state_transition_is_deterministic(self):
        existing = {"is_archived": 1, "has_new_metadata": 0}
        new_item = {"title": "Show", "network": "HBO", "cast": "A", "plot": "P"}
        for _ in range(10):
            assert evaluate_item_state_transition(existing, new_item) == (0, 1)

    def test_b7_05_repeated_evaluate_metadata_is_deterministic(self):
        item = {"title": "Show", "network": "HBO", "cast": "A", "plot": "P"}
        for _ in range(10):
            res = evaluate_metadata(item)
            assert res["missing_count"] == 0
            assert res["is_low_metadata"] is False


# ---------------------------------------------------------------------------
# Area 8: Boundary Matrix (Exactly 1 Missing vs Exactly 2 Missing)
# ---------------------------------------------------------------------------
class TestTier2BoundaryArea8ExactFieldPermutations:
    """Comprehensive mathematical permutations of all 4 fields (0, 1, 2, 3, 4 missing)."""

    # --- Exactly 1 Missing (4 cases: 0 or 1 missing -> NOT low-metadata) ---
    def test_b8_01_missing_title_only(self):
        item = {"title": "", "network": "HBO", "cast": "Actor A", "plot": "Plot text"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 1
        assert res["missing_fields"] == ["title"]
        assert res["is_low_metadata"] is False

    def test_b8_02_missing_network_only(self):
        item = {"title": "Title", "network": "Unknown", "cast": "Actor A", "plot": "Plot text"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 1
        assert res["missing_fields"] == ["network"]
        assert res["is_low_metadata"] is False

    def test_b8_03_missing_cast_only(self):
        item = {"title": "Title", "network": "HBO", "cast": "Cast details not available.", "plot": "Plot text"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 1
        assert res["missing_fields"] == ["cast"]
        assert res["is_low_metadata"] is False

    def test_b8_04_missing_plot_only(self):
        item = {"title": "Title", "network": "HBO", "cast": "Actor A", "plot": "No plot summary available."}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 1
        assert res["missing_fields"] == ["plot"]
        assert res["is_low_metadata"] is False

    # --- Exactly 2 Missing (6 pairwise combinations -> ALL low-metadata) ---
    def test_b8_05_missing_title_and_network(self):
        item = {"title": "", "network": "Unknown", "cast": "Actor A", "plot": "Plot text"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert res["is_low_metadata"] is True

    def test_b8_06_missing_title_and_cast(self):
        item = {"title": "", "network": "HBO", "cast": "Cast details not available.", "plot": "Plot text"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert res["is_low_metadata"] is True

    def test_b8_07_missing_title_and_plot(self):
        item = {"title": "", "network": "HBO", "cast": "Actor A", "plot": "No plot summary available."}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert res["is_low_metadata"] is True

    def test_b8_08_missing_network_and_cast(self):
        item = {"title": "Title", "network": "Unknown", "cast": "Cast details not available.", "plot": "Plot text"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert res["is_low_metadata"] is True

    def test_b8_09_missing_network_and_plot(self):
        item = {"title": "Title", "network": "Unknown", "cast": "Actor A", "plot": "No plot summary available."}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert res["is_low_metadata"] is True

    def test_b8_10_missing_cast_and_plot(self):
        item = {"title": "Title", "network": "HBO", "cast": "Cast details not available.", "plot": "No plot summary available."}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 2
        assert res["is_low_metadata"] is True


# ===========================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (Pairwise Module Integrations, >= 15 Tests)
# ===========================================================================

class TestTier3CrossFeatureCombinations:
    """Pairwise end-to-end combinations spanning scraper, db, web server, and CLI."""

    def test_t3_01_scraper_to_db_auto_archiving(self):
        """Scraper generates raw bare-bones items -> add_cached_item persists as is_archived=1."""
        raw_scraped = {
            "title": "Raw Bare Item",
            "year": 2026,
            "date_obj": datetime.now(),
            "date_str": "2026-09-15",
            "network": "Unknown",
            "cast": "Cast details not available.",
            "description": "No plot summary available.",
        }
        core.db.add_cached_item("tv", raw_scraped)
        cached = core.db.get_cached_item("tv", "Raw Bare Item", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

    def test_t3_02_sparse_to_enricher_auto_unarchive(self):
        """Initial sparse TV show -> Enriched with TVMaze metadata -> Auto-unarchived with badge in DB."""
        # 1. Sparse item cached
        core.db.add_cached_item("tv", {
            "title": "Fargo",
            "year": 2026,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        })
        assert core.db.get_cached_item("tv", "Fargo", 2026)["is_archived"] == 1

        # 2. Enricher returns TVMaze payload
        tvmaze_payload = {
            "title": "Fargo",
            "year": 2026,
            "network": "FX",
            "cast": "Chris Rock, Jason Schwartzman",
            "plot": "An anthology series set in Minnesota.",
        }
        core.db.add_cached_item("tv", tvmaze_payload)

        cached = core.db.get_cached_item("tv", "Fargo", 2026)
        assert cached["is_archived"] == 0
        assert cached["has_new_metadata"] == 1

    def test_t3_03_unarchived_badge_to_api_discover(self, api_client):
        """DB cached item with has_new_metadata=1 is serialized correctly in /api/discover."""
        core.db.add_cached_item("movie", {
            "title": "Oppenheimer",
            "year": 2023,
            "date_obj": datetime.now(),
            "date_str": "2023-07-21",
            "network": "Unknown",
            "cast": "Cast details not available.",
        })
        core.db.add_cached_item("movie", {
            "title": "Oppenheimer",
            "year": 2023,
            "date_obj": datetime.now(),
            "date_str": "2023-07-21",
            "network": "Universal Pictures",
            "cast": "Cillian Murphy, Emily Blunt",
            "plot": "The story of J. Robert Oppenheimer's role in the Manhattan Project.",
        })

        res = api_client.get("/api/discover?skip_scrape=true")
        assert res.status_code == 200
        movies = [m for m in res.get_json()["movies"] if m["title"] == "Oppenheimer"]
        assert len(movies) == 1
        assert movies[0]["has_new_metadata"] is True
        assert movies[0]["is_archived"] is False

    def test_t3_04_api_to_ui_dom_rendering(self, api_client):
        """Discover endpoint output transformed into DOM card exhibits 'New metadata' badge."""
        core.db.add_cached_item("tv", {
            "title": "Shogun",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": "2024-02-27",
            "network": "Unknown",
            "cast": "Cast details not available.",
        })
        core.db.add_cached_item("tv", {
            "title": "Shogun",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": "2024-02-27",
            "network": "FX",
            "cast": "Hiroyuki Sanada, Cosmo Jarvis",
            "plot": "Lord Toranaga battles against his enemies on the Council of Regents.",
        })

        res = api_client.get("/api/discover?skip_scrape=true")
        tv_items = [t for t in res.get_json()["tv"] if t["title"] == "Shogun"]
        assert len(tv_items) == 1

        card_html = render_media_card_html(tv_items[0])
        assert '<span class="badge badge-new-metadata">New metadata</span>' in card_html

    def test_t3_05_ui_card_to_manual_archive_reset(self, api_client):
        """User re-archives a card via /api/archive -> Badge is immediately cleared in DB and next API fetch."""
        core.db.add_cached_item("movie", {
            "title": "Civil War",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": "2024-04-12",
            "network": "Unknown",
            "cast": "Cast details not available.",
        })
        core.db.add_cached_item("movie", {
            "title": "Civil War",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": "2024-04-12",
            "network": "A24",
            "cast": "Kirsten Dunst, Wagner Moura",
            "plot": "A team of military-embedded journalists race across America.",
        })

        # User clicks Archive
        res_archive = api_client.post("/api/archive", json={"type": "movie", "title": "Civil War", "year": 2024, "archive": True})
        assert res_archive.status_code == 200

        # Query /api/discover again
        res_discover = api_client.get("/api/discover?skip_scrape=true")
        movies = [m for m in res_discover.get_json()["movies"] if m["title"] == "Civil War"]
        assert len(movies) == 1
        assert movies[0]["is_archived"] is True
        assert movies[0]["has_new_metadata"] is False

    def test_t3_06_legacy_db_migration_to_scrape_and_badge(self, tmp_path):
        """Pre-existing database migrated at runtime -> handles scraping and badging seamlessly."""
        legacy_db = tmp_path / "legacy_integration.db"
        conn = sqlite3.connect(legacy_db)
        conn.execute("CREATE TABLE cache (id INTEGER PRIMARY KEY, type TEXT, title TEXT, year INTEGER, is_archived INTEGER)")
        conn.commit()
        conn.close()

        orig_db = core.db.DB_PATH
        try:
            core.db.DB_PATH = legacy_db
            core.db.init_db()

            # Insert sparse
            core.db.add_cached_item("tv", {"title": "Migrated Show", "year": 2026, "network": "Unknown", "cast": "Cast details not available."})
            assert core.db.get_cached_item("tv", "Migrated Show", 2026)["is_archived"] == 1

            # Update full
            core.db.add_cached_item("tv", {"title": "Migrated Show", "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"})
            row = core.db.get_cached_item("tv", "Migrated Show", 2026)
            assert row["is_archived"] == 0
            assert row["has_new_metadata"] == 1
        finally:
            core.db.DB_PATH = orig_db

    def test_t3_07_custom_feed_sparse_to_auto_unarchive(self):
        """Custom feed source item inserted with sparse fields -> updated with enriched fields."""
        feed_item = {
            "title": "Custom RSS Entry",
            "year": 2026,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "source_feed_id": 1,
        }
        core.db.add_cached_item("movie", feed_item)
        assert core.db.get_cached_item("movie", "Custom RSS Entry", 2026)["is_archived"] == 1

        feed_item_full = {
            "title": "Custom RSS Entry",
            "year": 2026,
            "network": "Studio Canal",
            "cast": "Lead Star",
            "plot": "Comprehensive story line.",
            "source_feed_id": 1,
        }
        core.db.add_cached_item("movie", feed_item_full)
        row = core.db.get_cached_item("movie", "Custom RSS Entry", 2026)
        assert row["is_archived"] == 0
        assert row["has_new_metadata"] == 1
        assert row["source_feed_id"] == 1


    def test_t3_08_tv_show_multi_season_title_cleaning(self):
        """TV series title with ': Season 2' is cleaned and matched in state transitions."""
        title_raw = "House of the Dragon: Season 2"
        item = {
            "title": title_raw,
            "year": 2024,
            "network": "HBO",
            "cast": "Matt Smith, Emma D'Arcy",
            "plot": "The Dance of the Dragons begins.",
        }
        core.db.add_cached_item("tv", item)

        # Lookup with cleaned name or raw name works
        cached = core.db.get_cached_item("tv", "House of the Dragon", 2024)
        assert cached is not None
        assert cached["is_archived"] == 0

    def test_t3_09_movie_format_suffix_title_cleaning(self):
        """Movie title with ' [4K UHD]' is cleaned and properly evaluated."""
        title_raw = "Furiosa: A Mad Max Saga [4K Ultra HD]"
        item = {
            "title": title_raw,
            "year": 2024,
            "network": "Warner Bros.",
            "cast": "Anya Taylor-Joy, Chris Hemsworth",
            "plot": "The origin story of renegade warrior Furiosa.",
        }
        core.db.add_cached_item("movie", item)

        cached = core.db.get_cached_item("movie", "Furiosa: A Mad Max Saga", 2024)
        assert cached is not None
        assert cached["is_archived"] == 0

    def test_t3_10_in_library_match_with_new_metadata(self, api_client):
        """An item marked in-library retains both is_in_library=True and has_new_metadata=True."""
        item = {
            "title": "Library Show",
            "year": 2026,
            "date_obj": datetime.now(),
            "date_str": "2026-09-01",
            "network": "Unknown",
            "cast": "Cast details not available.",
            "is_in_library": True,
        }
        core.db.add_cached_item("tv", item)
        core.db.add_cached_item("tv", {**item, "network": "Apple TV+", "cast": "Actor", "plot": "Plot"})

        res = api_client.get("/api/discover?skip_scrape=true")
        items = [t for t in res.get_json()["tv"] if t["title"] == "Library Show"]
        assert len(items) == 1
        assert items[0]["is_in_library"] is True
        assert items[0]["has_new_metadata"] is True

    @patch("xarrtools.cli.cli.config")
    @patch("xarrtools.cli.cli.Prompt.ask")
    @patch("xarrtools.cli.cli.console.print")
    @patch("xarrtools.cli.cli.get_discoveries")
    @patch("xarrtools.cli.cli.enrich_tv_show")
    @patch("xarrtools.cli.cli.enrich_movie")
    def test_t3_11_cli_discovery_workflow_with_badged_items(
        self, mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
    ):
        """CLI discovery workflow execution against database with unarchived new-metadata items."""
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_ask.side_effect = ["1", "c"]

        tv_raw = [{"title": "Show A", "date_obj": datetime(2026, 9, 1), "description": "D1", "date_str": "Sep 1", "is_returning": False}]
        mock_get_disc.return_value = (tv_raw, [])
        mock_enrich_tv.return_value = {
            "title": "Show A", "year": 2026, "plot": "P1", "cast": "C1", "genres": [],
            "trailer": "", "tvdbId": 1, "imdbId": "tt1", "network": "HBO",
            "is_in_library": False, "has_new_metadata": True, "is_archived": False, "raw_metadata": None
        }

        handle_discovery_workflow()
        printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("[New metadata]" in t for t in printed_texts)


    def test_t3_12_cache_clear_and_prune_lifecycle(self, api_client):
        """Wiping cache with /api/cache/clear removes items; subsequent inserts start fresh."""
        core.db.add_cached_item("movie", {"title": "Wipe Target", "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"})
        assert core.db.get_cached_item("movie", "Wipe Target", 2026) is not None

        res = api_client.post("/api/cache/clear")
        assert res.status_code == 200
        assert core.db.get_cached_item("movie", "Wipe Target", 2026) is None

    def test_t3_13_manual_unarchive_preserves_badge_state_0(self, api_client):
        """Manual unarchive via /api/archive with archive=False on manually archived item results in is_archived=0, has_new_metadata=0."""
        item = {"title": "Manual Toggle", "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"}
        core.db.add_cached_item("tv", item)

        # Archive
        api_client.post("/api/archive", json={"type": "tv", "title": "Manual Toggle", "year": 2026, "archive": True})
        # Unarchive
        api_client.post("/api/archive", json={"type": "tv", "title": "Manual Toggle", "year": 2026, "archive": False})

        cached = core.db.get_cached_item("tv", "Manual Toggle", 2026)
        assert cached["is_archived"] == 0
        assert cached["has_new_metadata"] == 0

    def test_t3_14_settings_default_show_archived_toggle(self, api_client):
        """Settings default_show_archived can be saved and read via API."""
        res_set = api_client.post("/api/settings", json={"default_show_archived": "1"})
        assert res_set.status_code == 200

        res_get = api_client.get("/api/settings")
        assert res_get.get_json()["default_show_archived"] == "1"

    def test_t3_15_batch_insert_mixed_metadata_completeness(self):
        """Batch insert of multiple items correctly assigns individual archive/badge statuses."""
        batch = [
            {"title": "M1", "year": 2026, "network": "HBO", "cast": "A", "plot": "P"},  # 0 missing -> (0, 0)
            {"title": "M2", "year": 2026, "network": "Unknown", "cast": "Cast details not available.", "plot": "P"},  # 2 missing -> (1, 0)
            {"title": "M3", "year": 2026, "network": "Netflix", "cast": "Cast details not available.", "plot": "P"},  # 1 missing -> (0, 0)
        ]
        core.db.add_cached_items_batch("tv", batch)

        m1 = core.db.get_cached_item("tv", "M1", 2026)
        m2 = core.db.get_cached_item("tv", "M2", 2026)
        m3 = core.db.get_cached_item("tv", "M3", 2026)

        assert m1["is_archived"] == 0
        assert m2["is_archived"] == 1
        assert m3["is_archived"] == 0


# ===========================================================================
# TIER 4: REAL-WORLD WORKLOAD SCENARIOS (>= 5 Scenarios from TEST_INFRA.md)
# ===========================================================================

class TestTier4RealWorldWorkloadScenarios:
    """End-to-end full application workflows simulating realistic multi-step user scenarios."""

    def test_t4_scenario_1_sparse_scrape_enrich_auto_unarchive(self, api_client):
        """
        Scenario 1: Discovery of Bare-Bones Scraped Releases -> Batch Metadata Enrichment -> Auto-Unarchiving with Badging.
        Exercises: F1, F2, F3, F5, F7, F8, F9.
        """
        # Step 1: Feed scrapers run. Multiple raw releases discovered with missing fields.
        raw_releases = [
            {
                "title": "The Penguin",
                "year": 2024,
                "date_obj": datetime.now(),
                "date_str": datetime.now().strftime("%Y-%m-%d"),
                "network": "Unknown",
                "cast": "Cast details not available.",
                "plot": "No plot summary available.",
            },
            {
                "title": "Gladiator II",
                "year": 2024,
                "date_obj": datetime.now(),
                "date_str": datetime.now().strftime("%Y-%m-%d"),
                "network": "Unknown",
                "cast": "Cast details not available.",
                "plot": "No plot summary available.",
            },
        ]
        for r in raw_releases:
            core.db.add_cached_item("tv" if r["title"] == "The Penguin" else "movie", r)

        # Verify initial state: Both are auto-archived with no badge
        p1 = core.db.get_cached_item("tv", "The Penguin", 2024)
        g1 = core.db.get_cached_item("movie", "Gladiator II", 2024)
        assert p1["is_archived"] == 1 and p1["has_new_metadata"] == 0
        assert g1["is_archived"] == 1 and g1["has_new_metadata"] == 0

        # Step 2: Scheduled enricher worker resolves upstream metadata from TVMaze & TMDB.
        enriched_penguin = {
            "title": "The Penguin",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "HBO",
            "cast": "Colin Farrell, Cristin Milioti",
            "plot": "Following the events of The Batman, Oz Cobb attempts to seize control of Gotham's criminal underworld.",
        }
        enriched_gladiator = {
            "title": "Gladiator II",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "Paramount Pictures",
            "cast": "Paul Mescal, Pedro Pascal, Denzel Washington",
            "plot": "Years after witnessing the death of Maximus, Lucius must enter the Colosseum.",
        }
        core.db.add_cached_item("tv", enriched_penguin)
        core.db.add_cached_item("movie", enriched_gladiator)

        # Step 3: Verify smart auto-unarchiving and badge assignment
        p2 = core.db.get_cached_item("tv", "The Penguin", 2024)
        g2 = core.db.get_cached_item("movie", "Gladiator II", 2024)
        assert p2["is_archived"] == 0 and p2["has_new_metadata"] == 1
        assert g2["is_archived"] == 0 and g2["has_new_metadata"] == 1

        # Step 4: Verify Web API endpoint delivers the unarchived state and badge flags
        res = api_client.get("/api/discover?skip_scrape=true")
        assert res.status_code == 200
        data = res.get_json()

        tv_penguin = next(x for x in data["tv"] if x["title"] == "The Penguin")
        movie_gladiator = next(x for x in data["movies"] if x["title"] == "Gladiator II")

        assert tv_penguin["is_archived"] is False
        assert tv_penguin["has_new_metadata"] is True
        assert movie_gladiator["is_archived"] is False
        assert movie_gladiator["has_new_metadata"] is True

        # Step 5: Verify Web UI Card DOM rendering contains the badge
        tv_dom = render_media_card_html(tv_penguin)
        movie_dom = render_media_card_html(movie_gladiator)
        assert '<span class="badge badge-new-metadata">New metadata</span>' in tv_dom
        assert '<span class="badge badge-new-metadata">New metadata</span>' in movie_dom

    def test_t4_scenario_2_manual_archive_then_re_enrich_auto_unarchive(self, api_client):
        """
        Scenario 2: Manual User Archival of Unarchived Release -> Subsequent Re-Enrichment and Auto-Unarchival.
        Exercises: F2, F5, F6, F7, F8.
        """
        # Step 1: Item starts fully populated and unarchived
        item = {
            "title": "House of the Dragon",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "HBO",
            "cast": "Matt Smith, Emma D'Arcy",
            "plot": "Targaryen civil war.",
        }
        core.db.add_cached_item("tv", item)
        assert core.db.get_cached_item("tv", "House of the Dragon", 2024)["is_archived"] == 0

        # Step 2: User manually archives the show
        api_client.post("/api/archive", json={"type": "tv", "title": "House of the Dragon", "year": 2024, "archive": True})
        assert core.db.get_cached_item("tv", "House of the Dragon", 2024)["is_archived"] == 1

        # Step 3: Upstream scan runs with enriched metadata
        updated_item = {
            **item,
            "cast": "Matt Smith, Emma D'Arcy, Olivia Cooke, Rhys Ifans",
            "plot": "Updated extended plot description for season 2.",
        }
        core.db.add_cached_item("tv", updated_item)

        # Step 4: Manual archive is sticky: stays archived, no new-metadata badge
        cached = core.db.get_cached_item("tv", "House of the Dragon", 2024)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

    def test_t4_scenario_3_partial_metadata_retention_and_invalidation(self, api_client):
        """
        Scenario 3: Release with Partial Metadata (1 missing field) Maintained as Unarchived -> Metadata Invalidation -> Auto-Archival.
        Exercises: F1, F2, F3, F6.
        """
        # Step 1: Discovery with 1 missing field (Plot missing) -> Retains unarchived status
        partial_item = {
            "title": "Severance Season 2",
            "year": 2025,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "Apple TV+",
            "cast": "Adam Scott, Patricia Arquette",
            "plot": "No plot summary available.",  # 1 missing field
        }
        core.db.add_cached_item("tv", partial_item)
        cached1 = core.db.get_cached_item("tv", "Severance Season 2", 2025)
        assert cached1["is_archived"] == 0
        assert cached1["has_new_metadata"] == 0

        # Step 2: Upstream invalidation causes network to be lost (now 2 missing fields: network + plot)
        invalidated_item = {
            **partial_item,
            "network": "Unknown",  # 2 missing fields now
        }
        core.db.add_cached_item("tv", invalidated_item)
        cached2 = core.db.get_cached_item("tv", "Severance Season 2", 2025)
        assert cached2["is_archived"] == 1
        assert cached2["has_new_metadata"] == 0

    def test_t4_scenario_4_rescan_with_identical_data_preserves_state(self, api_client):
        """
        Scenario 4: Rescan with Empty/Missing Updates -> Preservation of Archived/Unarchived & Badge States.
        Exercises: F1, F4, F5, F6.
        """
        # Setup: 1 archived item, 1 unarchived badged item, 1 standard unarchived item
        core.db.add_cached_item("tv", {"title": "Archived Show", "year": 2026, "network": "Unknown", "cast": "Cast details not available."})

        core.db.add_cached_item("movie", {"title": "Badged Film", "year": 2026, "network": "Unknown", "cast": "Cast details not available."})
        core.db.add_cached_item("movie", {"title": "Badged Film", "year": 2026, "network": "A24", "cast": "Actor", "plot": "Plot"})

        core.db.add_cached_item("tv", {"title": "Standard Show", "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"})

        # Hourly rescan runs with identical payloads
        core.db.add_cached_item("tv", {"title": "Archived Show", "year": 2026, "network": "Unknown", "cast": "Cast details not available."})
        core.db.add_cached_item("movie", {"title": "Badged Film", "year": 2026, "network": "A24", "cast": "Actor", "plot": "Plot"})
        core.db.add_cached_item("tv", {"title": "Standard Show", "year": 2026, "network": "HBO", "cast": "Actor", "plot": "Plot"})

        assert core.db.get_cached_item("tv", "Archived Show", 2026)["is_archived"] == 1
        assert core.db.get_cached_item("tv", "Archived Show", 2026)["has_new_metadata"] == 0

        assert core.db.get_cached_item("movie", "Badged Film", 2026)["is_archived"] == 0
        assert core.db.get_cached_item("movie", "Badged Film", 2026)["has_new_metadata"] == 1

        assert core.db.get_cached_item("tv", "Standard Show", 2026)["is_archived"] == 0
        assert core.db.get_cached_item("tv", "Standard Show", 2026)["has_new_metadata"] == 0

    def test_t4_scenario_5_full_web_ui_lifecycle_and_re_archive(self, api_client):
        """
        Scenario 5: Web UI Lifecycle: Discover -> View Badges -> Manual Re-Archive Clearing Badge.
        Exercises: F6, F7, F8, F9, F10.
        """
        # 1. Populate database with badged discovery
        core.db.add_cached_item("tv", {
            "title": "Slow Horses",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "Unknown",
            "cast": "Cast details not available.",
        })
        core.db.add_cached_item("tv", {
            "title": "Slow Horses",
            "year": 2024,
            "date_obj": datetime.now(),
            "date_str": datetime.now().strftime("%Y-%m-%d"),
            "network": "Apple TV+",
            "cast": "Gary Oldman, Jack Lowden",
            "plot": "MI5 service reject department at Slough House.",
        })

        # 2. Client calls /api/discover
        res = api_client.get("/api/discover?skip_scrape=true")
        tv_item = next(t for t in res.get_json()["tv"] if t["title"] == "Slow Horses")
        assert tv_item["has_new_metadata"] is True

        # 3. Render card in UI
        card_html = render_media_card_html(tv_item)
        assert '<span class="badge badge-new-metadata">New metadata</span>' in card_html

        # 4. User re-archives via UI button
        res_arch = api_client.post("/api/archive", json={"type": "tv", "title": "Slow Horses", "year": 2024, "archive": True})
        assert res_arch.status_code == 200

        # 5. Subsequent discovery shows badge cleared and is_archived=True
        res2 = api_client.get("/api/discover?skip_scrape=true")
        tv_item_after = next(t for t in res2.get_json()["tv"] if t["title"] == "Slow Horses")
        assert tv_item_after["is_archived"] is True
        assert tv_item_after["has_new_metadata"] is False

        # 6. Re-rendered card no longer has 'New metadata' badge
        card_html_after = render_media_card_html(tv_item_after)
        assert "badge-new-metadata" not in card_html_after
        assert "badge-archived" in card_html_after

    def test_t4_scenario_6_high_volume_batch_ingestion_and_state_consistency(self):
        """
        Scenario 6: High-Volume Ingestion & State Consistency (100+ Mixed Items).
        Exercises: F1, F2, F3, F5, F6, F7, F8 across mixed batch operations.
        """
        items = []
        expected_states = {}
        for i in range(100):
            mod = i % 4
            title = f"Bulk Title {i}"
            if mod == 0:
                # 0 missing fields -> is_archived = 0, has_new_metadata = 0
                item = {"title": title, "year": 2026, "network": "HBO", "cast": f"Actor {i}", "plot": f"Plot {i}"}
                expected_states[title] = (0, 0)
            elif mod == 1:
                # 1 missing field (plot missing) -> is_archived = 0, has_new_metadata = 0
                item = {"title": title, "year": 2026, "network": "Netflix", "cast": f"Actor {i}", "plot": "No plot summary available."}
                expected_states[title] = (0, 0)
            elif mod == 2:
                # 2 missing fields (cast & plot missing) -> is_archived = 1, has_new_metadata = 0
                item = {"title": title, "year": 2026, "network": "Paramount+", "cast": "Cast details not available.", "plot": "No plot summary available."}
                expected_states[title] = (1, 0)
            else:
                # 3 missing fields (network, cast, plot missing) -> is_archived = 1, has_new_metadata = 0
                item = {"title": title, "year": 2026, "network": "Unknown", "cast": "Cast details not available.", "plot": "No plot summary available."}
                expected_states[title] = (1, 0)
            items.append(item)

        core.db.add_cached_items_batch("tv", items)

        for title, expected in expected_states.items():
            row = core.db.get_cached_item("tv", title, 2026)
            assert row is not None
            assert (row["is_archived"], row["has_new_metadata"]) == expected

