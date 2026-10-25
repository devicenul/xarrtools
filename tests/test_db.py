import os
import tempfile
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch, MagicMock

import core.db

@pytest.fixture
def temp_db():
    # Setup temporary database file
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    
    # Initialize the database tables
    core.db.init_db()
    
    yield temp_path
    
    # Teardown
    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

def test_init_db_migration(temp_db):
    # Verify tables were created
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]
    assert "settings" in tables
    assert "cache" in tables
    
    # Verify default settings were seeded
    cursor.execute("SELECT COUNT(*) FROM settings")
    assert cursor.fetchone()[0] > 0
    conn.close()

    # Call it a second time to execute the 'already exists' no-op branches
    core.db.init_db()

def test_init_db_env_migration_with_none():
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    
    # Mock config properties to return None to test the None branch in env migration
    with patch("core.config.config") as mock_config:
        mock_config.radarr_url = None
        mock_config.radarr_api_key = None
        mock_config.sonarr_url = None
        mock_config.sonarr_api_key = None
        
        core.db.init_db()
        
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM settings WHERE key='radarr_url'")
    assert cursor.fetchone()[0] == 0
    conn.close()
    
    # Cleanup
    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        os.remove(temp_path)

def test_init_db_seeding_missing_defaults():
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    
    # Create DB with one key in settings, so it's not empty, but lacks defaults
    conn = sqlite3.connect(temp_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT INTO settings VALUES ('radarr_url', 'http://localhost')")
    conn.commit()
    conn.close()
    
    # This should seed missing defaults (like default_show_returning)
    core.db.init_db()
    
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='default_show_returning'")
    assert cursor.fetchone()[0] == "0"
    conn.close()
    
    # Cleanup
    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        os.remove(temp_path)

def test_init_db_adds_missing_columns():
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    
    # Create database with a legacy cache table structure (missing columns)
    conn = sqlite3.connect(temp_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    # cache missing poster_url, rating_imdb, rating_metacritic, rating_rt, is_in_library
    cursor.execute("CREATE TABLE cache (id INTEGER PRIMARY KEY, type TEXT, title TEXT, year INTEGER)")
    conn.commit()
    conn.close()
    
    # Run init_db which should migrate columns
    core.db.init_db()
    
    # Inspect new columns
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(cache)")
    columns = [col["name"] for col in cursor.fetchall()]
    conn.close()
    
    assert "poster_url" in columns
    assert "rating_imdb" in columns
    assert "rating_metacritic" in columns
    assert "rating_rt" in columns
    assert "is_in_library" in columns
    assert "has_new_metadata" in columns
    
    # Cleanup
    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        os.remove(temp_path)

def test_settings_get_set(temp_db):
    core.db.set_setting("test_key", "test_val")
    assert core.db.get_setting("test_key") == "test_val"
    assert core.db.get_setting("non_existent", "default_val") == "default_val"
    
    all_settings = core.db.get_all_settings()
    assert all_settings["test_key"] == "test_val"

def test_normalize_title():
    assert core.db.normalize_title("A.B. C! & D-E 2026") == "abcandde"
    assert core.db.normalize_title("Rivals: Season 1", is_tv=True) == "rivals"
    assert core.db.normalize_title("Rivals: Season One", is_tv=True) == "rivals"
    assert core.db.normalize_title("Slow Horses - Season 4", is_tv=True) == "slowhorses"
    assert core.db.normalize_title("Only Murders in the Building (Season 3)", is_tv=True) == "onlymurdersinthebuilding"
    assert core.db.clean_tv_title("The White Lotus: Season 3") == "The White Lotus"

def test_cache_crud(temp_db):
    # Pre-seed settings
    core.db.set_setting("default_match_ignore_year", "0")
    
    item = {
        "title": "Antigravity Movie",
        "year": 2026,
        "imdbId": "tt1234567",
        "tmdbId": 123456,
        "genres": ["Sci-Fi", "Action"],
        "plot": "An anti-gravity movie.",
        "date_obj": datetime(2026, 5, 29),
        "date_str": "May 29, 2026",
        "rating_imdb": "8.5",
        "is_in_library": False
    }
    
    # 1. Add item
    core.db.add_cached_item("movie", item)
    
    # 2. Get item (Exact year match / IMDb ID match)
    cached = core.db.get_cached_item("movie", "Antigravity Movie", 2026, "tt1234567")
    assert cached is not None
    assert cached["title"] == "Antigravity Movie"
    assert cached["year"] == 2026
    assert bool(cached["is_in_library"]) is False
    
    # 3. Get item (Title match within 1 year range, settings = ignore_year = 0)
    cached_range = core.db.get_cached_item("movie", "Antigravity Movie", 2027)
    assert cached_range is not None
    
    # 4. Get item (Should return None if year exceeds 1 year difference and ignore_year = 0)
    cached_none = core.db.get_cached_item("movie", "Antigravity Movie", 2029)
    assert cached_none is None
    
    # 5. Get item (Should match even with large year gap if ignore_year = 1)
    core.db.set_setting("default_match_ignore_year", "1")
    cached_ignore = core.db.get_cached_item("movie", "Antigravity Movie", 2029)
    assert cached_ignore is not None
    
    # 5b. Get item when settings key default_match_ignore_year is deleted
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM settings WHERE key='default_match_ignore_year'")
    conn.commit()
    conn.close()
    # It should fallback to ignore_year = True
    cached_fallback = core.db.get_cached_item("movie", "Antigravity Movie", 2029)
    assert cached_fallback is not None
    
    # 6. Update existing item
    item["plot"] = "Updated plot summary."
    item["date_obj"] = "2026-05-29" # Pass as string to cover branch
    core.db.add_cached_item("movie", item)
    updated = core.db.get_cached_item("movie", "Antigravity Movie", 2026, "tt1234567")
    assert updated["description"] == "Updated plot summary."
    
    # 6b. Update item when date_obj is None/missing
    item["date_obj"] = None
    core.db.add_cached_item("movie", item)
    
    # 7. Update library status (False to True transitions)
    core.db.update_cached_library_status("movie", "Antigravity Movie", 2026, True, "tt1234567")
    updated_lib = core.db.get_cached_item("movie", "Antigravity Movie", 2026, "tt1234567")
    assert bool(updated_lib["is_in_library"]) is True
    
    # 7b. Attempt to transition back to False (should be ignored / remain True)
    core.db.update_cached_library_status("movie", "Antigravity Movie", 2026, False, "tt1234567")
    updated_lib2 = core.db.get_cached_item("movie", "Antigravity Movie", 2026, "tt1234567")
    assert bool(updated_lib2["is_in_library"]) is True
    
    # 7c. Update library status for non-existent item (covers no-op branch)
    core.db.update_cached_library_status("movie", "Non Existent Movie", 2026, True)

def test_archive_cached_item(temp_db):
    # Archive non-existent item (with raw_item skeleton and date_obj as string)
    raw_item = {
        "imdb_id": "tt7654321",
        "genres": ["Comedy"],
        "date_obj": "2026-01-01",
        "is_returning": True,
        "is_in_library": True
    }
    core.db.archive_cached_item("tv", "Test Show", 2026, is_archived=True, raw_item=raw_item)
    cached = core.db.get_cached_item("tv", "Test Show", 2026, "tt7654321")
    assert cached is not None
    assert bool(cached["is_archived"]) is True
    
    # Archive non-existent item (with raw_item skeleton and date_obj as datetime)
    raw_item_dt = {
        "imdb_id": "tt7654322",
        "genres": ["Drama"],
        "date_obj": datetime(2026, 1, 1),
        "is_returning": False,
        "is_in_library": False
    }
    core.db.archive_cached_item("tv", "Test Show 2", 2026, is_archived=True, raw_item=raw_item_dt)
    
    # Archive non-existent item (with raw_item skeleton and date_obj missing)
    raw_item_no_date = {
        "imdb_id": "tt7654323",
        "genres": ["Sci-Fi"]
    }
    core.db.archive_cached_item("tv", "Test Show 3", 2026, is_archived=True, raw_item=raw_item_no_date)
    
    # Archive non-existent item (no raw_item)
    core.db.archive_cached_item("movie", "Test Show No Raw", 2026, is_archived=True)
    cached_no_raw = core.db.get_cached_item("movie", "Test Show No Raw", 2026)
    assert cached_no_raw is not None
    assert bool(cached_no_raw["is_archived"]) is True
    
    # Archive existing item
    core.db.archive_cached_item("tv", "Test Show", 2026, is_archived=False, raw_item=raw_item)
    cached_unarchived = core.db.get_cached_item("tv", "Test Show", 2026, "tt7654321")
    assert bool(cached_unarchived["is_archived"]) is False

def test_clean_expired_cache(temp_db):
    # Running clean when cache is empty (covers deleted = 0 branch)
    core.db.clean_expired_cache()
    
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    
    # 1. Insert item that is expired from premiere date (date_obj)
    old_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    cursor.execute('''
        INSERT INTO cache (type, title, year, date_obj, added_at, normalized_title)
        VALUES ('movie', 'Expired Movie', 2024, ?, ?, ?)
    ''', (old_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), core.db.normalize_title("Expired Movie", is_tv=False)))
    
    # 2. Insert item that is expired by added_at (date_obj is 1900-01-01)
    old_added_at = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO cache (type, title, year, date_obj, added_at, normalized_title)
        VALUES ('tv', 'Expired TV', 2024, '1900-01-01', ?, ?)
    ''', (old_added_at, core.db.normalize_title("Expired TV", is_tv=True)))
    
    # 3. Insert item that is NOT expired
    recent_added_at = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO cache (type, title, year, date_obj, added_at, normalized_title)
        VALUES ('tv', 'Recent TV', 2026, '1900-01-01', ?, ?)
    ''', (recent_added_at, core.db.normalize_title("Recent TV", is_tv=True)))
    
    conn.commit()
    conn.close()
    
    # Clean expired (covers deleted > 0 branch)
    core.db.clean_expired_cache()
    
    # Verify Expired are deleted, Recent remains
    assert core.db.get_cached_item("movie", "Expired Movie", 2024) is None
    assert core.db.get_cached_item("tv", "Expired TV", 2024) is None
    assert core.db.get_cached_item("tv", "Recent TV", 2026) is not None

def test_cache_stats_and_clear(temp_db):
    # Add dummy cache row
    core.db.archive_cached_item("movie", "Stat Movie 1", 2026, is_archived=True)
    core.db.archive_cached_item("movie", "Stat Movie 2", 2026, is_archived=False)
    
    stats = core.db.get_cache_stats()
    assert stats["total_discoveries"] == 2
    assert stats["archived_discoveries"] == 1
    assert stats["database_size"] != "Unknown"
    
    # Test large file size formatting (MB branch)
    with patch("os.path.getsize", return_value=3_000_000):
        mb_stats = core.db.get_cache_stats()
        assert "MB" in mb_stats["database_size"]
        
    # Test file size fallback by patching os.path.getsize to raise an error
    with patch("os.path.getsize", side_effect=Exception()):
        err_stats = core.db.get_cache_stats()
        assert err_stats["database_size"] == "Unknown"
        
    # Clear cache
    core.db.clear_all_cache()
    stats_cleared = core.db.get_cache_stats()
    assert stats_cleared["total_discoveries"] == 0

def test_get_cached_discoveries(temp_db):
    # Insert two cached discoveries
    item1 = {
        "title": "Movie 1",
        "year": 2026,
        "date_obj": datetime(2026, 6, 1),
    }
    item2 = {
        "title": "Show 1",
        "year": 2026,
        "date_obj": datetime(2026, 6, 5),
    }
    core.db.add_cached_item("movie", item1)
    core.db.add_cached_item("tv", item2)
    
    tv, movies = core.db.get_cached_discoveries("2026-06-01", "2026-06-10")
    assert len(tv) == 1
    assert len(movies) == 1
    assert tv[0]["title"] == "Show 1"
    assert movies[0]["title"] == "Movie 1"


def test_db_frozen_path():
    import sys
    import importlib
    
    old_db_path = core.db.DB_PATH
    old_frozen = getattr(sys, 'frozen', None)
    sys.frozen = True
    try:
        importlib.reload(core.db)
        from pathlib import Path
        expected = Path(sys.executable).resolve().parent / "xarrtools.db"
        assert core.db.DB_PATH == expected
    finally:
        if old_frozen is None:
            if hasattr(sys, 'frozen'):
                del sys.frozen
        else:
            sys.frozen = old_frozen
        importlib.reload(core.db)
        core.db.DB_PATH = old_db_path

def test_db_default_profile_settings_seeds(temp_db):
    assert core.db.get_setting("radarr_default_profile_id") == ""
    assert core.db.get_setting("sonarr_default_profile_id") == ""


def test_init_db_creates_has_new_metadata_column(temp_db):
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(cache)")
    cols = {col["name"]: col["type"] for col in cursor.fetchall()}
    conn.close()
    assert "has_new_metadata" in cols
    assert "INTEGER" in cols["has_new_metadata"].upper()


def test_init_db_migrates_legacy_cache_table_missing_has_new_metadata():
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    try:
        # Create legacy cache table without has_new_metadata
        conn = sqlite3.connect(temp_path)
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("""
            CREATE TABLE cache (
                id INTEGER PRIMARY KEY, type TEXT, title TEXT, year INTEGER,
                is_archived INTEGER DEFAULT 0
            )
        """)
        conn.execute("INSERT INTO cache (type, title, year, is_archived) VALUES ('movie', 'Legacy Movie', 2024, 0)")
        conn.commit()
        conn.close()

        # Run init_db migration
        core.db.init_db()

        # Verify column added
        conn = core.db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(cache)")
        col_names = [col["name"] for col in cursor.fetchall()]
        assert "has_new_metadata" in col_names

        # Verify existing row can be fetched and default value is 0 (or coerced to 0)
        cursor.execute("SELECT id, title, has_new_metadata FROM cache WHERE title = 'Legacy Movie'")
        row = cursor.fetchone()
        assert row["has_new_metadata"] in (0, None)
        conn.close()
    finally:
        core.db.DB_PATH = old_db_path
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_add_cached_item_auto_archiving_on_insert(temp_db):
    # Insert item with low metadata (missing network and plot -> 2 missing)
    low_meta_item = {
        "title": "Low Meta Movie",
        "year": 2026,
        "network": "Unknown",
        "cast": "Actor One",
        "plot": "No plot summary available.",
    }
    core.db.add_cached_item("movie", low_meta_item)
    cached = core.db.get_cached_item("movie", "Low Meta Movie", 2026)
    assert cached is not None
    assert cached["is_archived"] == 1
    assert cached["has_new_metadata"] == 0


def test_add_cached_item_rich_metadata_unarchived_on_insert(temp_db):
    rich_item = {
        "title": "Rich Movie",
        "year": 2026,
        "network": "Universal Pictures",
        "cast": "Actor One, Actor Two",
        "plot": "An exciting cinematic storyline.",
    }
    core.db.add_cached_item("movie", rich_item)
    cached = core.db.get_cached_item("movie", "Rich Movie", 2026)
    assert cached is not None
    assert cached["is_archived"] == 0
    assert cached["has_new_metadata"] == 0


def test_add_cached_item_smart_unarchiving_on_update(temp_db):
    # 1. Insert item as low-metadata (auto-archived)
    low_item = {
        "title": "Smart Show",
        "year": 2026,
        "network": "Unknown",
        "cast": "Unknown",
        "plot": "Unknown",
    }
    core.db.add_cached_item("tv", low_item)
    cached_1 = core.db.get_cached_item("tv", "Smart Show", 2026)
    assert cached_1["is_archived"] == 1
    assert cached_1["has_new_metadata"] == 0

    # 2. Rescan/update item with newly discovered rich metadata
    enriched_item = {
        "title": "Smart Show",
        "year": 2026,
        "network": "Apple TV+",
        "cast": "Gary Oldman, Jack Lowden",
        "plot": "A team of British intelligence agents serve in Slough House.",
    }
    core.db.add_cached_item("tv", enriched_item)
    cached_2 = core.db.get_cached_item("tv", "Smart Show", 2026)
    assert cached_2["is_archived"] == 0        # AUTO-UNARCHIVED!
    assert cached_2["has_new_metadata"] == 1   # NEW METADATA BADGE SET!


def test_add_cached_item_preserves_badge_on_subsequent_updates(temp_db):
    # 1. Create unarchived badged item
    low_item = {"title": "Badge Item", "year": 2026, "network": "Unknown", "cast": "Unknown", "plot": "Unknown"}
    core.db.add_cached_item("movie", low_item)
    rich_item = {"title": "Badge Item", "year": 2026, "network": "HBO", "cast": "Actor A", "plot": "Plot B"}
    core.db.add_cached_item("movie", rich_item)
    cached = core.db.get_cached_item("movie", "Badge Item", 2026)
    assert cached["has_new_metadata"] == 1

    # 2. Update with rich metadata again (should keep badge)
    rich_item["plot"] = "Updated rich plot."
    core.db.add_cached_item("movie", rich_item)
    cached_again = core.db.get_cached_item("movie", "Badge Item", 2026)
    assert cached_again["is_archived"] == 0
    assert cached_again["has_new_metadata"] == 1


def test_add_cached_item_clears_badge_on_degraded_metadata(temp_db):
    # 1. Create unarchived badged item
    low_item = {"title": "Degraded Item", "year": 2026, "network": "Unknown", "cast": "Unknown", "plot": "Unknown"}
    core.db.add_cached_item("movie", low_item)
    rich_item = {"title": "Degraded Item", "year": 2026, "network": "HBO", "cast": "Actor A", "plot": "Plot B"}
    core.db.add_cached_item("movie", rich_item)
    cached = core.db.get_cached_item("movie", "Degraded Item", 2026)
    assert cached["has_new_metadata"] == 1

    # 2. Rescan with degraded / low metadata
    degraded = {"title": "Degraded Item", "year": 2026, "network": "Unknown", "cast": "Unknown", "plot": "Unknown"}
    core.db.add_cached_item("movie", degraded)
    cached_degraded = core.db.get_cached_item("movie", "Degraded Item", 2026)
    assert cached_degraded["is_archived"] == 1
    assert cached_degraded["has_new_metadata"] == 0


def test_archive_cached_item_resets_has_new_metadata_flag(temp_db):
    # 1. Create an item that has has_new_metadata = 1
    low_item = {"title": "Badge Reset Item", "year": 2026, "network": "Unknown", "cast": "Unknown", "plot": "Unknown"}
    core.db.add_cached_item("movie", low_item)
    rich_item = {"title": "Badge Reset Item", "year": 2026, "network": "HBO", "cast": "Actor A", "plot": "Plot B"}
    core.db.add_cached_item("movie", rich_item)
    
    cached = core.db.get_cached_item("movie", "Badge Reset Item", 2026)
    assert cached["is_archived"] == 0
    assert cached["has_new_metadata"] == 1

    # 2. Manually re-archive the item
    core.db.archive_cached_item("movie", "Badge Reset Item", 2026, is_archived=True)
    
    cached_archived = core.db.get_cached_item("movie", "Badge Reset Item", 2026)
    assert cached_archived["is_archived"] == 1
    assert cached_archived["has_new_metadata"] == 0  # BADGE RESET TO 0!


def test_archive_cached_item_skeleton_has_zero_badge(temp_db):
    # Archive skeleton item with raw_item
    raw_item = {"imdb_id": "tt8888888", "network": "Unknown", "cast": "Unknown"}
    core.db.archive_cached_item("tv", "Skeleton Show", 2026, is_archived=True, raw_item=raw_item)
    cached = core.db.get_cached_item("tv", "Skeleton Show", 2026, "tt8888888")
    assert cached["is_archived"] == 1
    assert cached["has_new_metadata"] == 0

    # Archive skeleton item without raw_item
    core.db.archive_cached_item("tv", "Skeleton Show 2", 2026, is_archived=True)
    cached2 = core.db.get_cached_item("tv", "Skeleton Show 2", 2026)
    assert cached2["is_archived"] == 1
    assert cached2["has_new_metadata"] == 0


def test_get_cached_discoveries_includes_has_new_metadata(temp_db):
    low_item = {
        "title": "Discovery Show",
        "year": 2026,
        "network": "Unknown",
        "cast": "Unknown",
        "plot": "Unknown",
        "date_obj": datetime(2026, 6, 1),
    }
    core.db.add_cached_item("tv", low_item)
    rich_item = {
        "title": "Discovery Show",
        "year": 2026,
        "network": "HBO",
        "cast": "Actor A",
        "plot": "Plot B",
        "date_obj": datetime(2026, 6, 1),
    }
    core.db.add_cached_item("tv", rich_item)

    tv, movies = core.db.get_cached_discoveries("2026-06-01", "2026-06-10")
    assert len(tv) == 1
    assert tv[0]["title"] == "Discovery Show"
    assert tv[0]["has_new_metadata"] == 1



def _full_item(**over):
    item = {
        "title": "Manual Archive Show", "year": 2026, "network": "HBO",
        "cast": "A Actor, B Actor", "plot": "A full plot.", "poster_url": "p.jpg",
        "genres": ["Drama"], "date_str": "Dec 01, 2026", "date_obj": "2026-12-01",
    }
    item.update(over)
    return item


def test_manual_archive_not_resurfaced_by_enrichment(temp_db):
    # Low-metadata item is auto-archived, then archived by hand
    low = _full_item(network="Unknown", cast="", plot="")
    core.db.add_cached_item("tv", low)
    core.db.archive_cached_item("tv", "Manual Archive Show", 2026, True)

    # Later enrichment fills in all metadata: must stay archived, no 'new metadata' badge
    core.db.add_cached_item("tv", _full_item())
    row = core.db.get_cached_item("tv", "Manual Archive Show", 2026)
    assert row["is_archived"] == 1
    assert row["has_new_metadata"] == 0
    assert row["manually_archived"] == 1


def test_auto_archive_still_resurfaces_when_not_manual(temp_db):
    core.db.add_cached_item("tv", _full_item(network="Unknown", cast="", plot=""))
    assert core.db.get_cached_item("tv", "Manual Archive Show", 2026)["is_archived"] == 1

    core.db.add_cached_item("tv", _full_item())
    row = core.db.get_cached_item("tv", "Manual Archive Show", 2026)
    assert row["is_archived"] == 0
    assert row["has_new_metadata"] == 1
    assert row["manually_archived"] == 0


def test_manual_unarchive_clears_flag_and_allows_auto_archive_again(temp_db):
    core.db.add_cached_item("tv", _full_item())
    core.db.archive_cached_item("tv", "Manual Archive Show", 2026, True)
    core.db.archive_cached_item("tv", "Manual Archive Show", 2026, False)
    row = core.db.get_cached_item("tv", "Manual Archive Show", 2026)
    assert row["is_archived"] == 0 and row["manually_archived"] == 0


def test_manual_archive_flag_backfill_on_existing_db(temp_db):
    # Simulate a pre-migration DB: drop the column by rebuilding the table state
    conn = core.db.get_db_connection()
    core.db.add_cached_item("tv", _full_item(title="Hand Archived"))
    core.db.add_cached_item("tv", _full_item(title="Auto Archived", network="Unknown", cast="", plot=""))
    conn.execute("UPDATE cache SET is_archived = 1 WHERE title = 'Hand Archived'")
    conn.execute("ALTER TABLE cache DROP COLUMN manually_archived")
    conn.close()

    core.db.init_db()  # re-adds the column and backfills
    conn = core.db.get_db_connection()
    rows = {r["title"]: r["manually_archived"] for r in conn.execute("SELECT title, manually_archived FROM cache")}
    conn.close()
    assert rows["Hand Archived"] == 1   # archived but complete metadata -> must be manual
    assert rows["Auto Archived"] == 0   # low metadata -> ambiguous, treated as auto


def test_tmdb_feed_default_and_letterboxd_migration(temp_db):
    # Fresh DB: TMDB is a default, Letterboxd is not
    conn = core.db.get_db_connection()
    types = [r["feed_type"] for r in conn.execute("SELECT feed_type FROM custom_feeds")]
    assert "tmdb_movies" in types
    assert conn.execute("SELECT COUNT(*) FROM custom_feeds WHERE url = ?", (core.db.LETTERBOXD_DEFAULT_URL,)).fetchone()[0] == 0

    # Simulate a pre-migration DB: legacy Letterboxd feed present, TMDB feed + migration flag absent
    conn.execute("DELETE FROM custom_feeds WHERE feed_type = 'tmdb_movies'")
    conn.execute("DELETE FROM settings WHERE key = 'migrated_tmdb_feed'")
    conn.execute(
        "INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config) "
        "VALUES ('Letterboxd', ?, 'rss', 'movie', 1, '{}', '{}')", (core.db.LETTERBOXD_DEFAULT_URL,))
    conn.execute(
        "INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config) "
        "VALUES ('My Custom RSS', 'https://example.com/feed.xml', 'rss', 'movie', 1, '{}', '{}')")
    conn.close()

    core.db.init_db()
    conn = core.db.get_db_connection()
    urls = [r["url"] for r in conn.execute("SELECT url FROM custom_feeds")]
    types = [r["feed_type"] for r in conn.execute("SELECT feed_type FROM custom_feeds")]
    conn.close()
    assert core.db.LETTERBOXD_DEFAULT_URL not in urls          # legacy default removed
    assert "https://example.com/feed.xml" in urls              # user's own feed untouched
    assert types.count("tmdb_movies") == 1                     # TMDB added exactly once

    # Running again must not re-add a TMDB feed the user deleted
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM custom_feeds WHERE feed_type = 'tmdb_movies'")
    conn.close()
    core.db.init_db()
    conn = core.db.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM custom_feeds WHERE feed_type = 'tmdb_movies'").fetchone()[0] == 0
    conn.close()


def test_cache_language_country_roundtrip_and_preservation(temp_db):
    item = {"title": "Locale Show", "year": 2026, "date_str": "Dec 01", "date_obj": "2026-12-01",
            "plot": "p", "country": "KR", "language": "Korean"}
    core.db.add_cached_item("tv", item)
    row = core.db.get_cached_item("tv", "Locale Show", 2026)
    assert row["country"] == "KR" and row["language"] == "Korean"

    # a later update without locale data must not wipe the stored values
    core.db.add_cached_item("tv", dict(item, country="", language=""))
    row = core.db.get_cached_item("tv", "Locale Show", 2026)
    assert row["country"] == "KR" and row["language"] == "Korean"

    # a new non-empty value overrides
    core.db.add_cached_item("tv", dict(item, country="JP", language="Japanese"))
    row = core.db.get_cached_item("tv", "Locale Show", 2026)
    assert row["country"] == "JP" and row["language"] == "Japanese"


def test_init_db_adds_locale_columns_to_old_schema(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("ALTER TABLE cache DROP COLUMN country")
    conn.execute("ALTER TABLE cache DROP COLUMN language")
    conn.commit()
    conn.close()
    core.db.init_db()
    conn = sqlite3.connect(temp_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cache)")}
    conn.close()
    assert {"country", "language"} <= cols


def test_non_latin_titles_cached_separately_and_renormalized(temp_db):
    core.db.add_cached_item("movie", {"title": "Οβολός", "year": 2026, "date_obj": "2026-12-03", "plot": "p"})
    core.db.add_cached_item("movie", {"title": "Άλλη Ταινία", "year": 2026, "date_obj": "2026-12-04", "plot": "p"})
    assert core.db.get_cached_item("movie", "Οβολός", 2026)["title"] == "Οβολός"
    assert core.db.get_cached_item("movie", "Άλλη Ταινία", 2026)["title"] == "Άλλη Ταινία"
    assert core.db.get_cached_item("movie", "Τρίτη", 2026) is None

    # legacy rows stored with an empty key are repaired once by init_db
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE cache SET normalized_title = ''")
    conn.execute("DELETE FROM settings WHERE key = 'migrated_unicode_norm'")
    conn.commit(); conn.close()
    core.db.init_db()
    conn = sqlite3.connect(temp_db)
    norms = {r[0] for r in conn.execute("SELECT normalized_title FROM cache")}
    conn.close()
    assert "" not in norms and len(norms) == 2
