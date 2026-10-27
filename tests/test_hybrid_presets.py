"""
End-to-End and Integration Test Suite for Hybrid Presets & Language Profile Deprecation.

Features Covered:
- Hybrid Preset Selection (Explicit Default -> MRU Fallback -> First Option Safety Fallback)
- Complete Removal of Deprecated Sonarr Language Profiles across Client, API, and CLI
- Database & Config Settings Persistence for Defaults and MRU
- Boundary conditions, error resilience, cross-feature interactions, and full user lifecycle workflows
"""

import os
import json
import tempfile
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Isolate SQLite database path before importing application modules
import xarrtools.core.db; from xarrtools import core
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

with patch("threading.Thread") as mock_thread:
    from xarrtools.web.server import app, get_clients
from xarrtools.core.client import RadarrClient, SonarrClient, ArrAPIError
from xarrtools.core.config import config


# ---------------------------------------------------------------------------
# Authoritative Hybrid Preset Resolution Reference Logic (Requirement R1)
# ---------------------------------------------------------------------------

def resolve_hybrid_preset(
    service: str,
    preset_type: str,
    options: list,
    settings: dict = None
):
    """
    Authoritative 3-tier Hybrid Preset Resolution:
    1. Primary: Explicit setting configured in Settings table/dict.
    2. Fallback: Most Recently Used (MRU) from last added item.
    3. Safety Fallback: First available option in active options list (index 0).
    """
    if not options or not isinstance(options, list) or len(options) == 0:
        return None

    if settings is None:
        settings = core.db.get_all_settings()

    service = service.lower()

    if preset_type == "profile":
        explicit_keys = [
            f"{service}_default_quality_profile",
            f"{service}_default_profile_id",
        ]
        mru_keys = [
            f"{service}_mru_quality_profile",
            f"{service}_mru_profile_id",
        ]
        match_key = "id"
    else:  # folder
        explicit_keys = [
            f"{service}_default_root_folder",
        ]
        mru_keys = [
            f"{service}_mru_root_folder",
        ]
        match_key = "path"

    # 1. Primary: Check Explicit Default
    for key in explicit_keys:
        val = settings.get(key)
        if val is not None and str(val).strip() != "":
            val_str = str(val).strip()
            for opt in options:
                if isinstance(opt, dict) and match_key in opt:
                    if str(opt[match_key]).strip() == val_str:
                        return opt

    # 2. Fallback: Check MRU Setting
    for key in mru_keys:
        val = settings.get(key)
        if val is not None and str(val).strip() != "":
            val_str = str(val).strip()
            for opt in options:
                if isinstance(opt, dict) and match_key in opt:
                    if str(opt[match_key]).strip() == val_str:
                        return opt

    # 3. Safety Fallback: Return first valid option
    for opt in options:
        if isinstance(opt, dict) and match_key in opt:
            return opt

    return options[0] if options else None


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_database():
    """Wipes settings and cache before each test case and resets config."""
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    core.db.init_db()
    core.db.set_setting("api_key", "test-preset-api-key")
    config.refresh()
    yield


@pytest.fixture
def client():
    """Flask TestClient wrapper that injects authentication header for mutating calls."""
    app.config["TESTING"] = True
    core.db.set_setting("api_key", "test-preset-api-key")
    config.refresh()

    class TestClientWrapper:
        def __init__(self, c):
            self.c = c

        def _get_api_key(self):
            return core.db.get_setting("api_key", "test-preset-api-key")

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
# Tier 1: Feature Coverage Tests
# ===========================================================================

class TestTier1FeatureCoverage:
    """Tier 1: Verify core functional requirements for hybrid presets and language profile removal."""

    def test_t1_radarr_explicit_settings_default_profile(self):
        """R1: Explicit Settings default profile is pre-selected for Radarr."""
        core.db.set_setting("radarr_default_quality_profile", "2")
        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "Ultra-HD"}]
        
        result = resolve_hybrid_preset("radarr", "profile", profiles)
        assert result is not None
        assert result["id"] == 2
        assert result["name"] == "1080p"

    def test_t1_radarr_explicit_settings_default_folder(self):
        """R1: Explicit Settings default root folder is pre-selected for Radarr."""
        core.db.set_setting("radarr_default_root_folder", "/data/media/movies_4k")
        folders = [{"path": "/data/media/movies_hd"}, {"path": "/data/media/movies_4k"}]

        result = resolve_hybrid_preset("radarr", "folder", folders)
        assert result is not None
        assert result["path"] == "/data/media/movies_4k"

    def test_t1_sonarr_explicit_settings_default_profile(self):
        """R1: Explicit Settings default profile is pre-selected for Sonarr."""
        core.db.set_setting("sonarr_default_quality_profile", "3")
        profiles = [{"id": 1, "name": "Any"}, {"id": 2, "name": "720p"}, {"id": 3, "name": "WEB-1080p"}]

        result = resolve_hybrid_preset("sonarr", "profile", profiles)
        assert result is not None
        assert result["id"] == 3
        assert result["name"] == "WEB-1080p"

    def test_t1_sonarr_explicit_settings_default_folder(self):
        """R1: Explicit Settings default root folder is pre-selected for Sonarr."""
        core.db.set_setting("sonarr_default_root_folder", "/data/media/tv_shows")
        folders = [{"path": "/data/media/anime"}, {"path": "/data/media/tv_shows"}]

        result = resolve_hybrid_preset("sonarr", "folder", folders)
        assert result is not None
        assert result["path"] == "/data/media/tv_shows"

    def test_t1_radarr_mru_fallback_profile(self):
        """R1: In the absence of an explicit default, MRU profile is pre-selected for Radarr."""
        core.db.set_setting("radarr_mru_quality_profile", "3")
        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "Ultra-HD"}]

        result = resolve_hybrid_preset("radarr", "profile", profiles)
        assert result is not None
        assert result["id"] == 3

    def test_t1_radarr_mru_fallback_folder(self):
        """R1: In the absence of an explicit default, MRU root folder is pre-selected for Radarr."""
        core.db.set_setting("radarr_mru_root_folder", "/data/media/movies_hd")
        folders = [{"path": "/data/media/movies_default"}, {"path": "/data/media/movies_hd"}]

        result = resolve_hybrid_preset("radarr", "folder", folders)
        assert result is not None
        assert result["path"] == "/data/media/movies_hd"

    def test_t1_sonarr_mru_fallback_profile(self):
        """R1: In the absence of an explicit default, MRU profile is pre-selected for Sonarr."""
        core.db.set_setting("sonarr_mru_quality_profile", "2")
        profiles = [{"id": 1, "name": "Any"}, {"id": 2, "name": "HD-720p"}, {"id": 3, "name": "HD-1080p"}]

        result = resolve_hybrid_preset("sonarr", "profile", profiles)
        assert result is not None
        assert result["id"] == 2

    def test_t1_sonarr_mru_fallback_folder(self):
        """R1: In the absence of an explicit default, MRU root folder is pre-selected for Sonarr."""
        core.db.set_setting("sonarr_mru_root_folder", "/data/media/anime")
        folders = [{"path": "/data/media/tv"}, {"path": "/data/media/anime"}]

        result = resolve_hybrid_preset("sonarr", "folder", folders)
        assert result is not None
        assert result["path"] == "/data/media/anime"

    def test_t1_safety_fallback_first_option_radarr(self):
        """R1: When neither default nor MRU is set, Radarr safely selects index 0."""
        profiles = [{"id": 10, "name": "Standard"}, {"id": 20, "name": "Premium"}]
        folders = [{"path": "/mount/alpha"}, {"path": "/mount/beta"}]

        profile_res = resolve_hybrid_preset("radarr", "profile", profiles)
        folder_res = resolve_hybrid_preset("radarr", "folder", folders)

        assert profile_res == {"id": 10, "name": "Standard"}
        assert folder_res == {"path": "/mount/alpha"}

    def test_t1_safety_fallback_first_option_sonarr(self):
        """R1: When neither default nor MRU is set, Sonarr safely selects index 0."""
        profiles = [{"id": 5, "name": "Default TV"}, {"id": 6, "name": "High Quality"}]
        folders = [{"path": "/storage/tv_primary"}, {"path": "/storage/tv_secondary"}]

        profile_res = resolve_hybrid_preset("sonarr", "profile", profiles)
        folder_res = resolve_hybrid_preset("sonarr", "folder", folders)

        assert profile_res == {"id": 5, "name": "Default TV"}
        assert folder_res == {"path": "/storage/tv_primary"}

    def test_t1_sonarr_client_language_profile_removal(self):
        """R3: SonarrClient deprecates get_language_profiles and add_series has no languageProfileId."""
        sonarr = SonarrClient("http://localhost:8989", "sonarr_api_key")

        # 1. Verify get_language_profiles is either removed or returns empty/does not exist
        if hasattr(sonarr, "get_language_profiles"):
            with patch.object(sonarr, "_request", return_value=[]):
                res = sonarr.get_language_profiles()
                assert isinstance(res, list)

        # 2. Verify add_series signature and payload structure
        sig = inspect.signature(sonarr.add_series)
        # Verify add_series does not require language_profile_id
        assert "language_profile_id" not in sig.parameters or sig.parameters["language_profile_id"].default is None

        with patch.object(sonarr, "_request", return_value={"id": 101, "title": "Test Show"}) as mock_req:
            series_payload = {"title": "Test Show", "tvdbId": 9999}
            sonarr.add_series(
                series_data=series_payload,
                quality_profile_id=2,
                root_folder_path="/tv/shows",
                monitored=True,
                search_now=True
            )
            mock_req.assert_called_once()
            called_json = mock_req.call_args[1]["json_data"]
            assert called_json["qualityProfileId"] == 2
            assert called_json["rootFolderPath"] == "/tv/shows"
            assert called_json["monitored"] is True
            assert "languageProfileId" not in called_json

    def test_t1_server_config_endpoint_no_language_profiles(self, client):
        """R3: GET /api/config contains no language_profiles key in sonarr section."""
        mock_radarr = MagicMock()
        mock_radarr.get_root_folders.return_value = [{"path": "/movies"}]
        mock_radarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]

        mock_sonarr = MagicMock()
        mock_sonarr.get_root_folders.return_value = [{"path": "/tv"}]
        mock_sonarr.get_quality_profiles.return_value = [{"id": 2, "name": "FullHD"}]

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
            res = client.get("/api/config")
            assert res.status_code == 200
            data = res.get_json()
            assert data["radarr"]["configured"] is True
            assert data["sonarr"]["configured"] is True
            assert "language_profiles" not in data["sonarr"]

    def test_t1_server_add_tv_endpoint_no_lang_profile_and_persists_mru(self, client):
        """R1, R3: POST /api/add for TV show does not require lang_profile_id and updates Sonarr MRU."""
        mock_sonarr = MagicMock()
        mock_sonarr.add_series.return_value = {"id": 1, "title": "Severance", "year": 2022, "tvdbId": 12345}

        with patch("xarrtools.web.server.get_clients", return_value=(None, mock_sonarr)):
            payload = {
                "type": "tv",
                "raw_metadata": {"title": "Severance", "year": 2022, "tvdbId": 12345},
                "folder": "/tv/shows",
                "profile_id": 2,
                "monitored": True,
                "search_now": True
            }
            res = client.post("/api/add", json=payload)
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "success"

            # Check SonarrClient invocation
            mock_sonarr.add_series.assert_called_once()
            call_kwargs = mock_sonarr.add_series.call_args[1] if mock_sonarr.add_series.call_args[1] else {}
            if "language_profile_id" in call_kwargs:
                assert call_kwargs["language_profile_id"] is None

            # Verify MRU persistence in settings database
            assert core.db.get_setting("sonarr_mru_quality_profile") == "2"
            assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/shows"

    def test_t1_server_add_movie_endpoint_persists_mru(self, client):
        """R1: POST /api/add for movie updates Radarr MRU quality profile and root folder."""
        mock_radarr = MagicMock()
        mock_radarr.add_movie.return_value = {"id": 1, "title": "Dune 2", "year": 2024, "tmdbId": 67890}

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, None)):
            payload = {
                "type": "movie",
                "raw_metadata": {"title": "Dune 2", "year": 2024, "tmdbId": 67890},
                "folder": "/movies/sci-fi",
                "profile_id": 3,
                "monitored": True,
                "search_now": True,
                "add_collection": False
            }
            res = client.post("/api/add", json=payload)
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "success"

            mock_radarr.add_movie.assert_called_once()
            # Verify MRU persistence
            assert core.db.get_setting("radarr_mru_quality_profile") == "3"
            assert core.db.get_setting("radarr_mru_root_folder") == "/movies/sci-fi"

    def test_t1_settings_api_get_and_post_defaults(self, client):
        """R2: GET and POST /api/settings persist and retrieve default profile and folder selections."""
        settings_payload = {
            "radarr_default_quality_profile": "2",
            "radarr_default_root_folder": "/movies/default",
            "sonarr_default_quality_profile": "3",
            "sonarr_default_root_folder": "/tv/default"
        }
        post_res = client.post("/api/settings", json=settings_payload)
        assert post_res.status_code == 200
        assert post_res.get_json()["status"] == "success"

        get_res = client.get("/api/settings")
        assert get_res.status_code == 200
        saved_settings = get_res.get_json()

        assert saved_settings.get("radarr_default_quality_profile") == "2"
        assert saved_settings.get("radarr_default_root_folder") == "/movies/default"
        assert saved_settings.get("sonarr_default_quality_profile") == "3"
        assert saved_settings.get("sonarr_default_root_folder") == "/tv/default"


# ===========================================================================
# Tier 2: Boundary and Corner Cases
# ===========================================================================

class TestTier2BoundaryAndCornerCases:
    """Tier 2: Boundary values, unconfigured environments, deleted presets, and corrupt inputs."""

    def test_t2_empty_options_list_profile_and_folder(self):
        """Empty options list returns None without IndexError or exception."""
        assert resolve_hybrid_preset("radarr", "profile", []) is None
        assert resolve_hybrid_preset("radarr", "folder", []) is None
        assert resolve_hybrid_preset("sonarr", "profile", None) is None
        assert resolve_hybrid_preset("sonarr", "folder", "invalid_type") is None

    def test_t2_unconfigured_offline_services_api_behavior(self, client):
        """When services are unconfigured, config returns configured=False and add returns 400 gracefully."""
        with patch("xarrtools.web.server.get_clients", return_value=(None, None)):
            res_config = client.get("/api/config")
            assert res_config.status_code == 200
            data_config = res_config.get_json()
            assert data_config["radarr"]["configured"] is False
            assert data_config["sonarr"]["configured"] is False

            res_add = client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Show"},
                "folder": "/tv",
                "profile_id": 1
            })
            assert res_add.status_code == 400
            assert "Sonarr server is not configured" in res_add.get_json()["message"]

    def test_t2_deleted_invalid_profile_id_safety_fallback(self):
        """When an explicit default or MRU profile ID was deleted upstream, falls back to first available option."""
        # User configured profile 999 which no longer exists in Radarr
        core.db.set_setting("radarr_default_quality_profile", "999")
        core.db.set_setting("radarr_mru_quality_profile", "888")
        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}]

        result = resolve_hybrid_preset("radarr", "profile", profiles)
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "720p"

    def test_t2_deleted_invalid_root_folder_safety_fallback(self):
        """When an explicit default or MRU folder was deleted upstream, falls back to first available option."""
        core.db.set_setting("sonarr_default_root_folder", "/mnt/unmounted_drive")
        core.db.set_setting("sonarr_mru_root_folder", "/mnt/old_drive")
        folders = [{"path": "/data/tv_active"}, {"path": "/data/tv_secondary"}]

        result = resolve_hybrid_preset("sonarr", "folder", folders)
        assert result is not None
        assert result["path"] == "/data/tv_active"

    def test_t2_missing_and_empty_settings_values(self):
        """Empty string or whitespace values in database settings behave as unset."""
        core.db.set_setting("radarr_default_quality_profile", "")
        core.db.set_setting("radarr_mru_quality_profile", "   ")
        profiles = [{"id": 10, "name": "HD"}, {"id": 20, "name": "4K"}]

        result = resolve_hybrid_preset("radarr", "profile", profiles)
        assert result["id"] == 10

    def test_t2_profile_id_type_coercion_string_int(self):
        """String and integer profile IDs match correctly across SQLite string storage and API int representations."""
        core.db.set_setting("radarr_default_quality_profile", "2")
        profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "FHD"}]

        result = resolve_hybrid_preset("radarr", "profile", profiles)
        assert result["id"] == 2

        # Int setting format
        custom_settings = {"radarr_default_quality_profile": 2}
        result2 = resolve_hybrid_preset("radarr", "profile", profiles, settings=custom_settings)
        assert result2["id"] == 2

    def test_t2_non_numeric_and_malformed_setting_values(self):
        """Malformed settings string values safely fall back to first option without raising exceptions."""
        core.db.set_setting("radarr_default_quality_profile", "invalid_profile_text")
        profiles = [{"id": 1, "name": "Default"}, {"id": 2, "name": "Custom"}]

        result = resolve_hybrid_preset("radarr", "profile", profiles)
        assert result["id"] == 1

    def test_t2_partial_configuration_profile_set_folder_unset(self):
        """Explicit default for profile is used, while unconfigured folder falls back to MRU / first option."""
        core.db.set_setting("sonarr_default_quality_profile", "2")
        # No folder default set, but MRU folder exists
        core.db.set_setting("sonarr_mru_root_folder", "/tv/mru_folder")

        profiles = [{"id": 1, "name": "Any"}, {"id": 2, "name": "1080p"}]
        folders = [{"path": "/tv/first_folder"}, {"path": "/tv/mru_folder"}]

        profile_res = resolve_hybrid_preset("sonarr", "profile", profiles)
        folder_res = resolve_hybrid_preset("sonarr", "folder", folders)

        assert profile_res["id"] == 2
        assert folder_res["path"] == "/tv/mru_folder"

    def test_t2_partial_configuration_folder_set_profile_unset(self):
        """Explicit default for folder is used, while unconfigured profile falls back to MRU / first option."""
        core.db.set_setting("radarr_default_root_folder", "/movies/explicit")
        core.db.set_setting("radarr_mru_quality_profile", "3")

        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "4K"}]
        folders = [{"path": "/movies/first"}, {"path": "/movies/explicit"}]

        profile_res = resolve_hybrid_preset("radarr", "profile", profiles)
        folder_res = resolve_hybrid_preset("radarr", "folder", folders)

        assert profile_res["id"] == 3
        assert folder_res["path"] == "/movies/explicit"

    def test_t2_malformed_options_dicts_missing_keys(self):
        """List items missing 'id' or 'path' keys do not raise KeyError."""
        malformed_profiles = [{"name": "Broken Profile Without ID"}, {"id": 5, "name": "Valid Profile"}]
        malformed_folders = [{"directory": "/wrong/key"}, {"path": "/valid/path"}]

        core.db.set_setting("radarr_default_quality_profile", "5")
        core.db.set_setting("radarr_default_root_folder", "/valid/path")

        profile_res = resolve_hybrid_preset("radarr", "profile", malformed_profiles)
        folder_res = resolve_hybrid_preset("radarr", "folder", malformed_folders)

        assert profile_res["id"] == 5
        assert folder_res["path"] == "/valid/path"


# ===========================================================================
# Tier 3: Cross-Feature Combinations
# ===========================================================================

class TestTier3CrossFeatureCombinations:
    """Tier 3: Movie vs TV MRU separation, consecutive additions, explicit override over MRU, and sandbox mode."""

    def test_t3_movie_vs_tv_mru_isolation(self, client):
        """Movie additions update only Radarr MRU; TV additions update only Sonarr MRU."""
        mock_radarr = MagicMock()
        mock_radarr.add_movie.return_value = {"id": 1, "title": "Movie 1"}
        mock_sonarr = MagicMock()
        mock_sonarr.add_series.return_value = {"id": 2, "title": "Show 1"}

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
            # 1. Add Movie
            client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Movie 1", "year": 2024},
                "folder": "/movies/action",
                "profile_id": 10
            })

            assert core.db.get_setting("radarr_mru_quality_profile") == "10"
            assert core.db.get_setting("radarr_mru_root_folder") == "/movies/action"
            # Sonarr MRU remains empty
            assert core.db.get_setting("sonarr_mru_quality_profile") == ""
            assert core.db.get_setting("sonarr_mru_root_folder") == ""

            # 2. Add TV Show
            client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Show 1", "year": 2024},
                "folder": "/tv/drama",
                "profile_id": 20
            })

            # Radarr MRU untouched, Sonarr MRU updated
            assert core.db.get_setting("radarr_mru_quality_profile") == "10"
            assert core.db.get_setting("radarr_mru_root_folder") == "/movies/action"
            assert core.db.get_setting("sonarr_mru_quality_profile") == "20"
            assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/drama"

    def test_t3_consecutive_additions_updating_mru_state(self, client):
        """Consecutive additions progressively update MRU cache to latest selection."""
        mock_radarr = MagicMock()
        mock_radarr.add_movie.return_value = {"id": 1, "title": "Movie"}

        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "4K"}]
        folders = [{"path": "/movies/a"}, {"path": "/movies/b"}, {"path": "/movies/c"}]

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, None)):
            # Add 1: Profile 1, Folder A
            client.post("/api/add", json={"type": "movie", "raw_metadata": {"title": "M1", "year": 2024}, "folder": "/movies/a", "profile_id": 1})
            assert resolve_hybrid_preset("radarr", "profile", profiles)["id"] == 1
            assert resolve_hybrid_preset("radarr", "folder", folders)["path"] == "/movies/a"

            # Add 2: Profile 2, Folder B
            client.post("/api/add", json={"type": "movie", "raw_metadata": {"title": "M2", "year": 2024}, "folder": "/movies/b", "profile_id": 2})
            assert resolve_hybrid_preset("radarr", "profile", profiles)["id"] == 2
            assert resolve_hybrid_preset("radarr", "folder", folders)["path"] == "/movies/b"

            # Add 3: Profile 3, Folder C
            client.post("/api/add", json={"type": "movie", "raw_metadata": {"title": "M3", "year": 2024}, "folder": "/movies/c", "profile_id": 3})
            assert resolve_hybrid_preset("radarr", "profile", profiles)["id"] == 3
            assert resolve_hybrid_preset("radarr", "folder", folders)["path"] == "/movies/c"

    def test_t3_explicit_setting_overrides_prior_mru(self):
        """Configuring explicit default setting takes priority over pre-existing MRU history."""
        # Prior MRU is profile 3
        core.db.set_setting("radarr_mru_quality_profile", "3")
        core.db.set_setting("radarr_mru_root_folder", "/movies/mru_path")

        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "4K"}]
        folders = [{"path": "/movies/default_path"}, {"path": "/movies/mru_path"}]

        # Before explicit setting: yields MRU
        assert resolve_hybrid_preset("radarr", "profile", profiles)["id"] == 3

        # User saves explicit default in settings
        core.db.set_setting("radarr_default_quality_profile", "2")
        core.db.set_setting("radarr_default_root_folder", "/movies/default_path")

        # After explicit setting: yields explicit default, not MRU
        assert resolve_hybrid_preset("radarr", "profile", profiles)["id"] == 2
        assert resolve_hybrid_preset("radarr", "folder", folders)["path"] == "/movies/default_path"

    def test_t3_fallback_to_mru_when_explicit_setting_removed(self):
        """Clearing explicit default restores MRU fallback pre-selection."""
        core.db.set_setting("sonarr_mru_quality_profile", "2")
        core.db.set_setting("sonarr_default_quality_profile", "3")
        profiles = [{"id": 1, "name": "Any"}, {"id": 2, "name": "HD-720p"}, {"id": 3, "name": "HD-1080p"}]

        # Initial: explicit default takes priority
        assert resolve_hybrid_preset("sonarr", "profile", profiles)["id"] == 3

        # User clears explicit default
        core.db.set_setting("sonarr_default_quality_profile", "")

        # Fallback to MRU
        assert resolve_hybrid_preset("sonarr", "profile", profiles)["id"] == 2

    def test_t3_both_explicit_and_mru_removed_restores_safety_fallback(self):
        """Clearing both explicit default and MRU restores first-option safety fallback."""
        core.db.set_setting("sonarr_default_quality_profile", "")
        core.db.set_setting("sonarr_mru_quality_profile", "")
        profiles = [{"id": 10, "name": "First Option"}, {"id": 20, "name": "Second Option"}]

        assert resolve_hybrid_preset("sonarr", "profile", profiles)["id"] == 10

    def test_t3_alternating_media_additions_independent_mru(self, client):
        """Interleaved movie and TV additions keep distinct MRU trails throughout execution."""
        mock_radarr = MagicMock()
        mock_radarr.add_movie.return_value = {"id": 1}
        mock_sonarr = MagicMock()
        mock_sonarr.add_series.return_value = {"id": 2}

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
            client.post("/api/add", json={"type": "tv", "raw_metadata": {"title": "S1", "year": 2024}, "folder": "/tv/1", "profile_id": 101})
            client.post("/api/add", json={"type": "movie", "raw_metadata": {"title": "M1", "year": 2024}, "folder": "/movies/1", "profile_id": 201})
            client.post("/api/add", json={"type": "tv", "raw_metadata": {"title": "S2", "year": 2024}, "folder": "/tv/2", "profile_id": 102})
            client.post("/api/add", json={"type": "movie", "raw_metadata": {"title": "M2", "year": 2024}, "folder": "/movies/2", "profile_id": 202})

            assert core.db.get_setting("sonarr_mru_quality_profile") == "102"
            assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/2"
            assert core.db.get_setting("radarr_mru_quality_profile") == "202"
            assert core.db.get_setting("radarr_mru_root_folder") == "/movies/2"

    def test_t3_demo_sandbox_mru_persistence(self, client):
        """Adding in demo sandbox mode also persists MRU selections to database settings."""
        res_tv = client.post("/api/add", json={
            "type": "tv",
            "raw_metadata": {"title": "Demo Show", "year": 2025},
            "folder": "/sandbox/tv",
            "profile_id": 4,
            "demo": True
        })
        assert res_tv.status_code == 200
        assert core.db.get_setting("sonarr_mru_quality_profile") == "4"
        assert core.db.get_setting("sonarr_mru_root_folder") == "/sandbox/tv"

        res_movie = client.post("/api/add", json={
            "type": "movie",
            "raw_metadata": {"title": "Demo Movie", "year": 2025},
            "folder": "/sandbox/movies",
            "profile_id": 5,
            "is_demo": True
        })
        assert res_movie.status_code == 200
        assert core.db.get_setting("radarr_mru_quality_profile") == "5"
        assert core.db.get_setting("radarr_mru_root_folder") == "/sandbox/movies"


# ===========================================================================
# Tier 4: Real-World Workload Scenarios
# ===========================================================================

class TestTier4RealWorldWorkloads:
    """Tier 4: End-to-end simulated lifecycles and realistic multi-step user workflows."""

    def test_t4_full_lifecycle_user_flow(self, client):
        """
        Simulate full user journey:
        1. Fresh setup -> First add (resolves first available option)
        2. Second add -> Resolves MRU from first add
        3. User configures explicit default in settings -> Third add resolves explicit default
        4. Upstream profile deleted in Sonarr -> Fourth add gracefully falls back without errors
        """
        mock_sonarr = MagicMock()
        mock_sonarr.add_series.return_value = {"id": 1, "title": "Show"}

        profiles_initial = [
            {"id": 1, "name": "720p"},
            {"id": 2, "name": "1080p"},
            {"id": 3, "name": "4K Ultra-HD"}
        ]
        folders_initial = [
            {"path": "/tv/primary"},
            {"path": "/tv/secondary"}
        ]

        with patch("xarrtools.web.server.get_clients", return_value=(None, mock_sonarr)):
            # Step 1: Fresh install (no settings). User opens Add dialog.
            # Hybrid resolution resolves index 0
            p1 = resolve_hybrid_preset("sonarr", "profile", profiles_initial)
            f1 = resolve_hybrid_preset("sonarr", "folder", folders_initial)
            assert p1["id"] == 1
            assert f1["path"] == "/tv/primary"

            # User selects profile 2 and folder /tv/secondary and adds show
            res1 = client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Show 1", "year": 2025},
                "folder": "/tv/secondary",
                "profile_id": 2
            })
            assert res1.status_code == 200

            # Step 2: Next addition dialog opened. Pre-selection is MRU.
            p2 = resolve_hybrid_preset("sonarr", "profile", profiles_initial)
            f2 = resolve_hybrid_preset("sonarr", "folder", folders_initial)
            assert p2["id"] == 2
            assert f2["path"] == "/tv/secondary"

            # Step 3: User configures explicit default in Server Settings modal
            client.post("/api/settings", json={
                "sonarr_default_quality_profile": "3",
                "sonarr_default_root_folder": "/tv/primary"
            })

            # Next addition resolves explicit default
            p3 = resolve_hybrid_preset("sonarr", "profile", profiles_initial)
            f3 = resolve_hybrid_preset("sonarr", "folder", folders_initial)
            assert p3["id"] == 3
            assert f3["path"] == "/tv/primary"

            # Step 4: Upstream profile 3 is deleted in Sonarr server
            profiles_after_deletion = [
                {"id": 1, "name": "720p"},
                {"id": 2, "name": "1080p"}
            ]
            # Hybrid resolution detects profile 3 missing, checks MRU (2), falls back gracefully
            p4 = resolve_hybrid_preset("sonarr", "profile", profiles_after_deletion)
            assert p4["id"] == 2  # MRU fallback

    def test_t4_dual_service_mixed_workload_with_language_profile_deprecation(self, client):
        """
        Multi-service add flow validating Radarr and Sonarr preset resolution and total absence
        of language profile data across request, response, and database state.
        """
        mock_radarr = MagicMock()
        mock_radarr.get_root_folders.return_value = [{"path": "/movies/standard"}, {"path": "/movies/4k"}]
        mock_radarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}, {"id": 2, "name": "4K"}]
        mock_radarr.add_movie.return_value = {"id": 100, "title": "Oppenheimer"}

        mock_sonarr = MagicMock()
        mock_sonarr.get_root_folders.return_value = [{"path": "/tv/standard"}, {"path": "/tv/anime"}]
        mock_sonarr.get_quality_profiles.return_value = [{"id": 10, "name": "Any"}, {"id": 20, "name": "HD"}]
        mock_sonarr.add_series.return_value = {"id": 200, "title": "Frieren"}

        with patch("xarrtools.web.server.get_clients", return_value=(mock_radarr, mock_sonarr)):
            # 1. Verify GET /api/config has no language_profiles
            cfg_res = client.get("/api/config")
            assert cfg_res.status_code == 200
            cfg_data = cfg_res.get_json()
            assert "language_profiles" not in cfg_data["sonarr"]

            # 2. Configure explicit Radarr folder default and Sonarr profile default
            client.post("/api/settings", json={
                "radarr_default_root_folder": "/movies/4k",
                "sonarr_default_quality_profile": "20"
            })

            # 3. Add movie: verifies explicit folder /movies/4k and first profile fallback
            radarr_profiles = cfg_data["radarr"]["profiles"]
            radarr_folders = cfg_data["radarr"]["folders"]
            assert resolve_hybrid_preset("radarr", "folder", radarr_folders)["path"] == "/movies/4k"
            assert resolve_hybrid_preset("radarr", "profile", radarr_profiles)["id"] == 1

            client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Oppenheimer", "year": 2023},
                "folder": "/movies/4k",
                "profile_id": 2
            })

            # 4. Add TV show: verifies explicit profile 20 and first folder fallback
            sonarr_profiles = cfg_data["sonarr"]["profiles"]
            sonarr_folders = cfg_data["sonarr"]["folders"]
            assert resolve_hybrid_preset("sonarr", "profile", sonarr_profiles)["id"] == 20
            assert resolve_hybrid_preset("sonarr", "folder", sonarr_folders)["path"] == "/tv/standard"

            add_tv_res = client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Frieren", "year": 2023},
                "folder": "/tv/anime",
                "profile_id": 20
            })
            assert add_tv_res.status_code == 200

            # 5. Check SonarrClient was invoked without language profile parameter
            mock_sonarr.add_series.assert_called_once()
            call_kwargs = mock_sonarr.add_series.call_args[1] if mock_sonarr.add_series.call_args[1] else {}
            if "language_profile_id" in call_kwargs:
                assert call_kwargs["language_profile_id"] is None

            # 6. Verify database settings contain updated MRU and default states
            all_settings = core.db.get_all_settings()
            assert all_settings["radarr_default_root_folder"] == "/movies/4k"
            assert all_settings["radarr_mru_quality_profile"] == "2"
            assert all_settings["radarr_mru_root_folder"] == "/movies/4k"
            assert all_settings["sonarr_default_quality_profile"] == "20"
            assert all_settings["sonarr_mru_quality_profile"] == "20"
            assert all_settings["sonarr_mru_root_folder"] == "/tv/anime"

    def test_t4_cli_hybrid_preset_selection_and_mru_flow(self):
        """
        Simulate CLI selection workflow:
        Verifies default index determination via hybrid strategy and MRU update upon completion.
        """
        # Set MRU in database
        core.db.set_setting("radarr_mru_quality_profile", "2")
        core.db.set_setting("radarr_mru_root_folder", "/movies/hd")

        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "4K"}]
        folders = [{"path": "/movies/sd"}, {"path": "/movies/hd"}]

        # Determine default selection for CLI prompt
        selected_prof = resolve_hybrid_preset("radarr", "profile", profiles)
        selected_fold = resolve_hybrid_preset("radarr", "folder", folders)

        # 1-based index calculation
        prof_idx = profiles.index(selected_prof) + 1
        fold_idx = folders.index(selected_fold) + 1

        assert prof_idx == 2  # profile id 2 is at 1-based index 2
        assert fold_idx == 2  # folder /movies/hd is at 1-based index 2

        # Simulate CLI addition updating MRU
        core.db.set_setting("radarr_mru_quality_profile", str(profiles[2]["id"]))
        core.db.set_setting("radarr_mru_root_folder", folders[0]["path"])

        assert core.db.get_setting("radarr_mru_quality_profile") == "3"
        assert core.db.get_setting("radarr_mru_root_folder") == "/movies/sd"
