import json
import pytest
from io import BytesIO
from unittest.mock import patch
import core.db
from web.server import app


@pytest.fixture(autouse=True)
def cleanup_db():
    """Wipes the database cache and settings tables between test cases."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    core.db.init_db()
    core.db.set_setting("api_key", "test_api_key")
    from core.config import config
    config.refresh()
    yield


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

    # 3. Export to dict (excluding media)
    data_no_media = core.db.export_to_dict(include_media=False)
    assert "media_items" not in data_no_media

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
