import sqlite3
import os
import json
import re
from pathlib import Path
from datetime import datetime, timedelta

# Store database in the project root folder
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
            is_returning INTEGER DEFAULT 0,
            is_archived INTEGER DEFAULT 0,
            added_at TEXT
        )
    ''')
    conn.commit()
    
    # 3. Migrate from .env if settings table is empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        # Import config dynamically to bypass circular dependency
        from xarrtools.config import config
        env_settings = {
            "radarr_url": config.radarr_url,
            "radarr_api_key": config.radarr_api_key,
            "sonarr_url": config.sonarr_url,
            "sonarr_api_key": config.sonarr_api_key,
            "default_past_months": "1",
            "default_future_months": "2",
            "default_show_returning": "0",
            "default_show_library": "0",
            "default_show_archived": "0"
        }
        for key, val in env_settings.items():
            if val is not None:
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
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

def normalize_title(title: str) -> str:
    """Normalizes title for comparison (same as scraper.py)."""
    return re.sub(r'[^a-z0-9]', '', title.lower())

def get_cached_item(type_: str, title: str, year: int, imdb_id: str = None) -> dict:
    """Retrieves a cached movie or TV show by IMDb ID or normalized title + year."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if imdb_id:
        cursor.execute("SELECT * FROM cache WHERE imdb_id = ?", (imdb_id,))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)
            
    cursor.execute("SELECT * FROM cache WHERE type = ? AND year = ?", (type_, year))
    rows = cursor.fetchall()
    conn.close()
    
    norm_title = normalize_title(title)
    for row in rows:
        if normalize_title(row["title"]) == norm_title:
            return dict(row)
            
    return None

def add_cached_item(type_: str, item: dict):
    """Caches or updates a media discovery details item."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if already exists in cache
    cursor.execute("SELECT id FROM cache WHERE type = ? AND title = ? AND year = ?", (type_, item["title"], item["year"]))
    row = cursor.fetchone()
    
    genres_json = json.dumps(item.get("genres", []))
    imdb_id = item.get("imdbId") or item.get("imdb_id")
    tvdb_id = item.get("tvdbId") or item.get("tvdb_id")
    tmdb_id = item.get("tmdbId") or item.get("tmdb_id")
    
    date_obj_str = ""
    if item.get("date_obj"):
        if isinstance(item["date_obj"], datetime):
            date_obj_str = item["date_obj"].strftime("%Y-%m-%d")
        else:
            date_obj_str = str(item["date_obj"])
            
    if row:
        cursor.execute('''
            UPDATE cache SET
                date_str = ?, date_obj = ?, description = ?, href = ?, imdb_id = ?,
                tvdb_id = ?, tmdb_id = ?, genres = ?, cast = ?, network = ?, trailer = ?,
                is_returning = ?, added_at = ?
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
            1 if item.get("is_returning") else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            row[0]
        ))
    else:
        cursor.execute('''
            INSERT INTO cache (
                type, title, year, date_str, date_obj, description, href, imdb_id,
                tvdb_id, tmdb_id, genres, cast, network, trailer, is_returning, is_archived, added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            1 if item.get("is_returning") else 0,
            1 if item.get("is_archived") else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
    conn.commit()
    conn.close()

def archive_cached_item(type_: str, title: str, year: int, is_archived: bool = True, raw_item: dict = None):
    """Sets the is_archived flag on a cached discovery. Inserts a skeleton if not in cache."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM cache WHERE type = ? AND title = ? AND year = ?", (type_, title, year))
    row = cursor.fetchone()
    
    archived_val = 1 if is_archived else 0
    
    if row:
        cursor.execute("UPDATE cache SET is_archived = ? WHERE id = ?", (archived_val, row[0]))
    else:
        if raw_item:
            genres_json = json.dumps(raw_item.get("genres", []))
            imdb_id = raw_item.get("imdbId") or raw_item.get("imdb_id")
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
                    tvdb_id, tmdb_id, genres, cast, network, trailer, is_returning, is_archived, added_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1 if raw_item.get("is_returning") else 0,
                archived_val,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
        else:
            cursor.execute('''
                INSERT INTO cache (type, title, year, is_archived, added_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (type_, title, year, archived_val, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
    conn.commit()
    conn.close()

def clean_expired_cache():
    """Removes cached discoveries older than 12 months (365 days)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    limit = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("DELETE FROM cache WHERE added_at < ?", (limit,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        print(f"Purged {deleted} expired entries from cache.")
