"""
Adversarial Challenge Test Suite for Milestone 1
Targeting:
1. Complete removal of deprecated Sonarr Language Profiles (Client, API, Server)
2. Hybrid Settings and MRU Persistence
3. Priority Resolution & Config Accessors
4. Edge cases: concurrency, malformed payloads, special characters, fallback mechanisms
"""

import os
import json
import inspect
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Isolate DB
import core.db
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

with patch("threading.Thread"):
    from web.server import app, get_clients
from core.client import RadarrClient, SonarrClient, ArrAPIError, BaseArrClient
from core.config import config, Config


@pytest.fixture(autouse=True)
def clean_db_and_env(monkeypatch):
    """Clean DB and reset environment before each test."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    core.db.init_db()
    core.db.set_setting("api_key", "test-key-challenge")
    config.refresh()
    yield


@pytest.fixture
def auth_client():
    app.config["TESTING"] = True
    core.db.set_setting("api_key", "test-key-challenge")
    config.refresh()

    class TestClientWrapper:
        def __init__(self, c):
            self.c = c

        def get(self, *args, **kwargs):
            return self.c.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test-key-challenge"
            kwargs["headers"] = headers
            return self.c.post(*args, **kwargs)

    with app.test_client() as c:
        yield TestClientWrapper(c)


# =========================================================================
# 1. EMPIRICAL VERIFICATION: Language Profile Absence & Client Signatures
# =========================================================================

def test_sonarr_client_no_language_profile_methods_or_attributes():
    """Verify SonarrClient class has no get_language_profiles method."""
    sonarr = SonarrClient("http://localhost:8989", "fake-key")
    assert not hasattr(sonarr, "get_language_profiles"), "SonarrClient still has get_language_profiles method!"
    assert not hasattr(BaseArrClient, "get_language_profiles")


def test_sonarr_client_add_series_signature_and_wire_payload():
    """Verify SonarrClient.add_series accepts NO language_profile_id and sends clean payload."""
    sonarr = SonarrClient("http://localhost:8989", "fake-key")
    sig = inspect.signature(sonarr.add_series)
    params = list(sig.parameters.keys())

    assert "language_profile_id" not in params, f"add_series signature contains language_profile_id: {params}"
    assert params == ["series_data", "quality_profile_id", "root_folder_path", "monitored", "search_now"]

    # Verify wire payload
    with patch.object(sonarr, "_request", return_value={"id": 1}) as mock_req:
        series_data = {
            "title": "Breaking Bad",
            "tvdbId": 81189,
            "seasons": [{"seasonNumber": 1, "monitored": True}]
        }
        sonarr.add_series(
            series_data=series_data,
            quality_profile_id=4,
            root_folder_path="/media/tv",
            monitored=True,
            search_now=False
        )

        mock_req.assert_called_once()
        called_args, called_kwargs = mock_req.call_args
        assert called_args == ("POST", "series")
        payload = called_kwargs["json_data"]
        assert payload["qualityProfileId"] == 4
        assert payload["rootFolderPath"] == "/media/tv"
        assert payload["monitored"] is True
        assert payload["addOptions"]["searchForMissingEpisodes"] is False
        assert "languageProfileId" not in payload, "languageProfileId was unexpectedly sent in Sonarr payload!"
        assert "language_profile_id" not in payload


def test_server_config_api_strictly_omits_language_profiles(auth_client):
    """Verify GET /api/config response has zero references to language profiles."""
    mock_radarr = MagicMock()
    mock_radarr.get_root_folders.return_value = [{"id": 1, "path": "/data/movies"}]
    mock_radarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD-1080p"}]

    mock_sonarr = MagicMock()
    mock_sonarr.get_root_folders.return_value = [{"id": 1, "path": "/data/tv"}]
    mock_sonarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD-1080p"}]

    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        res = auth_client.get("/api/config")
        assert res.status_code == 200
        data = res.get_json()

        assert "sonarr" in data
        assert "radarr" in data
        assert "language_profiles" not in data["sonarr"]
        assert "language_profiles" not in data["radarr"]
        assert "languageProfiles" not in data["sonarr"]
        assert "languageProfiles" not in data["radarr"]


# =========================================================================
# 2. EMPIRICAL VERIFICATION: Settings & MRU Persistence
# =========================================================================

def test_settings_api_full_crud_and_refresh(auth_client):
    """Test saving and retrieving default settings and MRU settings via /api/settings."""
    payload = {
        "radarr_default_quality_profile": "12",
        "radarr_default_root_folder": "/volume1/movies",
        "sonarr_default_quality_profile": "15",
        "sonarr_default_root_folder": "/volume1/tv",
        "radarr_mru_quality_profile": "10",
        "radarr_mru_root_folder": "/volume1/movies_mru",
        "sonarr_mru_quality_profile": "11",
        "sonarr_mru_root_folder": "/volume1/tv_mru",
    }

    res_post = auth_client.post("/api/settings", json=payload)
    assert res_post.status_code == 200
    assert res_post.get_json()["status"] == "success"

    res_get = auth_client.get("/api/settings")
    assert res_get.status_code == 200
    all_settings = res_get.get_json()

    for k, v in payload.items():
        assert all_settings.get(k) == v

    # Verify Config properties reflect updated values
    assert config.radarr_default_quality_profile == "12"
    assert config.radarr_default_profile_id == "12"
    assert config.radarr_default_root_folder == "/volume1/movies"
    assert config.sonarr_default_quality_profile == "15"
    assert config.sonarr_default_profile_id == "15"
    assert config.sonarr_default_root_folder == "/volume1/tv"
    assert config.radarr_mru_quality_profile == "10"
    assert config.radarr_mru_profile_id == "10"
    assert config.radarr_mru_root_folder == "/volume1/movies_mru"
    assert config.sonarr_mru_quality_profile == "11"
    assert config.sonarr_mru_profile_id == "11"
    assert config.sonarr_mru_root_folder == "/volume1/tv_mru"


def test_add_media_mru_isolation_and_live_updates(auth_client):
    """Test that POST /api/add updates MRU immediately and isolates Movie vs TV."""
    mock_radarr = MagicMock()
    mock_radarr.add_movie.return_value = {"id": 100, "title": "Inception"}
    mock_sonarr = MagicMock()
    mock_sonarr.add_series.return_value = {"id": 200, "title": "Dark"}

    with patch("web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
        # 1. Add Movie
        movie_req = {
            "type": "movie",
            "raw_metadata": {"title": "Inception", "year": 2010, "tmdbId": 27205},
            "folder": "/movies/4k",
            "profile_id": 7,
            "monitored": True,
            "search_now": True,
            "add_collection": True
        }
        res1 = auth_client.post("/api/add", json=movie_req)
        assert res1.status_code == 200

        # Verify Radarr client called properly
        assert mock_radarr.add_movie.call_count == 1
        call_kwargs = mock_radarr.add_movie.call_args[1]
        assert call_kwargs["quality_profile_id"] == 7
        assert call_kwargs["root_folder_path"] == "/movies/4k"
        assert call_kwargs["monitored"] is True
        assert call_kwargs["search_now"] is True
        assert call_kwargs["add_collection"] is True
        assert call_kwargs["movie_data"]["title"] == "Inception"

        # Verify Radarr MRU updated in DB and Config
        assert core.db.get_setting("radarr_mru_quality_profile") == "7"
        assert core.db.get_setting("radarr_mru_profile_id") == "7"
        assert core.db.get_setting("radarr_mru_root_folder") == "/movies/4k"
        assert config.radarr_mru_quality_profile == "7"
        assert config.radarr_mru_root_folder == "/movies/4k"

        # Verify Sonarr MRU is still empty
        assert core.db.get_setting("sonarr_mru_quality_profile") == ""
        assert core.db.get_setting("sonarr_mru_root_folder") == ""

        # 2. Add TV Show
        tv_req = {
            "type": "tv",
            "raw_metadata": {"title": "Dark", "year": 2017, "tvdbId": 334824},
            "folder": "/tv/sci-fi",
            "profile_id": 9,
            "monitored": False,
            "search_now": False
        }
        res2 = auth_client.post("/api/add", json=tv_req)
        assert res2.status_code == 200

        # Verify Sonarr client called properly
        assert mock_sonarr.add_series.call_count == 1
        call_kwargs = mock_sonarr.add_series.call_args[1]
        assert call_kwargs["quality_profile_id"] == 9
        assert call_kwargs["root_folder_path"] == "/tv/sci-fi"
        assert call_kwargs["monitored"] is False
        assert call_kwargs["search_now"] is False
        assert call_kwargs["series_data"]["title"] == "Dark"

        # Verify Sonarr MRU updated in DB and Config
        assert core.db.get_setting("sonarr_mru_quality_profile") == "9"
        assert core.db.get_setting("sonarr_mru_profile_id") == "9"
        assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/sci-fi"
        assert config.sonarr_mru_quality_profile == "9"
        assert config.sonarr_mru_root_folder == "/tv/sci-fi"

        # Verify Radarr MRU was NOT overwritten
        assert core.db.get_setting("radarr_mru_quality_profile") == "7"
        assert core.db.get_setting("radarr_mru_root_folder") == "/movies/4k"


def test_add_media_demo_sandbox_mru_updates(auth_client):
    """Test demo sandbox additions for both `demo: True` and `is_demo: True`."""
    # 1. Movie demo sandbox
    res_movie = auth_client.post("/api/add", json={
        "type": "movie",
        "raw_metadata": {"title": "Demo Movie", "year": 2025, "tmdbId": 9999},
        "folder": "/sandbox/movies",
        "profile_id": 3,
        "demo": True
    })
    assert res_movie.status_code == 200
    assert "Sandbox" in res_movie.get_json()["message"]
    assert core.db.get_setting("radarr_mru_quality_profile") == "3"
    assert core.db.get_setting("radarr_mru_root_folder") == "/sandbox/movies"

    # 2. TV show demo sandbox (with is_demo flag)
    res_tv = auth_client.post("/api/add", json={
        "type": "tv",
        "raw_metadata": {"title": "Demo TV", "year": 2025, "tvdbId": 8888},
        "folder": "/sandbox/tv",
        "profile_id": 6,
        "is_demo": True
    })
    assert res_tv.status_code == 200
    assert "Sandbox" in res_tv.get_json()["message"]
    assert core.db.get_setting("sonarr_mru_quality_profile") == "6"
    assert core.db.get_setting("sonarr_mru_root_folder") == "/sandbox/tv"


# =========================================================================
# 3. EMPIRICAL VERIFICATION: Config Precedence & Fallback Logic
# =========================================================================

def test_config_db_priority_over_env(monkeypatch):
    """Test that SQLite database settings take precedence over environment variables."""
    cfg = Config()

    monkeypatch.setenv("RADARR_DEFAULT_QUALITY_PROFILE", "env_profile_1")
    monkeypatch.setenv("RADARR_DEFAULT_ROOT_FOLDER", "/env/movies")

    # When DB is empty, falls back to ENV
    cfg.refresh()
    assert cfg.radarr_default_quality_profile == "env_profile_1"
    assert cfg.radarr_default_root_folder == "/env/movies"

    # When DB is set, DB takes priority over ENV
    core.db.set_setting("radarr_default_quality_profile", "db_profile_2")
    core.db.set_setting("radarr_default_root_folder", "/db/movies")
    cfg.refresh()

    assert cfg.radarr_default_quality_profile == "db_profile_2"
    assert cfg.radarr_default_root_folder == "/db/movies"


def test_config_alias_key_fallbacks():
    """Test that Config properties check both _quality_profile and _profile_id keys."""
    cfg = Config()

    # Test setting only _profile_id
    core.db.set_setting("radarr_default_profile_id", "42")
    core.db.set_setting("sonarr_mru_profile_id", "84")
    cfg.refresh()

    assert cfg.radarr_default_quality_profile == "42"
    assert cfg.radarr_default_profile_id == "42"
    assert cfg.sonarr_mru_quality_profile == "84"
    assert cfg.sonarr_mru_profile_id == "84"


# =========================================================================
# 4. EMPIRICAL VERIFICATION: Edge Cases & Adversarial Inputs
# =========================================================================

def test_add_media_missing_parameters_validation(auth_client):
    """Test parameter validation in POST /api/add."""
    # 1. Missing type
    res = auth_client.post("/api/add", json={"raw_metadata": {}, "folder": "/tv", "profile_id": 1})
    assert res.status_code == 400

    # 2. Missing raw_metadata
    res = auth_client.post("/api/add", json={"type": "tv", "folder": "/tv", "profile_id": 1})
    assert res.status_code == 400

    # 3. Missing folder
    res = auth_client.post("/api/add", json={"type": "tv", "raw_metadata": {"title": "A"}, "profile_id": 1})
    assert res.status_code == 400

    # 4. Missing profile_id
    res = auth_client.post("/api/add", json={"type": "tv", "raw_metadata": {"title": "A"}, "folder": "/tv"})
    assert res.status_code == 400


def test_add_media_unconfigured_clients(auth_client):
    """Test POST /api/add when clients are not configured."""
    with patch("web.server.get_clients", return_value=(None, None)):
        res_tv = auth_client.post("/api/add", json={
            "type": "tv",
            "raw_metadata": {"title": "Test TV"},
            "folder": "/tv",
            "profile_id": 1
        })
        assert res_tv.status_code == 400
        assert "Sonarr server is not configured" in res_tv.get_json()["message"]

        res_movie = auth_client.post("/api/add", json={
            "type": "movie",
            "raw_metadata": {"title": "Test Movie"},
            "folder": "/movies",
            "profile_id": 1
        })
        assert res_movie.status_code == 400
        assert "Radarr server is not configured" in res_movie.get_json()["message"]


def test_add_media_arr_api_error_handling(auth_client):
    """Test that upstream ArrAPIError is captured and returned as a 500 error."""
    mock_sonarr = MagicMock()
    mock_sonarr.add_series.side_effect = ArrAPIError("Sonarr API HTTP Error 400: Path does not exist", status_code=400)

    with patch("web.server.get_clients", return_value=(None, mock_sonarr)):
        res = auth_client.post("/api/add", json={
            "type": "tv",
            "raw_metadata": {"title": "Failing TV", "tvdbId": 123},
            "folder": "/nonexistent/tv",
            "profile_id": 1
        })
        assert res.status_code == 500
        data = res.get_json()
        assert data["status"] == "error"
        assert "Path does not exist" in data["message"]


def test_special_characters_and_unicode_in_paths(auth_client):
    """Test special characters, spaces, and Unicode paths in settings and MRU."""
    weird_path = "/mnt/Media (4K)/TV [Shows]/!Special #1/Café & Co/"
    auth_client.post("/api/settings", json={"sonarr_default_root_folder": weird_path})

    assert core.db.get_setting("sonarr_default_root_folder") == weird_path
    assert config.sonarr_default_root_folder == weird_path

    # Simulate add with weird path
    auth_client.post("/api/add", json={
        "type": "tv",
        "raw_metadata": {"title": "Café Show", "year": 2025},
        "folder": weird_path,
        "profile_id": 1,
        "demo": True
    })
    assert core.db.get_setting("sonarr_mru_root_folder") == weird_path
    assert config.sonarr_mru_root_folder == weird_path


def test_sequential_and_consecutive_mru_updates(auth_client):
    """Test sequential MRU additions across movie and TV."""
    for idx in range(1, 10):
        t = "tv" if idx % 2 == 0 else "movie"
        res = auth_client.post("/api/add", json={
            "type": t,
            "raw_metadata": {"title": f"Item {idx}", "year": 2025},
            "folder": f"/media/folder_{idx}",
            "profile_id": idx,
            "demo": True
        })
        assert res.status_code == 200
        if t == "tv":
            assert core.db.get_setting("sonarr_mru_quality_profile") == str(idx)
            assert core.db.get_setting("sonarr_mru_root_folder") == f"/media/folder_{idx}"
        else:
            assert core.db.get_setting("radarr_mru_quality_profile") == str(idx)
            assert core.db.get_setting("radarr_mru_root_folder") == f"/media/folder_{idx}"
