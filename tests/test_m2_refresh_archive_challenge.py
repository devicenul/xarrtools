"""
tests/test_m2_refresh_archive_challenge.py
-------------------------------------------
Milestone 2 Challenger Adversarial Stress Test Suite:
1. Combinatorial state transition testing for `POST /api/cache/refresh` across all 16 core metadata permutations.
2. Verification of Auto-Unarchiving with `is_archived: False, has_new_metadata: True` on metadata enrichment.
3. Verification of Low-Metadata Retention `is_archived: True, has_new_metadata: False` when refreshed data remains low.
4. Verification of Badge Preservation `has_new_metadata: True` when refreshing already-badged unarchived items.
5. Exhaustive testing of `POST /api/archive`:
   - Archiving an item with `has_new_metadata: True` resets `has_new_metadata` to `False` in DB and subsequent API calls.
   - Manual un-archiving with `archive: False` maintains `has_new_metadata: False`.
   - Archiving skeleton vs raw_item entries.
6. Full multi-step lifecycle simulation loops (Ingest -> Auto-Archive -> Live Refresh -> Auto-Unarchive -> Re-Archive -> Reset).
7. Boundary sentinels, whitespace fuzzing, string variations.
8. Concurrent multi-threaded persistence & archiving stress harness.
"""

import os
import json
import tempfile
import itertools
import threading
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest

# Isolate the database path for this test module
import core.db
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

from core.config import config
from core.metadata import evaluate_metadata, should_auto_archive
from web.server import app


@pytest.fixture(autouse=True)
def cleanup_db():
    """Wipes test database tables between test cases for fast, isolated execution."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()

    core.db.init_db()
    core.db.set_setting("api_key", "test_key_m2_challenge")
    config.refresh()
    yield


@pytest.fixture
def auth_client():
    """Authenticated Flask test client wrapper."""
    app.config["TESTING"] = True
    core.db.set_setting("api_key", "test_key_m2_challenge")
    config.refresh()

    class AuthenticatedTestClient:
        def __init__(self, client):
            self._client = client

        def get(self, *args, **kwargs):
            return self._client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_key_m2_challenge"
            kwargs["headers"] = headers
            return self._client.post(*args, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_key_m2_challenge"
            kwargs["headers"] = headers
            return self._client.put(*args, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_key_m2_challenge"
            kwargs["headers"] = headers
            return self._client.delete(*args, **kwargs)

    with app.test_client() as client:
        yield AuthenticatedTestClient(client)


# ===========================================================================
# 1. Exhaustive Combinatorial Matrix for POST /api/cache/refresh (16 permutations)
# ===========================================================================

CORE_FIELD_SAMPLES = {
    "title": {"valid": "Foundation", "missing": "Unknown"},
    "network": {"valid": "Apple TV+", "missing": "Unknown Network"},
    "cast": {"valid": "Lee Pace, Jared Harris", "missing": "Cast details not available."},
    "plot": {"valid": "A complex saga of humans scattered on planets.", "missing": "No plot summary available."},
}

@pytest.mark.parametrize("has_title, has_network, has_cast, has_plot", list(
    itertools.product([True, False], [True, False], [True, False], [True, False])
))
@pytest.mark.parametrize("media_type", ["tv", "movie"])
def test_cache_refresh_combinatorial_matrix_from_archived(
    auth_client, media_type, has_title, has_network, has_cast, has_plot
):
    """
    Tests refreshing an initially archived item across all 16 core field permutations.
    If missing < 2 -> item MUST auto-unarchive: is_archived=False, has_new_metadata=True.
    If missing >= 2 -> item MUST stay archived: is_archived=True, has_new_metadata=False.
    """
    title_seed = f"Comb Test {media_type} {has_title}_{has_network}_{has_cast}_{has_plot}"
    imdb_id = f"tt_{media_type}_{int(has_title)}_{int(has_network)}_{int(has_cast)}_{int(has_plot)}"
    year = 2026
    current_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Seed item as auto-archived with low metadata
    core.db.add_cached_item(media_type, {
        "title": title_seed,
        "year": year,
        "imdbId": imdb_id,
        "plot": "No plot summary available.",
        "cast": "Cast details not available.",
        "network": "Unknown",
        "is_archived": True,
        "is_in_library": False,
        "date_str": current_date,
        "date_obj": current_date
    })

    # Prepare refreshed metadata
    refreshed_payload = {
        "title": title_seed if has_title else "Unknown",
        "year": year,
        "imdbId": imdb_id,
        "network": CORE_FIELD_SAMPLES["network"]["valid"] if has_network else CORE_FIELD_SAMPLES["network"]["missing"],
        "cast": CORE_FIELD_SAMPLES["cast"]["valid"] if has_cast else CORE_FIELD_SAMPLES["cast"]["missing"],
        "plot": CORE_FIELD_SAMPLES["plot"]["valid"] if has_plot else CORE_FIELD_SAMPLES["plot"]["missing"],
        "genres": ["Drama", "Sci-Fi"],
        "poster_url": "http://img.jpg",
        "trailer": "http://trailer.com",
    }
    if media_type == "tv":
        refreshed_payload["tvdbId"] = 12345
    else:
        refreshed_payload["tmdbId"] = 67890

    eval_result = evaluate_metadata(refreshed_payload)
    expected_low = eval_result["is_low_metadata"]
    expected_archived = expected_low
    expected_has_new_metadata = not expected_low  # was archived, so if not low now -> True

    with patch("web.server.get_clients", return_value=(None, None)), \
         patch("web.server.enrich_tv_show", return_value=refreshed_payload), \
         patch("web.server.enrich_movie", return_value=refreshed_payload):

        res = auth_client.post("/api/cache/refresh", json={
            "type": media_type,
            "title": title_seed,
            "year": year,
            "imdbId": imdb_id
        })

        assert res.status_code == 200
        item = res.get_json()["item"]
        assert item["is_archived"] is expected_archived
        assert item["has_new_metadata"] is expected_has_new_metadata

        # Verify DB directly
        cached = core.db.get_cached_item(media_type, title_seed, year, imdb_id)
        assert cached is not None
        assert bool(cached["is_archived"]) is expected_archived
        assert bool(cached.get("has_new_metadata", 0)) is expected_has_new_metadata

        # Verify discover endpoint returns consistent state
        disc_res = auth_client.get("/api/discover?skip_scrape=true")
        assert disc_res.status_code == 200
        disc_items = disc_res.get_json()[media_type if media_type == "tv" else "movies"]
        matching = [i for i in disc_items if i.get("imdbId") == imdb_id or i["title"] in [title_seed, "Unknown"]]
        assert len(matching) >= 1
        assert matching[0]["is_archived"] is expected_archived
        assert matching[0]["has_new_metadata"] is expected_has_new_metadata


# ===========================================================================
# 2. Refresh on Unarchived Items (Badge Preservation vs Demotion)
# ===========================================================================

def test_cache_refresh_preserves_new_metadata_badge_on_rich_update(auth_client):
    """
    Refreshing an unarchived item that ALREADY has has_new_metadata=True
    with rich metadata MUST PRESERVE has_new_metadata=True.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    for media_type in ["tv", "movie"]:
        title = f"Badge Preservation Show {media_type}"
        year = 2026

        # Seed item with badge = 1, is_archived = 0
        core.db.add_cached_item(media_type, {
            "title": title,
            "year": year,
            "plot": "Original rich plot",
            "cast": "Actor One",
            "network": "HBO Max",
            "is_archived": False,
            "date_str": current_date,
            "date_obj": current_date
        })
        conn = core.db.get_db_connection()
        conn.execute("UPDATE cache SET has_new_metadata = 1, is_archived = 0 WHERE title = ?", (title,))
        conn.commit()
        conn.close()

        refreshed = {
            "title": title,
            "year": year,
            "plot": "Updated even better plot summary",
            "cast": "Actor One, Actor Two",
            "network": "Max",
            "genres": ["Drama"],
            "poster_url": "http://poster.jpg",
            "trailer": "http://trailer.com",
            "tvdbId" if media_type == "tv" else "tmdbId": 9999,
            "imdbId": "tt9999"
        }

        with patch("web.server.get_clients", return_value=(None, None)), \
             patch("web.server.enrich_tv_show", return_value=refreshed), \
             patch("web.server.enrich_movie", return_value=refreshed):

            res = auth_client.post("/api/cache/refresh", json={
                "type": media_type,
                "title": title,
                "year": year
            })
            assert res.status_code == 200
            data = res.get_json()["item"]
            assert data["is_archived"] is False
            assert data["has_new_metadata"] is True

            cached = core.db.get_cached_item(media_type, title, year)
            assert bool(cached["is_archived"]) is False
            assert bool(cached["has_new_metadata"]) is True


def test_cache_refresh_demotes_unarchived_to_archived_if_metadata_degrades(auth_client):
    """
    If an unarchived item (with or without badge) is refreshed and the live API returns
    degraded data (>= 2 missing core fields), it MUST be auto-archived and badge reset.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    for media_type in ["tv", "movie"]:
        title = f"Degrading Item {media_type}"
        year = 2026

        # Seed item unarchived with badge
        core.db.add_cached_item(media_type, {
            "title": title,
            "year": year,
            "plot": "Original plot",
            "cast": "Actor",
            "network": "Netflix",
            "is_archived": False,
            "date_str": current_date,
            "date_obj": current_date
        })
        conn = core.db.get_db_connection()
        conn.execute("UPDATE cache SET has_new_metadata = 1, is_archived = 0 WHERE title = ?", (title,))
        conn.commit()
        conn.close()

        # Upstream returns degraded metadata (empty plot, unknown network)
        degraded = {
            "title": title,
            "year": year,
            "plot": "No plot summary available.",
            "cast": "Cast details not available.",
            "network": "Unknown",
            "genres": [],
        }

        with patch("web.server.get_clients", return_value=(None, None)), \
             patch("web.server.enrich_tv_show", return_value=degraded), \
             patch("web.server.enrich_movie", return_value=degraded):

            res = auth_client.post("/api/cache/refresh", json={
                "type": media_type,
                "title": title,
                "year": year
            })
            assert res.status_code == 200
            data = res.get_json()["item"]
            assert data["is_archived"] is True
            assert data["has_new_metadata"] is False

            cached = core.db.get_cached_item(media_type, title, year)
            assert cached["is_archived"] == 1
            assert cached["has_new_metadata"] == 0


def test_cache_refresh_unarchived_without_badge_remains_unarchived_without_badge(auth_client):
    """
    An unarchived item with has_new_metadata=False refreshed with rich metadata
    remains is_archived=False, has_new_metadata=False.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    for media_type in ["tv", "movie"]:
        title = f"Standard Show {media_type}"
        year = 2026

        core.db.add_cached_item(media_type, {
            "title": title,
            "year": year,
            "plot": "Good plot",
            "cast": "Good cast",
            "network": "Hulu",
            "is_archived": False,
            "date_str": current_date,
            "date_obj": current_date
        })

        rich_update = {
            "title": title,
            "year": year,
            "plot": "Updated good plot",
            "cast": "Good cast",
            "network": "Hulu",
            "genres": ["Comedy"]
        }

        with patch("web.server.get_clients", return_value=(None, None)), \
             patch("web.server.enrich_tv_show", return_value=rich_update), \
             patch("web.server.enrich_movie", return_value=rich_update):

            res = auth_client.post("/api/cache/refresh", json={
                "type": media_type,
                "title": title,
                "year": year
            })
            assert res.status_code == 200
            data = res.get_json()["item"]
            assert data["is_archived"] is False
            assert data["has_new_metadata"] is False

            cached = core.db.get_cached_item(media_type, title, year)
            assert cached["is_archived"] == 0
            assert cached["has_new_metadata"] == 0


# ===========================================================================
# 3. POST /api/archive Stress Testing & Badge Reset Verification
# ===========================================================================

def test_api_archive_resets_has_new_metadata_in_db_and_subsequent_apis(auth_client):
    """
    Stress test POST /api/archive:
    1. Seed an item that was smart-unarchived (has_new_metadata=1, is_archived=0).
    2. Verify GET /api/discover returns has_new_metadata=True.
    3. Call POST /api/archive with archive=True.
    4. Assert DB column has_new_metadata is reset to 0, is_archived = 1.
    5. Call GET /api/discover?skip_scrape=true and assert has_new_metadata=False, is_archived=True.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    for media_type in ["tv", "movie"]:
        title = f"Archive Reset Target {media_type}"
        year = 2026

        core.db.add_cached_item(media_type, {
            "title": title,
            "year": year,
            "plot": "Rich plot synopsis.",
            "cast": "Main Actor",
            "network": "FX",
            "is_archived": False,
            "date_str": current_date,
            "date_obj": current_date
        })
        conn = core.db.get_db_connection()
        conn.execute("UPDATE cache SET has_new_metadata = 1, is_archived = 0 WHERE title = ?", (title,))
        conn.commit()
        conn.close()

        # Step 2: verify discover returns has_new_metadata=True before archive
        res_before = auth_client.get("/api/discover?skip_scrape=true")
        assert res_before.status_code == 200
        items_before = res_before.get_json()[media_type if media_type == "tv" else "movies"]
        item_before = [i for i in items_before if i["title"] == title][0]
        assert item_before["has_new_metadata"] is True
        assert item_before["is_archived"] is False

        # Step 3: Archive the item
        res_archive = auth_client.post("/api/archive", json={
            "type": media_type,
            "title": title,
            "year": year,
            "archive": True
        })
        assert res_archive.status_code == 200
        assert res_archive.get_json()["status"] == "success"

        # Step 4: Verify DB directly
        cached = core.db.get_cached_item(media_type, title, year)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

        # Step 5: Verify discover endpoint
        res_after = auth_client.get("/api/discover?skip_scrape=true")
        assert res_after.status_code == 200
        items_after = res_after.get_json()[media_type if media_type == "tv" else "movies"]
        item_after = [i for i in items_after if i["title"] == title][0]
        assert item_after["is_archived"] is True
        assert item_after["has_new_metadata"] is False


def test_api_archive_manual_unarchive_retains_badge_reset(auth_client):
    """
    When an archived item is manually unarchived via POST /api/archive (archive=False),
    it becomes is_archived=0, but has_new_metadata remains 0 (badge is NOT awarded for manual unarchive).
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    for media_type in ["tv", "movie"]:
        title = f"Manual Unarchive Item {media_type}"
        year = 2026

        core.db.add_cached_item(media_type, {
            "title": title,
            "year": year,
            "plot": "Plot",
            "cast": "Cast",
            "network": "AMC",
            "is_archived": True,
            "date_str": current_date,
            "date_obj": current_date
        })

        res = auth_client.post("/api/archive", json={
            "type": media_type,
            "title": title,
            "year": year,
            "archive": False
        })
        assert res.status_code == 200
        assert res.get_json()["status"] == "success"

        cached = core.db.get_cached_item(media_type, title, year)
        assert cached["is_archived"] == 0
        assert cached["has_new_metadata"] == 0

        disc = auth_client.get("/api/discover?skip_scrape=true").get_json()
        item = [i for i in disc[media_type if media_type == "tv" else "movies"] if i["title"] == title][0]
        assert item["is_archived"] is False
        assert item["has_new_metadata"] is False


def test_api_archive_non_cached_item_with_raw_payload(auth_client):
    """
    Archiving an item not previously in cache using raw_item payload inserts it
    with is_archived=1, has_new_metadata=0.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    raw_tv = {
        "title": "Fresh Uncached TV",
        "year": 2027,
        "plot": "A brand new story.",
        "cast": "Actor Alpha",
        "network": "Showtime",
        "date_str": current_date,
        "date_obj": current_date
    }

    res = auth_client.post("/api/archive", json={
        "type": "tv",
        "title": "Fresh Uncached TV",
        "year": 2027,
        "archive": True,
        "raw_item": raw_tv
    })
    assert res.status_code == 200
    cached = core.db.get_cached_item("tv", "Fresh Uncached TV", 2027)
    assert cached is not None
    assert cached["is_archived"] == 1
    assert cached["has_new_metadata"] == 0
    assert cached["network"] == "Showtime"


def test_api_archive_skeleton_creation_without_raw_item(auth_client):
    """
    Archiving an item not in cache without raw_item creates a skeleton with is_archived=1, has_new_metadata=0.
    """
    res = auth_client.post("/api/archive", json={
        "type": "movie",
        "title": "Ghost Movie",
        "year": 2028,
        "archive": True
    })
    assert res.status_code == 200
    cached = core.db.get_cached_item("movie", "Ghost Movie", 2028)
    assert cached is not None
    assert cached["is_archived"] == 1
    assert cached["has_new_metadata"] == 0


# ===========================================================================
# 4. Multi-Step Full Lifecycle State Machine Simulations
# ===========================================================================

def test_full_lifecycle_archive_refresh_unarchive_rearchive_loop(auth_client):
    """
    Complete lifecycle loop:
    1. Ingestion of low metadata -> auto-archived (is_archived=1, has_new_metadata=0).
    2. Refresh with rich data -> auto-unarchived with badge (is_archived=0, has_new_metadata=1).
    3. Subsequent refresh with rich data -> stays unarchived with badge preserved (is_archived=0, has_new_metadata=1).
    4. Manual re-archive via API -> archived and badge reset (is_archived=1, has_new_metadata=0).
    5. Refresh with low metadata -> stays archived, badge=0 (is_archived=1, has_new_metadata=0).
    6. Refresh with rich metadata -> auto-unarchived with badge AGAIN! (is_archived=0, has_new_metadata=1).
    7. Manual unarchive via API -> is_archived=0, badge reset or 0 (is_archived=0, has_new_metadata=0).
    8. Refresh with rich metadata -> stays unarchived, badge=0 (is_archived=0, has_new_metadata=0).
    """
    title = "Lifecycle Epic Show"
    year = 2026
    current_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Ingestion: low metadata
    core.db.add_cached_item("tv", {
        "title": title,
        "year": year,
        "plot": "No plot summary available.",
        "cast": "Cast details not available.",
        "network": "Unknown",
        "is_archived": True,
        "date_str": current_date,
        "date_obj": current_date
    })
    item1 = core.db.get_cached_item("tv", title, year)
    assert item1["is_archived"] == 1 and item1["has_new_metadata"] == 0

    rich_enrichment = {
        "title": title, "year": year,
        "plot": "Deep narrative plot summary.",
        "cast": "Star Actor, Supporting Actor",
        "network": "HBO", "genres": ["Drama"],
        "poster_url": "http://poster.jpg", "trailer": "http://trailer.com",
        "tvdbId": 1001, "imdbId": "tt1001"
    }
    low_enrichment = {
        "title": title, "year": year,
        "plot": "No plot summary available.",
        "cast": "Cast details not available.",
        "network": "Unknown", "genres": [],
        "poster_url": "", "trailer": "",
        "tvdbId": None, "imdbId": None
    }

    with patch("web.server.get_clients", return_value=(None, None)):
        # 2. Live refresh with rich data -> auto-unarchives with badge
        with patch("web.server.enrich_tv_show", return_value=rich_enrichment):
            res2 = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
            assert res2.status_code == 200
            assert res2.get_json()["item"]["is_archived"] is False
            assert res2.get_json()["item"]["has_new_metadata"] is True

        # 3. Subsequent live refresh with rich data -> badge preserved
        with patch("web.server.enrich_tv_show", return_value=rich_enrichment):
            res3 = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
            assert res3.status_code == 200
            assert res3.get_json()["item"]["is_archived"] is False
            assert res3.get_json()["item"]["has_new_metadata"] is True

        # 4. Re-archive via API -> is_archived=1, has_new_metadata=0
        res4 = auth_client.post("/api/archive", json={"type": "tv", "title": title, "year": year, "archive": True})
        assert res4.status_code == 200
        item4 = core.db.get_cached_item("tv", title, year)
        assert item4["is_archived"] == 1 and item4["has_new_metadata"] == 0

        # 5. Live refresh with low metadata -> stays archived, badge=0
        with patch("web.server.enrich_tv_show", return_value=low_enrichment):
            res5 = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
            assert res5.status_code == 200
            assert res5.get_json()["item"]["is_archived"] is True
            assert res5.get_json()["item"]["has_new_metadata"] is False

        # 6. Live refresh with rich metadata -> manual archive is sticky: stays archived, no badge
        with patch("web.server.enrich_tv_show", return_value=rich_enrichment):
            res6 = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
            assert res6.status_code == 200
            assert res6.get_json()["item"]["is_archived"] is True
            assert res6.get_json()["item"]["has_new_metadata"] is False

        # 7. Manual unarchive via API (archive=False) -> is_archived=0, manual flag cleared
        res7 = auth_client.post("/api/archive", json={"type": "tv", "title": title, "year": year, "archive": False})
        assert res7.status_code == 200
        item7 = core.db.get_cached_item("tv", title, year)
        assert item7["is_archived"] == 0 and item7["manually_archived"] == 0

        # 8. Live refresh with rich metadata while unarchived & badge=0 -> stays is_archived=0, has_new_metadata=0
        # (use a fresh dict: the endpoint mutates the shared one with is_archived=True from step 6)
        fresh_rich = {k: v for k, v in rich_enrichment.items() if k not in ("is_archived", "has_new_metadata")}
        with patch("web.server.enrich_tv_show", return_value=fresh_rich):
            res8 = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
            assert res8.status_code == 200
            assert res8.get_json()["item"]["is_archived"] is False
            assert res8.get_json()["item"]["has_new_metadata"] is False


# ===========================================================================
# 5. Boundary Sentinels, Whitespace Fuzzing & String Variations
# ===========================================================================

@pytest.mark.parametrize("sentinel_plot", [
    "", "   ", "\t\n", "no plot summary available.", "NO PLOT SUMMARY AVAILABLE", "unknown", "n/a", "null", "none", "tbd"
])
@pytest.mark.parametrize("sentinel_cast", [
    "", "   ", "cast details not available.", "CAST DETAILS NOT AVAILABLE", "unknown", "n/a", "none", "null", "error getting details."
])
def test_cache_refresh_boundary_sentinel_variations(auth_client, sentinel_plot, sentinel_cast):
    """
    Ensure all sentinel variations in plot and cast cause the item to be classified as missing
    and auto-archived when refreshed.
    """
    title = f"Sentinel Test {hash((sentinel_plot, sentinel_cast))}"
    year = 2026
    current_date = datetime.now().strftime("%Y-%m-%d")

    core.db.add_cached_item("tv", {
        "title": title, "year": year,
        "plot": "Initial plot", "cast": "Initial cast", "network": "Netflix",
        "is_archived": False, "date_str": current_date, "date_obj": current_date
    })

    enrichment = {
        "title": title,
        "year": year,
        "network": "Unknown",  # missing
        "plot": sentinel_plot,  # missing
        "cast": sentinel_cast,  # missing
        "genres": []
    }

    with patch("web.server.get_clients", return_value=(None, None)), \
         patch("web.server.enrich_tv_show", return_value=enrichment):

        res = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
        assert res.status_code == 200
        item = res.get_json()["item"]
        assert item["is_archived"] is True
        assert item["has_new_metadata"] is False


def test_cache_refresh_rich_metadata_with_clean_strings(auth_client):
    """
    Test rich network strings and comma-separated cast strings passed in enrichment payload.
    """
    title = "Rich Structure Show"
    year = 2026
    current_date = datetime.now().strftime("%Y-%m-%d")

    core.db.add_cached_item("tv", {
        "title": title, "year": year,
        "plot": "No plot summary available.", "cast": "Cast details not available.",
        "network": "Unknown", "is_archived": True, "date_str": current_date, "date_obj": current_date
    })

    rich_payload = {
        "title": title,
        "year": year,
        "network": "HBO",
        "cast": "Pedro Pascal, Bella Ramsey",
        "plot": "Survivors journey through a post-apocalyptic world.",
        "genres": ["Drama", "Sci-Fi"]
    }

    with patch("web.server.get_clients", return_value=(None, None)), \
         patch("web.server.enrich_tv_show", return_value=rich_payload):

        res = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": title, "year": year})
        assert res.status_code == 200
        item = res.get_json()["item"]
        assert item["is_archived"] is False
        assert item["has_new_metadata"] is True


# ===========================================================================
# 6. Error Handling & Validation on Endpoints
# ===========================================================================

def test_cache_refresh_invalid_requests(auth_client):
    """Test validation errors for /api/cache/refresh."""
    # Missing body
    res = auth_client.post("/api/cache/refresh", json={})
    assert res.status_code == 400
    assert "Missing required fields" in res.get_json()["message"]

    # Missing type
    res = auth_client.post("/api/cache/refresh", json={"title": "T", "year": 2026})
    assert res.status_code == 400

    # Missing title
    res = auth_client.post("/api/cache/refresh", json={"type": "tv", "year": 2026})
    assert res.status_code == 400

    # Missing year
    res = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": "T"})
    assert res.status_code == 400

    # Invalid media type
    res = auth_client.post("/api/cache/refresh", json={"type": "podcast", "title": "T", "year": 2026})
    assert res.status_code == 400
    assert "Invalid media type" in res.get_json()["message"]


def test_archive_invalid_requests(auth_client):
    """Test validation errors for /api/archive."""
    res = auth_client.post("/api/archive", json={})
    assert res.status_code == 400

    res = auth_client.post("/api/archive", json={"type": "tv"})
    assert res.status_code == 400

    res = auth_client.post("/api/archive", json={"title": "No Type"})
    assert res.status_code == 400


def test_cache_refresh_enricher_exception_handling(auth_client):
    """If enricher raises an unexpected exception, API returns 500 error cleanly."""
    with patch("web.server.get_clients", return_value=(None, None)), \
         patch("web.server.enrich_tv_show", side_effect=Exception("Upstream network timeout")):

        res = auth_client.post("/api/cache/refresh", json={"type": "tv", "title": "Crash Show", "year": 2026})
        assert res.status_code == 500
        assert "Upstream network timeout" in res.get_json()["message"]


# ===========================================================================
# 7. Concurrent Multi-Threaded Stress Harness
# ===========================================================================

def test_concurrent_refresh_and_archive_stress():
    """
    Stress test SQLite WAL concurrency with multiple threads executing
    add_cached_item and archive_cached_item concurrently.
    Verifies that no lock contention errors, data corruption, or crash occurs.
    """
    num_items = 5
    current_date = datetime.now().strftime("%Y-%m-%d")
    for i in range(num_items):
        core.db.add_cached_item("tv", {
            "title": f"Concurrent Show {i}",
            "year": 2026,
            "imdbId": f"tt{5000000 + i}",
            "plot": "No plot summary available.",
            "cast": "Cast details not available.",
            "network": "Unknown",
            "is_archived": True,
            "date_str": current_date,
            "date_obj": current_date
        })

    errors = []

    def updater(thread_id):
        try:
            for iteration in range(2):
                for i in range(num_items):
                    if (iteration + thread_id) % 2 == 0:
                        core.db.add_cached_item("tv", {
                            "title": f"Concurrent Show {i}",
                            "year": 2026,
                            "imdbId": f"tt{5000000 + i}",
                            "plot": f"Rich plot from thread {thread_id}",
                            "cast": f"Actor {thread_id}",
                            "network": "Apple TV+",
                            "date_str": current_date,
                            "date_obj": current_date
                        })
                    else:
                        core.db.archive_cached_item("tv", f"Concurrent Show {i}", 2026, is_archived=True)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=updater, args=(t,)) for t in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent updater encountered errors: {errors}"

    # Verify DB health after concurrent operations
    conn = core.db.get_db_connection()
    count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    conn.close()
    assert count == num_items
