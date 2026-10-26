import sqlite3
import os
import json
import re
from pathlib import Path
from datetime import datetime, timedelta

import sys
from core.metadata import evaluate_item_state_transition
from core.locales import slug

# Store database in the project root folder (or executable directory if compiled)
if getattr(sys, 'frozen', False):
    DB_PATH = Path(sys.executable).resolve().parent / "xarrtools.db"
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "xarrtools.db"

TVMAZE_SCHEDULE_URL = "https://api.tvmaze.com/schedule/full"
TMDB_DISCOVER_URL = "https://api.themoviedb.org/3/discover/movie"
LETTERBOXD_DEFAULT_URL = "https://letterboxd.com/films/popular/this/week/size/small/rss/"

def get_db_connection():
    """Establishes and returns a connection to the SQLite database with Row factory."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.isolation_level = None
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def init_db():
    """Creates settings, cache, and custom_feeds tables, and migrates existing settings/columns."""
    parent_dir = DB_PATH.parent
    if not os.access(parent_dir, os.W_OK):
        print(f"ERROR: Database parent directory {parent_dir} is not writable. UID: {os.getuid()}, GID: {os.getgid()}", file=sys.stderr)
        sys.exit(1)
    if DB_PATH.exists() and not os.access(DB_PATH, os.R_OK | os.W_OK):
        print(f"ERROR: Database file {DB_PATH} is not writable. UID: {os.getuid()}, GID: {os.getgid()}", file=sys.stderr)
        sys.exit(1)

    conn = get_db_connection()
    conn.execute("PRAGMA journal_mode = WAL;")
    cursor = conn.cursor()
    
    # 1. Create Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # 2. Create Custom Feeds table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            feed_type TEXT NOT NULL,          -- 'rss', 'json', 'html'
            default_media_type TEXT NOT NULL, -- 'movie', 'tv'
            http_headers TEXT,                -- JSON dictionary structure
            parser_config TEXT NOT NULL,      -- JSON dictionary containing mappings/rules
            enabled INTEGER DEFAULT 1,        -- 0 = Disabled, 1 = Enabled
            last_run TEXT,                    -- Datetime timestamp
            last_status TEXT,                 -- 'success', 'error', 'blocked'
            last_error_message TEXT           -- Traceback or error details
        )
    ''')
    
    # 3. Create Cache table
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
            manually_archived INTEGER DEFAULT 0,
            country TEXT DEFAULT '',
            language TEXT DEFAULT '',
            has_new_metadata INTEGER DEFAULT 0,
            added_at TEXT,
            rating_imdb TEXT,
            rating_metacritic TEXT,
            rating_rt TEXT,
            is_in_library INTEGER DEFAULT 0,
            source_feed_id INTEGER REFERENCES custom_feeds(id) ON DELETE SET NULL,
            normalized_title TEXT,
            director TEXT,
            producer TEXT
        )
    ''')
    
    # Check and add columns dynamically for existing databases
    cursor.execute("PRAGMA table_info(cache)")
    columns = [col[1] for col in cursor.fetchall()]
    
    expected_cols = {
        "type": "TEXT",
        "title": "TEXT",
        "year": "INTEGER",
        "date_str": "TEXT",
        "date_obj": "TEXT",
        "description": "TEXT",
        "href": "TEXT",
        "imdb_id": "TEXT",
        "tvdb_id": "INTEGER",
        "tmdb_id": "INTEGER",
        "genres": "TEXT",
        "cast": "TEXT",
        "network": "TEXT",
        "trailer": "TEXT",
        "poster_url": "TEXT",
        "is_returning": "INTEGER DEFAULT 0",
        "is_archived": "INTEGER DEFAULT 0",
        "manually_archived": "INTEGER DEFAULT 0",
        "country": "TEXT DEFAULT ''",
        "language": "TEXT DEFAULT ''",
        "has_new_metadata": "INTEGER DEFAULT 0",
        "added_at": "TEXT",
        "rating_imdb": "TEXT",
        "rating_metacritic": "TEXT",
        "rating_rt": "TEXT",
        "is_in_library": "INTEGER DEFAULT 0",
        "source_feed_id": "INTEGER REFERENCES custom_feeds(id) ON DELETE SET NULL",
        "normalized_title": "TEXT",
        "director": "TEXT",
        "producer": "TEXT"
    }
    
    manual_flag_is_new = "manually_archived" not in columns
    for col, col_type in expected_cols.items():
        if col not in columns:
            cursor.execute(f"ALTER TABLE cache ADD COLUMN {col} {col_type}")

    if manual_flag_is_new:
        # Existing archived rows whose metadata is NOT low can't have been auto-archived,
        # so the user must have archived them by hand. (Low-metadata rows are ambiguous
        # and are left as auto-archived.)
        from core.metadata import should_auto_archive
        cursor.execute('SELECT id, title, network, "cast", description FROM cache WHERE is_archived = 1')
        for r in cursor.fetchall():
            if not should_auto_archive({"title": r["title"], "network": r["network"], "cast": r["cast"], "plot": r["description"]}):
                cursor.execute("UPDATE cache SET manually_archived = 1 WHERE id = ?", (r["id"],))

    # Expunge legacy incomplete cached items (where title, cast, and plot are all missing/placeholder)
    cursor.execute('''
        DELETE FROM cache 
        WHERE (title IS NULL OR title = '' OR title = 'Unknown')
          AND ("cast" IS NULL OR "cast" = '' OR "cast" = 'Cast details not available.')
          AND (description IS NULL OR description = '' OR description = 'No plot summary available.')
    ''')

        
    # Repair legacy cached titles with truncated trailing year parentheses (e.g. "Carrie (2026" -> "Carrie (2026)")
    cursor.execute("SELECT id, title FROM cache WHERE title LIKE '%(____'")
    for row in cursor.fetchall():
        if row["title"] and re.search(r'\(\d{4}$', row["title"]):
            cursor.execute("UPDATE cache SET title = ? WHERE id = ?", (row["title"] + ")", row["id"]))

    # Populate normalized_title for legacy cached entries
    cursor.execute("SELECT id, title, type FROM cache WHERE normalized_title IS NULL")
    rows = cursor.fetchall()
    for row in rows:
        is_tv = (row["type"] == "tv")
        norm = normalize_title(row["title"], is_tv)
        cursor.execute("UPDATE cache SET normalized_title = ? WHERE id = ?", (norm, row["id"]))
        
    # One-time: recompute normalized titles with the Unicode-aware key (non-Latin titles used to collapse to '')
    cursor.execute("SELECT value FROM settings WHERE key = 'migrated_unicode_norm'")
    if not cursor.fetchone():
        cursor.execute("SELECT id, title, type FROM cache")
        cache_rows = cursor.fetchall()
        for row in cache_rows:
            norm = normalize_title(row["title"], row["type"] == "tv")
            cursor.execute("UPDATE cache SET normalized_title = ? WHERE id = ?", (norm, row["id"]))
        if cache_rows:  # keep fresh DBs' settings table empty so default seeding still runs
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('migrated_unicode_norm', '1')")

    # Create indices
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_normalized ON cache(type, normalized_title)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_date_obj ON cache(date_obj) WHERE date_obj IS NOT NULL AND date_obj != ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_imdb_id ON cache(imdb_id) WHERE imdb_id IS NOT NULL AND imdb_id != ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_source_feed_id ON cache(source_feed_id) WHERE source_feed_id IS NOT NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_type_date_obj ON cache(type, date_obj)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_missing_poster ON cache(id) WHERE poster_url IS NULL OR poster_url = ''")
    
    # 4. Migrate from .env if settings table is empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        # Import config dynamically to bypass circular dependency
        from core.config import config
        env_settings = {
            "radarr_url": config.radarr_url,
            "radarr_api_key": config.radarr_api_key,
            "sonarr_url": config.sonarr_url,
            "sonarr_api_key": config.sonarr_api_key,
            "tmdb_api_key": config.tmdb_api_key,
            "default_past_months": "1",
            "default_future_months": "2",
            "default_show_returning": "0",
            "default_show_library": "0",
            "default_show_archived": "0",
            "default_match_ignore_year": "1",
            "radarr_default_profile_id": "",
            "sonarr_default_profile_id": ""
        }
        for key, val in env_settings.items():
            if val is not None:
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
        
    # 5. Ensure any missing default settings are seeded (e.g. if database already exists)
    default_settings = {
        "default_past_months": "1",
        "default_future_months": "2",
        "default_show_returning": "0",
        "default_show_library": "0",
        "default_show_archived": "0",
        "default_match_ignore_year": "1",
        "radarr_default_profile_id": "",
        "sonarr_default_profile_id": ""
    }
    for key, val in default_settings.items():
        cursor.execute("SELECT COUNT(*) FROM settings WHERE key = ?", (key,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))

    # Clear template placeholder API keys if previously migrated from .env.example
    cursor.execute("""
        UPDATE settings
        SET value = ''
        WHERE (key = 'radarr_api_key' AND value = 'your_radarr_api_key_here')
           OR (key = 'sonarr_api_key' AND value = 'your_sonarr_api_key_here')
    """)
            
    # 6. Ensure default feeds are seeded if the table is empty
    cursor.execute("SELECT COUNT(*) FROM custom_feeds")
    if cursor.fetchone()[0] == 0:
        restore_default_feeds(conn)

    # 7. One-time migration: add the TVmaze upcoming-premieres feed to existing databases
    cursor.execute("SELECT 1 FROM settings WHERE key = 'migrated_tvmaze_feed'")
    if not cursor.fetchone():
        cursor.execute("SELECT 1 FROM custom_feeds WHERE feed_type = 'tvmaze_schedule'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config)
                VALUES (?, ?, 'tvmaze_schedule', 'tv', 1, '{}', '{}')
            ''', ("TVmaze - Upcoming Premieres & Specials", TVMAZE_SCHEDULE_URL))
        cursor.execute("INSERT INTO settings (key, value) VALUES ('migrated_tvmaze_feed', '1')")

    # 8. One-time migration: replace the Cloudflare-blocked Letterboxd default feed with the TMDB feed
    cursor.execute("SELECT 1 FROM settings WHERE key = 'migrated_tmdb_feed'")
    if not cursor.fetchone():
        cursor.execute("DELETE FROM custom_feeds WHERE url = ?", (LETTERBOXD_DEFAULT_URL,))
        cursor.execute("SELECT 1 FROM custom_feeds WHERE feed_type = 'tmdb_movies'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config)
                VALUES (?, ?, 'tmdb_movies', 'movie', 1, '{}', '{}')
            ''', ("TMDB - Popular Upcoming & Recent Movies", TMDB_DISCOVER_URL))
        cursor.execute("INSERT INTO settings (key, value) VALUES ('migrated_tmdb_feed', '1')")
    conn.close()

def restore_default_feeds(conn=None):
    """Wipes all custom feeds and inserts the standard default feeds (Metacritic, DVDs, TVmaze, TMDB, Wikipedia)."""
    local_conn = False
    if conn is None:
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        local_conn = True
        
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_feeds")
        
        import json
        default_feeds = [
            {
                "name": "Metacritic - New TV Shows",
                "url": "https://www.metacritic.com/browse/tv/all/all/all-time/new/",
                "feed_type": "metacritic_tv",
                "default_media_type": "tv",
                "enabled": 1,
                "http_headers": "{}",
                "parser_config": "{}"
            },
            {
                "name": "Metacritic - New Movies",
                "url": "https://www.metacritic.com/browse/movie/all/all/all-time/new/",
                "feed_type": "metacritic_movie",
                "default_media_type": "movie",
                "enabled": 1,
                "http_headers": "{}",
                "parser_config": "{}"
            },
            {
                "name": "TVmaze - Upcoming Premieres & Specials",
                "url": TVMAZE_SCHEDULE_URL,
                "feed_type": "tvmaze_schedule",
                "default_media_type": "tv",
                "enabled": 1,
                "http_headers": "{}",
                "parser_config": "{}"
            },
            {
                "name": "DVDs Release Dates",
                "url": "https://www.dvdsreleasedates.com/releases/{year}/{month:02d}/",
                "feed_type": "dvds_releases",
                "default_media_type": "movie",
                "enabled": 1,
                "http_headers": "{}",
                "parser_config": "{}"
            },
            {
                "name": "TMDB - Popular Upcoming & Recent Movies",
                "url": TMDB_DISCOVER_URL,
                "feed_type": "tmdb_movies",
                "default_media_type": "movie",
                "enabled": 1,
                "http_headers": "{}",
                "parser_config": "{}"
            },
            {
                "name": "Wikipedia - 2026 American Films",
                "url": "https://en.wikipedia.org/wiki/List_of_American_films_of_2026",
                "feed_type": "html",
                "default_media_type": "movie",
                "enabled": 1,
                "http_headers": "{}",
                "parser_config": json.dumps({
                    "item_selector": "table.wikitable tbody tr",
                    "mappings": {
                        "title": {"selector": "td i a", "extract": "text"},
                        "year": {"selector": "td", "extract": "text", "transforms": [{"type": "regex_search", "pattern": "\\d{4}"}, {"type": "default", "value": "2026"}]},
                        "href": {"selector": "td i a", "extract": "attribute", "attribute_name": "href"}
                    }
                })
            }
        ]
        for feed in default_feeds:
            cursor.execute('''
                INSERT INTO custom_feeds (name, url, feed_type, default_media_type, enabled, http_headers, parser_config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (feed["name"], feed["url"], feed["feed_type"], feed["default_media_type"], feed["enabled"], feed["http_headers"], feed["parser_config"]))
            
        if local_conn:
            conn.commit()
    except Exception:
        if local_conn:
            conn.rollback()
        raise
    finally:
        if local_conn:
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
    # Repair truncated trailing year parentheses like "Carrie (2026" -> "Carrie (2026)"
    title = re.sub(r'\((\d{4})$', r'(\1)', title)
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
    
    # 3. Clean any trailing punctuation or unmatched parentheses/whitespace
    title = re.sub(r'[\s:\-\(,]+$', '', title).strip()
    if title.endswith(')') and '(' not in title:
        title = title.rstrip(')').strip()
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
            
    # 4. Clean any trailing punctuation or unmatched opening brackets/whitespace
    title = re.sub(r'[\s:\-\(\[,]+$', '', title).strip()
    if title.endswith(')') and '(' not in title:
        title = title.rstrip(')').strip()
    if title.endswith(']') and '[' not in title:
        title = title.rstrip(']').strip()
    return title

def normalize_title(title: str, is_tv: bool = False) -> str:
    """Normalizes title for comparison (same as scraper.py)."""
    if is_tv:
        title = clean_tv_title(title)
    else:
        title = clean_movie_title(title)
    return slug(title)

def get_cached_item(type_: str, title: str, year: int, imdb_id: str = None, conn = None) -> dict:
    """Retrieves a cached movie or TV show by IMDb ID or normalized title (checking exact/close matches first, falling back to ignore year setting)."""
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
            
    # 2. Fetch default_match_ignore_year setting
    cursor.execute("SELECT value FROM settings WHERE key = 'default_match_ignore_year'")
    row_setting = cursor.fetchone()
    ignore_year = (row_setting[0] == "1") if row_setting else True
        
    # 3. Query cache by indexed normalized title (O(1)) with fallback for NULL columns
    is_tv = (type_ == "tv")
    norm_title = normalize_title(title, is_tv=is_tv)
    
    cursor.execute("SELECT * FROM cache WHERE type = ? AND normalized_title = ?", (type_, norm_title))
    all_rows = [dict(row) for row in cursor.fetchall()]
    
    if local_conn:
        conn.close()
        
    if not all_rows:
        return None
        
    # Filter rows verifying title matching (especially if normalized_title was NULL)
    rows = []
    for r in all_rows:
        r_norm = r["normalized_title"] or normalize_title(r["title"], is_tv=is_tv)
        if r_norm == norm_title:
            rows.append(r)
            
    if not rows:
        return None
        
    # 4. Check for exact year match first
    for row in rows:
        if row["year"] == year:
            return row
            
    # 5. Check for close year match (+/- 1 year)
    for row in rows:
        if row["year"] and abs(row["year"] - year) <= 1:
            return row
            
    # 6. Year-agnostic fallback if setting enabled
    if ignore_year:
        return rows[0]
            
    return None

def add_cached_item(type_: str, item: dict, conn = None):
    """Caches or updates a media discovery details item, running within explicit BEGIN IMMEDIATE transactions."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        close_conn = True
        
    try:
        cursor = conn.cursor()
        imdb_id = item.get("imdbId") or item.get("imdb_id")
        
        # Check if already exists in cache using our robust lookup inside transaction
        existing = get_cached_item(type_, item["title"], item["year"], imdb_id, conn=conn)
        
        # Compute state transition for auto-archiving and smart unarchiving
        is_archived, has_new_metadata = evaluate_item_state_transition(existing, item)
        if existing and existing.get("manually_archived"):
            # User archived this by hand: never resurface it due to new metadata
            is_archived, has_new_metadata = 1, 0
        
        genres_json = json.dumps(item.get("genres", []))
        tvdb_id = item.get("tvdbId") or item.get("tvdb_id")
        tmdb_id = item.get("tmdbId") or item.get("tmdb_id")
        is_in_lib = 1 if item.get("is_in_library") else 0
        if existing and existing.get("is_in_library"):
            is_in_lib = 1
        source_feed_id = item.get("source_feed_id")
        
        normalized_title = normalize_title(item["title"], is_tv=(type_ == "tv"))
        
        date_obj_str = ""
        if item.get("date_obj"):
            if isinstance(item["date_obj"], datetime):
                date_obj_str = item["date_obj"].strftime("%Y-%m-%d")
            else:
                date_obj_str = str(item["date_obj"])
                
        if existing:
            # We preserve existing source_feed_id if it's already set and not provided
            feed_id = source_feed_id if source_feed_id is not None else existing.get("source_feed_id")
            cursor.execute('''
                UPDATE cache SET
                    date_str = ?, date_obj = ?, description = ?, href = ?, imdb_id = ?,
                    tvdb_id = ?, tmdb_id = ?, genres = ?, cast = ?, network = ?, trailer = ?,
                    poster_url = ?, is_returning = ?, is_archived = ?, has_new_metadata = ?, added_at = ?,
                    rating_imdb = ?, rating_metacritic = ?, rating_rt = ?, is_in_library = ?,
                    source_feed_id = ?, normalized_title = ?, director = ?, producer = ?,
                    country = ?, language = ?
                WHERE id = ?
            ''', (
                item.get("date_str", ""),
                date_obj_str,
                item.get("plot") or item.get("description") or "No plot summary available.",
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
                is_archived,
                has_new_metadata,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                item.get("rating_imdb", ""),
                item.get("rating_metacritic", ""),
                item.get("rating_rt", ""),
                is_in_lib,
                feed_id,
                normalized_title,
                item.get("director", ""),
                item.get("producer", ""),
                item.get("country") or (existing.get("country") or ""),
                item.get("language") or (existing.get("language") or ""),
                existing["id"]
            ))
        else:
            cursor.execute('''
                INSERT INTO cache (
                    type, title, year, date_str, date_obj, description, href, imdb_id,
                    tvdb_id, tmdb_id, genres, cast, network, trailer, poster_url, is_returning,
                    is_archived, has_new_metadata, added_at,
                    rating_imdb, rating_metacritic, rating_rt, is_in_library, source_feed_id, normalized_title,
                    director, producer, country, language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                type_,
                item["title"],
                item["year"],
                item.get("date_str", ""),
                date_obj_str,
                item.get("plot") or item.get("description") or "No plot summary available.",
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
                is_archived,
                has_new_metadata,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                item.get("rating_imdb", ""),
                item.get("rating_metacritic", ""),
                item.get("rating_rt", ""),
                is_in_lib,
                source_feed_id,
                normalized_title,
                item.get("director", ""),
                item.get("producer", ""),
                item.get("country", ""),
                item.get("language", "")
            ))
            
        if close_conn:
            conn.commit()
    except Exception:
        if close_conn:
            conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()

def add_cached_items_batch(type_: str, items: list):
    """Batches inserts to yield the WAL lock periodically for concurrent operations."""
    chunk_size = 25
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for item in chunk:
                add_cached_item(type_, item, conn=conn)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error in batch insertion: {e}", file=sys.stderr)
        finally:
            conn.close()

def archive_cached_item(type_: str, title: str, year: int, is_archived: bool = True, raw_item: dict = None):
    """Sets the is_archived flag on a cached discovery. Inserts a skeleton if not in cache."""
    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.cursor()
        
        imdb_id = None
        if raw_item:
            imdb_id = raw_item.get("imdbId") or raw_item.get("imdb_id")
            
        existing = get_cached_item(type_, title, year, imdb_id, conn=conn)
        
        archived_val = 1 if is_archived else 0
        normalized_title = normalize_title(title, is_tv=(type_ == "tv"))
        
        if existing:
            if archived_val == 1:
                cursor.execute("UPDATE cache SET is_archived = 1, has_new_metadata = 0 WHERE id = ?", (existing["id"],))
            else:
                cursor.execute("UPDATE cache SET is_archived = 0 WHERE id = ?", (existing["id"],))
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
                        
                is_in_lib = 1 if raw_item.get("is_in_library") else 0
                cursor.execute('''
                    INSERT INTO cache (
                        type, title, year, date_str, date_obj, description, href, imdb_id,
                        tvdb_id, tmdb_id, genres, cast, network, trailer, poster_url, is_returning,
                        is_archived, has_new_metadata, added_at,
                        rating_imdb, rating_metacritic, rating_rt, is_in_library, normalized_title,
                        director, producer
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    0,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    raw_item.get("rating_imdb", ""),
                    raw_item.get("rating_metacritic", ""),
                    raw_item.get("rating_rt", ""),
                    1 if raw_item.get("is_in_library") else 0,
                    normalized_title,
                    raw_item.get("director", ""),
                    raw_item.get("producer", "")
                ))
            else:
                cursor.execute('''
                    INSERT INTO cache (type, title, year, is_archived, has_new_metadata, added_at, normalized_title)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (type_, title, year, archived_val, 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), normalized_title))
        # This function is only reached from an explicit user action: remember it so
        # later enrichment never auto-unarchives (or re-archives) the item.
        row = get_cached_item(type_, title, year, imdb_id, conn=conn)
        if row:
            cursor.execute("UPDATE cache SET manually_archived = ? WHERE id = ?", (archived_val, row["id"]))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
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
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.cursor()
        existing = get_cached_item(type_, title, year, imdb_id, conn=conn)
        if existing:
            if existing.get("is_in_library") and not is_in_library:
                # Never transition from True to False
                return
            cursor.execute("UPDATE cache SET is_in_library = ? WHERE id = ?", (1 if is_in_library else 0, existing["id"]))
            conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def export_to_dict(include_media: bool = True) -> dict:
    """Exports all settings and optionally basic details of cached media objects to a dict with integrity checksum."""
    import hashlib
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch settings
    cursor.execute("SELECT key, value FROM settings")
    settings = {row["key"]: row["value"] for row in cursor.fetchall()}
    
    data = {
        "format_version": 1,
        "settings": settings
    }
    
    # 2. Optionally fetch basic media items
    if include_media:
        cursor.execute("""
            SELECT type, title, year, imdb_id, tvdb_id, tmdb_id, is_in_library, is_archived 
            FROM cache
        """)
        media_items = []
        for row in cursor.fetchall():
            media_items.append({
                "type": row["type"],
                "title": row["title"],
                "year": row["year"],
                "imdb_id": row["imdb_id"],
                "tvdb_id": row["tvdb_id"],
                "tmdb_id": row["tmdb_id"],
                "is_in_library": int(row["is_in_library"]),
                "is_archived": int(row["is_archived"])
            })
        data["media_items"] = media_items
        
    conn.close()
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    data["checksum"] = hashlib.sha256(canonical).hexdigest()
    return data


def verify_backup_checksum(data: dict) -> bool | None:
    """Verifies SHA-256 checksum of canonical JSON payload. None if absent (legacy), True if valid, False if mismatch."""
    import hashlib
    if not isinstance(data, dict):
        return False
    if "checksum" not in data:
        return None
    expected = data["checksum"]
    payload = {k: v for k, v in data.items() if k != "checksum"}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    actual = hashlib.sha256(canonical).hexdigest()
    return actual == expected


def import_from_dict(data: dict) -> tuple[int, int]:
    """Imports settings and basic details of cached media objects from a dict."""
    settings_count = 0
    media_count = 0
    
    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.cursor()
        
        # 1. Import settings
        settings_data = data.get("settings", {})
        for key, val in settings_data.items():
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
            settings_count += 1
            
        # 2. Import media items
        media_items = data.get("media_items", [])
        for item in media_items:
            type_ = item.get("type")
            title = item.get("title")
            year = item.get("year")
            imdb_id = item.get("imdb_id")
            tvdb_id = item.get("tvdb_id")
            tmdb_id = item.get("tmdb_id")
            is_in_library = int(item.get("is_in_library", 0))
            is_archived = int(item.get("is_archived", 0))
            
            if not type_ or not title:
                continue
                
            # Try to find existing cached item
            existing = get_cached_item(type_, title, year, imdb_id=imdb_id, conn=conn)
            
            if existing:
                # Update indicators and identifiers
                cursor.execute("""
                    UPDATE cache 
                    SET is_in_library = ?, is_archived = ?, manually_archived = ?, imdb_id = COALESCE(imdb_id, ?), tvdb_id = COALESCE(tvdb_id, ?), tmdb_id = COALESCE(tmdb_id, ?)
                    WHERE id = ?
                """, (is_in_library, is_archived, is_archived, imdb_id, tvdb_id, tmdb_id, existing["id"]))
            else:
                # Insert skeleton/stub media cache record
                norm_title = normalize_title(title, is_tv=(type_ == "tv"))
                cursor.execute("""
                    INSERT INTO cache (type, title, year, imdb_id, tvdb_id, tmdb_id, is_in_library, is_archived, manually_archived, normalized_title)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (type_, title, year, imdb_id, tvdb_id, tmdb_id, is_in_library, is_archived, is_archived, norm_title))
            media_count += 1
            
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        
    return settings_count, media_count


