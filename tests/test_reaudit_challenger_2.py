"""
Adversarial Stress Testing & Re-Audit Challenge Suite 2.
Empirical verification of:
1. Hybrid preset resolution matrix across all tiers (Explicit -> MRU -> Safety Fallback).
2. Complete Sonarr Language Profile excision across Client, Server, CLI, Web UI, and DOM templates.
3. Multi-threaded concurrency and race condition stability on DB settings & MRU updates.
4. Input fuzzing, SQL injection resistance, and boundary handling for settings & add endpoints.
5. Upstream ArrAPIError resilience and fallback handling.
6. JavaScript resolveHybridPreset and updateMRUCache execution under Node.js runtime.
"""

import os
import json
import subprocess
import threading
import tempfile
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import core.db
from core.config import config, Config
from core.client import RadarrClient, SonarrClient, ArrAPIError, BaseArrClient
from cli.cli import resolve_preset_index, select_from_list, parse_indices
from web.server import app, get_clients


@pytest.fixture(autouse=True)
def isolated_db():
    """Provides an isolated SQLite database for each test in the suite."""
    fd, temp_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    temp_path = Path(temp_path_str)
    old_path = core.db.DB_PATH
    core.db.DB_PATH = temp_path
    core.db.init_db()
    core.db.set_setting("api_key", "test-api-key-reaudit-2")
    config.refresh()
    yield temp_path
    core.db.DB_PATH = old_path
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def auth_client():
    """Authenticated Flask Test Client."""
    app.config["TESTING"] = True
    core.db.set_setting("api_key", "test-api-key-reaudit-2")
    config.refresh()

    class AuthenticatedClient:
        def __init__(self, client):
            self._client = client

        def get(self, *args, **kwargs):
            return self._client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test-api-key-reaudit-2"
            kwargs["headers"] = headers
            return self._client.post(*args, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test-api-key-reaudit-2"
            kwargs["headers"] = headers
            return self._client.put(*args, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = "test-api-key-reaudit-2"
            kwargs["headers"] = headers
            return self._client.delete(*args, **kwargs)

    with app.test_client() as c:
        yield AuthenticatedClient(c)


# ============================================================================
# 1. 3-TIER HYBRID PRESET RESOLUTION FULL MATRIX (RADARR & SONARR)
# ============================================================================

class TestHybridPresetResolutionMatrix:
    """Stress tests every branch of the 3-tier hybrid selection algorithm."""

    @pytest.mark.parametrize("service", ["radarr", "sonarr"])
    def test_tier1_explicit_default_priority_over_mru_and_first(self, service):
        """Tier 1: Explicit default MUST win over MRU and first available."""
        profiles = [{"id": 1, "name": "720p"}, {"id": 2, "name": "1080p"}, {"id": 3, "name": "4K"}]
        folders = [{"id": 1, "path": "/data/folder1"}, {"id": 2, "path": "/data/folder2"}, {"id": 3, "path": "/data/folder3"}]

        # Set explicit = 3, MRU = 2
        core.db.set_setting(f"{service}_default_quality_profile", "3")
        core.db.set_setting(f"{service}_mru_quality_profile", "2")
        core.db.set_setting(f"{service}_default_root_folder", "/data/folder3")
        core.db.set_setting(f"{service}_mru_root_folder", "/data/folder2")
        config.refresh()

        prof_idx = resolve_preset_index(
            profiles, "id",
            [f"{service}_default_quality_profile", f"{service}_default_profile_id"],
            [f"{service}_mru_quality_profile", f"{service}_mru_profile_id"]
        )
        folder_idx = resolve_preset_index(
            folders, "path",
            [f"{service}_default_root_folder"],
            [f"{service}_mru_root_folder"]
        )

        assert prof_idx == 3  # Index 3 is profile id 3 (4K)
        assert folder_idx == 3  # Index 3 is /data/folder3

    @pytest.mark.parametrize("service", ["radarr", "sonarr"])
    def test_tier2_mru_fallback_when_explicit_unset(self, service):
        """Tier 2: When explicit default is absent, MRU MUST win over first available."""
        profiles = [{"id": 10, "name": "SD"}, {"id": 20, "name": "HD"}, {"id": 30, "name": "Ultra"}]
        folders = [{"id": 1, "path": "/srv/media/a"}, {"id": 2, "path": "/srv/media/b"}]

        core.db.set_setting(f"{service}_mru_quality_profile", "20")
        core.db.set_setting(f"{service}_mru_root_folder", "/srv/media/b")
        config.refresh()

        prof_idx = resolve_preset_index(
            profiles, "id",
            [f"{service}_default_quality_profile", f"{service}_default_profile_id"],
            [f"{service}_mru_quality_profile", f"{service}_mru_profile_id"]
        )
        folder_idx = resolve_preset_index(
            folders, "path",
            [f"{service}_default_root_folder"],
            [f"{service}_mru_root_folder"]
        )

        assert prof_idx == 2  # Matches id=20
        assert folder_idx == 2  # Matches /srv/media/b

    @pytest.mark.parametrize("service", ["radarr", "sonarr"])
    def test_tier2_mru_fallback_when_explicit_is_stale_or_invalid(self, service):
        """Tier 2: When explicit default references a deleted/invalid profile/folder, MRU MUST win."""
        profiles = [{"id": 5, "name": "720p"}, {"id": 15, "name": "1080p"}]
        folders = [{"id": 1, "path": "/media/main"}]

        # Explicit references non-existent ID 999 and non-existent folder /nonexistent
        core.db.set_setting(f"{service}_default_quality_profile", "999")
        core.db.set_setting(f"{service}_mru_quality_profile", "15")
        core.db.set_setting(f"{service}_default_root_folder", "/nonexistent")
        core.db.set_setting(f"{service}_mru_root_folder", "/media/main")
        config.refresh()

        prof_idx = resolve_preset_index(
            profiles, "id",
            [f"{service}_default_quality_profile", f"{service}_default_profile_id"],
            [f"{service}_mru_quality_profile", f"{service}_mru_profile_id"]
        )
        folder_idx = resolve_preset_index(
            folders, "path",
            [f"{service}_default_root_folder"],
            [f"{service}_mru_root_folder"]
        )

        assert prof_idx == 2  # Falls back to MRU id 15
        assert folder_idx == 1  # Falls back to MRU /media/main

    @pytest.mark.parametrize("service", ["radarr", "sonarr"])
    def test_tier3_safety_fallback_when_both_explicit_and_mru_stale(self, service):
        """Tier 3: When explicit and MRU are both stale/absent, safety fallback returns index 1."""
        profiles = [{"id": 77, "name": "4K Remux"}, {"id": 88, "name": "1080p Web"}]
        folders = [{"id": 1, "path": "/pool/tv"}, {"id": 2, "path": "/pool/movies"}]

        # Both point to ghost IDs/paths
        core.db.set_setting(f"{service}_default_quality_profile", "9999")
        core.db.set_setting(f"{service}_mru_quality_profile", "8888")
        core.db.set_setting(f"{service}_default_root_folder", "/invalid/1")
        core.db.set_setting(f"{service}_mru_root_folder", "/invalid/2")
        config.refresh()

        prof_idx = resolve_preset_index(
            profiles, "id",
            [f"{service}_default_quality_profile", f"{service}_default_profile_id"],
            [f"{service}_mru_quality_profile", f"{service}_mru_profile_id"]
        )
        folder_idx = resolve_preset_index(
            folders, "path",
            [f"{service}_default_root_folder"],
            [f"{service}_mru_root_folder"]
        )

        assert prof_idx == 1
        assert folder_idx == 1


# ============================================================================
# 2. ADVERSARIAL INPUT & MALICIOUS VALUE HANDLING IN SETTINGS & RESOLUTION
# ============================================================================

class TestAdversarialSettingsValues:
    """Stress tests bizarre, malformed, and adversarial settings inputs."""

    @pytest.mark.parametrize("bad_val", [
        "",
        "   ",
        "\t\n",
        "null",
        "undefined",
        "None",
        "NaN",
        "-1",
        "0",
        "999999999999999999999999999999999999",
        "3.1415926535",
        "<html><script>alert(1)</script></html>",
        "'; DROP TABLE settings; --",
        "UNION SELECT 1, 'admin', 'password'--",
        "🚀🌟🔥",
        "\\x00\\x01\\x02",
        '{"nested": {"json": true}}',
    ])
    def test_resolve_preset_index_robustness_against_pathological_settings(self, bad_val):
        """resolve_preset_index must never crash or raise on pathological setting strings."""
        profiles = [{"id": 1, "name": "Standard"}, {"id": 2, "name": "High"}]
        folders = [{"id": 1, "path": "/data/media"}]

        core.db.set_setting("radarr_default_quality_profile", bad_val)
        core.db.set_setting("radarr_mru_quality_profile", bad_val)
        core.db.set_setting("radarr_default_root_folder", bad_val)
        core.db.set_setting("radarr_mru_root_folder", bad_val)
        config.refresh()

        prof_idx = resolve_preset_index(
            profiles, "id",
            ["radarr_default_quality_profile"],
            ["radarr_mru_quality_profile"]
        )
        folder_idx = resolve_preset_index(
            folders, "path",
            ["radarr_default_root_folder"],
            ["radarr_mru_root_folder"]
        )

        assert prof_idx == 1
        assert folder_idx == 1

    def test_options_list_with_malformed_entries(self):
        """resolve_preset_index must safely skip missing keys or malformed dictionary entries."""
        bad_options = [
            {},
            {"wrong_key": "val"},
            {"id": None},
            {"id": ""},
            {"id": "   "},
            {"id": 42, "name": "Target"}
        ]

        core.db.set_setting("sonarr_default_quality_profile", "42")
        config.refresh()

        idx = resolve_preset_index(
            bad_options, "id",
            ["sonarr_default_quality_profile"],
            ["sonarr_mru_quality_profile"]
        )
        assert idx == 6  # Matched 6th item (1-indexed)

    def test_empty_and_none_options_list(self):
        """Empty or None options list must safely return 1 without exceptions."""
        assert resolve_preset_index([], "id", ["key"], ["mru"]) == 1
        assert resolve_preset_index(None, "id", ["key"], ["mru"]) == 1
        assert select_from_list("Prompt", []) == {}
        assert select_from_list("Prompt", None) == {}


# ============================================================================
# 3. COMPLETE LANGUAGE PROFILE EXCISION NEGATIVE VERIFICATION
# ============================================================================

class TestLanguageProfileExcisionCompleteness:
    """Verifies that Sonarr language profiles are completely purged everywhere."""

    def test_sonarr_client_no_language_profile_methods(self):
        """SonarrClient class must have no get_language_profiles method."""
        client = SonarrClient("http://localhost:8989", "mock-key")
        assert not hasattr(client, "get_language_profiles")
        assert not hasattr(SonarrClient, "get_language_profiles")

    def test_sonarr_client_add_series_signature_no_language_profile_id(self):
        """SonarrClient.add_series signature must not accept language_profile_id."""
        sig = inspect.signature(SonarrClient.add_series)
        assert "language_profile_id" not in sig.parameters
        assert "lang_profile_id" not in sig.parameters
        assert "languageProfileId" not in sig.parameters

    def test_sonarr_client_add_series_payload_has_no_language_profile_id(self):
        """SonarrClient.add_series MUST NOT include languageProfileId in the HTTP request payload."""
        client = SonarrClient("http://localhost:8989", "mock-key")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"id": 100, "title": "Test Show", "year": 2026}
            client.add_series(
                series_data={"title": "Test Show", "year": 2026, "tvdbId": 12345},
                quality_profile_id=4,
                root_folder_path="/tv",
                monitored=True,
                search_now=False
            )
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            json_payload = call_args.kwargs.get("json_data") or call_args[1].get("json_data")
            assert "languageProfileId" not in json_payload
            assert "language_profile_id" not in json_payload

    def test_radarr_client_no_language_profile_methods(self):
        """RadarrClient class must have no language profile references."""
        client = RadarrClient("http://localhost:7878", "mock-key")
        assert not hasattr(client, "get_language_profiles")

    def test_api_config_no_language_profiles_key(self, auth_client):
        """GET /api/config must not contain language_profiles in radarr or sonarr payloads."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_radarr = MagicMock(spec=RadarrClient)
            mock_radarr.get_root_folders.return_value = [{"id": 1, "path": "/movies"}]
            mock_radarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]

            mock_sonarr = MagicMock(spec=SonarrClient)
            mock_sonarr.get_root_folders.return_value = [{"id": 1, "path": "/tv"}]
            mock_sonarr.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]

            mock_get_clients.return_value = (mock_radarr, mock_sonarr)

            resp = auth_client.get("/api/config")
            assert resp.status_code == 200
            data = resp.get_json()

            assert "language_profiles" not in data.get("sonarr", {})
            assert "language_profiles" not in data.get("radarr", {})
            assert "language_profile" not in json.dumps(data)

    def test_api_add_ignores_deprecated_lang_profile_id_gracefully(self, auth_client):
        """POST /api/add should succeed even if legacy client sends lang_profile_id without error."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_sonarr = MagicMock(spec=SonarrClient)
            mock_sonarr.add_series.return_value = {"id": 55, "title": "Breaking Bad", "year": 2008}
            mock_get_clients.return_value = (None, mock_sonarr)

            payload = {
                "type": "tv",
                "raw_metadata": {"title": "Breaking Bad", "year": 2008, "tvdbId": 81189},
                "folder": "/data/tv",
                "profile_id": 3,
                "lang_profile_id": 999  # Deprecated legacy field
            }
            resp = auth_client.post("/api/add", json=payload)
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "success"

            # Assert mock_sonarr.add_series was called without lang_profile_id in kwargs or series_data
            mock_sonarr.add_series.assert_called_once()
            call_kwargs = mock_sonarr.add_series.call_args.kwargs
            assert "lang_profile_id" not in call_kwargs
            assert "language_profile_id" not in call_kwargs
            assert call_kwargs.get("quality_profile_id") == 3
            assert call_kwargs.get("root_folder_path") == "/data/tv"

    def test_html_template_has_no_language_profile_dom(self):
        """web/templates/index.html must not contain #select-lang-profile or language profile markup."""
        html_path = Path("web/templates/index.html")
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "select-lang-profile" not in content
        assert "group-lang-profile" not in content
        assert "Language Profile" not in content


# ============================================================================
# 4. CROSS-WORKFLOW MRU CACHE PERSISTENCE & CONCURRENCY
# ============================================================================

class TestMRUPersistenceAndConcurrency:
    """Stress tests MRU persistence across API, CLI, and multi-threaded concurrency."""

    def test_api_add_persists_mru_in_db_for_movie_and_tv(self, auth_client):
        """POST /api/add MUST update SQLite MRU settings and refresh config."""
        with patch("web.server.get_clients") as mock_get_clients:
            mock_radarr = MagicMock(spec=RadarrClient)
            mock_radarr.add_movie.return_value = {"id": 1, "title": "Inception", "year": 2010}
            mock_sonarr = MagicMock(spec=SonarrClient)
            mock_sonarr.add_series.return_value = {"id": 2, "title": "Chernobyl", "year": 2019}
            mock_get_clients.return_value = (mock_radarr, mock_sonarr)

            # 1. Add Movie
            auth_client.post("/api/add", json={
                "type": "movie",
                "raw_metadata": {"title": "Inception", "year": 2010, "tmdbId": 27205},
                "folder": "/movies/4k",
                "profile_id": 7
            })
            assert core.db.get_setting("radarr_mru_quality_profile") == "7"
            assert core.db.get_setting("radarr_mru_profile_id") == "7"
            assert core.db.get_setting("radarr_mru_root_folder") == "/movies/4k"

            # 2. Add TV Show
            auth_client.post("/api/add", json={
                "type": "tv",
                "raw_metadata": {"title": "Chernobyl", "year": 2019, "tvdbId": 360893},
                "folder": "/tv/documentaries",
                "profile_id": 12
            })
            assert core.db.get_setting("sonarr_mru_quality_profile") == "12"
            assert core.db.get_setting("sonarr_mru_profile_id") == "12"
            assert core.db.get_setting("sonarr_mru_root_folder") == "/tv/documentaries"

            # 3. Verify Movie MRU was not overwritten by TV Show addition
            assert core.db.get_setting("radarr_mru_quality_profile") == "7"
            assert core.db.get_setting("radarr_mru_root_folder") == "/movies/4k"

    def test_demo_mode_add_persists_mru_in_db(self, auth_client):
        """POST /api/add in demo/sandbox mode MUST also update MRU settings."""
        resp = auth_client.post("/api/add", json={
            "type": "tv",
            "demo": True,
            "raw_metadata": {"title": "Demo Show", "year": 2026},
            "folder": "/sandbox/tv",
            "profile_id": 99
        })
        assert resp.status_code == 200
        assert core.db.get_setting("sonarr_mru_quality_profile") == "99"
        assert core.db.get_setting("sonarr_mru_root_folder") == "/sandbox/tv"

    def test_concurrent_settings_and_mru_writes(self):
        """Spawn 20 parallel threads concurrently writing settings and reading config."""
        errors = []

        def worker(thread_id):
            try:
                for i in range(25):
                    core.db.set_setting(f"test_key_{thread_id}", f"val_{i}")
                    core.db.set_setting("radarr_mru_quality_profile", str(thread_id * 100 + i))
                    core.db.set_setting("radarr_mru_root_folder", f"/data/thread_{thread_id}")
                    val = core.db.get_setting(f"test_key_{thread_id}")
                    assert val == f"val_{i}"
                    all_s = core.db.get_all_settings()
                    assert isinstance(all_s, dict)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent database operations failed: {errors}"


# ============================================================================
# 5. JAVASCRIPT HYBRID PRESET HARNESS (NODE.JS EXECUTION)
# ============================================================================

class TestJavaScriptHybridPresetHarness:
    """Stress tests web/templates/app.js resolveHybridPreset and updateMRUCache under Node.js."""

    def test_app_js_hybrid_preset_exhaustive_node_harness(self):
        """Executes Node.js test harness loading web/templates/app.js directly."""
        app_js_path = os.path.abspath("web/templates/app.js")
        assert os.path.exists(app_js_path)

        script = f"""
        const fs = require('fs');
        const code = fs.readFileSync('{app_js_path}', 'utf8').split('\\n').filter(l => !l.startsWith('import ')).join('\\n');

        // Mock browser DOM & Storage environment
        const store = {{}};
        global.window = {{}};
        global.localStorage = {{
            getItem: (k) => store[k] || null,
            setItem: (k, v) => {{ store[k] = String(v); }},
            removeItem: (k) => {{ delete store[k]; }}
        }};
        global.document = {{
            querySelector: () => null,
            getElementById: () => null,
            querySelectorAll: () => [],
            addEventListener: () => {{}}
        }};

        // Execute app.js in global context
        eval(code);

        const resolve = window.resolveHybridPreset;
        const updateMRU = window.updateMRUCache;

        if (typeof resolve !== 'function') throw new Error('resolveHybridPreset not defined on window');
        if (typeof updateMRU !== 'function') throw new Error('updateMRUCache not defined on window');

        const profiles = [
            {{ id: 1, name: 'SD' }},
            {{ id: 2, name: 'HD' }},
            {{ id: 3, name: '4K' }}
        ];

        // 1. Tier 1: Explicit match wins over MRU
        global.localStorage.setItem('xarrtools_mru_radarr_profile', '2');
        let res = resolve(profiles, 'id', 3, 'xarrtools_mru_radarr_profile');
        if (res !== '3') throw new Error('Tier 1 explicit match failed, got: ' + res);

        // 2. Tier 2: MRU wins when explicit is null/empty
        res = resolve(profiles, 'id', null, 'xarrtools_mru_radarr_profile');
        if (res !== '2') throw new Error('Tier 2 MRU match failed, got: ' + res);

        // 3. Tier 2: MRU wins when explicit is invalid/stale
        res = resolve(profiles, 'id', '999', 'xarrtools_mru_radarr_profile');
        if (res !== '2') throw new Error('Tier 2 fallback on stale explicit failed, got: ' + res);

        // 4. Tier 3: First available wins when explicit & MRU are both stale
        global.localStorage.setItem('xarrtools_mru_radarr_profile', '888');
        res = resolve(profiles, 'id', '999', 'xarrtools_mru_radarr_profile');
        if (res !== '1') throw new Error('Tier 3 safety fallback failed, got: ' + res);

        // 5. updateMRUCache test
        updateMRU('tv', '/storage/tv', 5);
        if (global.localStorage.getItem('xarrtools_mru_sonarr_folder') !== '/storage/tv') throw new Error('updateMRUCache TV folder failed');
        if (global.localStorage.getItem('xarrtools_mru_sonarr_profile') !== '5') throw new Error('updateMRUCache TV profile failed');

        updateMRU('movie', '/storage/movies', 10);
        if (global.localStorage.getItem('xarrtools_mru_radarr_folder') !== '/storage/movies') throw new Error('updateMRUCache Movie folder failed');
        if (global.localStorage.getItem('xarrtools_mru_radarr_profile') !== '10') throw new Error('updateMRUCache Movie profile failed');

        console.log("NODE_JS_HARNESS_SUCCESS");
        """

        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        assert "NODE_JS_HARNESS_SUCCESS" in result.stdout


# ============================================================================
# 6. CLI PARSING & WORKFLOW RESILIENCE
# ============================================================================

class TestCLIParsingAndResilience:
    """Stress tests CLI index parsing and interactive selection."""

    def test_parse_indices_boundaries(self):
        """Test extreme boundary cases for parse_indices."""
        # Valid cases
        assert parse_indices("1", 5) == [0]
        assert parse_indices("1,3,5", 5) == [0, 2, 4]
        assert parse_indices("2-4", 5) == [1, 2, 3]
        assert parse_indices("all", 3) == [0, 1, 2]
        assert parse_indices("ALL", 3) == [0, 1, 2]

        # Invalid / Cancellation
        assert parse_indices("c", 5) == []
        assert parse_indices("cancel", 5) == []
        assert parse_indices("", 5) == []
        assert parse_indices("0", 5) == []
        assert parse_indices("6", 5) == []
        assert parse_indices("999", 5) == []
        assert parse_indices("-1", 5) == []
        assert parse_indices("abc", 5) == []
        assert parse_indices("1-99", 3) == [0, 1, 2]  # Clamped to max
