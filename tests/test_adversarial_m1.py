"""
Adversarial Stress Test Suite for Milestone 1:
- Boundary conditions (missing IDs, deleted folders, invalid JSON types in settings)
- Concurrency & race conditions (concurrent adds, concurrent settings reads/writes)
- Deprecation contract enforcement (Sonarr language profiles removal)
- Error handling, security, and type coercion
"""

import os
import json
import tempfile
import threading
import concurrent.futures
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import requests

# Isolate database for adversarial tests
import xarrtools.core.db; from xarrtools import core
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

with patch("threading.Thread"):
    from xarrtools.web.server import app, get_clients
from xarrtools.core.client import RadarrClient, SonarrClient, ArrAPIError
from xarrtools.core.config import config


@pytest.fixture(autouse=True)
def clean_test_db():
    """Cleans database before each test and resets test api key."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    core.db.init_db()
    core.db.set_setting("api_key", "adversarial-key")
    config.refresh()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    core.db.set_setting("api_key", "adversarial-key")
    config.refresh()

    class TestClientWrapper:
        def __init__(self, c):
            self.c = c

        def _get_api_key(self):
            return core.db.get_setting("api_key", "adversarial-key")

        def get(self, *args, **kwargs):
            return self.c.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.c.post(*args, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.c.put(*args, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.c.delete(*args, **kwargs)

    with app.test_client() as c:
        yield TestClientWrapper(c)


# ===========================================================================
# 1. Boundary Conditions: Missing IDs and Invalid Fields in POST /api/add
# ===========================================================================

class TestBoundaryConditionsAddAPI:
    """Stress-test POST /api/add boundary conditions."""

    @pytest.mark.parametrize("payload,expected_status", [
        ({}, 400),
        ({"type": "movie"}, 400),
        ({"type": "tv"}, 400),
        ({"type": "movie", "raw_metadata": {"title": "Test"}}, 400),
        ({"type": "movie", "raw_metadata": {"title": "Test"}, "folder": "/movies"}, 400),
        ({"type": "movie", "raw_metadata": {"title": "Test"}, "profile_id": 1}, 400),
        ({"type": "movie", "raw_metadata": None, "folder": "/movies", "profile_id": 1}, 400),
        ({"type": "movie", "raw_metadata": {}, "folder": None, "profile_id": 1}, 400),
        ({"type": "movie", "raw_metadata": {}, "folder": "/movies", "profile_id": None}, 400),
        ({"type": "movie", "raw_metadata": {}, "folder": "", "profile_id": 1}, 400),
        ({"type": "movie", "raw_metadata": {}, "folder": "/movies", "profile_id": ""}, 400),
    ])
    def test_missing_and_invalid_required_fields_add_api(self, client, payload, expected_status):
        res = client.post("/api/add", json=payload)
        assert res.status_code == expected_status
        data = res.get_json()
        assert data["status"] == "error"

    def test_add_api_unconfigured_radarr_returns_400(self, client):
        with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
            res = client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Movie"},
                "folder": "/movies",
                "profile_id": 1
            })
            assert res.status_code == 400
            assert "Radarr server is not configured" in res.get_json()["message"]

    def test_add_api_unconfigured_sonarr_returns_400(self, client):
        with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
            res = client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Show"},
                "folder": "/tv",
                "profile_id": 1
            })
            assert res.status_code == 400
            assert "Sonarr server is not configured" in res.get_json()["message"]

    def test_add_api_upstream_error_handling(self, client):
        mock_radarr = MagicMock()
        mock_radarr.add_movie.side_effect = ArrAPIError("Movie folder does not exist", status_code=400)
        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, None)):
            res = client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Movie"},
                "folder": "/nonexistent/folder",
                "profile_id": 999
            })
            assert res.status_code == 500
            assert "Movie folder does not exist" in res.get_json()["message"]

    def test_add_options_boolean_flags_forwarding(self, client):
        """Verify monitored=False, search_now=False, add_collection=True forward correctly."""
        mock_radarr = MagicMock()
        mock_radarr.add_movie.return_value = {"id": 1, "title": "Movie"}
        mock_sonarr = MagicMock()
        mock_sonarr.add_series.return_value = {"id": 2, "title": "Show"}

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
            # Test movie flags
            client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Movie", "year": 2024},
                "folder": "/movies",
                "profile_id": 1,
                "monitored": False,
                "search_now": False,
                "add_collection": True
            })
            mock_radarr.add_movie.assert_called_once_with(
                movie_data={"title": "Movie", "year": 2024, "is_in_library": True},
                quality_profile_id=1,
                root_folder_path="/movies",
                monitored=False,
                search_now=False,
                add_collection=True
            )

            # Test TV flags
            client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Show", "year": 2024},
                "folder": "/tv",
                "profile_id": 2,
                "monitored": False,
                "search_now": False
            })
            mock_sonarr.add_series.assert_called_once_with(
                series_data={"title": "Show", "year": 2024, "is_in_library": True},
                quality_profile_id=2,
                root_folder_path="/tv",
                monitored=False,
                search_now=False
            )


# ===========================================================================
# 2. Boundary Conditions: Invalid JSON Types in POST /api/settings
# ===========================================================================

class TestBoundaryConditionsSettingsAPI:
    """Stress-test POST /api/settings with various invalid or extreme data types."""

    def test_settings_empty_payload(self, client):
        res = client.post("/api/settings", json={})
        assert res.status_code == 200
        assert res.get_json()["status"] == "success"

    def test_settings_coercion_types(self, client):
        """Verify integers, booleans, floats, lists, dicts, None in settings are serialized without crashing."""
        payload = {
            "radarr_default_quality_profile": 12345,
            "radarr_default_root_folder": "/data/movies",
            "sonarr_default_quality_profile": True,
            "sonarr_default_root_folder": 3.14159,
            "custom_list_val": [1, 2, "3"],
            "custom_dict_val": {"nested": "value"},
            "null_val": None
        }
        res = client.post("/api/settings", json=payload)
        assert res.status_code == 200
        assert res.get_json()["status"] == "success"

        # Verify retrieval
        get_res = client.get("/api/settings")
        assert get_res.status_code == 200
        settings = get_res.get_json()
        assert settings["radarr_default_quality_profile"] == "12345"
        assert settings["radarr_default_root_folder"] == "/data/movies"
        assert settings["sonarr_default_quality_profile"] == "True"
        assert settings["sonarr_default_root_folder"] == "3.14159"
        assert settings["null_val"] == "None"

    def test_settings_extreme_large_string_values(self, client):
        """Stress-test large payloads in settings table."""
        large_str = "A" * 100000  # 100 KB string
        res = client.post("/api/settings", json={"large_key": large_str})
        assert res.status_code == 200
        assert core.db.get_setting("large_key") == large_str

    def test_settings_unicode_and_special_characters(self, client):
        """Verify international characters, emojis, and special symbols in settings."""
        unicode_payload = {
            "radarr_default_root_folder": "/media/filmer/🎬_movies_4k/日本語",
            "sonarr_default_root_folder": "/media/serier/📺_tv_1080p/한국어",
            "radarr_default_quality_profile": "720p/1080p & 4K (Ultra-HD) 🚀"
        }
        res = client.post("/api/settings", json=unicode_payload)
        assert res.status_code == 200

        get_res = client.get("/api/settings")
        settings = get_res.get_json()
        assert settings["radarr_default_root_folder"] == "/media/filmer/🎬_movies_4k/日本語"
        assert settings["sonarr_default_root_folder"] == "/media/serier/📺_tv_1080p/한국어"
        assert settings["radarr_default_quality_profile"] == "720p/1080p & 4K (Ultra-HD) 🚀"

    def test_settings_sql_injection_defense(self, client):
        """Verify SQL injection strings in setting keys and values are safely escaped."""
        sql_payload = {
            "injection_key'; DROP TABLE settings; --": "test_val",
            "radarr_default_quality_profile": "' OR '1'='1'; --",
            "radarr_default_root_folder": "'; DELETE FROM cache; --"
        }
        res = client.post("/api/settings", json=sql_payload)
        assert res.status_code == 200

        # Ensure settings table was not dropped or corrupted
        conn = core.db.get_db_connection()
        count = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
        conn.close()
        assert count > 0
        assert core.db.get_setting("radarr_default_quality_profile") == "' OR '1'='1'; --"


# ===========================================================================
# 3. Concurrency Stress Testing: Concurrent Adds & MRU Updates
# ===========================================================================

class TestConcurrencyAndRaceConditions:
    """Stress-test concurrent calls to DB and settings."""

    def test_concurrent_demo_adds_database_isolation(self):
        """20 threads concurrently updating database and cache in demo mode without SQLite locks."""
        errors = []
        successes = []

        def worker_add(idx):
            is_tv = (idx % 2 == 0)
            media_type = "tv" if is_tv else "movie"
            profile_id = (idx % 4) + 1
            folder = f"/media/folder_{idx % 3}"
            raw_meta = {
                "title": f"Concurrent Item {idx}",
                "year": 2020 + (idx % 5),
                "imdbId": f"tt{idx:07d}",
                "tvdbId": idx if is_tv else None,
                "tmdbId": idx if not is_tv else None
            }
            try:
                raw_meta["is_in_library"] = True
                core.db.add_cached_item(media_type, raw_meta)
                if media_type == "tv":
                    core.db.set_setting("sonarr_mru_quality_profile", str(profile_id))
                    core.db.set_setting("sonarr_mru_profile_id", str(profile_id))
                    core.db.set_setting("sonarr_mru_root_folder", str(folder))
                else:
                    core.db.set_setting("radarr_mru_quality_profile", str(profile_id))
                    core.db.set_setting("radarr_mru_profile_id", str(profile_id))
                    core.db.set_setting("radarr_mru_root_folder", str(folder))
                config.refresh()
                successes.append(idx)
            except Exception as e:
                errors.append((idx, str(e)))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_add, i) for i in range(20)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Concurrent add errors encountered: {errors}"
        assert len(successes) == 20

        # Verify that MRU settings exist and are valid
        assert core.db.get_setting("sonarr_mru_quality_profile") != ""
        assert core.db.get_setting("radarr_mru_quality_profile") != ""

    def test_concurrent_settings_read_write_and_config_refresh(self):
        """Simultaneous reads, writes, and config refreshes across 20 threads without deadlocks."""
        errors = []

        def writer(idx):
            try:
                core.db.set_setting(f"key_{idx}", f"val_{idx}")
                core.db.set_setting("radarr_default_quality_profile", str(idx))
                core.db.set_setting("sonarr_default_root_folder", f"/tv_{idx}")
                config.refresh()
            except Exception as e:
                errors.append(f"Writer {idx} failed: {e}")

        def reader(idx):
            try:
                settings = core.db.get_all_settings()
                _ = settings.get("radarr_default_quality_profile")
                _ = config.radarr_default_quality_profile
                _ = config.sonarr_default_root_folder
                config.refresh()
            except Exception as e:
                errors.append(f"Reader {idx} failed: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(10):
                futures.append(executor.submit(writer, i))
                futures.append(executor.submit(reader, i))
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Concurrent settings read/write errors: {errors}"


# ===========================================================================
# 4. Strict Deprecation Enforcement: Sonarr Language Profile Removal
# ===========================================================================

class TestSonarrLanguageProfileDeprecation:
    """R3: Enforce strict removal of Sonarr language profile support across client, config, and add API."""

    def test_sonarr_client_no_language_profile_methods(self):
        sonarr = SonarrClient("http://localhost:8989", "sonarr_key")
        assert not hasattr(sonarr, "get_language_profiles"), "get_language_profiles must be completely removed from SonarrClient"

    def test_sonarr_client_add_series_no_language_profile_arg(self):
        sonarr = SonarrClient("http://localhost:8989", "sonarr_key")
        import inspect
        sig = inspect.signature(sonarr.add_series)
        assert "language_profile_id" not in sig.parameters, "language_profile_id must be removed from SonarrClient.add_series parameters"

        # Verify add_series payload does not contain languageProfileId
        with patch.object(sonarr, "_request", return_value={"id": 1}) as mock_req:
            sonarr.add_series(
                series_data={"title": "Show"},
                quality_profile_id=1,
                root_folder_path="/tv",
                monitored=True,
                search_now=True
            )
            json_payload = mock_req.call_args[1]["json_data"]
            assert "languageProfileId" not in json_payload, "languageProfileId must NOT be present in Sonarr add_series request payload"

    def test_api_config_no_language_profiles(self, client):
        mock_sonarr = MagicMock()
        mock_sonarr.get_root_folders.return_value = [{"path": "/tv"}]
        mock_sonarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]

        with patch("xarrtools.web.server.get_clients", return_value=(None, mock_sonarr)):
            res = client.get("/api/config")
            assert res.status_code == 200
            data = res.get_json()
            assert "language_profiles" not in data["sonarr"]
            assert "languageProfiles" not in data["sonarr"]

    def test_api_add_ignores_extraneous_lang_profile_id(self, client):
        mock_sonarr = MagicMock()
        mock_sonarr.add_series.return_value = {"id": 10, "title": "Show"}

        with patch("xarrtools.web.server.get_clients", return_value=(None, mock_sonarr)):
            res = client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Show", "year": 2024},
                "folder": "/tv/folder",
                "profile_id": 2,
                "lang_profile_id": 9999,  # Deprecated key passed by legacy client
                "language_profile_id": 8888
            })
            assert res.status_code == 200
            mock_sonarr.add_series.assert_called_once()
            called_kwargs = mock_sonarr.add_series.call_args[1]
            assert "language_profile_id" not in called_kwargs
            assert "lang_profile_id" not in called_kwargs


# ===========================================================================
# 5. Core Config Property Hierarchy & Aliasing Tests
# ===========================================================================

class TestConfigPropertiesAndAliasing:
    """Verify all Config property getters, DB precedence over env vars, and alias properties."""

    def test_config_property_db_precedence_over_env(self):
        core.db.set_setting("radarr_default_quality_profile", "10")
        core.db.set_setting("radarr_default_root_folder", "/db/radarr")
        core.db.set_setting("sonarr_default_quality_profile", "20")
        core.db.set_setting("sonarr_default_root_folder", "/db/sonarr")
        core.db.set_setting("radarr_mru_quality_profile", "11")
        core.db.set_setting("radarr_mru_root_folder", "/db/radarr_mru")
        core.db.set_setting("sonarr_mru_quality_profile", "21")
        core.db.set_setting("sonarr_mru_root_folder", "/db/sonarr_mru")

        with patch.dict(os.environ, {
            "RADARR_DEFAULT_QUALITY_PROFILE": "99",
            "RADARR_DEFAULT_ROOT_FOLDER": "/env/radarr",
            "SONARR_DEFAULT_QUALITY_PROFILE": "99",
            "SONARR_DEFAULT_ROOT_FOLDER": "/env/sonarr",
            "RADARR_MRU_QUALITY_PROFILE": "99",
            "RADARR_MRU_ROOT_FOLDER": "/env/radarr_mru",
            "SONARR_MRU_QUALITY_PROFILE": "99",
            "SONARR_MRU_ROOT_FOLDER": "/env/sonarr_mru",
        }):
            config.refresh()
            # DB values must take precedence
            assert config.radarr_default_quality_profile == "10"
            assert config.radarr_default_profile_id == "10"
            assert config.radarr_default_root_folder == "/db/radarr"
            assert config.sonarr_default_quality_profile == "20"
            assert config.sonarr_default_profile_id == "20"
            assert config.sonarr_default_root_folder == "/db/sonarr"
            assert config.radarr_mru_quality_profile == "11"
            assert config.radarr_mru_profile_id == "11"
            assert config.radarr_mru_root_folder == "/db/radarr_mru"
            assert config.sonarr_mru_quality_profile == "21"
            assert config.sonarr_mru_profile_id == "21"
            assert config.sonarr_mru_root_folder == "/db/sonarr_mru"

    def test_config_property_fallback_to_env_when_db_empty(self):
        with patch.dict(os.environ, {
            "RADARR_DEFAULT_QUALITY_PROFILE": "55",
            "RADARR_DEFAULT_ROOT_FOLDER": "/env/movies",
            "SONARR_DEFAULT_QUALITY_PROFILE": "66",
            "SONARR_DEFAULT_ROOT_FOLDER": "/env/tv",
            "RADARR_MRU_QUALITY_PROFILE": "56",
            "RADARR_MRU_ROOT_FOLDER": "/env/movies_mru",
            "SONARR_MRU_QUALITY_PROFILE": "67",
            "SONARR_MRU_ROOT_FOLDER": "/env/tv_mru",
        }):
            config.refresh()
            assert config.radarr_default_quality_profile == "55"
            assert config.radarr_default_root_folder == "/env/movies"
            assert config.sonarr_default_quality_profile == "66"
            assert config.sonarr_default_root_folder == "/env/tv"
            assert config.radarr_mru_quality_profile == "56"
            assert config.radarr_mru_root_folder == "/env/movies_mru"
            assert config.sonarr_mru_quality_profile == "67"
            assert config.sonarr_mru_root_folder == "/env/tv_mru"

    def test_config_property_alias_fallback(self):
        """Verify *_profile_id alias keys in database work if *_quality_profile is unset."""
        core.db.set_setting("radarr_default_profile_id", "7")
        core.db.set_setting("sonarr_default_profile_id", "8")
        core.db.set_setting("radarr_mru_profile_id", "9")
        core.db.set_setting("sonarr_mru_profile_id", "10")

        config.refresh()
        assert config.radarr_default_quality_profile == "7"
        assert config.radarr_default_profile_id == "7"
        assert config.sonarr_default_quality_profile == "8"
        assert config.sonarr_default_profile_id == "8"
        assert config.radarr_mru_quality_profile == "9"
        assert config.radarr_mru_profile_id == "9"
        assert config.sonarr_mru_quality_profile == "10"
        assert config.sonarr_mru_profile_id == "10"


# ===========================================================================
# 6. Client Trailing Slashes & Error Parsing Resilience
# ===========================================================================

class TestClientResilience:
    """Stress-test BaseArrClient URL normalization, headers, and error parsing."""

    def test_client_url_trailing_slashes_normalization(self):
        client = RadarrClient("http://radarr-host:7878///", "api_key_123")
        assert client.base_url == "http://radarr-host:7878"
        assert client.headers["X-Api-Key"] == "api_key_123"

        with patch("requests.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            mock_req.return_value = mock_resp

            client._request("GET", "///movie///lookup")
            mock_req.assert_called_once_with(
                method="GET",
                url="http://radarr-host:7878/api/v3/movie///lookup",
                headers={"X-Api-Key": "api_key_123", "Content-Type": "application/json"},
                params=None,
                json=None,
                timeout=15
            )

    def test_client_error_parsing_html_502_bad_gateway(self):
        client = SonarrClient("http://sonarr:8989", "key")
        with patch("requests.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 502
            mock_resp.text = "<html><body>502 Bad Gateway</body></html>"
            mock_resp.json.side_effect = Exception("Not JSON")
            mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("502 Bad Gateway")
            mock_req.return_value = mock_resp

            with pytest.raises(ArrAPIError) as exc_info:
                client.get_library()

            assert exc_info.value.status_code == 502
            assert "502 Bad Gateway" in str(exc_info.value)
            assert exc_info.value.response_text == "<html><body>502 Bad Gateway</body></html>"
