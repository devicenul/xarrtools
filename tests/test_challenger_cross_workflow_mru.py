"""
Empirical Challenger Test Suite: Cross-Workflow MRU Synchronization between CLI and Server API
"""
import os
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import core.db
from core.config import config
from core.client import RadarrClient, SonarrClient
from cli.cli import resolve_preset_index, select_from_list
from web.server import app

@pytest.fixture
def isolated_db():
    """Sets up a temporary SQLite database isolated from production DB."""
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    core.db.init_db()
    core.db.set_setting("api_key", "test-api-key")
    config.refresh()
    
    yield temp_path
    
    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

@pytest.fixture
def web_client(isolated_db):
    app.config["TESTING"] = True
    core.db.set_setting("api_key", "test-api-key")
    config.refresh()

    class TestClientWrapper:
        def __init__(self, c):
            self.c = c

        def get(self, *args, **kwargs):
            return self.c.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test-api-key"
            return self.c.post(*args, headers=headers, **kwargs)

    with app.test_client() as client:
        yield TestClientWrapper(client)

class TestCrossWorkflowMRU:
    
    def test_server_add_movie_syncs_to_cli_preselection(self, isolated_db, web_client):
        """Scenario 1: Movie added via Server API POST /api/add updates DB MRU, CLI pre-selects that MRU."""
        # 1. Server adds movie in demo mode
        payload = {
            "type": "movie",
            "folder": "/media/movies_server",
            "profile_id": 42,
            "demo": True,
            "raw_metadata": {
                "title": "Challenger Movie",
                "year": 2026,
                "tmdbId": 12345
            }
        }
        res = web_client.post("/api/add", json=payload)
        assert res.status_code == 200
        
        # Verify MRU in DB
        assert core.db.get_setting("radarr_mru_quality_profile") == "42"
        assert core.db.get_setting("radarr_mru_root_folder") == "/media/movies_server"
        
        # 2. CLI queries profiles and folders
        available_profiles = [
            {"id": 10, "name": "720p"},
            {"id": 42, "name": "1080p Remux"},
            {"id": 99, "name": "4K UHD"}
        ]
        available_folders = [
            {"id": 1, "path": "/data/default"},
            {"id": 2, "path": "/media/movies_server"},
            {"id": 3, "path": "/archive/movies"}
        ]
        
        # CLI resolves default index (1-based)
        cli_profile_idx = resolve_preset_index(
            available_profiles,
            key_field="id",
            explicit_keys=["radarr_default_quality_profile", "radarr_default_profile_id"],
            mru_keys=["radarr_mru_quality_profile", "radarr_mru_profile_id"]
        )
        cli_folder_idx = resolve_preset_index(
            available_folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        
        assert cli_profile_idx == 2  # profile 42 is 2nd item (index 2)
        assert cli_folder_idx == 2   # /media/movies_server is 2nd item (index 2)
        assert available_profiles[cli_profile_idx - 1]["id"] == 42
        assert available_folders[cli_folder_idx - 1]["path"] == "/media/movies_server"

    def test_cli_add_tv_syncs_to_server_and_settings_api(self, isolated_db, web_client):
        """Scenario 2: TV show added via CLI workflow updates DB MRU, Server GET /api/settings returns it."""
        # 1. Simulate CLI setting MRU upon successful Sonarr addition
        core.db.set_setting("sonarr_mru_quality_profile", "15")
        core.db.set_setting("sonarr_mru_profile_id", "15")
        core.db.set_setting("sonarr_mru_root_folder", "/tv/anime_storage")
        
        # 2. Server GET /api/settings
        res = web_client.get("/api/settings")
        assert res.status_code == 200
        settings = res.get_json()
        assert settings.get("sonarr_mru_quality_profile") == "15"
        assert settings.get("sonarr_mru_root_folder") == "/tv/anime_storage"

    def test_explicit_default_overrides_cross_workflow_mru_in_both_directions(self, isolated_db, web_client):
        """Scenario 3: Explicit server settings override MRU across both CLI and Server workflows."""
        # 1. Server has MRU = 99
        core.db.set_setting("radarr_mru_quality_profile", "99")
        core.db.set_setting("radarr_mru_root_folder", "/media/mru_folder")
        
        # 2. User configures explicit default = 10 via POST /api/settings
        settings_update = {
            "radarr_default_quality_profile": "10",
            "radarr_default_root_folder": "/media/explicit_folder"
        }
        res = web_client.post("/api/settings", json=settings_update)
        assert res.status_code == 200
        
        available_profiles = [
            {"id": 10, "name": "Explicit Profile"},
            {"id": 99, "name": "MRU Profile"}
        ]
        available_folders = [
            {"path": "/media/explicit_folder"},
            {"path": "/media/mru_folder"}
        ]
        
        # CLI must resolve explicit default (index 1)
        cli_profile_idx = resolve_preset_index(
            available_profiles,
            key_field="id",
            explicit_keys=["radarr_default_quality_profile", "radarr_default_profile_id"],
            mru_keys=["radarr_mru_quality_profile", "radarr_mru_profile_id"]
        )
        cli_folder_idx = resolve_preset_index(
            available_folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert cli_profile_idx == 1
        assert cli_folder_idx == 1
        
        # 3. User clears explicit default in settings
        web_client.post("/api/settings", json={"radarr_default_quality_profile": "", "radarr_default_root_folder": ""})
        
        # CLI must now seamlessly fall back to MRU (index 2)
        cli_profile_idx_fallback = resolve_preset_index(
            available_profiles,
            key_field="id",
            explicit_keys=["radarr_default_quality_profile", "radarr_default_profile_id"],
            mru_keys=["radarr_mru_quality_profile", "radarr_mru_profile_id"]
        )
        cli_folder_idx_fallback = resolve_preset_index(
            available_folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert cli_profile_idx_fallback == 2
        assert cli_folder_idx_fallback == 2

    def test_cross_media_isolation(self, isolated_db, web_client):
        """Scenario 4: Movie additions do not contaminate Sonarr MRU and vice versa."""
        # Add Movie on Server
        res = web_client.post("/api/add", json={
            "type": "movie",
            "folder": "/movies/exclusive",
            "profile_id": 100,
            "demo": True,
            "raw_metadata": {"title": "Movie Isolation", "year": 2026}
        })
        assert res.status_code == 200
        
        # Add TV on CLI
        core.db.set_setting("sonarr_mru_quality_profile", "200")
        core.db.set_setting("sonarr_mru_root_folder", "/tv/exclusive")
        
        # Assert complete independence
        assert core.db.get_setting("radarr_mru_quality_profile") == "100"
        assert core.db.get_setting("radarr_mru_root_folder") == "/movies/exclusive"
        assert core.db.get_setting("sonarr_mru_quality_profile") == "200"
        assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/exclusive"

    def test_safety_fallback_on_deleted_upstream_id(self, isolated_db):
        """Scenario 5: Deleted profile ID / root folder falls back safely to index 1."""
        core.db.set_setting("radarr_mru_quality_profile", "999999")  # Deleted ID
        core.db.set_setting("radarr_mru_root_folder", "/deleted/path") # Deleted Path
        
        available_profiles = [{"id": 1, "name": "Standard"}, {"id": 2, "name": "Ultra"}]
        available_folders = [{"path": "/valid/path/1"}, {"path": "/valid/path/2"}]
        
        idx_prof = resolve_preset_index(
            available_profiles, "id",
            ["radarr_default_quality_profile"],
            ["radarr_mru_quality_profile"]
        )
        idx_fold = resolve_preset_index(
            available_folders, "path",
            ["radarr_default_root_folder"],
            ["radarr_mru_root_folder"]
        )
        
        assert idx_prof == 1
        assert idx_fold == 1

    def test_interleaved_multi_step_cross_workflow_updates(self, isolated_db, web_client):
        """Scenario 6: Interleaved additions across CLI and Server step-by-step update MRU sequentially."""
        profiles = [
            {"id": 1, "name": "720p"},
            {"id": 2, "name": "1080p"},
            {"id": 3, "name": "4K"}
        ]
        folders = [
            {"path": "/media/drive1"},
            {"path": "/media/drive2"},
            {"path": "/media/drive3"}
        ]
        
        # Step 1: Server adds TV with profile 1, folder /media/drive1
        res1 = web_client.post("/api/add", json={
            "type": "tv", "folder": "/media/drive1", "profile_id": 1, "demo": True,
            "raw_metadata": {"title": "Show A", "year": 2026}
        })
        assert res1.status_code == 200
        
        # CLI resolves TV preset -> profile 1 (idx 1), folder drive1 (idx 1)
        assert resolve_preset_index(profiles, "id", ["sonarr_default_quality_profile"], ["sonarr_mru_quality_profile"]) == 1
        assert resolve_preset_index(folders, "path", ["sonarr_default_root_folder"], ["sonarr_mru_root_folder"]) == 1
        
        # Step 2: CLI user adds TV with profile 3, folder /media/drive3
        core.db.set_setting("sonarr_mru_quality_profile", "3")
        core.db.set_setting("sonarr_mru_root_folder", "/media/drive3")
        
        # Server settings API reflects the CLI update
        settings_res = web_client.get("/api/settings").get_json()
        assert settings_res.get("sonarr_mru_quality_profile") == "3"
        assert settings_res.get("sonarr_mru_root_folder") == "/media/drive3"
        
        # Step 3: Next CLI resolve reflects profile 3 (idx 3), drive3 (idx 3)
        assert resolve_preset_index(profiles, "id", ["sonarr_default_quality_profile"], ["sonarr_mru_quality_profile"]) == 3
        assert resolve_preset_index(folders, "path", ["sonarr_default_root_folder"], ["sonarr_mru_root_folder"]) == 3

    def test_case_insensitive_path_matching_in_cli_and_db(self, isolated_db):
        """Scenario 7: Root folder paths match case-insensitively and normalize trailing slashes."""
        folders = [
            {"path": "/Media/Movies/"},
            {"path": "/media/tv/"}
        ]
        # MRU saved without trailing slash and lowercase
        core.db.set_setting("radarr_mru_root_folder", "/media/movies")
        
        idx = resolve_preset_index(
            folders, "path",
            ["radarr_default_root_folder"],
            ["radarr_mru_root_folder"]
        )
        assert idx == 1

    def test_string_int_type_coercion_robustness(self, isolated_db):
        """Scenario 8: Profile IDs stored as integers or strings match correctly."""
        profiles = [{"id": 105, "name": "Ultra-HD"}]
        
        # Case A: String stored in DB
        core.db.set_setting("radarr_mru_quality_profile", "105")
        assert resolve_preset_index(profiles, "id", [], ["radarr_mru_quality_profile"]) == 1
        
        # Case B: Integer ID stored
        core.db.set_setting("radarr_mru_quality_profile", 105)
        assert resolve_preset_index(profiles, "id", [], ["radarr_mru_quality_profile"]) == 1

    def test_adversarial_empty_and_corrupt_options(self, isolated_db):
        """Scenario 9: Empty options list or malformed items do not raise unhandled exceptions."""
        assert resolve_preset_index([], "id", [], []) == 1
        assert resolve_preset_index(None, "id", [], []) == 1
        
        corrupt_items = [None, "invalid_string", {"no_id_key": "val"}]
        # Should gracefully return fallback index 1
        assert resolve_preset_index(corrupt_items, "id", ["radarr_default_quality_profile"], ["radarr_mru_quality_profile"]) == 1
