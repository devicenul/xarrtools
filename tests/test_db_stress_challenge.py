"""
tests/test_db_stress_challenge.py
---------------------------------
Adversarial stress testing for SQLite persistence, schema migrations,
concurrency, transaction integrity, and metadata state transitions in core/db.py.
"""

import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

import pytest

import core.db
from core.metadata import evaluate_item_state_transition, should_auto_archive


@pytest.fixture
def isolated_db():
    """Provides a clean, temporary database for testing, restoring DB_PATH on exit."""
    fd, temp_path = tempfile.mkstemp(suffix=".db")
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


class TestLegacyMigrationAndDataIntegrity:
    """Stress-test legacy SQLite migrations, ensuring zero data loss and correct default values."""

    def test_legacy_upgrade_500_records_zero_data_loss(self):
        """Creates a legacy database with 500 records missing has_new_metadata and normalized_title."""
        fd, temp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        old_db_path = core.db.DB_PATH
        core.db.DB_PATH = Path(temp_path)

        try:
            conn = sqlite3.connect(temp_path)
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("""
                CREATE TABLE cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT,
                    title TEXT,
                    year INTEGER,
                    date_str TEXT,
                    date_obj TEXT,
                    description TEXT,
                    href TEXT,
                    imdb_id TEXT,
                    is_returning INTEGER DEFAULT 0,
                    is_archived INTEGER DEFAULT 0,
                    added_at TEXT
                )
            """)

            # Insert 500 legacy records with varied characteristics
            records = []
            for i in range(500):
                is_tv = (i % 2 == 0)
                media_type = "tv" if is_tv else "movie"
                title = f"Legacy Show {i}: Season 1" if is_tv else f"Legacy Movie {i} [4K UHD]"
                year = 2000 + (i % 30)
                imdb_id = f"tt{1000000 + i}"
                is_arch = 1 if (i % 3 == 0) else 0
                records.append((
                    media_type, title, year, "2026-01-01", "2026-01-01",
                    f"Legacy description {i}", f"https://example.com/{i}",
                    imdb_id, 0, is_arch, "2026-01-01 12:00:00"
                ))

            conn.executemany("""
                INSERT INTO cache (type, title, year, date_str, date_obj, description, href, imdb_id, is_returning, is_archived, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()
            conn.close()

            # Execute migration via init_db()
            core.db.init_db()

            # Re-connect and inspect schema & data
            conn = core.db.get_db_connection()
            cursor = conn.cursor()

            # 1. Verify all columns are present
            cursor.execute("PRAGMA table_info(cache)")
            cols = {col["name"]: col["type"] for col in cursor.fetchall()}
            assert "has_new_metadata" in cols
            assert "normalized_title" in cols
            assert "poster_url" in cols
            assert "is_in_library" in cols

            # 2. Verify exact row count
            cursor.execute("SELECT COUNT(*) FROM cache")
            assert cursor.fetchone()[0] == 500

            # 3. Verify has_new_metadata is defaulted to 0 or None coerced to 0 for all rows
            cursor.execute("SELECT COUNT(*) FROM cache WHERE has_new_metadata = 0 OR has_new_metadata IS NULL")
            assert cursor.fetchone()[0] == 500
            cursor.execute("SELECT COUNT(*) FROM cache WHERE has_new_metadata != 0 AND has_new_metadata IS NOT NULL")
            assert cursor.fetchone()[0] == 0

            # 4. Verify normalized_title was backfilled correctly
            cursor.execute("SELECT COUNT(*) FROM cache WHERE normalized_title IS NULL OR normalized_title = ''")
            assert cursor.fetchone()[0] == 0

            # Spot-check specific normalized titles
            cursor.execute("SELECT normalized_title FROM cache WHERE title = 'Legacy Show 0: Season 1'")
            assert cursor.fetchone()["normalized_title"] == "legacyshow0"

            cursor.execute("SELECT normalized_title FROM cache WHERE title = 'Legacy Movie 1 [4K UHD]'")
            assert cursor.fetchone()["normalized_title"] == "legacymovie1"

            # 5. Verify lookup works seamlessly on migrated items
            item = core.db.get_cached_item("tv", "Legacy Show 0", 2000, "tt1000000", conn=conn)
            assert item is not None
            assert item["title"] == "Legacy Show 0: Season 1"
            assert item["has_new_metadata"] in (0, None)

            conn.close()

            # 6. Verify idempotency: run init_db() multiple times
            core.db.init_db()
            core.db.init_db()

            conn2 = core.db.get_db_connection()
            cursor2 = conn2.cursor()
            cursor2.execute("SELECT COUNT(*) FROM cache")
            assert cursor2.fetchone()[0] == 500
            conn2.close()

        finally:
            core.db.DB_PATH = old_db_path
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestConcurrencyAndRapidPersistence:
    """Stress-test concurrent writes, updates, and reads in SQLite WAL mode."""

    def test_concurrent_rapid_insertions(self, isolated_db):
        """20 threads inserting distinct items simultaneously."""
        thread_count = 20
        items_per_thread = 25
        errors = []

        def worker(thread_id: int):
            try:
                for j in range(items_per_thread):
                    idx = thread_id * items_per_thread + j
                    item = {
                        "title": f"Concurrent Movie {idx}",
                        "year": 2026,
                        "imdbId": f"tt{2000000 + idx}",
                        "network": "Universal Pictures",
                        "cast": f"Actor {idx}",
                        "plot": f"Plot for movie {idx}",
                        "date_obj": datetime(2026, 6, 1),
                    }
                    core.db.add_cached_item("movie", item)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Encountered concurrency errors: {errors}"

        # Verify total inserted records
        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == thread_count * items_per_thread

    def test_concurrent_updates_on_same_items(self, isolated_db):
        """Multiple threads updating the SAME items repeatedly to test race condition resilience."""
        # Pre-seed 10 items
        for i in range(10):
            item = {
                "title": f"Contended Item {i}",
                "year": 2026,
                "imdbId": f"tt{3000000 + i}",
                "network": "Unknown",
                "cast": "Unknown",
                "plot": "Unknown",
            }
            core.db.add_cached_item("tv", item)

        errors = []

        def updater(thread_id: int):
            try:
                for iteration in range(20):
                    for i in range(10):
                        if (iteration + thread_id) % 2 == 0:
                            # Rich metadata update
                            update_item = {
                                "title": f"Contended Item {i}",
                                "year": 2026,
                                "imdbId": f"tt{3000000 + i}",
                                "network": f"Network-{thread_id}",
                                "cast": f"Actor-{thread_id}",
                                "plot": f"Rich plot from thread {thread_id} iteration {iteration}",
                            }
                        else:
                            # Low metadata update
                            update_item = {
                                "title": f"Contended Item {i}",
                                "year": 2026,
                                "imdbId": f"tt{3000000 + i}",
                                "network": "Unknown",
                                "cast": "Unknown",
                                "plot": "Unknown",
                            }
                        core.db.add_cached_item("tv", update_item)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Encountered concurrency update errors: {errors}"

        # Ensure no duplicates were created (still exactly 10 items)
        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 10

        # Check each item's consistency
        for i in range(10):
            cached = core.db.get_cached_item("tv", f"Contended Item {i}", 2026, f"tt{3000000 + i}")
            assert cached is not None
            # If low metadata, is_archived must be 1 and has_new_metadata must be 0
            # If rich metadata, is_archived must be 0
            is_low = (cached["network"] == "Unknown" and cached["cast"] == "Unknown")
            if is_low:
                assert cached["is_archived"] == 1
                assert cached["has_new_metadata"] == 0
            else:
                assert cached["is_archived"] == 0


class TestArchiveAndBadgeResetOracles:
    """Stress-test archive_cached_item reset behaviors under diverse conditions."""

    def test_archive_existing_badged_item_unconditionally_resets_badge(self, isolated_db):
        """Verifies that archiving a previously smart-unarchived item (has_new_metadata=1) resets the badge."""
        # 1. Low metadata -> auto-archived
        item = {"title": "Oracle Show", "year": 2026, "network": "Unknown", "cast": "Unknown", "plot": "Unknown"}
        core.db.add_cached_item("tv", item)
        cached = core.db.get_cached_item("tv", "Oracle Show", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

        # 2. Rich metadata -> smart unarchived with badge = 1
        item_rich = {"title": "Oracle Show", "year": 2026, "network": "HBO", "cast": "Actor X", "plot": "Plot Y"}
        core.db.add_cached_item("tv", item_rich)
        cached = core.db.get_cached_item("tv", "Oracle Show", 2026)
        assert cached["is_archived"] == 0
        assert cached["has_new_metadata"] == 1

        # 3. Explicit archive -> is_archived = 1, has_new_metadata = 0
        core.db.archive_cached_item("tv", "Oracle Show", 2026, is_archived=True)
        cached = core.db.get_cached_item("tv", "Oracle Show", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

    def test_archive_skeleton_without_prior_cache(self, isolated_db):
        """Archiving items not yet present in cache creates skeleton with has_new_metadata=0."""
        # Archive skeleton with raw_item
        raw = {"title": "Skeleton 1", "year": 2026, "imdb_id": "tt9990001", "network": "CBS"}
        core.db.archive_cached_item("tv", "Skeleton 1", 2026, is_archived=True, raw_item=raw)
        cached = core.db.get_cached_item("tv", "Skeleton 1", 2026, "tt9990001")
        assert cached is not None
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

        # Archive skeleton without raw_item
        core.db.archive_cached_item("movie", "Skeleton 2", 2026, is_archived=True)
        cached2 = core.db.get_cached_item("movie", "Skeleton 2", 2026)
        assert cached2 is not None
        assert cached2["is_archived"] == 1
        assert cached2["has_new_metadata"] == 0

    def test_smart_unarchive_lifecycle_after_manual_archive(self, isolated_db):
        """Tests full lifecycle: Manual Archive -> Enrich Rich Metadata -> Smart Unarchive -> Re-archive."""
        # 1. Start with rich item manually archived
        raw = {"title": "Lifecycle Movie", "year": 2026, "network": "Sony", "cast": "Lead", "plot": "Story"}
        core.db.archive_cached_item("movie", "Lifecycle Movie", 2026, is_archived=True, raw_item=raw)
        cached = core.db.get_cached_item("movie", "Lifecycle Movie", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

        # 2. Rescan with rich metadata -> manual archive is sticky: stays archived, no badge
        core.db.add_cached_item("movie", raw)
        cached = core.db.get_cached_item("movie", "Lifecycle Movie", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0

        # 3. Manual re-archive -> resets badge
        core.db.archive_cached_item("movie", "Lifecycle Movie", 2026, is_archived=True)
        cached = core.db.get_cached_item("movie", "Lifecycle Movie", 2026)
        assert cached["is_archived"] == 1
        assert cached["has_new_metadata"] == 0


class TestBatchOperationsAndEdgeCases:
    """Stress-test batch insertion and boundary value inputs."""

    def test_batch_insertion_mixed_states(self, isolated_db):
        """Batch inserting 60 items with a mix of low and rich metadata."""
        items = []
        for i in range(60):
            if i % 3 == 0:
                # low metadata
                items.append({
                    "title": f"Batch Item {i}",
                    "year": 2026,
                    "network": "Unknown",
                    "cast": "Unknown",
                    "plot": "Unknown",
                })
            else:
                # rich metadata
                items.append({
                    "title": f"Batch Item {i}",
                    "year": 2026,
                    "network": "Netflix",
                    "cast": f"Actor {i}",
                    "plot": f"Plot {i}",
                })

        core.db.add_cached_items_batch("tv", items)

        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 60
        assert stats["archived_discoveries"] == 20  # exactly 20 low-metadata items archived

    def test_special_characters_and_unicode_handling(self, isolated_db):
        """Titles with unicode, emojis, SQL injection patterns, and special punctuation."""
        tricky_items = [
            {"title": "L'Étranger: Season 1", "year": 2026, "network": "Canal+", "cast": "Jean", "plot": "Roman"},
            {"title": "Robert'); DROP TABLE cache;--", "year": 2026, "network": "Exploit TV", "cast": "Hacker", "plot": "SQL Injection attempt"},
            {"title": "🎬 Movie with Emojis & Symbols #1! [Digital Edition]", "year": 2026, "network": "Studio", "cast": "Cast", "plot": "Plot"},
            {"title": "   Spaces Everywhere   ", "year": 2026, "network": "Space Net", "cast": "Astronaut", "plot": "Deep space"},
        ]

        for item in tricky_items:
            core.db.add_cached_item("tv", item)

        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 4

        # Verify SQL injection title is safely stored as literal text and table is intact
        cached_sql = core.db.get_cached_item("tv", "Robert'); DROP TABLE cache;--", 2026)
        assert cached_sql is not None
        assert cached_sql["title"] == "Robert'); DROP TABLE cache;--"

        # Verify unicode lookup
        cached_unicode = core.db.get_cached_item("tv", "L'Étranger: Season 1", 2026)
        assert cached_unicode is not None


class TestAdvancedIntegrityAndRollbacks:
    """Stress-test transaction rollbacks, IMDb ID priority matching, and year disambiguation."""

    def test_imdb_id_priority_over_title_change(self, isolated_db):
        """Updating an item whose title changed upstream matches correctly via IMDb ID."""
        # 1. Insert original item
        item_orig = {
            "title": "Working Title Alpha",
            "year": 2026,
            "imdbId": "tt5555555",
            "network": "HBO",
            "cast": "Actor One",
            "plot": "Original plot summary.",
        }
        core.db.add_cached_item("tv", item_orig)
        cached1 = core.db.get_cached_item("tv", "Working Title Alpha", 2026, "tt5555555")
        assert cached1 is not None
        assert cached1["id"] is not None
        orig_id = cached1["id"]

        # 2. Update with changed title but same IMDb ID
        item_updated = {
            "title": "Official Final Title",
            "year": 2026,
            "imdbId": "tt5555555",
            "network": "HBO Max",
            "cast": "Actor One, Actor Two",
            "plot": "Updated plot summary.",
        }
        core.db.add_cached_item("tv", item_updated)

        # 3. Lookup by IMDb ID should return the same row updated
        cached2 = core.db.get_cached_item("tv", "Official Final Title", 2026, "tt5555555")
        assert cached2 is not None
        assert cached2["id"] == orig_id
        assert cached2["network"] == "HBO Max"
        assert cached2["normalized_title"] == "officialfinaltitle"

        # Verify only 1 record exists in database
        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 1

    def test_multi_year_title_isolation(self, isolated_db):
        """Multiple items sharing the same title but different release years are kept distinct when ignore_year=0."""
        core.db.set_setting("default_match_ignore_year", "0")

        item_2009 = {
            "title": "Rebooted Franchise",
            "year": 2009,
            "imdbId": "tt1001",
            "network": "Fox",
            "cast": "Original Cast",
            "plot": "2009 Original movie.",
        }
        item_2026 = {
            "title": "Rebooted Franchise",
            "year": 2026,
            "imdbId": "tt2001",
            "network": "Disney",
            "cast": "New Cast",
            "plot": "2026 Reboot movie.",
        }

        core.db.add_cached_item("movie", item_2009)
        core.db.add_cached_item("movie", item_2026)

        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 2

        cached_2009 = core.db.get_cached_item("movie", "Rebooted Franchise", 2009, "tt1001")
        cached_2026 = core.db.get_cached_item("movie", "Rebooted Franchise", 2026, "tt2001")

        assert cached_2009["id"] != cached_2026["id"]
        assert cached_2009["network"] == "Fox"
        assert cached_2026["network"] == "Disney"

    def test_concurrent_readers_and_writers(self, isolated_db):
        """Concurrent reader threads querying while writers are rapidly inserting."""
        stop_event = threading.Event()
        errors = []

        # Pre-seed items
        for i in range(20):
            core.db.add_cached_item("movie", {
                "title": f"Reader Seed {i}",
                "year": 2026,
                "network": "Paramount",
                "cast": "Actor",
                "plot": "Plot",
                "date_obj": datetime(2026, 6, 1),
            })

        def reader_loop():
            try:
                while not stop_event.is_set():
                    core.db.get_cached_discoveries("2026-06-01", "2026-06-30")
                    core.db.get_cache_stats()
                    core.db.get_cached_item("movie", "Reader Seed 5", 2026)
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        def writer_loop(writer_id: int):
            try:
                for j in range(20):
                    core.db.add_cached_item("movie", {
                        "title": f"Writer Item {writer_id}-{j}",
                        "year": 2026,
                        "network": "Sony",
                        "cast": f"Actor {writer_id}",
                        "plot": f"Plot {j}",
                        "date_obj": datetime(2026, 6, 15),
                    })
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        reader_threads = [threading.Thread(target=reader_loop) for _ in range(5)]
        writer_threads = [threading.Thread(target=writer_loop, args=(w,)) for w in range(5)]

        for t in reader_threads:
            t.start()
        for t in writer_threads:
            t.start()

        for t in writer_threads:
            t.join()

        stop_event.set()
        for t in reader_threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent readers/writers: {errors}"
        stats = core.db.get_cache_stats()
        assert stats["total_discoveries"] == 20 + (5 * 20)

