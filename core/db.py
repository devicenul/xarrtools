import sqlite3
import os
import json
import re
from pathlib import Path
from datetime import datetime, timedelta

import sys

# Store database in the project root folder (or executable directory if compiled)
if getattr(sys, 'frozen', False):
    DB_PATH = Path(sys.executable).resolve().parent / "xarrtools.db"
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "xarrtools.db"

def get_db_connection():
    """Establishes and returns a connection to the SQLite database with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates settings and cache tables, and migrates existing .env variables if empty."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Create Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # 2. Create Cache table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            title TEXT,
            year INTEGER,
            date_str TEXT,
            date_obj TEXT,
            description TEXT,
            href TEXT,
            imdb_id TEXT,
            tvdb_id INTEGER,
            tmdb_id INTEGER,
            genres TEXT,
            cast TEXT,
            network TEXT,
            trailer TEXT,
            poster_url TEXT,
            is_returning INTEGER DEFAULT 0,
            is_archived INTEGER DEFAULT 0,
            added_at TEXT
        )
    ''')
    conn.commit()
    
    # 2b. Add poster_url to cache table if not present (migration for existing database)
    cursor.execute("PRAGMA table_info(cache)")
    columns = [col[1] for col in cursor.fetchall()]
    if "poster_url" not in columns:
        cursor.execute("ALTER TABLE cache ADD COLUMN poster_url TEXT")
        conn.commit()
    
    # 2c. Add rating columns to cache table if not present (migration for existing database)
    cursor.execute("PRAGMA table_info(cache)")
    columns = [col[1] for col in cursor.fetchall()]
    if "rating_imdb" not in columns:
        cursor.execute("ALTER TABLE cache ADD COLUMN rating_imdb TEXT")
        conn.commit()
    if "rating_metacritic" not in columns:
        cursor.execute("ALTER TABLE cache ADD COLUMN rating_metacritic TEXT")
        conn.commit()
    if "rating_rt" not in columns:
        cursor.execute("ALTER TABLE cache ADD COLUMN rating_rt TEXT")
        conn.commit()
        
    # 2d. Add is_in_library column to cache table if not present (migration for existing database)
    cursor.execute("PRAGMA table_info(cache)")
    columns = [col[1] for col in cursor.fetchall()]
    if "is_in_library" not in columns:
        cursor.execute("ALTER TABLE cache ADD COLUMN is_in_library INTEGER DEFAULT 0")
        conn.commit()
    
    # 3. Migrate from .env if settings table is empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        # Import config dynamically to bypass circular dependency
        from core.config import config
        env_settings = {
            "radarr_url": config.radarr_url,
            "radarr_api_key": config.radarr_api_key,
            "sonarr_url": config.sonarr_url,
            "sonarr_api_key": config.sonarr_api_key,
            "default_past_months": "1",
            "default_future_months": "2",
            "default_show_returning": "0",
            "default_show_library": "0",
            "default_show_archived": "0",
            "default_match_ignore_year": "1"
        }
        for key, val in env_settings.items():
            if val is not None:
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
        conn.commit()
        
    # 4. Ensure any missing default settings are seeded (e.g. if database already exists)
    default_settings = {
        "default_past_months": "1",
        "default_future_months": "2",
        "default_show_returning": "0",
        "default_show_library": "0",
        "default_show_archived": "0",
        "default_match_ignore_year": "1"
    }
    for key, val in default_settings.items():
        cursor.execute("SELECT COUNT(*) FROM settings WHERE key = ?", (key,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit()
        
    conn.close()

def get_setting(key: str, default: str = "") -> str:
    """Fetches a setting value by key."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    """Inserts or updates a setting key-value pair."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings() -> dict:
    """Returns all settings as a flat dictionary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def clean_tv_title(title: str) -> str:
    """Strips season descriptors, years, or format suffixes from TV show titles."""
    title = title.strip()
    # 1. Remove "Season X" patterns: e.g. ": Season 1", " - Season 2", " (Season 3)"
    # Also handles words like "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"
    # Case-insensitive
    pattern = r'\s*[:\-\(]?\s*season\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*\)?'
    title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    
    # 2. Remove other common TV series qualifiers: " Series 1", " The Complete Series", " - Series", " (Series)"
    pattern_series = r'\s*[:\-\(]?\s*(the\s+)?complete\s+series\s*\)?'
    title = re.sub(pattern_series, '', title, flags=re.IGNORECASE)
    
    pattern_series_num = r'\s*[:\-\(]?\s*series\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*\)?'
    title = re.sub(pattern_series_num, '', title, flags=re.IGNORECASE)
    
    # 3. Clean any trailing punctuation or whitespace
    title = re.sub(r'[\s:\-\(\),]+$', '', title).strip()
    return title

def clean_movie_title(title: str) -> str:
    """Strips common release format suffixes, brackets, or parenthetical packaging descriptors."""
    title = title.strip()
    
    # 1. Strip common formats inside brackets or parentheses at the end:
    # E.g. " [Digital]", " (Digital)", " [4K UHD]", " (4K Ultra HD)", " (Blu-ray + DVD)"
    pattern_brackets = r'\s*[\[\(][^\]\)]*(digital|4k|uhd|ultra\s+hd|blu-ray|bluray|dvd|steelbook|hd|sd|rip|edition|cut|screen|combo|pack|disc|special)[^\]\)]*[\]\)]'
    title = re.sub(pattern_brackets, '', title, flags=re.IGNORECASE)
    
    # 2. Strip common raw suffixes that are not inside brackets/parentheses:
    suffixes = [" DVD", " Blu-ray", " BluRay", " 4K", " 3D", " Steelbook", " Digital", " 4K Ultra HD", " 4K UHD", " UHD"]
    for suffix in suffixes:
        if title.lower().endswith(suffix.lower()):
            title = title[:-len(suffix)].strip()
            
    # 3. Remove year suffixes like (2024) or [2024] at the end
    title = re.sub(r'\s*[\[\(\s]\d{4}[\]\)]?$', '', title)
            
    # 4. Clean any trailing punctuation or whitespace
    title = re.sub(r'[\s:\-\(\),\[\]]+$', '', title).strip()
    return title

def normalize_title(title: str, is_tv: bool = False) -> str:
    """Normalizes title for comparison (same as scraper.py)."""
    if is_tv:
        title = clean_tv_title(title)
    else:
        title = clean_movie_title(title)
    return re.sub(r'[^a-z0-9]', '', title.lower())

def get_cached_item(type_: str, title: str, year: int, imdb_id: str = None, conn = None) -> dict:
    """Retrieves a cached movie or TV show by IMDb ID or normalized title (ignoring year if setting enabled)."""
    local_conn = False
    if conn is None:
        conn = get_db_connection()
        local_conn = True
        
    cursor = conn.cursor()
    
    # 1. Match by IMDb ID if available
    if imdb_id:
        cursor.execute("SELECT * FROM cache WHERE imdb_id = ?", (imdb_id,))
        row = cursor.fetchone()
        if row:
            if local_conn:
                conn.close()
            return dict(row)
            
    # 2. Check default_match_ignore_year setting
    cursor.execute("SELECT value FROM settings WHERE key = 'default_match_ignore_year'")
    row_setting = cursor.fetchone()
    ignore_year = True # default on
    if row_setting:
        ignore_year = (row_setting[0] == "1")
        
    # 3. Query based on year constraint setting
    if ignore_year:
        cursor.execute("SELECT * FROM cache WHERE type = ?", (type_,))
    else:
        cursor.execute("SELECT * FROM cache WHERE type = ? AND year >= ? AND year <= ?", (type_, year - 1, year + 1))
        
    rows = cursor.fetchall()
    if local_conn:
        conn.close()
        
    is_tv = (type_ == "tv")
    norm_title = normalize_title(title, is_tv=is_tv)
    for row in rows:
        if normalize_title(row["title"], is_tv=is_tv) == norm_title:
            return dict(row)
            
    return None

def add_cached_item(type_: str, item: dict):
    """Caches or updates a media discovery details item."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    imdb_id = item.get("imdbId") or item.get("imdb_id")
    
    # Check if already exists in cache using our robust lookup
    existing = get_cached_item(type_, item["title"], item["year"], imdb_id, conn=conn)
    
    genres_json = json.dumps(item.get("genres", []))
    tvdb_id = item.get("tvdbId") or item.get("tvdb_id")
    tmdb_id = item.get("tmdbId") or item.get("tmdb_id")
    is_in_lib = 1 if item.get("is_in_library") else 0
    
    date_obj_str = ""
    if item.get("date_obj"):
        if isinstance(item["date_obj"], datetime):
            date_obj_str = item["date_obj"].strftime("%Y-%m-%d")
        else:
            date_obj_str = str(item["date_obj"])
            
    if existing:
        cursor.execute('''
            UPDATE cache SET
                date_str = ?, date_obj = ?, description = ?, href = ?, imdb_id = ?,
                tvdb_id = ?, tmdb_id = ?, genres = ?, cast = ?, network = ?, trailer = ?,
                poster_url = ?, is_returning = ?, added_at = ?,
                rating_imdb = ?, rating_metacritic = ?, rating_rt = ?, is_in_library = ?
            WHERE id = ?
        ''', (
            item.get("date_str", ""),
            date_obj_str,
            item.get("plot", "No plot summary available."),
            item.get("href", ""),
            imdb_id,
            tvdb_id,
            tmdb_id,
            genres_json,
            item.get("cast", "Cast details not available."),
            item.get("network", "Unknown"),
            item.get("trailer", ""),
            item.get("poster_url", ""),
            1 if item.get("is_returning") else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            item.get("rating_imdb", ""),
            item.get("rating_metacritic", ""),
            item.get("rating_rt", ""),
            is_in_lib,
            existing["id"]
        ))
    else:
        cursor.execute('''
            INSERT INTO cache (
                type, title, year, date_str, date_obj, description, href, imdb_id,
                tvdb_id, tmdb_id, genres, cast, network, trailer, poster_url, is_returning, is_archived, added_at,
                rating_imdb, rating_metacritic, rating_rt, is_in_library
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            type_,
            item["title"],
            item["year"],
            item.get("date_str", ""),
            date_obj_str,
            item.get("plot", "No plot summary available."),
            item.get("href", ""),
            imdb_id,
            tvdb_id,
            tmdb_id,
            genres_json,
            item.get("cast", "Cast details not available."),
            item.get("network", "Unknown"),
            item.get("trailer", ""),
            item.get("poster_url", ""),
            1 if item.get("is_returning") else 0,
            1 if item.get("is_archived") else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            item.get("rating_imdb", ""),
            item.get("rating_metacritic", ""),
            item.get("rating_rt", ""),
            is_in_lib
        ))
    conn.commit()
    conn.close()

def archive_cached_item(type_: str, title: str, year: int, is_archived: bool = True, raw_item: dict = None):
    """Sets the is_archived flag on a cached discovery. Inserts a skeleton if not in cache."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    imdb_id = None
    if raw_item:
        imdb_id = raw_item.get("imdbId") or raw_item.get("imdb_id")
        
    existing = get_cached_item(type_, title, year, imdb_id, conn=conn)
    
    archived_val = 1 if is_archived else 0
    
    if existing:
        cursor.execute("UPDATE cache SET is_archived = ? WHERE id = ?", (archived_val, existing["id"]))
    else:
        if raw_item:
            genres_json = json.dumps(raw_item.get("genres", []))
            tvdb_id = raw_item.get("tvdbId") or raw_item.get("tvdb_id")
            tmdb_id = raw_item.get("tmdbId") or raw_item.get("tmdb_id")
            
            date_obj_str = ""
            if raw_item.get("date_obj"):
                if isinstance(raw_item["date_obj"], datetime):
                    date_obj_str = raw_item["date_obj"].strftime("%Y-%m-%d")
                else:
                    date_obj_str = str(raw_item["date_obj"])
                    
            cursor.execute('''
                INSERT INTO cache (
                    type, title, year, date_str, date_obj, description, href, imdb_id,
                    tvdb_id, tmdb_id, genres, cast, network, trailer, poster_url, is_returning, is_archived, added_at,
                    rating_imdb, rating_metacritic, rating_rt, is_in_library
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                type_, title, year,
                raw_item.get("date_str", ""),
                date_obj_str,
                raw_item.get("plot") or raw_item.get("description", "No plot summary available."),
                raw_item.get("href", ""),
                imdb_id,
                tvdb_id,
                tmdb_id,
                genres_json,
                raw_item.get("cast", "Cast details not available."),
                raw_item.get("network", "Unknown"),
                raw_item.get("trailer", ""),
                raw_item.get("poster_url", ""),
                1 if raw_item.get("is_returning") else 0,
                archived_val,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                raw_item.get("rating_imdb", ""),
                raw_item.get("rating_metacritic", ""),
                raw_item.get("rating_rt", ""),
                1 if raw_item.get("is_in_library") else 0
            ))
        else:
            cursor.execute('''
                INSERT INTO cache (type, title, year, is_archived, added_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (type_, title, year, archived_val, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
    conn.commit()
    conn.close()

def clean_expired_cache():
    """Removes cached discoveries older than 12 months (365 days) from premiere/release date."""
    conn = get_db_connection()
    cursor = conn.cursor()
    limit_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    limit_added = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        DELETE FROM cache 
        WHERE (date_obj IS NOT NULL AND date_obj != "" AND date_obj NOT LIKE '1900-01-01%' AND date_obj < ?)
           OR ((date_obj IS NULL OR date_obj = "" OR date_obj LIKE '1900-01-01%') AND added_at < ?)
    ''', (limit_date, limit_added))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        print(f"Purged {deleted} expired entries from cache.")

def get_cache_stats() -> dict:
    """Returns row counts and disk space diagnostics of the cache."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM cache")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM cache WHERE is_archived = 1")
    archived = cursor.fetchone()[0]
    
    conn.close()
    
    # Calculate disk size of database
    try:
        size_bytes = os.path.getsize(DB_PATH)
        if size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
    except Exception:
        size_str = "Unknown"
        
    return {
        "total_discoveries": total,
        "archived_discoveries": archived,
        "database_size": size_str
    }

def clear_all_cache():
    """Wipes all cached discovery details from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cache")
    conn.commit()
    conn.close()

def get_cached_discoveries(start_date: str, end_date: str) -> tuple:
    """Retrieves cached TV shows and movies with release dates in the specified range YYYY-MM-DD."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # TV shows
    cursor.execute(
        "SELECT * FROM cache WHERE type = 'tv' AND date_obj >= ? AND date_obj <= ?",
        (start_date, end_date)
    )
    tv_rows = cursor.fetchall()
    
    # Movies
    cursor.execute(
        "SELECT * FROM cache WHERE type = 'movie' AND date_obj >= ? AND date_obj <= ?",
        (start_date, end_date)
    )
    movie_rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in tv_rows], [dict(row) for row in movie_rows]

def update_cached_library_status(type_: str, title: str, year: int, is_in_library: bool, imdb_id: str = None):
    """Updates the is_in_library status for a cached item in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    existing = get_cached_item(type_, title, year, imdb_id, conn=conn)
    if existing:
        cursor.execute("UPDATE cache SET is_in_library = ? WHERE id = ?", (1 if is_in_library else 0, existing["id"]))
        conn.commit()
    conn.close()
