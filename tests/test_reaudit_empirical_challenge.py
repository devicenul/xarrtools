"""
Comprehensive Empirical Challenge Re-audit Test Suite for xarrtools.

Exhaustive tests covering:
1. Deprecated Language Profile Absence Oracle across AST, signatures, API, DOM, and CLI.
2. Hybrid Preset Selection Engine (Explicit -> MRU -> Safety Fallback) for Radarr & Sonarr.
3. Path Normalization, Type Coercion, and Fault Tolerance.
4. Server API Endpoints (/api/config, /api/settings, /api/add) demo & live mode state transitions.
5. Cross-Workflow State Transitions & MRU Invariants.
6. Direct Node.js execution harness for frontend `app.js` functions (`resolveHybridPreset`, `updateMRUCache`).
7. CLI Interactive Prompt Flow Simulation & MRU Persistence.
"""

import os
import sys
import json
import inspect
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Ensure test DB isolation
import core.db
_temp_dir = tempfile.mkdtemp()
core.db.DB_PATH = Path(_temp_dir) / "test_challenge_reaudit.db"
core.db.init_db()

with patch("threading.Thread"):
    from web.server import app
from core.client import RadarrClient, SonarrClient, ArrAPIError
from core.config import config
import cli.cli as cli_mod


@pytest.fixture(autouse=True)
def reset_db():
    """Wipes test DB and ensures clean test api_key."""
    core.db.init_db()
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM settings")
    conn.execute("DELETE FROM cache")
    conn.commit()
    conn.close()
    core.db.set_setting("api_key", "test_api_key")
    config.refresh()
    yield


@pytest.fixture
def auth_client():
    """Provides Flask test client with automatic X-API-Key injection for modifying requests."""
    app.config["TESTING"] = True

    class WrappedClient:
        def __init__(self, inner):
            self.inner = inner

        def get(self, *args, **kwargs):
            return self.inner.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_api_key"
            kwargs["headers"] = headers
            return self.inner.post(*args, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_api_key"
            kwargs["headers"] = headers
            return self.inner.put(*args, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test_api_key"
            kwargs["headers"] = headers
            return self.inner.delete(*args, **kwargs)

    with app.test_client() as c:
        yield WrappedClient(c)


# ==============================================================================
# SECTION 1: LANGUAGE PROFILE ABSENCE ORACLES (Requirement R3)
# ==============================================================================

class TestLanguageProfileAbsence:
    """Rigorous verification that all traces of Sonarr Language Profiles are removed."""

    def test_sonarr_client_class_has_no_language_profile_methods(self):
        """SonarrClient must not expose get_language_profiles or language_profile_id in add_series."""
        assert not hasattr(SonarrClient, "get_language_profiles"), "SonarrClient still has get_language_profiles method!"
        
        # Check add_series signature
        sig = inspect.signature(SonarrClient.add_series)
        assert "language_profile_id" not in sig.parameters, "SonarrClient.add_series still accepts language_profile_id!"
        assert "lang_profile_id" not in sig.parameters, "SonarrClient.add_series still accepts lang_profile_id!"

    def test_sonarr_client_add_series_payload_does_not_contain_language_profile(self):
        """When calling SonarrClient.add_series, the POST request payload must not include language profile keys."""
        client = SonarrClient("http://fake-sonarr:8989", "fake-key")
        
        with patch.object(client, "_request", return_value={"id": 123, "title": "Test Show"}) as mock_req:
            series_data = {
                "title": "Breaking Bad",
                "year": 2008,
                "tvdbId": 81189,
                "titleSlug": "breaking-bad"
            }
            res = client.add_series(
                series_data=series_data,
                quality_profile_id=4,
                root_folder_path="/media/tv",
                monitored=True,
                search_now=False
            )
            
            assert res["id"] == 123
            mock_req.assert_called_once()
            method, endpoint = mock_req.call_args[0]
            kwargs = mock_req.call_args[1]
            json_payload = kwargs.get("json_data", {})
            
            assert method == "POST"
            assert endpoint == "series"
            assert "languageProfileId" not in json_payload
            assert "language_profile_id" not in json_payload
            assert "languageProfiles" not in json_payload
            assert json_payload["qualityProfileId"] == 4
            assert json_payload["rootFolderPath"] == "/media/tv"

    def test_server_get_config_omits_language_profiles(self, auth_client):
        """GET /api/config response must never include language_profiles in sonarr or radarr sections."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_radarr = MagicMock(spec=RadarrClient)
            mock_radarr.get_root_folders.return_value = [{"path": "/movies"}]
            mock_radarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD-1080p"}]
            
            mock_sonarr = MagicMock(spec=SonarrClient)
            mock_sonarr.get_root_folders.return_value = [{"path": "/tv"}]
            mock_sonarr.get_quality_profiles.return_value = [{"id": 2, "name": "Any"}]
            
            mock_get_clients.return_value = (mock_radarr, mock_sonarr)
            
            resp = auth_client.get("/api/config")
            assert resp.status_code == 200
            data = resp.get_json()
            
            assert "radarr" in data
            assert "sonarr" in data
            assert "language_profiles" not in data["sonarr"]
            assert "language_profiles" not in data["radarr"]
            assert "languageProfiles" not in data["sonarr"]
            assert "languageProfiles" not in data["radarr"]
            assert data["sonarr"]["configured"] is True
            assert data["radarr"]["configured"] is True

    def test_server_post_add_ignores_deprecated_lang_profile_id(self, auth_client):
        """POST /api/add must succeed without lang_profile_id, and if sent, must not propagate it."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_sonarr = MagicMock(spec=SonarrClient)
            mock_sonarr.add_series.return_value = {"id": 99, "title": "Test Show", "year": 2024}
            mock_get_clients.return_value = (None, mock_sonarr)
            
            payload = {
                "type": "tv",
                "raw_metadata": {"title": "Test Show", "year": 2024, "tvdbId": 1234},
                "folder": "/data/tv",
                "profile_id": 3,
                "lang_profile_id": 999  # Deprecated key sent by legacy clients
            }
            
            resp = auth_client.post("/api/add", json=payload)
            assert resp.status_code == 200
            res_data = resp.get_json()
            assert res_data["status"] == "success"
            
            # Verify add_series was called with clean v4 parameters
            mock_sonarr.add_series.assert_called_once_with(
                series_data={"title": "Test Show", "year": 2024, "tvdbId": 1234, "is_in_library": True},
                quality_profile_id=3,
                root_folder_path="/data/tv",
                monitored=True,
                search_now=True
            )

    def test_web_templates_no_language_profile_elements(self):
        """HTML templates must have no language profile select elements or groups."""
        html_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html"
        content = html_path.read_text(encoding="utf-8")
        
        assert "select-lang-profile" not in content
        assert "group-lang-profile" not in content
        assert "Language Profile" not in content


# ==============================================================================
# SECTION 2: HYBRID PRESET SELECTION ENGINE (CLI & Python Logic)
# ==============================================================================

class TestHybridPresetResolutionCLI:
    """Stress-test cli_mod.resolve_preset_index across 3 tiers, type variations, and edge cases."""

    def test_explicit_setting_matches_first(self):
        """Tier 1: Explicit setting takes precedence over MRU and first option."""
        folders = [{"path": "/media/movies1"}, {"path": "/media/movies2"}, {"path": "/media/movies3"}]
        
        core.db.set_setting("radarr_default_root_folder", "/media/movies3")
        core.db.set_setting("radarr_mru_root_folder", "/media/movies1")
        config.refresh()

        idx = cli_mod.resolve_preset_index(
            folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 3

    def test_explicit_setting_invalid_falls_back_to_mru(self):
        """Tier 2: If Explicit setting is set to a non-existent item, fall back to MRU."""
        profiles = [{"id": 1, "name": "Any"}, {"id": 2, "name": "HD-1080p"}, {"id": 3, "name": "Ultra-HD"}]
        
        core.db.set_setting("sonarr_default_quality_profile", "999")  # Deleted/invalid profile ID
        core.db.set_setting("sonarr_mru_quality_profile", "2")
        config.refresh()

        idx = cli_mod.resolve_preset_index(
            profiles,
            key_field="id",
            explicit_keys=["sonarr_default_quality_profile", "sonarr_default_profile_id"],
            mru_keys=["sonarr_mru_quality_profile", "sonarr_mru_profile_id"]
        )
        assert idx == 2

    def test_both_explicit_and_mru_invalid_falls_back_to_safety_first_option(self):
        """Tier 3: If both Explicit and MRU are missing/invalid, fall back to 1."""
        folders = [{"path": "/storage/shows1"}, {"path": "/storage/shows2"}]
        
        core.db.set_setting("sonarr_default_root_folder", "/nonexistent/path")
        core.db.set_setting("sonarr_mru_root_folder", "/another/old/path")
        config.refresh()

        idx = cli_mod.resolve_preset_index(
            folders,
            key_field="path",
            explicit_keys=["sonarr_default_root_folder"],
            mru_keys=["sonarr_mru_root_folder"]
        )
        assert idx == 1

    def test_empty_or_none_items_list_safety(self):
        """Edge Case: Empty or None options list returns 1 without raising an exception."""
        assert cli_mod.resolve_preset_index([], "path", ["radarr_default_root_folder"], ["radarr_mru_root_folder"]) == 1
        assert cli_mod.resolve_preset_index(None, "id", ["sonarr_default_quality_profile"], ["sonarr_mru_quality_profile"]) == 1

    def test_path_normalization_trailing_slashes_and_case(self):
        """Path comparisons should match despite trailing slashes and case variations."""
        folders = [{"path": "/Data/Media/Movies"}]
        
        core.db.set_setting("radarr_default_root_folder", "/data/media/movies/")
        config.refresh()

        idx = cli_mod.resolve_preset_index(
            folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 1

    def test_profile_id_integer_and_string_coercion(self):
        """Profile ID comparisons should match integer to string representation cleanly."""
        profiles = [{"id": 5, "name": "WEB-DL 1080p"}, {"id": 10, "name": "Remux-4K"}]
        
        core.db.set_setting("radarr_mru_quality_profile", "10")
        config.refresh()

        idx = cli_mod.resolve_preset_index(
            profiles,
            key_field="id",
            explicit_keys=["radarr_default_quality_profile"],
            mru_keys=["radarr_mru_quality_profile"]
        )
        assert idx == 2

    def test_corrupted_database_values_graceful_handling(self):
        """Corrupted/garbage values in settings should not crash resolution."""
        profiles = [{"id": 1, "name": "SD"}, {"id": 2, "name": "HD"}]
        
        core.db.set_setting("sonarr_default_quality_profile", "\x00\xff!!garbage??")
        core.db.set_setting("sonarr_mru_quality_profile", "")
        config.refresh()

        idx = cli_mod.resolve_preset_index(
            profiles,
            key_field="id",
            explicit_keys=["sonarr_default_quality_profile"],
            mru_keys=["sonarr_mru_quality_profile"]
        )
        assert idx == 1

    def test_select_from_list_default_index_clamping(self):
        """select_from_list should clamp out-of-bounds default_index to 1."""
        items = [{"name": "Item A"}, {"name": "Item B"}]
        with patch("rich.prompt.IntPrompt.ask", return_value=1) as mock_prompt:
            res = cli_mod.select_from_list("Prompt", items, "name", default_index=99)
            assert res == items[0]
            mock_prompt.assert_called_once_with("Prompt", default=1)

        with patch("rich.prompt.IntPrompt.ask", return_value=2) as mock_prompt:
            res = cli_mod.select_from_list("Prompt", items, "name", default_index=2)
            assert res == items[1]
            mock_prompt.assert_called_once_with("Prompt", default=2)


# ==============================================================================
# SECTION 3: SERVER API SETTINGS & ADD WORKFLOWS
# ==============================================================================

class TestServerAPISettingsAndMRU:
    """Verify backend settings persistence and MRU updates on media addition."""

    def test_settings_get_and_post_roundtrip(self, auth_client):
        """GET /api/settings and POST /api/settings should store and retrieve configurations."""
        new_settings = {
            "radarr_default_quality_profile": "7",
            "radarr_default_root_folder": "/movies/vault",
            "sonarr_default_quality_profile": "4",
            "sonarr_default_root_folder": "/tv/vault"
        }
        resp = auth_client.post("/api/settings", json=new_settings)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

        # Retrieve settings
        resp = auth_client.get("/api/settings")
        assert resp.status_code == 200
        saved = resp.get_json()
        assert saved["radarr_default_quality_profile"] == "7"
        assert saved["radarr_default_root_folder"] == "/movies/vault"
        assert saved["sonarr_default_quality_profile"] == "4"
        assert saved["sonarr_default_root_folder"] == "/tv/vault"

    def test_post_api_add_updates_mru_in_sandbox_demo_mode(self, auth_client):
        """POST /api/add in demo mode updates MRU keys in database immediately."""
        # Add movie in demo mode
        movie_payload = {
            "type": "movie",
            "demo": True,
            "raw_metadata": {"title": "Inception", "year": 2010, "imdbId": "tt1375666"},
            "folder": "/movies/sandbox",
            "profile_id": 8
        }
        resp = auth_client.post("/api/add", json=movie_payload)
        assert resp.status_code == 200
        assert "Successfully added" in resp.get_json()["message"]

        assert core.db.get_setting("radarr_mru_quality_profile") == "8"
        assert core.db.get_setting("radarr_mru_profile_id") == "8"
        assert core.db.get_setting("radarr_mru_root_folder") == "/movies/sandbox"

        # Add TV in demo mode
        tv_payload = {
            "type": "tv",
            "demo": True,
            "raw_metadata": {"title": "Severance", "year": 2022, "imdbId": "tt11280740"},
            "folder": "/tv/sandbox",
            "profile_id": 5
        }
        resp = auth_client.post("/api/add", json=tv_payload)
        assert resp.status_code == 200
        assert "Successfully added" in resp.get_json()["message"]

        assert core.db.get_setting("sonarr_mru_quality_profile") == "5"
        assert core.db.get_setting("sonarr_mru_profile_id") == "5"
        assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/sandbox"

    def test_post_api_add_updates_mru_in_live_mode(self, auth_client):
        """POST /api/add in live mode invokes client and updates MRU keys in database."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_radarr = MagicMock(spec=RadarrClient)
            mock_radarr.add_movie.return_value = {"id": 101, "title": "Oppenheimer", "year": 2023}
            mock_sonarr = MagicMock(spec=SonarrClient)
            mock_sonarr.add_series.return_value = {"id": 202, "title": "Dark", "year": 2017}
            mock_get_clients.return_value = (mock_radarr, mock_sonarr)

            # Add live movie
            resp = auth_client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Oppenheimer", "year": 2023, "tmdbId": 872585},
                "folder": "/mnt/movies/4k",
                "profile_id": 9,
                "add_collection": True
            })
            assert resp.status_code == 200
            mock_radarr.add_movie.assert_called_once_with(
                movie_data={"title": "Oppenheimer", "year": 2023, "tmdbId": 872585, "is_in_library": True},
                quality_profile_id=9,
                root_folder_path="/mnt/movies/4k",
                monitored=True,
                search_now=True,
                add_collection=True
            )
            assert core.db.get_setting("radarr_mru_quality_profile") == "9"
            assert core.db.get_setting("radarr_mru_root_folder") == "/mnt/movies/4k"

            # Add live TV
            resp = auth_client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Dark", "year": 2017, "tvdbId": 334824},
                "folder": "/mnt/tv/series",
                "profile_id": 6
            })
            assert resp.status_code == 200
            mock_sonarr.add_series.assert_called_once_with(
                series_data={"title": "Dark", "year": 2017, "tvdbId": 334824, "is_in_library": True},
                quality_profile_id=6,
                root_folder_path="/mnt/tv/series",
                monitored=True,
                search_now=True
            )
            assert core.db.get_setting("sonarr_mru_quality_profile") == "6"
            assert core.db.get_setting("sonarr_mru_root_folder") == "/mnt/tv/series"


# ==============================================================================
# SECTION 4: MULTI-ROUND STATE MACHINE & CROSS-WORKFLOW STRESS TESTS
# ==============================================================================

class TestCrossWorkflowStateInvariants:
    """Stress test consecutive adds, alternating profiles, and explicit overriding."""

    def test_multi_addition_mru_sequence(self, auth_client):
        """MRU must always reflect the single most recently added item's configuration."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_radarr = MagicMock(spec=RadarrClient)
            mock_radarr.add_movie.side_effect = lambda **kwargs: {"id": 1, "title": kwargs["movie_data"]["title"], "year": 2024}
            mock_get_clients.return_value = (mock_radarr, None)

            rounds = [
                ("/movies/hd", 1),
                ("/movies/4k", 4),
                ("/movies/remux", 9),
                ("/movies/anime", 2),
                ("/movies/final", 10),
            ]

            for folder, profile_id in rounds:
                resp = auth_client.post("/api/add", json={
                    "type": "movie",
                    "raw_metadata": {"title": f"Movie-{profile_id}", "year": 2024},
                    "folder": folder,
                    "profile_id": profile_id
                })
                assert resp.status_code == 200
                assert core.db.get_setting("radarr_mru_quality_profile") == str(profile_id)
                assert core.db.get_setting("radarr_mru_root_folder") == folder

    def test_explicit_setting_retains_priority_across_mru_updates(self):
        """Even when MRU updates on each add, resolution still favors Explicit Default when present."""
        folders = [
            {"path": "/movies/explicit_default"},
            {"path": "/movies/mru_folder"},
            {"path": "/movies/safety_folder"}
        ]
        core.db.set_setting("radarr_default_root_folder", "/movies/explicit_default")
        core.db.set_setting("radarr_mru_root_folder", "/movies/mru_folder")
        config.refresh()

        # Resolution returns explicit default
        idx = cli_mod.resolve_preset_index(
            folders, "path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 1

        # Clear explicit setting -> now returns MRU
        core.db.set_setting("radarr_default_root_folder", "")
        config.refresh()
        idx = cli_mod.resolve_preset_index(
            folders, "path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 2


# ==============================================================================
# SECTION 5: DIRECT JAVASCRIPT EXECUTION HARNESS (Node.js)
# ==============================================================================

class TestFrontendJavaScriptResolutionViaNode:
    """Empirically test web/templates/app.js resolveHybridPreset and updateMRUCache using Node.js."""

    def test_node_resolve_hybrid_preset_execution(self):
        """Execute app.js functions directly in a mock browser environment via Node.js."""
        app_js_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"
        assert app_js_path.exists(), "app.js not found!"

        runner_code = f"""
        const fs = require('fs');
        const code = fs.readFileSync({json.dumps(str(app_js_path))}, 'utf8');

        // Mock browser globals
        global.window = {{}};
        global.document = {{
            addEventListener: () => {{}},
            getElementById: () => ({{ classList: {{ add: () => {{}}, remove: () => {{}} }} }}),
            querySelector: () => null,
            querySelectorAll: () => []
        }};
        global.localStorage = {{
            store: {{}},
            getItem(key) {{ return this.store[key] || null; }},
            setItem(key, val) {{ this.store[key] = String(val); }},
            clear() {{ this.store = {{}}; }}
        }};
        global.appSettings = {{}};
        global.console = {{ log: () => {{}}, warn: () => {{}}, error: () => {{}} }};

        // Evaluate app.js
        eval(code);

        const resolve = window.resolveHybridPreset;
        const updateMRU = window.updateMRUCache;

        if (typeof resolve !== 'function') {{
            throw new Error("resolveHybridPreset is not exported to window!");
        }}
        if (typeof updateMRU !== 'function') {{
            throw new Error("updateMRUCache is not exported to window!");
        }}

        const testFolders = [
            {{ path: "/data/movies1" }},
            {{ path: "/data/movies2" }},
            {{ path: "/data/movies3" }}
        ];

        const testProfiles = [
            {{ id: 1, name: "SD" }},
            {{ id: 2, name: "HD-1080p" }},
            {{ id: 3, name: "UHD-4K" }}
        ];

        // 1. Tier 1 Test: Explicit setting match
        let res1 = resolve(testFolders, "path", "/data/movies2", "xarrtools_mru_radarr_folder");
        if (res1 !== "/data/movies2") throw new Error("Tier 1 Explicit failed: expected /data/movies2, got " + res1);

        // 2. Tier 2 Test: MRU in localStorage
        localStorage.setItem("xarrtools_mru_radarr_folder", "/data/movies3");
        let res2 = resolve(testFolders, "path", null, "xarrtools_mru_radarr_folder");
        if (res2 !== "/data/movies3") throw new Error("Tier 2 MRU localStorage failed: expected /data/movies3, got " + res2);

        // 3. Tier 2 Test: MRU in appSettings backend key map
        localStorage.clear();
        global.appSettings = {{ "radarr_mru_root_folder": "/data/movies1" }};
        let res3 = resolve(testFolders, "path", "", "xarrtools_mru_radarr_folder");
        if (res3 !== "/data/movies1") throw new Error("Tier 2 MRU appSettings failed: expected /data/movies1, got " + res3);

        // 4. Tier 3 Test: Safety Fallback to first available option
        global.appSettings = {{}};
        let res4 = resolve(testFolders, "path", "/nonexistent", "xarrtools_mru_radarr_folder");
        if (res4 !== "/data/movies1") throw new Error("Tier 3 Safety fallback failed: expected /data/movies1, got " + res4);

        // 5. Profile ID String/Number Coercion Test
        let resProfile = resolve(testProfiles, "id", 3, "xarrtools_mru_radarr_profile");
        if (resProfile !== "3") throw new Error("Profile ID match failed: expected '3', got " + resProfile);

        // 6. updateMRUCache test
        updateMRU("movie", "/data/movies_updated", 2);
        if (localStorage.getItem("xarrtools_mru_radarr_folder") !== "/data/movies_updated") {{
            throw new Error("updateMRUCache failed for folder");
        }}
        if (localStorage.getItem("xarrtools_mru_radarr_profile") !== "2") {{
            throw new Error("updateMRUCache failed for profile");
        }}

        // 7. TV updateMRUCache test
        updateMRU("tv", "/data/tv_updated", 1);
        if (localStorage.getItem("xarrtools_mru_sonarr_folder") !== "/data/tv_updated") {{
            throw new Error("updateMRUCache failed for TV folder");
        }}
        if (localStorage.getItem("xarrtools_mru_sonarr_profile") !== "1") {{
            throw new Error("updateMRUCache failed for TV profile");
        }}

        // 8. Empty list resilience
        let resEmpty = resolve([], "path", "/data/movies1", "mru_key");
        if (resEmpty !== "") throw new Error("Empty list failed: expected '', got " + resEmpty);

        process.stdout.write("JS_TESTS_ALL_PASSED\\n");
        """

        result = subprocess.run(
            ["node", "-e", runner_code],
            capture_output=True,
            text=True,
            timeout=10
        )
        assert result.returncode == 0, f"Node.js tests failed: {result.stderr}"
        assert "JS_TESTS_ALL_PASSED" in result.stdout


# ==============================================================================
# SECTION 6: CLI INTERACTIVE FLOW SIMULATION & MRU UPDATES
# ==============================================================================

class TestCLIInteractiveWorkflows:
    """Simulate CLI interactive prompt flows for adding movies and TV shows."""

    def test_cli_handle_radarr_workflow(self):
        """Simulate handle_radarr_workflow end-to-end with MRU update."""
        with patch.object(config, "validate_radarr", return_value=True), \
             patch("cli.cli.RadarrClient") as mock_client_cls, \
             patch("cli.cli.Prompt.ask", side_effect=["Dune", "1"]), \
             patch("cli.cli.IntPrompt.ask", side_effect=[1, 1]), \
             patch("cli.cli.Confirm.ask", side_effect=[True, True]):
            
            mock_client = mock_client_cls.return_value
            mock_client.lookup_movie.return_value = [{"title": "Dune 2", "year": 2024, "tmdbId": 693134, "id": None}]
            mock_client.get_root_folders.return_value = [{"path": "/data/movies"}]
            mock_client.get_quality_profiles.return_value = [{"id": 4, "name": "Ultra-HD"}]
            mock_client.add_movie.return_value = {"id": 55, "title": "Dune 2", "year": 2024}

            cli_mod.handle_radarr_workflow()

            mock_client.add_movie.assert_called_once_with(
                movie_data={"title": "Dune 2", "year": 2024, "tmdbId": 693134, "id": None},
                quality_profile_id=4,
                root_folder_path="/data/movies",
                monitored=True,
                search_now=True
            )
            assert core.db.get_setting("radarr_mru_quality_profile") == "4"
            assert core.db.get_setting("radarr_mru_root_folder") == "/data/movies"

    def test_cli_handle_sonarr_workflow(self):
        """Simulate handle_sonarr_workflow end-to-end with MRU update."""
        with patch.object(config, "validate_sonarr", return_value=True), \
             patch("cli.cli.SonarrClient") as mock_client_cls, \
             patch("cli.cli.Prompt.ask", side_effect=["Shogun", "1"]), \
             patch("cli.cli.IntPrompt.ask", side_effect=[1, 1]), \
             patch("cli.cli.Confirm.ask", side_effect=[True, True]):
            
            mock_client = mock_client_cls.return_value
            mock_client.lookup_series.return_value = [{"title": "Shogun", "year": 2024, "tvdbId": 361701, "id": None}]
            mock_client.get_root_folders.return_value = [{"path": "/data/tv"}]
            mock_client.get_quality_profiles.return_value = [{"id": 7, "name": "1080p HD"}]
            mock_client.add_series.return_value = {"id": 77, "title": "Shogun", "year": 2024}

            cli_mod.handle_sonarr_workflow()

            mock_client.add_series.assert_called_once_with(
                series_data={"title": "Shogun", "year": 2024, "tvdbId": 361701, "id": None},
                quality_profile_id=7,
                root_folder_path="/data/tv",
                monitored=True,
                search_now=True
            )
            assert core.db.get_setting("sonarr_mru_quality_profile") == "7"
            assert core.db.get_setting("sonarr_mru_root_folder") == "/data/tv"
