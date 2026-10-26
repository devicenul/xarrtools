"""Full instance backup/restore and JSON integrity checksum utilities."""
import os
import io
import json
import hashlib
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from pathlib import Path
import logging
from typing import Any, Dict, IO, List, Optional, Set, Tuple, Union

logger = logging.getLogger("xarrtools.backup")

import core.db
from core.db import get_db_connection, get_cached_item, normalize_title
from core.posters import (
    get_cached_poster,
    store_poster,
    download_poster,
    get_extension_for_mimetype,
    get_mimetype_for_filename
)

MAX_UNCOMPRESSED_TOTAL: int = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_ENTRY_SIZE: int = 20 * 1024 * 1024                 # 20 MB


def verify_backup_checksum(data: Dict[str, Any]) -> Optional[bool]:
    """Verifies SHA-256 checksum of canonical JSON payload.
    
    Returns:
        None if 'checksum' field is absent (legacy backup accepted).
        True if checksum matches canonical JSON payload.
        False if checksum mismatch or data is invalid.
    """
    if not isinstance(data, dict):
        return False
    if "checksum" not in data:
        return None
    expected = data["checksum"]
    payload = {k: v for k, v in data.items() if k != "checksum"}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    actual = hashlib.sha256(canonical).hexdigest()
    return actual == expected


def export_full_backup(
    path_or_fileobj: Union[str, Path, IO[bytes]],
    include_media: bool = True,
    max_poster_fetch_time: float = 10.0
) -> Dict[str, int]:
    """Exports a full backup zip containing backup.json (format_version 2), posters, and manifest.json.
    
    Args:
        path_or_fileobj: File path or file-like object to write the ZIP archive to.
        include_media: Whether to include cache entries and download/archive posters.
        max_poster_fetch_time: Maximum total time (seconds) to spend downloading uncached posters.
        
    Returns:
        Dictionary of counts: settings_count, custom_feeds_count, media_count, posters_count.
    """
    logger.info(f"Starting full backup export (include_media={include_media})...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch settings
    cursor.execute("SELECT key, value FROM settings")
    settings = {row["key"]: row["value"] for row in cursor.fetchall()}
    
    # 2. Fetch custom feeds
    cursor.execute("SELECT * FROM custom_feeds")
    custom_feeds_rows = cursor.fetchall()
    custom_feeds = []
    feed_id_map = {}  # id -> {name, url}
    for row in custom_feeds_rows:
        feed_dict = {
            "name": row["name"],
            "url": row["url"],
            "feed_type": row["feed_type"],
            "default_media_type": row["default_media_type"],
            "http_headers": row["http_headers"],
            "parser_config": row["parser_config"],
            "enabled": int(row["enabled"]) if row["enabled"] is not None else 1,
            "last_run": row["last_run"],
            "last_status": row["last_status"],
            "last_error_message": row["last_error_message"]
        }
        custom_feeds.append(feed_dict)
        feed_id_map[row["id"]] = {"name": row["name"], "url": row["url"]}
        
    # 3. Fetch cache items
    cache_items = []
    distinct_poster_urls = set()
    if include_media:
        cursor.execute("SELECT * FROM cache")
        for row in cursor.fetchall():
            row_dict = dict(row)
            row_dict.pop("id", None)
            source_feed_id = row_dict.pop("source_feed_id", None)
            if source_feed_id and source_feed_id in feed_id_map:
                row_dict["source_feed_name"] = feed_id_map[source_feed_id]["name"]
                row_dict["source_feed_url"] = feed_id_map[source_feed_id]["url"]
            else:
                row_dict["source_feed_name"] = None
                row_dict["source_feed_url"] = None
                
            p_url = row_dict.get("poster_url")
            if p_url and isinstance(p_url, str) and p_url.startswith(("http://", "https://")):
                distinct_poster_urls.add(p_url)
                
            cache_items.append(row_dict)
            
    conn.close()
    
    # 4. Construct backup.json (format_version 2)
    backup_data = {
        "format_version": 2,
        "settings": settings,
        "custom_feeds": custom_feeds,
        "cache": cache_items
    }
    canonical = json.dumps(backup_data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    backup_data["checksum"] = hashlib.sha256(canonical).hexdigest()
    backup_json_bytes = json.dumps(backup_data, indent=2, ensure_ascii=False).encode('utf-8')
    
    # 5. Fetch/cache posters concurrently (cached first, uncached bounded by max_poster_fetch_time)
    manifest_files = {
        "backup.json": hashlib.sha256(backup_json_bytes).hexdigest()
    }
    poster_index: Dict[str, str] = {}  # sha256_of_url -> url
    poster_archive_data: Dict[str, bytes] = {}  # archive_name -> bytes

    uncached_poster_urls: List[str] = []
    if distinct_poster_urls:
        # Load all already-cached posters immediately without thread pool / network overhead
        for url in distinct_poster_urls:
            try:
                res = get_cached_poster(url)
                if res:
                    data, ct = res
                    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
                    ext = get_extension_for_mimetype(ct)
                    archive_name = f"posters/{key}{ext}"
                    poster_index[key] = url
                    poster_archive_data[archive_name] = data
                    manifest_files[archive_name] = hashlib.sha256(data).hexdigest()
                else:
                    uncached_poster_urls.append(url)
            except Exception:
                uncached_poster_urls.append(url)

        # Download uncached posters concurrently with bounded overall time
        if uncached_poster_urls and max_poster_fetch_time > 0:
            executor = ThreadPoolExecutor(max_workers=8)
            try:
                future_to_url = {executor.submit(download_poster, url): url for url in uncached_poster_urls}
                for future in as_completed(future_to_url, timeout=max_poster_fetch_time):
                    url = future_to_url[future]
                    try:
                        res = future.result()
                        if res:
                            data, ct = res
                            key = hashlib.sha256(url.encode("utf-8")).hexdigest()
                            ext = get_extension_for_mimetype(ct)
                            archive_name = f"posters/{key}{ext}"
                            poster_index[key] = url
                            poster_archive_data[archive_name] = data
                            manifest_files[archive_name] = hashlib.sha256(data).hexdigest()
                    except Exception as e:
                        logger.warning(f"Failed to fetch poster {url} for backup: {e}")
            except (TimeoutError, Exception) as te:
                if isinstance(te, TimeoutError):
                    logger.warning(
                        f"Poster download deadline ({max_poster_fetch_time}s) reached during full backup; "
                        f"continuing export with {len(poster_archive_data)} posters."
                    )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
                    
    # 6. Construct manifest.json
    manifest_data = {
        "manifest_version": 1,
        "files": manifest_files,
        "posters": poster_index
    }
    manifest_bytes = json.dumps(manifest_data, indent=2, ensure_ascii=False).encode('utf-8')
    
    # 7. Write ZIP archive
    with zipfile.ZipFile(path_or_fileobj, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("backup.json", backup_json_bytes)
        for archive_name, data in poster_archive_data.items():
            zf.writestr(archive_name, data)
            
    return {
        "settings_count": len(settings),
        "custom_feeds_count": len(custom_feeds),
        "media_count": len(cache_items),
        "posters_count": len(poster_archive_data)
    }


def import_full_backup(fileobj: Union[str, Path, IO[bytes]]) -> Dict[str, Union[str, int]]:
    """Imports full backup archive from a ZIP file or file-like object.
    
    Verifies manifest hashes and backup.json checksum before writing anything.
    Rejects zip-slip/path traversal, caps entry sizes at 20MB and total size at 2GB.
    Performs restoration of settings, custom_feeds, and cache items in ONE transaction.
    Writes posters into poster cache directory.
    
    Returns:
        dict with status and counts.
    """
    logger.info("Starting full backup import...")
    try:
        zf = zipfile.ZipFile(fileobj, mode="r")
    except Exception as e:
        raise ValueError(f"Invalid ZIP archive: {e}")
        
    with zf:
        total_uncompressed = 0
        entry_names = []
        for info in zf.infolist():
            name = info.filename
            if os.path.isabs(name) or name.startswith(("/", "\\")):
                raise ValueError(f"Zip-slip detected: absolute path '{name}'")
            parts = Path(name).parts
            if ".." in parts or "." in parts:
                raise ValueError(f"Zip-slip detected: path traversal '{name}'")
            if info.file_size > MAX_ENTRY_SIZE:
                raise ValueError(f"Archive entry '{name}' exceeds 20MB limit ({info.file_size} bytes)")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_TOTAL:
                raise ValueError("Total uncompressed archive size exceeds 2GB limit")
            if not info.is_dir():
                entry_names.append(name)
                
        if "manifest.json" not in entry_names:
            raise ValueError("Archive is missing manifest.json")
        if "backup.json" not in entry_names:
            raise ValueError("Archive is missing backup.json")
            
        manifest_bytes = zf.read("manifest.json")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid manifest.json: {e}")
            
        files_hashes = manifest.get("files", {})
        poster_index = manifest.get("posters", {})
        if not isinstance(files_hashes, dict):
            raise ValueError("Invalid manifest.json structure: 'files' must be a dictionary")
            
        # Verify hashes of every non-manifest file listed in manifest and ensure all zip entries are accounted for
        for name in entry_names:
            if name == "manifest.json":
                continue
            if name not in files_hashes:
                raise ValueError(f"Archive entry '{name}' is not listed in manifest.json")
            entry_bytes = zf.read(name)
            expected_hash = files_hashes[name]
            actual_hash = hashlib.sha256(entry_bytes).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"Manifest checksum mismatch for '{name}'")
                
        # Read and verify backup.json
        backup_bytes = zf.read("backup.json")
        try:
            backup_data = json.loads(backup_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid backup.json: {e}")
            
        check = verify_backup_checksum(backup_data)
        if check is False:
            raise ValueError("backup.json checksum verification failed (tampered data)")
        if check is None:
            raise ValueError("backup.json is missing required integrity checksum")
            
        # All integrity checks passed! Perform database restoration in ONE transaction.
        settings_count = 0
        feeds_count = 0
        media_count = 0
        posters_count = 0
        
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.cursor()
            
            # 1. Restore settings
            for key, val in backup_data.get("settings", {}).items():
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
                settings_count += 1
                
            # 2. Restore custom_feeds
            feed_id_map = {}  # (name, url) -> target feed id, and url -> target feed id
            for feed in backup_data.get("custom_feeds", []):
                fname = feed.get("name")
                furl = feed.get("url")
                if not fname or not furl:
                    continue
                cursor.execute("SELECT id FROM custom_feeds WHERE url = ?", (furl,))
                existing_feed = cursor.fetchone()
                if existing_feed:
                    fid = existing_feed[0]
                    cursor.execute("""
                        UPDATE custom_feeds SET
                            name = ?, feed_type = ?, default_media_type = ?, http_headers = ?,
                            parser_config = ?, enabled = ?, last_run = ?, last_status = ?, last_error_message = ?
                        WHERE id = ?
                    """, (
                        fname,
                        feed.get("feed_type", "rss"),
                        feed.get("default_media_type", "movie"),
                        feed.get("http_headers"),
                        feed.get("parser_config", "{}"),
                        feed.get("enabled", 1),
                        feed.get("last_run"),
                        feed.get("last_status"),
                        feed.get("last_error_message"),
                        fid
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO custom_feeds (
                            name, url, feed_type, default_media_type, http_headers,
                            parser_config, enabled, last_run, last_status, last_error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        fname, furl,
                        feed.get("feed_type", "rss"),
                        feed.get("default_media_type", "movie"),
                        feed.get("http_headers"),
                        feed.get("parser_config", "{}"),
                        feed.get("enabled", 1),
                        feed.get("last_run"),
                        feed.get("last_status"),
                        feed.get("last_error_message")
                    ))
                    fid = cursor.lastrowid
                feed_id_map[(fname, furl)] = fid
                feed_id_map[furl] = fid
                feeds_count += 1
                
            # 3. Restore cache rows
            for item in backup_data.get("cache", []):
                type_ = item.get("type")
                title = item.get("title")
                year = item.get("year")
                imdb_id = item.get("imdb_id")
                if not type_ or not title:
                    continue
                    
                target_feed_id = None
                furl = item.get("source_feed_url")
                fname = item.get("source_feed_name")
                if (fname, furl) in feed_id_map:
                    target_feed_id = feed_id_map[(fname, furl)]
                elif furl in feed_id_map:
                    target_feed_id = feed_id_map[furl]
                    
                norm_title = normalize_title(title, is_tv=(type_ == "tv"))
                existing = get_cached_item(type_, title, year, imdb_id=imdb_id, conn=conn)
                
                is_archived = int(item.get("is_archived", 0))
                manually_archived = int(item.get("manually_archived", 0))
                is_in_library = int(item.get("is_in_library", 0))
                
                if existing:
                    # Sticky manually_archived
                    if existing.get("manually_archived"):
                        manually_archived = 1
                        is_archived = 1
                    # Sticky library status
                    if existing.get("is_in_library"):
                        is_in_library = 1
                    feed_to_use = target_feed_id if target_feed_id is not None else existing.get("source_feed_id")
                    
                    cursor.execute("""
                        UPDATE cache SET
                            type = ?, title = ?, year = ?, date_str = ?, date_obj = ?,
                            description = ?, href = ?, imdb_id = ?, tvdb_id = ?, tmdb_id = ?,
                            genres = ?, cast = ?, network = ?, trailer = ?, poster_url = ?,
                            is_returning = ?, is_archived = ?, manually_archived = ?,
                            country = ?, language = ?, has_new_metadata = ?, added_at = ?,
                            rating_imdb = ?, rating_metacritic = ?, rating_rt = ?,
                            is_in_library = ?, source_feed_id = ?, normalized_title = ?,
                            director = ?, producer = ?
                        WHERE id = ?
                    """, (
                        type_, title, year, item.get("date_str", ""), item.get("date_obj", ""),
                        item.get("description", ""), item.get("href", ""), imdb_id,
                        item.get("tvdb_id"), item.get("tmdb_id"), item.get("genres", "[]"),
                        item.get("cast", ""), item.get("network", ""), item.get("trailer", ""),
                        item.get("poster_url", ""), item.get("is_returning", 0),
                        is_archived, manually_archived,
                        item.get("country", ""), item.get("language", ""),
                        item.get("has_new_metadata", 0), item.get("added_at", ""),
                        item.get("rating_imdb", ""), item.get("rating_metacritic", ""),
                        item.get("rating_rt", ""), is_in_library, feed_to_use, norm_title,
                        item.get("director", ""), item.get("producer", ""),
                        existing["id"]
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO cache (
                            type, title, year, date_str, date_obj, description, href, imdb_id,
                            tvdb_id, tmdb_id, genres, cast, network, trailer, poster_url,
                            is_returning, is_archived, manually_archived, country, language,
                            has_new_metadata, added_at, rating_imdb, rating_metacritic, rating_rt,
                            is_in_library, source_feed_id, normalized_title, director, producer
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                    """, (
                        type_, title, year, item.get("date_str", ""), item.get("date_obj", ""),
                        item.get("description", ""), item.get("href", ""), imdb_id,
                        item.get("tvdb_id"), item.get("tmdb_id"), item.get("genres", "[]"),
                        item.get("cast", ""), item.get("network", ""), item.get("trailer", ""),
                        item.get("poster_url", ""), item.get("is_returning", 0),
                        is_archived, manually_archived,
                        item.get("country", ""), item.get("language", ""),
                        item.get("has_new_metadata", 0), item.get("added_at", ""),
                        item.get("rating_imdb", ""), item.get("rating_metacritic", ""),
                        item.get("rating_rt", ""), is_in_library, target_feed_id, norm_title,
                        item.get("director", ""), item.get("producer", "")
                    ))
                media_count += 1
                
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            
        # 4. Write poster files into poster cache directory
        for name in entry_names:
            if not name.startswith("posters/"):
                continue
            base = os.path.basename(name)
            key = base.split(".")[0]
            url = poster_index.get(key)
            if not url:
                continue
            poster_bytes = zf.read(name)
            ct = get_mimetype_for_filename(name)
            if store_poster(url, poster_bytes, ct):
                posters_count += 1
                
        return {
            "status": "success",
            "settings_count": settings_count,
            "media_count": media_count,
            "custom_feeds_count": feeds_count,
            "posters_count": posters_count
        }
