import io
import os
import json
import shutil
import zipfile
import tempfile
import urllib.parse
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import core.db
from core.db import verify_backup_checksum
from core.backup import export_full_backup, import_full_backup
from core.posters import (
    get_posters_dir,
    get_cached_poster,
    store_poster,
    download_poster,
    validate_poster_url
)
from web.server import app

# Isolate database path to a temp file before tests run
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()


@pytest.fixture(autouse=True)
def cleanup_db():
    """Wipes the database cache, settings, custom_feeds, and temp posters between test cases."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.execute("DELETE FROM custom_feeds")
    conn.commit()
    conn.close()
    core.db.init_db()
    core.db.set_setting("api_key", "test_api_key")
    from core.config import config
    config.refresh()

    p_dir = get_posters_dir()
    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)
    yield
    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    
    class TestClientAPIKeyWrapper:
        def __init__(self, client):
            self.client = client
            
        def _get_api_key(self):
            from core.db import get_setting, set_setting
            key = get_setting("api_key", "")
            if not key:
                key = "test_api_key"
                set_setting("api_key", key)
                from core.config import config
                config.refresh()
            return key
            
        def get(self, *args, **kwargs):
            return self.client.get(*args, **kwargs)
            
        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.client.post(*args, **kwargs)

    with app.test_client() as c:
        yield TestClientAPIKeyWrapper(c)


# ==============================================================================
# Existing JSON Backup & Restore Tests (Preserved)
# ==============================================================================

def test_core_export_and_import():
    # 1. Modify settings and add cache entry
    core.db.set_setting("radarr_url", "http://my-radarr-instance:7878")
    
    conn = core.db.get_db_connection()
    conn.execute("""
        INSERT INTO cache (type, title, year, imdb_id, is_in_library, is_archived)
        VALUES ('movie', 'Test Movie', 2024, 'tt999999', 1, 0)
    """)
    conn.commit()
    conn.close()

    # 2. Export to dict (including media)
    data = core.db.export_to_dict(include_media=True)
    assert "settings" in data
    assert data["settings"]["radarr_url"] == "http://my-radarr-instance:7878"
    assert len(data["media_items"]) == 1
    assert data["media_items"][0]["title"] == "Test Movie"
    assert data["media_items"][0]["is_in_library"] == 1
    assert data["format_version"] == 1
    assert "checksum" in data

    # 3. Export to dict (excluding media)
    data_no_media = core.db.export_to_dict(include_media=False)
    assert "media_items" not in data_no_media
    assert "checksum" in data_no_media

    # 4. Clear database
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()

    # 5. Import from dict
    settings_count, media_count = core.db.import_from_dict(data)
    assert settings_count > 0
    assert media_count == 1

    # Verify restoration
    restored_settings = core.db.get_all_settings()
    assert restored_settings["radarr_url"] == "http://my-radarr-instance:7878"

    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cache")
    rows = cursor.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["title"] == "Test Movie"
    assert rows[0]["is_in_library"] == 1


def test_import_existing_update():
    # 1. Add item to cache
    conn = core.db.get_db_connection()
    conn.execute("""
        INSERT INTO cache (type, title, year, imdb_id, is_in_library, is_archived)
        VALUES ('movie', 'Existing Movie', 2024, 'tt888888', 0, 0)
    """)
    conn.commit()
    conn.close()

    # 2. Prepare import data that updates this item
    data = {
        "settings": {},
        "media_items": [
            {
                "type": "movie",
                "title": "Existing Movie",
                "year": 2024,
                "imdb_id": "tt888888",
                "is_in_library": 1,
                "is_archived": 1
            }
        ]
    }

    settings_count, media_count = core.db.import_from_dict(data)
    assert media_count == 1

    # Verify updated fields
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cache WHERE title = 'Existing Movie'")
    row = cursor.fetchone()
    conn.close()
    assert row["is_in_library"] == 1
    assert row["is_archived"] == 1


def test_api_backup_export(client):
    core.db.set_setting("radarr_url", "http://radarr-api-test:7878")
    
    res = client.get("/api/backup/export?include_media=false")
    assert res.status_code == 200
    assert res.headers["Content-Disposition"] == "attachment; filename=xarrtools_backup.json"
    
    data = json.loads(res.data)
    assert data["settings"]["radarr_url"] == "http://radarr-api-test:7878"
    assert "media_items" not in data
    assert data["format_version"] == 1
    assert "checksum" in data


def test_api_backup_import(client):
    backup_data = {
        "settings": {
            "radarr_url": "http://imported-via-api:7878"
        },
        "media_items": [
            {
                "type": "movie",
                "title": "API Imported Movie",
                "year": 2025,
                "is_in_library": 1,
                "is_archived": 0
            }
        ]
    }
    
    file_content = json.dumps(backup_data).encode("utf-8")
    data = {
        "file": (BytesIO(file_content), "xarrtools_backup.json")
    }
    
    res = client.post(
        "/api/backup/import",
        data=data,
        content_type="multipart/form-data"
    )
    assert res.status_code == 200
    
    res_data = json.loads(res.data)
    assert res_data["status"] == "success"
    assert res_data["settings_count"] > 0
    assert res_data["media_count"] == 1
    
    # Verify settings database change
    assert core.db.get_setting("radarr_url") == "http://imported-via-api:7878"


# ==============================================================================
# New Checksum & Tamper Detection Tests
# ==============================================================================

def test_json_backup_checksum_roundtrip():
    core.db.set_setting("sonarr_url", "http://sonarr:8989")
    data = core.db.export_to_dict(include_media=True)
    assert data["format_version"] == 1
    assert "checksum" in data
    assert verify_backup_checksum(data) is True


def test_json_backup_tamper_detection(client):
    core.db.set_setting("radarr_url", "http://original:7878")
    data = core.db.export_to_dict(include_media=False)
    assert verify_backup_checksum(data) is True

    # Tamper with settings
    data["settings"]["radarr_url"] = "http://tampered:7878"
    assert verify_backup_checksum(data) is False

    # Importing tampered file must be rejected with 400
    file_content = json.dumps(data).encode("utf-8")
    res = client.post(
        "/api/backup/import",
        data={"file": (BytesIO(file_content), "xarrtools_backup.json")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 400
    res_data = json.loads(res.data)
    assert res_data["status"] == "error"
    assert "checksum" in res_data["message"].lower()


def test_json_backup_legacy_accepted(client):
    # Legacy file without 'checksum' field
    legacy_data = {
        "settings": {
            "sonarr_url": "http://legacy-sonarr:8989"
        },
        "media_items": [
            {
                "type": "tv",
                "title": "Legacy Show",
                "year": 2024,
                "is_in_library": 1,
                "is_archived": 0
            }
        ]
    }
    assert verify_backup_checksum(legacy_data) is None

    file_content = json.dumps(legacy_data).encode("utf-8")
    res = client.post(
        "/api/backup/import",
        data={"file": (BytesIO(file_content), "xarrtools_backup.json")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 200
    res_data = json.loads(res.data)
    assert res_data["status"] == "success"
    assert core.db.get_setting("sonarr_url") == "http://legacy-sonarr:8989"


# ==============================================================================
# Full Backup (ZIP) Roundtrip, Columns, Remapping, and Posters Tests
# ==============================================================================

def test_full_backup_roundtrip_with_posters_and_remapping():
    # 1. Create a custom feed
    conn = core.db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO custom_feeds (name, url, feed_type, default_media_type, parser_config, enabled)
        VALUES ('Sci-Fi RSS', 'https://feeds.example.com/scifi.xml', 'rss', 'movie', '{}', 1)
    """)
    feed_id = cursor.lastrowid

    # 2. Add full-featured cache item
    cursor.execute("""
        INSERT INTO cache (
            type, title, year, date_str, date_obj, description, href, imdb_id,
            tvdb_id, tmdb_id, genres, cast, network, trailer, poster_url,
            is_returning, is_archived, manually_archived, country, language,
            has_new_metadata, added_at, rating_imdb, rating_metacritic, rating_rt,
            is_in_library, source_feed_id, normalized_title, director, producer
        ) VALUES (
            'movie', 'Starlight Odyssey', 2026, '2026-12-15', '2026-12-15',
            'Deep space exploration.', 'https://imdb.com/title/tt7654321', 'tt7654321',
            0, 112233, '["Sci-Fi", "Adventure"]', 'Alice Smith, Bob Jones', 'Solaris',
            'https://youtube.com/watch?v=starlight', 'https://example.com/poster.jpg',
            0, 0, 0, 'US', 'English',
            0, '2026-10-26 12:00:00', '8.9', '88', '94%',
            1, ?, 'starlight-odyssey', 'Jane Director', 'John Producer'
        )
    """, (feed_id,))
    conn.commit()
    conn.close()

    # 3. Export full backup with mock poster download
    fake_img = b"\xff\xd8\xff\xe0\x00\x10JFIFfakejpgbytes"
    with patch("socket.gethostbyname", return_value="93.184.216.34"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_resp.iter_content = MagicMock(return_value=[fake_img])
        with patch("requests.get", return_value=mock_resp):
            bio = io.BytesIO()
            stats = export_full_backup(bio, include_media=True)
            assert stats["settings_count"] > 0
            assert stats["custom_feeds_count"] >= 1
            assert stats["media_count"] == 1
            assert stats["posters_count"] == 1

    # 4. Verify ZIP structure and manifest
    bio.seek(0)
    with zipfile.ZipFile(bio, "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "backup.json" in names
        poster_files = [n for n in names if n.startswith("posters/")]
        assert len(poster_files) == 1

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "files" in manifest
        assert "posters" in manifest
        assert "backup.json" in manifest["files"]
        assert poster_files[0] in manifest["files"]

        backup_obj = json.loads(zf.read("backup.json").decode("utf-8"))
        assert backup_obj["format_version"] == 2
        assert verify_backup_checksum(backup_obj) is True
        assert len(backup_obj["custom_feeds"]) >= 1
        assert len(backup_obj["cache"]) == 1
        row = backup_obj["cache"][0]
        assert row["title"] == "Starlight Odyssey"
        assert row["source_feed_name"] == "Sci-Fi RSS"
        assert row["source_feed_url"] == "https://feeds.example.com/scifi.xml"
        assert "id" not in row

    # 5. Restore into a fresh database and verify full column preservation
    fresh_fd, fresh_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fresh_fd)
    old_db_path = core.db.DB_PATH
    try:
        core.db.DB_PATH = Path(fresh_db_path)
        core.db.init_db()

        # Clear any auto-seeded rows
        c = core.db.get_db_connection()
        c.execute("DELETE FROM cache")
        c.execute("DELETE FROM custom_feeds")
        c.execute("DELETE FROM settings")
        c.commit()
        c.close()

        bio.seek(0)
        res = import_full_backup(bio)
        assert res["status"] == "success"
        assert res["media_count"] == 1
        assert res["custom_feeds_count"] >= 1
        assert res["posters_count"] == 1

        # Check that columns and foreign key remapping are exact
        conn = core.db.get_db_connection()
        restored_feed = conn.execute("SELECT * FROM custom_feeds WHERE url = 'https://feeds.example.com/scifi.xml'").fetchone()
        assert restored_feed is not None
        new_feed_id = restored_feed["id"]

        restored_item = conn.execute("SELECT * FROM cache WHERE title = 'Starlight Odyssey'").fetchone()
        assert restored_item is not None
        assert restored_item["source_feed_id"] == new_feed_id
        assert restored_item["year"] == 2026
        assert restored_item["date_str"] == "2026-12-15"
        assert restored_item["date_obj"] == "2026-12-15"
        assert restored_item["description"] == "Deep space exploration."
        assert restored_item["href"] == "https://imdb.com/title/tt7654321"
        assert restored_item["imdb_id"] == "tt7654321"
        assert restored_item["tmdb_id"] == 112233
        assert restored_item["cast"] == "Alice Smith, Bob Jones"
        assert restored_item["network"] == "Solaris"
        assert restored_item["trailer"] == "https://youtube.com/watch?v=starlight"
        assert restored_item["poster_url"] == "https://example.com/poster.jpg"
        assert restored_item["country"] == "US"
        assert restored_item["language"] == "English"
        assert restored_item["rating_imdb"] == "8.9"
        assert restored_item["rating_metacritic"] == "88"
        assert restored_item["rating_rt"] == "94%"
        assert restored_item["is_in_library"] == 1
        assert restored_item["director"] == "Jane Director"
        assert restored_item["producer"] == "John Producer"
        conn.close()

        # Check poster disk cache
        poster_res = get_cached_poster("https://example.com/poster.jpg")
        assert poster_res is not None
        data, ct = poster_res
        assert data == fake_img
        assert ct == "image/jpeg"
    finally:
        core.db.DB_PATH = old_db_path
        if os.path.exists(fresh_db_path):
            os.remove(fresh_db_path)


def test_full_backup_sticky_manual_archive_and_library():
    # 1. Existing item in DB has manually_archived = 1 and is_in_library = 1
    conn = core.db.get_db_connection()
    conn.execute("""
        INSERT INTO cache (type, title, year, imdb_id, is_in_library, is_archived, manually_archived)
        VALUES ('movie', 'Sticky Title', 2024, 'tt111222', 1, 1, 1)
    """)
    conn.commit()
    conn.close()

    # 2. Full backup has the same item but with is_archived = 0, manually_archived = 0, is_in_library = 0
    backup_data = {
        "format_version": 2,
        "settings": {},
        "custom_feeds": [],
        "cache": [
            {
                "type": "movie",
                "title": "Sticky Title",
                "year": 2024,
                "imdb_id": "tt111222",
                "is_in_library": 0,
                "is_archived": 0,
                "manually_archived": 0
            }
        ]
    }
    canonical = json.dumps(backup_data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    import hashlib
    backup_data["checksum"] = hashlib.sha256(canonical).hexdigest()
    backup_bytes = json.dumps(backup_data).encode('utf-8')

    manifest = {
        "manifest_version": 1,
        "files": {"backup.json": hashlib.sha256(backup_bytes).hexdigest()},
        "posters": {}
    }

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("backup.json", backup_bytes)

    bio.seek(0)
    import_full_backup(bio)

    # 3. Verify that manually_archived and is_in_library remained sticky!
    conn = core.db.get_db_connection()
    row = conn.execute("SELECT * FROM cache WHERE title = 'Sticky Title'").fetchone()
    conn.close()
    assert row["manually_archived"] == 1
    assert row["is_archived"] == 1
    assert row["is_in_library"] == 1


def test_full_backup_manifest_tamper_rejected(client):
    bio = io.BytesIO()
    export_full_backup(bio, include_media=False)
    bio.seek(0)

    # Read zip, tamper backup.json content without updating manifest
    zf_in = zipfile.ZipFile(bio, "r")
    tampered_bio = io.BytesIO()
    with zipfile.ZipFile(tampered_bio, "w") as zf_out:
        for item in zf_in.infolist():
            content = zf_in.read(item.filename)
            if item.filename == "backup.json":
                # tamper bytes
                content = content + b" "
            zf_out.writestr(item, content)

    tampered_bio.seek(0)
    with pytest.raises(ValueError, match="Manifest checksum mismatch"):
        import_full_backup(tampered_bio)

    # Endpoint must return 400
    tampered_bio.seek(0)
    res = client.post(
        "/api/backup/import",
        data={"file": (tampered_bio, "backup.zip")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 400
    res_data = json.loads(res.data)
    assert res_data["status"] == "error"
    assert "manifest checksum mismatch" in res_data["message"].lower()


def test_full_backup_zip_slip_rejected(client):
    slip_bio = io.BytesIO()
    with zipfile.ZipFile(slip_bio, "w") as zf:
        zf.writestr("../../etc/passwd", "malicious_payload")
        zf.writestr("manifest.json", "{}")
        zf.writestr("backup.json", "{}")

    slip_bio.seek(0)
    with pytest.raises(ValueError, match="Zip-slip detected"):
        import_full_backup(slip_bio)

    slip_bio.seek(0)
    res = client.post(
        "/api/backup/import",
        data={"file": (slip_bio, "backup.zip")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 400
    res_data = json.loads(res.data)
    assert res_data["status"] == "error"
    assert "zip-slip" in res_data["message"].lower()


# ==============================================================================
# API Endpoints & Poster Disk Cache Integration Tests
# ==============================================================================

def test_api_backup_export_full_format(client):
    core.db.set_setting("radarr_url", "http://full-test:7878")
    res = client.get("/api/backup/export?format=full&include_media=false")
    assert res.status_code == 200
    assert res.mimetype == "application/zip"
    assert res.headers["Content-Disposition"] == "attachment; filename=xarrtools_full_backup.zip"

    # Verify returned bytes form a valid zip
    with zipfile.ZipFile(BytesIO(res.data), "r") as zf:
        assert "manifest.json" in zf.namelist()
        assert "backup.json" in zf.namelist()


def test_api_backup_import_zip(client):
    bio = io.BytesIO()
    export_full_backup(bio, include_media=False)
    bio.seek(0)

    res = client.post(
        "/api/backup/import",
        data={"file": (bio, "full_backup.zip")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 200
    res_data = json.loads(res.data)
    assert res_data["status"] == "success"
    assert "posters_count" in res_data
    assert "media_count" in res_data


def test_api_poster_cache_hit_avoids_network(client):
    url = "https://images.example.com/movie_poster.png"
    fake_bytes = b"\x89PNG\r\n\x1a\nposterdata"
    assert store_poster(url, fake_bytes, "image/png") is True

    # Check that disk cache serves it directly and network is not touched
    with patch("requests.get") as mock_get:
        res = client.get(f"/api/poster?url={urllib.parse.quote(url)}")
        assert res.status_code == 200
        assert res.data == fake_bytes
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        mock_get.assert_not_called()


def test_api_poster_write_through(client):
    url = "https://images.example.com/new_poster.jpg"
    fake_bytes = b"\xff\xd8\xff\xe0write_through_bytes"

    with patch("socket.gethostbyname", return_value="93.184.216.34"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_resp.iter_content = MagicMock(return_value=[fake_bytes])

        with patch("requests.get", return_value=mock_resp):
            res = client.get(f"/api/poster?url={urllib.parse.quote(url)}")
            assert res.status_code == 200
            assert res.data == fake_bytes
            assert res.headers["X-Content-Type-Options"] == "nosniff"

    # Verify it is now cached on disk
    cached = get_cached_poster(url)
    assert cached is not None
    assert cached[0] == fake_bytes
    assert cached[1] == "image/jpeg"


def test_api_poster_ssrf_blocked(client):
    # Private IP
    res_local = client.get("/api/poster?url=http://127.0.0.1/evil.jpg")
    assert res_local.status_code == 403

    res_private = client.get("/api/poster?url=http://10.0.0.1/evil.jpg")
    assert res_private.status_code == 403

    # Invalid schemes
    res_scheme1 = client.get("/api/poster?url=file:///etc/passwd")
    assert res_scheme1.status_code == 400

    res_scheme2 = client.get("/api/poster?url=ftp://evil.com/pic.jpg")
    assert res_scheme2.status_code == 400

    # Missing URL
    res_empty = client.get("/api/poster")
    assert res_empty.status_code == 400
