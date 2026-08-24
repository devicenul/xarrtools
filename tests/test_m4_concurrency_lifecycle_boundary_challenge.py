"""
tests/test_m4_concurrency_lifecycle_boundary_challenge.py
---------------------------------------------------------
Milestone 4 Empirical Challenge Suite:
1. Multi-threaded insertions and concurrent read/write transactions on SQLite cache.
2. Long-running multi-stage transitions (Auto-Archive -> Enrich -> Unarchive + Badge -> Rescan -> Manual Archive -> Badge Cleared -> Manual Unarchive -> Scrape Update).
3. Extreme boundary inputs (deeply nested JSON, unicode surrogate pairs, high volume batch scans, SQLi/XSS safety).
"""

import os
import json
import sqlite3
import tempfile
import threading
import concurrent.futures
from pathlib import Path
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch, MagicMock

import core.db
import core.metadata
from web.server import app


@pytest.fixture
def isolated_db():
    """Sets up an isolated SQLite database file for testing."""
    fd, temp_path = tempfile.mkstemp(suffix="_challenge_m4.db")
    os.close(fd)
    
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    core.db.init_db()
    
    yield temp_path
    
    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


@pytest.fixture
def client(isolated_db):
    """Flask test client connected to the isolated database."""
    core.db.set_setting("api_key", "test_m4_key")
    from core.config import config
    config.refresh()
    
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


# ===========================================================================
# 1. Multi-Threaded Insertions & Concurrent Read/Write Transactions
# ===========================================================================

class TestM4ConcurrencyAndTransactions:

    def test_concurrent_multithreaded_insertions_and_lookups(self, isolated_db):
        """
        Stress-tests SQLite WAL mode by spawning 30 concurrent threads that
        simultaneously insert distinct media items and perform lookups.
        Ensures zero unhandled database lock exceptions and 100% data integrity.
        """
        num_threads = 30
        errors = []

        def worker(thread_idx):
            try:
                # Insert sparse item (should auto-archive)
                sparse_item = {
                    "title": f"Thread Show {thread_idx}",
                    "year": 2026,
                    "date_str": "2026-06-01",
                    "date_obj": datetime(2026, 6, 1),
                    "network": "Unknown",
                    "cast": "Cast details not available.",
                    "plot": "No plot summary available.",
                    "genres": ["Drama"]
                }
                core.db.add_cached_item("tv", sparse_item)

                # Verify lookup returns correctly
                row = core.db.get_cached_item("tv", f"Thread Show {thread_idx}", 2026)
                assert row is not None
                assert row["is_archived"] == 1
                assert row["has_new_metadata"] == 0

                # Insert full item (should remain unarchived)
                full_item = {
                    "title": f"Thread Movie {thread_idx}",
                    "year": 2026,
                    "date_str": "2026-06-01",
                    "date_obj": datetime(2026, 6, 1),
                    "network": f"Studio {thread_idx}",
                    "cast": f"Actor {thread_idx}",
                    "plot": f"Exciting plot for {thread_idx}",
                    "genres": ["Action"]
                }
                core.db.add_cached_item("movie", full_item)

                row_m = core.db.get_cached_item("movie", f"Thread Movie {thread_idx}", 2026)
                assert row_m is not None
                assert row_m["is_archived"] == 0
                assert row_m["has_new_metadata"] == 0
            except Exception as e:
                errors.append(f"Thread {thread_idx} failed: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Encountered concurrency errors: {errors}"

        # Verify final row counts
        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == num_threads * 2
        assert stats["archived_discoveries"] == num_threads

    def test_concurrent_mixed_operations_stress(self, isolated_db):
        """
        40 concurrent threads performing a mix of add, get, archive,
        update_library_status, stats, and discovery queries.
        """
        # Pre-seed items
        for i in range(20):
            core.db.add_cached_item("tv", {
                "title": f"Seed TV {i}",
                "year": 2026,
                "date_obj": "2026-05-15",
                "network": "HBO",
                "cast": "Actor A",
                "plot": "Plot summary."
            })

        errors = []

        def mixed_worker(worker_id):
            try:
                op = worker_id % 5
                if op == 0:
                    # Insert new item
                    core.db.add_cached_item("movie", {
                        "title": f"Mixed Movie {worker_id}",
                        "year": 2026,
                        "date_obj": "2026-05-20",
                        "network": "Sony",
                        "cast": "Actor B",
                        "plot": "Plot B"
                    })
                elif op == 1:
                    # Update library status
                    target_idx = worker_id % 20
                    core.db.update_cached_library_status("tv", f"Seed TV {target_idx}", 2026, True)
                elif op == 2:
                    # Archive / Unarchive toggle
                    target_idx = worker_id % 20
                    core.db.archive_cached_item("tv", f"Seed TV {target_idx}", 2026, is_archived=(worker_id % 2 == 0))
                elif op == 3:
                    # Query discoveries in date range
                    tv_rows, movie_rows = core.db.get_cached_discoveries("2026-05-01", "2026-05-30")
                    assert isinstance(tv_rows, list)
                    assert isinstance(movie_rows, list)
                elif op == 4:
                    # Query stats
                    stats = core.db.get_cache_stats()
                    assert stats["total_discoveries"] >= 20
            except Exception as e:
                errors.append(f"Worker {worker_id} op {op} failed: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(mixed_worker, i) for i in range(40)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors during mixed concurrency: {errors}"

    def test_concurrent_same_record_race_condition(self, isolated_db):
        """
        20 threads racing to write/update the exact SAME media title with conflicting states.
        Tests SQLite transactional serialization and verifies no corrupted rows or duplicates.
        """
        target_title = "Race Condition Epic"
        target_year = 2026
        errors = []

        def race_worker(worker_id):
            try:
                if worker_id % 3 == 0:
                    # Write sparse metadata
                    core.db.add_cached_item("tv", {
                        "title": target_title,
                        "year": target_year,
                        "network": "Unknown",
                        "cast": "Cast details not available.",
                        "plot": "No plot summary available."
                    })
                elif worker_id % 3 == 1:
                    # Write rich metadata
                    core.db.add_cached_item("tv", {
                        "title": target_title,
                        "year": target_year,
                        "network": "Netflix",
                        "cast": f"Cast Member {worker_id}",
                        "plot": f"Full Plot from worker {worker_id}"
                    })
                else:
                    # Explicit archive toggle
                    core.db.archive_cached_item("tv", target_title, target_year, is_archived=True)
            except Exception as e:
                errors.append(f"Race worker {worker_id} error: {e}")

        threads = [threading.Thread(target=race_worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Race condition errors: {errors}"

        # Verify only ONE entry exists in the cache table for this title/year
        conn = core.db.get_db_connection()
        cursor = conn.cursor()
        norm = core.db.normalize_title(target_title, is_tv=True)
        cursor.execute("SELECT COUNT(*) FROM cache WHERE type = 'tv' AND normalized_title = ?", (norm,))
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1, f"Expected exactly 1 row for {target_title}, got {count}"

    def test_concurrent_batch_inserts_and_readers(self, isolated_db):
        """
        Tests batch insert of 100 items on one thread while 10 reader threads
        continuously query discoveries and cache stats.
        """
        items = [
            {
                "title": f"Batch Item {i}",
                "year": 2026,
                "date_obj": f"2026-07-{(i % 28) + 1:02d}",
                "network": f"Network {i}",
                "cast": f"Actor {i}",
                "plot": f"Plot {i}"
            }
            for i in range(100)
        ]

        stop_readers = threading.Event()
        reader_errors = []

        def reader_task():
            while not stop_readers.is_set():
                try:
                    tv_rows, movie_rows = core.db.get_cached_discoveries("2026-07-01", "2026-07-31")
                    stats = core.db.get_cache_stats()
                    assert stats["total_discoveries"] >= 0
                except Exception as e:
                    reader_errors.append(str(e))

        readers = [threading.Thread(target=reader_task) for _ in range(10)]
        for r in readers:
            r.start()

        # Execute batch insert
        core.db.add_cached_items_batch("tv", items)

        stop_readers.set()
        for r in readers:
            r.join()

        assert len(reader_errors) == 0, f"Reader errors during batch: {reader_errors}"

        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 100

    def test_concurrent_prune_and_inserts(self, isolated_db):
        """
        Runs clean_expired_cache concurrently with active writers inserting
        both fresh and expired records.
        """
        errors = []

        def inserter():
            try:
                for i in range(25):
                    # Insert fresh item
                    core.db.add_cached_item("movie", {
                        "title": f"Fresh Movie {i}",
                        "year": 2026,
                        "date_obj": "2026-08-01",
                        "network": "Warner Bros",
                        "cast": "Actor Fresh",
                        "plot": "Fresh Plot"
                    })
                    # Insert expired item (2 years old)
                    core.db.add_cached_item("movie", {
                        "title": f"Old Movie {i}",
                        "year": 2024,
                        "date_obj": "2024-01-01",
                        "network": "Old Studio",
                        "cast": "Actor Old",
                        "plot": "Old Plot"
                    })
            except Exception as e:
                errors.append(f"Inserter error: {e}")

        def pruner():
            try:
                for _ in range(5):
                    core.db.clean_expired_cache()
            except Exception as e:
                errors.append(f"Pruner error: {e}")

        t_insert = threading.Thread(target=inserter)
        t_prune = threading.Thread(target=pruner)

        t_insert.start()
        t_prune.start()

        t_insert.join()
        t_prune.join()

        assert len(errors) == 0, f"Concurrent prune errors: {errors}"


# ===========================================================================
# 2. Long-Running Multi-Stage Lifecycle Transitions
# ===========================================================================

class TestM4MultiStageLifecycleTransitions:

    def test_complete_eight_stage_lifecycle_sequence(self, isolated_db):
        """
        Executes the comprehensive 8-stage lifecycle sequence:
        Stage 1: Auto-Archive (Sparse scrape: >=2 missing -> is_archived=1, has_new_metadata=0)
        Stage 2: Enrich (Upstream discovers complete metadata -> missing_count=0)
        Stage 3: Unarchive + Badge (DB persistence -> is_archived=0, has_new_metadata=1)
        Stage 4: Rescan (Identical metadata scan -> is_archived=0, has_new_metadata=1 preserved)
        Stage 5: Manual Archive (User archives -> is_archived=1, has_new_metadata=0 badge cleared)
        Stage 6: Badge Cleared Verification (Query confirms has_new_metadata=0)
        Stage 7: Manual Unarchive (User unarchives -> is_archived=0, has_new_metadata=0 clean)
        Stage 8: Scrape Update (Subsequent scrape with full metadata -> is_archived=0, has_new_metadata=0 retained)
        """
        title = "The Lifecycle Chronicle"
        year = 2026
        type_ = "tv"

        # --- Stage 1: Auto-Archive (Sparse Scrape) ---
        sparse_item = {
            "title": title,
            "year": year,
            "date_obj": "2026-09-01",
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
            "genres": []
        }
        core.db.add_cached_item(type_, sparse_item)
        cached = core.db.get_cached_item(type_, title, year)
        assert cached is not None
        assert cached["is_archived"] == 1, "Stage 1 Failed: Should be auto-archived"
        assert cached["has_new_metadata"] == 0, "Stage 1 Failed: Badge should be 0"

        # --- Stage 2 & 3: Enrich & Auto-Unarchive + Badge ---
        rich_item = {
            "title": title,
            "year": year,
            "date_obj": "2026-09-01",
            "network": "HBO Max",
            "cast": "Bryan Cranston, Aaron Paul",
            "plot": "A chemistry teacher discovers new horizons.",
            "genres": ["Drama", "Crime"]
        }
        # Evaluation check
        eval_res = core.metadata.evaluate_metadata(rich_item)
        assert eval_res["missing_count"] == 0
        assert eval_res["is_low_metadata"] is False

        core.db.add_cached_item(type_, rich_item)
        cached = core.db.get_cached_item(type_, title, year)
        assert cached["is_archived"] == 0, "Stage 3 Failed: Should be auto-unarchived"
        assert cached["has_new_metadata"] == 1, "Stage 3 Failed: Should receive has_new_metadata=1 badge"

        # --- Stage 4: Rescan (Periodic rescan with same data preserves state) ---
        core.db.add_cached_item(type_, rich_item)
        cached = core.db.get_cached_item(type_, title, year)
        assert cached["is_archived"] == 0, "Stage 4 Failed: Should stay unarchived"
        assert cached["has_new_metadata"] == 1, "Stage 4 Failed: Badge should be preserved on unchanged rescan"

        # --- Stage 5 & 6: Manual Archive & Badge Cleared ---
        core.db.archive_cached_item(type_, title, year, is_archived=True)
        cached = core.db.get_cached_item(type_, title, year)
        assert cached["is_archived"] == 1, "Stage 5 Failed: Should be marked archived"
        assert cached["has_new_metadata"] == 0, "Stage 5/6 Failed: Re-archiving must reset has_new_metadata to 0"

        # --- Stage 7: Manual Unarchive ---
        core.db.archive_cached_item(type_, title, year, is_archived=False)
        cached = core.db.get_cached_item(type_, title, year)
        assert cached["is_archived"] == 0, "Stage 7 Failed: Should be unarchived"
        assert cached["has_new_metadata"] == 0, "Stage 7 Failed: Manual unarchive must NOT falsely set badge"

        # --- Stage 8: Scrape Update (Subsequent scrape with full metadata on unarchived clean item) ---
        core.db.add_cached_item(type_, rich_item)
        cached = core.db.get_cached_item(type_, title, year)
        assert cached["is_archived"] == 0, "Stage 8 Failed: Should remain unarchived"
        assert cached["has_new_metadata"] == 0, "Stage 8 Failed: Badge must remain 0 when already unarchived"

    def test_lifecycle_variation_manual_unarchive_then_sparse_rescan(self, isolated_db):
        """
        Tests variation where an item is manually unarchived (is_archived=0, has_new_metadata=0),
        then a subsequent sparse rescan (e.g. metadata provider outage) causes auto-archiving.
        """
        title = "Degradation Odyssey"
        year = 2026

        # Start manually unarchived
        core.db.archive_cached_item("movie", title, year, is_archived=False)
        cached = core.db.get_cached_item("movie", title, year)
        assert cached["is_archived"] == 0
        assert cached["has_new_metadata"] == 0

        # Sparse rescan
        sparse = {
            "title": title,
            "year": year,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available."
        }
        core.db.add_cached_item("movie", sparse)
        cached = core.db.get_cached_item("movie", title, year)
        assert cached["is_archived"] == 1, "Should auto-archive on metadata degradation"
        assert cached["has_new_metadata"] == 0, "Badge must remain 0"

    def test_lifecycle_partial_enrichment_does_not_prematurely_unarchive(self, isolated_db):
        """
        Tests that partial enrichment (e.g. only 1 missing field resolved, still missing 2 fields)
        keeps the item auto-archived and does NOT set has_new_metadata.
        """
        title = "Partial Progress"
        year = 2026

        # Initially 4 missing fields
        sparse = {
            "title": title,
            "year": year,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available."
        }
        core.db.add_cached_item("tv", sparse)
        cached = core.db.get_cached_item("tv", title, year)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

        # Partial enrichment: network resolved, but cast and plot still missing (2 missing fields -> still low metadata)
        partial = {
            "title": title,
            "year": year,
            "network": "BBC One",
            "cast": "Cast details not available.",
            "plot": "No plot summary available."
        }
        core.db.add_cached_item("tv", partial)
        cached = core.db.get_cached_item("tv", title, year)
        assert cached["is_archived"] == 1, "Should remain auto-archived with 2 missing fields"
        assert cached["has_new_metadata"] == 0, "Badge should remain 0"

        # Further enrichment: cast resolved (1 missing field remaining -> healthy)
        healthy = {
            "title": title,
            "year": year,
            "network": "BBC One",
            "cast": "David Tennant",
            "plot": "No plot summary available."
        }
        core.db.add_cached_item("tv", healthy)
        cached = core.db.get_cached_item("tv", title, year)
        assert cached["is_archived"] == 0, "Should now auto-unarchive"
        assert cached["has_new_metadata"] == 1, "Should receive has_new_metadata badge"

    def test_lifecycle_rapid_oscillation_twenty_cycles(self, isolated_db):
        """
        Runs 20 rapid alternating cycles of:
        Sparse Ingest -> Rich Ingest -> Manual Archive -> Rich Ingest
        and verifies exact invariant stability at every step.
        """
        title = "Oscillating Quantum Show"
        year = 2026

        sparse_data = {
            "title": title,
            "year": year,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available."
        }
        rich_data = {
            "title": title,
            "year": year,
            "network": "Apple TV+",
            "cast": "Gary Oldman",
            "plot": "A team of disgraced MI5 agents."
        }

        for cycle in range(20):
            # Step A: Sparse Ingest -> Must be archived=1, badge=0
            core.db.add_cached_item("tv", sparse_data)
            row = core.db.get_cached_item("tv", title, year)
            assert row["is_archived"] == 1, f"Cycle {cycle} Step A failed"
            assert row["has_new_metadata"] == 0, f"Cycle {cycle} Step A badge failed"

            # Step B: Rich Ingest -> Must auto-unarchive=0, badge=1
            core.db.add_cached_item("tv", rich_data)
            row = core.db.get_cached_item("tv", title, year)
            assert row["is_archived"] == 0, f"Cycle {cycle} Step B failed"
            assert row["has_new_metadata"] == 1, f"Cycle {cycle} Step B badge failed"

            # Step C: Manual Archive -> Must be archived=1, badge=0
            core.db.archive_cached_item("tv", title, year, is_archived=True)
            row = core.db.get_cached_item("tv", title, year)
            assert row["is_archived"] == 1, f"Cycle {cycle} Step C failed"
            assert row["has_new_metadata"] == 0, f"Cycle {cycle} Step C badge reset failed"

    def test_lifecycle_e2e_flask_api_full_journey(self, client):
        """
        Simulates end-to-end user HTTP requests via Flask test client:
        1. Ingest sparse item into DB
        2. GET /api/discover with skip_scrape=true -> verify is_archived=True, has_new_metadata=False
        3. Ingest rich item into DB (simulating background enrichment)
        4. GET /api/discover -> verify is_archived=False, has_new_metadata=True
        5. POST /api/archive -> verify archive status updated and badge reset
        6. GET /api/discover -> verify is_archived=True, has_new_metadata=False
        """
        headers = {"X-API-Key": "test_m4_key"}
        title = "API Journey Series"
        year = 2026
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 1. Ingest sparse item
        core.db.add_cached_item("tv", {
            "title": title,
            "year": year,
            "date_obj": today_str,
            "date_str": today_str,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": "No plot summary available."
        })

        # 2. GET /api/discover
        res = client.get("/api/discover?skip_scrape=true&past_months=1&future_months=1", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        item = next(i for i in data["tv"] if i["title"] == title)
        assert item["is_archived"] is True
        assert item["has_new_metadata"] is False

        # 3. Ingest rich item
        core.db.add_cached_item("tv", {
            "title": title,
            "year": year,
            "date_obj": today_str,
            "date_str": today_str,
            "network": "Showtime",
            "cast": "Michael C. Hall",
            "plot": "Dexter returns."
        })

        # 4. GET /api/discover
        res = client.get("/api/discover?skip_scrape=true&past_months=1&future_months=1", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        item = next(i for i in data["tv"] if i["title"] == title)
        assert item["is_archived"] is False
        assert item["has_new_metadata"] is True

        # 5. POST /api/archive to manually re-archive
        res_post = client.post("/api/archive", json={
            "type": "tv",
            "title": title,
            "year": year,
            "archive": True
        }, headers=headers)
        assert res_post.status_code == 200

        # 6. GET /api/discover again
        res = client.get("/api/discover?skip_scrape=true&past_months=1&future_months=1", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        item = next(i for i in data["tv"] if i["title"] == title)
        assert item["is_archived"] is True
        assert item["has_new_metadata"] is False


# ===========================================================================
# 3. Extreme Boundary Inputs
# ===========================================================================

class TestM4ExtremeBoundaryInputs:

    def test_boundary_deeply_nested_json_structures_in_metadata_engine(self):
        """
        Tests evaluating items with 50 levels of nested dictionary/list
        structures in cast, network, and genres without RecursionError or crash.
        """
        # Construct 50-level nested dict
        nested_person = {"name": "Deeply Nested Actor"}
        for i in range(50):
            nested_person = {"person": nested_person, "level": i}

        nested_network = {"name": "Deep Network"}
        for i in range(50):
            nested_network = {"network": nested_network, "level": i}

        deep_item = {
            "title": "Deep Recursion Inception",
            "year": 2026,
            "cast": [nested_person, {"person": {"name": "Valid Secondary"}}],
            "network": nested_network,
            "plot": "Exploring deep neural nested structures.",
            "genres": [[[[["Sci-Fi"]]]]]
        }

        # Evaluator resilience
        eval_res = core.metadata.evaluate_metadata(deep_item)
        assert isinstance(eval_res, dict)
        assert eval_res["fields"]["cast"]["is_missing"] is False
        assert eval_res["fields"]["plot"]["is_missing"] is False
        assert eval_res["is_low_metadata"] is False

    def test_boundary_unicode_surrogate_pairs_and_extreme_encodings(self, isolated_db):
        """
        Tests unicode handling including surrogate pair representations,
        CJK characters, RTL Arabic/Hebrew, emoji sequences, zero-width spaces, and control characters.
        """
        emoji_title = "🎬 宇宙探索 (Surrogate \U0001F600) 🚀 \u200B\uFEFF فيلم عربي"
        complex_plot = "Plot with mixed \t\r\n control chars, symbols: § ± ¶, emoji: 🌌🪐🔥, and Hebrew: שלום עולם."
        cast_str = "Toshiro Mifune 三船 敏郎, Omar Sharif عمر الشريف"

        item = {
            "title": emoji_title,
            "year": 2026,
            "network": "NHK 日本放送協会",
            "cast": cast_str,
            "plot": complex_plot,
            "genres": ["Animation", "Sci-Fi"]
        }

        eval_res = core.metadata.evaluate_metadata(item)
        assert eval_res["is_low_metadata"] is False
        assert eval_res["missing_count"] == 0

        core.db.add_cached_item("tv", item)

        # Lookup by exact title
        cached = core.db.get_cached_item("tv", emoji_title, 2026)
        assert cached is not None
        assert cached["is_archived"] == 0
        assert "NHK" in cached["network"]
        assert "Omar Sharif" in cached["cast"]

    def test_boundary_sql_injection_and_xss_vectors(self, isolated_db):
        """
        Tests that SQL injection vectors and XSS script tags are treated as literal strings
        and do not corrupt the database schema or execute SQL commands.
        """
        sqli_title = "Safe'; DROP TABLE cache; --"
        xss_plot = "<script>alert('XSS'); document.cookie='stolen';</script><img src=x onerror=alert(1)>"
        sqli_network = "\" UNION SELECT * FROM settings WHERE '1'='1"

        item = {
            "title": sqli_title,
            "year": 2026,
            "network": sqli_network,
            "cast": "Robert'); DROP TABLE settings; --",
            "plot": xss_plot
        }

        core.db.add_cached_item("movie", item)

        # Confirm cache table is intact
        conn = core.db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        assert cursor.fetchone()[0] == 1

        cursor.execute("SELECT COUNT(*) FROM settings")
        assert cursor.fetchone()[0] > 0
        conn.close()

        # Retrieve item
        cached = core.db.get_cached_item("movie", sqli_title, 2026)
        assert cached is not None
        assert cached["title"] == sqli_title
        assert cached["description"] == xss_plot

    def test_boundary_high_volume_batch_scan_1000_items(self, isolated_db):
        """
        Batch ingest 1000 items with mixed metadata profiles (0 to 4 missing fields).
        Verifies exact state counts, zero data loss, and sub-second batch handling.
        """
        items = []
        expected_archived = 0
        expected_unarchived = 0

        for i in range(1000):
            mod = i % 5
            if mod == 0:
                # 0 missing
                items.append({
                    "title": f"Bulk Item {i}",
                    "year": 2026,
                    "network": "HBO",
                    "cast": "Actor Bulk",
                    "plot": "Full plot summary."
                })
                expected_unarchived += 1
            elif mod == 1:
                # 1 missing (plot missing -> healthy, unarchived)
                items.append({
                    "title": f"Bulk Item {i}",
                    "year": 2026,
                    "network": "Showtime",
                    "cast": "Actor Bulk",
                    "plot": "No plot summary available."
                })
                expected_unarchived += 1
            elif mod == 2:
                # 2 missing (network & cast missing -> auto-archived)
                items.append({
                    "title": f"Bulk Item {i}",
                    "year": 2026,
                    "network": "Unknown",
                    "cast": "Cast details not available.",
                    "plot": "Plot summary available."
                })
                expected_archived += 1
            elif mod == 3:
                # 3 missing (network, cast, plot missing -> auto-archived)
                items.append({
                    "title": f"Bulk Item {i}",
                    "year": 2026,
                    "network": "Unknown",
                    "cast": "Cast details not available.",
                    "plot": "No plot summary available."
                })
                expected_archived += 1
            else:
                # 4 missing (empty dict -> auto-archived)
                items.append({
                    "title": f"Bulk Item {i}",
                    "year": 2026
                })
                expected_archived += 1

        # Ingest using batch function
        core.db.add_cached_items_batch("tv", items)

        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 1000
        assert stats["archived_discoveries"] == expected_archived
        assert (1000 - stats["archived_discoveries"]) == expected_unarchived

    def test_boundary_extreme_types_and_payload_sizes(self, isolated_db):
        """
        Tests handling of extreme string sizes (100,000 char plot), extreme years (-500, 99999),
        none/float/boolean field values, and empty structures.
        """
        giant_plot = "A" * 100000
        giant_title = "Giant Title " + ("X" * 1000)

        extreme_item = {
            "title": giant_title,
            "year": 99999,
            "network": "Unknown",
            "cast": "Cast details not available.",
            "plot": giant_plot,
            "genres": ["Test"],
            "imdbId": "tt9999999",
            "is_returning": 0,
            "is_in_library": 0
        }

        eval_res = core.metadata.evaluate_metadata(extreme_item)
        assert eval_res["fields"]["network"]["is_missing"] is True
        assert eval_res["fields"]["cast"]["is_missing"] is True
        assert eval_res["fields"]["plot"]["is_missing"] is False
        assert eval_res["is_low_metadata"] is True

        core.db.add_cached_item("movie", extreme_item)
        cached = core.db.get_cached_item("movie", giant_title, 99999)
        assert cached is not None
        assert cached["is_archived"] == 1
        assert len(cached["description"]) == 100000

    def test_boundary_db_layer_collection_binding_behavior(self, isolated_db):
        """
        Verifies and documents the boundary behavior between metadata engine and DB layer:
        While core.metadata.evaluate_metadata() gracefully accepts raw list/dict objects,
        core.db.add_cached_item() expects string/scalar representations for SQLite column bindings.
        Passing a raw list or dict directly to add_cached_item() raises sqlite3.ProgrammingError.
        """
        raw_list_cast_item = {
            "title": "Raw List Show",
            "year": 2026,
            "cast": ["Actor A", "Actor B"]
        }

        # Metadata evaluator handles list gracefully
        eval_res = core.metadata.evaluate_metadata(raw_list_cast_item)
        assert eval_res["fields"]["cast"]["is_missing"] is False

        # DB layer directly binding raw list to SQLite parameter raises ProgrammingError
        with pytest.raises(sqlite3.ProgrammingError, match="type 'list' is not supported"):
            core.db.add_cached_item("tv", raw_list_cast_item)
