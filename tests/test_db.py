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
    assert core.db.normalize_title("A.B. C! & D-E 2026") == "abcde"
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
        INSERT INTO cache (type, title, year, date_obj, added_at)
        VALUES ('movie', 'Expired Movie', 2024, ?, ?)
    ''', (old_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    # 2. Insert item that is expired by added_at (date_obj is 1900-01-01)
    old_added_at = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO cache (type, title, year, date_obj, added_at)
        VALUES ('tv', 'Expired TV', 2024, '1900-01-01', ?)
    ''', (old_added_at,))
    
    # 3. Insert item that is NOT expired
    recent_added_at = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO cache (type, title, year, date_obj, added_at)
        VALUES ('tv', 'Recent TV', 2026, '1900-01-01', ?)
    ''', (recent_added_at,))
    
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
