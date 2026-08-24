import pytest
import os
import tempfile
import pathlib
import sqlite3
import subprocess
from bs4 import BeautifulSoup
from unittest.mock import patch, MagicMock

import core.db
from core.config import config
from core.db import get_setting, set_setting, init_db, get_db_connection
from cli.cli import resolve_preset_index, select_from_list


@pytest.fixture
def temp_db():
    fd, temp_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    temp_path = pathlib.Path(temp_path_str)
    old_path = core.db.DB_PATH
    core.db.DB_PATH = temp_path
    init_db()
    config.refresh()
    yield temp_path
    core.db.DB_PATH = old_path
    if temp_path.exists():
        temp_path.unlink()


# =========================================================================
# Challenge 1: Corrupted/Deleted Upstream Profile IDs & Root Folder Paths
# =========================================================================

class TestChallenge1CorruptedDeletedUpstreamPresets:
    """Adversarial stress testing for corrupted, missing, and deleted upstream profiles & folders."""

    def test_corrupted_non_numeric_and_special_char_profile_ids_in_settings(self, temp_db):
        """Verify CLI resolve_preset_index recovers safely from corrupted non-numeric strings in settings."""
        corrupted_values = [
            "CORRUPTED_ID_NOT_INT",
            "-9999",
            "0",
            "3.14159",
            "undefined",
            "null",
            "[None]",
            "   ",
            "",
            "SELECT * FROM settings",
            "!@#$%^&*()",
            "99999999999999999999999999999999999999999"
        ]
        available_profiles = [
            {"id": 10, "name": "1080p WebDL"},
            {"id": 20, "name": "2160p UHD"}
        ]

        for bad_val in corrupted_values:
            set_setting("radarr_default_quality_profile", bad_val)
            config.refresh()
            
            idx = resolve_preset_index(
                available_profiles,
                key_field="id",
                explicit_keys=["radarr_default_quality_profile"],
                mru_keys=["radarr_mru_quality_profile"]
            )
            # Should safely fall back to 1 (first available option, id=10)
            assert idx == 1, f"Failed for corrupted value: {bad_val}"

    def test_deleted_profile_id_falls_back_to_mru_then_safety_default(self, temp_db):
        """When an explicit setting references a deleted profile ID, fallback to MRU if valid, or 1."""
        available_profiles = [
            {"id": 101, "name": "Standard Definition"},
            {"id": 102, "name": "High Definition"}
        ]

        # Explicit setting points to deleted profile 999; MRU points to valid profile 102
        set_setting("sonarr_default_quality_profile", "999")
        set_setting("sonarr_mru_quality_profile", "102")
        config.refresh()

        idx = resolve_preset_index(
            available_profiles,
            key_field="id",
            explicit_keys=["sonarr_default_quality_profile"],
            mru_keys=["sonarr_mru_quality_profile"]
        )
        assert idx == 2  # Matches MRU (id=102 at index 2)

        # Now MRU is also corrupted/deleted -> falls back to index 1
        set_setting("sonarr_mru_quality_profile", "888")
        config.refresh()

        idx2 = resolve_preset_index(
            available_profiles,
            key_field="id",
            explicit_keys=["sonarr_default_quality_profile"],
            mru_keys=["sonarr_mru_quality_profile"]
        )
        assert idx2 == 1  # Safety fallback to first available

    def test_corrupted_and_deleted_root_folder_paths(self, temp_db):
        """Verify corrupted paths, case differences, trailing slashes, and deleted folders."""
        available_folders = [
            {"id": 1, "path": "/data/media/movies"},
            {"id": 2, "path": "/mnt/storage/tv"}
        ]

        # Trailing slashes / casing normalization
        set_setting("radarr_default_root_folder", "/data/media/movies/")
        config.refresh()
        idx = resolve_preset_index(
            available_folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 1

        # Corrupted / deleted folder in settings -> MRU fallback
        set_setting("radarr_default_root_folder", "/deleted/nonexistent/path")
        set_setting("radarr_mru_root_folder", "/mnt/storage/tv")
        config.refresh()
        idx = resolve_preset_index(
            available_folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 2

        # Both corrupted -> safety fallback 1
        set_setting("radarr_mru_root_folder", "C:\\Windows\\System32\\bad")
        config.refresh()
        idx = resolve_preset_index(
            available_folders,
            key_field="path",
            explicit_keys=["radarr_default_root_folder"],
            mru_keys=["radarr_mru_root_folder"]
        )
        assert idx == 1

    def test_database_null_and_corrupt_settings_rows(self, temp_db):
        """Directly insert weird rows into SQLite settings table and verify stability."""
        conn = get_db_connection()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('radarr_default_quality_profile', NULL)")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('sonarr_default_root_folder', '')")
        conn.commit()
        conn.close()

        config.refresh()
        available_profiles = [{"id": 5, "name": "720p"}]
        idx = resolve_preset_index(
            available_profiles,
            key_field="id",
            explicit_keys=["radarr_default_quality_profile"],
            mru_keys=["radarr_mru_quality_profile"]
        )
        assert idx == 1


# =========================================================================
# Challenge 2: Empty Options Lists in CLI and Web UI
# =========================================================================

class TestChallenge2EmptyOptionsLists:
    """Stress testing empty options lists in CLI selection and Web UI preset resolution."""

    def test_cli_select_from_list_empty_list(self):
        """select_from_list returns {} immediately when items list is empty or None without crashing."""
        assert select_from_list("Select something", []) == {}
        assert select_from_list("Select something", None) == {}

    def test_cli_resolve_preset_index_empty_list(self):
        """resolve_preset_index returns 1 when items list is empty or None."""
        assert resolve_preset_index([], "id", ["explicit"], ["mru"]) == 1
        assert resolve_preset_index(None, "id", ["explicit"], ["mru"]) == 1

    def test_cli_select_from_list_invalid_clamped_default(self):
        """Verify select_from_list clamps default_index when out of bounds."""
        items = [{"id": 1, "name": "Option 1"}, {"id": 2, "name": "Option 2"}]
        
        # Test simulated input with choice 1 when default is invalid (-5, 0, 999, 'abc')
        with patch("rich.prompt.IntPrompt.ask", return_value=1) as mock_ask:
            res = select_from_list("Choose", items, default_index=-5)
            assert res == items[0]
            mock_ask.assert_called_with("Choose", default=1)

        with patch("rich.prompt.IntPrompt.ask", return_value=2) as mock_ask:
            res = select_from_list("Choose", items, default_index=999)
            assert res == items[1]
            mock_ask.assert_called_with("Choose", default=1)

        with patch("rich.prompt.IntPrompt.ask", return_value=1) as mock_ask:
            res = select_from_list("Choose", items, default_index="invalid")
            assert res == items[0]
            mock_ask.assert_called_with("Choose", default=1)

    def test_web_resolve_hybrid_preset_via_node_harness(self):
        """Run Node.js execution to stress-test resolveHybridPreset directly from app.js."""
        app_js_path = os.path.abspath("web/templates/app.js")
        
        js_code = f"""
        const fs = require('fs');
        let code = fs.readFileSync('{app_js_path}', 'utf8');

        // Mock window, localStorage, and DOM environment
        const localStorageStore = {{}};
        global.window = {{}};
        global.localStorage = {{
            getItem: (k) => localStorageStore[k] || null,
            setItem: (k, v) => {{ localStorageStore[k] = String(v); }},
            removeItem: (k) => {{ delete localStorageStore[k]; }}
        }};
        global.document = {{
            querySelector: () => null,
            getElementById: () => null,
            querySelectorAll: () => [],
            addEventListener: () => {{}}
        }};

        const harness = `
            ${{code}}

            const fn = window.resolveHybridPreset;
            if (typeof fn !== 'function') throw new Error('resolveHybridPreset not found');

            // 1. Empty options list edge cases
            if (fn([], 'id', 1, 'mru') !== '') throw new Error('Empty array failed');
            if (fn(null, 'id', 1, 'mru') !== '') throw new Error('Null options failed');
            if (fn(undefined, 'id', 1, 'mru') !== '') throw new Error('Undefined options failed');
            if (fn('not an array', 'id', 1, 'mru') !== '') throw new Error('String options failed');
            if (fn([{{}}], 'id', 1, 'mru') !== '') throw new Error('Empty dict options failed');

            // 2. Explicit match
            const profiles = [{{ id: 1, name: 'SD' }}, {{ id: 2, name: 'HD' }}, {{ id: 3, name: '4K' }}];
            if (fn(profiles, 'id', 2, 'mru') !== '2') throw new Error('Explicit match failed');
            if (fn(profiles, 'id', '3', 'mru') !== '3') throw new Error('Explicit string match failed');

            // 3. Deleted explicit -> MRU fallback
            localStorageStore['mru_key'] = '2';
            if (fn(profiles, 'id', 999, 'mru_key') !== '2') throw new Error('MRU fallback failed');

            // 4. Deleted explicit & deleted MRU -> Safety fallback to index 0
            localStorageStore['mru_key'] = '888';
            if (fn(profiles, 'id', 999, 'mru_key') !== '1') throw new Error('Safety fallback failed');

            // 5. Backend appSettings fallback (via mapped altKey)
            delete localStorageStore['xarrtools_mru_radarr_profile'];
            appSettings = {{ 'radarr_mru_quality_profile': '3' }};
            if (fn(profiles, 'id', null, 'xarrtools_mru_radarr_profile') !== '3') throw new Error('appSettings backend fallback failed');

            // 6. Direct appSettings key fallback
            appSettings = {{ 'custom_mru_key': '2' }};
            if (fn(profiles, 'id', null, 'custom_mru_key') !== '2') throw new Error('appSettings direct fallback failed');
        `;

        eval(harness);
        console.log('ALL_NODE_TESTS_PASSED');
        """

        res = subprocess.run(
            ["node", "-e", js_code],
            capture_output=True,
            text=True
        )
        assert res.returncode == 0, f"Node.js test harness failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        assert "ALL_NODE_TESTS_PASSED" in res.stdout


# =========================================================================
# Challenge 3: HTML / JS Syntax & DOM Integrity
# =========================================================================

class TestChallenge3HtmlJsIntegrity:
    """Verifies HTML/JS syntax, DOM element bindings, and language profile deprecation."""

    def test_javascript_syntax_cleanliness(self):
        """Execute node --check on web/templates/app.js to verify valid JS syntax."""
        app_js_path = os.path.abspath("web/templates/app.js")
        res = subprocess.run(["node", "--check", app_js_path], capture_output=True, text=True)
        assert res.returncode == 0, f"JS Syntax Error in app.js:\n{res.stderr}"

    def test_html_syntax_and_unique_ids(self):
        """Parse index.html with BeautifulSoup and ensure valid structure and no duplicate element IDs."""
        html_path = os.path.abspath("web/templates/index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        
        all_elements = soup.find_all(id=True)
        seen_ids = set()
        duplicates = []
        for el in all_elements:
            el_id = el["id"]
            if el_id in seen_ids:
                duplicates.append(el_id)
            seen_ids.add(el_id)

        assert not duplicates, f"Duplicate DOM element IDs found in index.html: {duplicates}"

    def test_settings_modal_element_ids_exist_in_dom(self):
        """Verify that all settings selectors referenced in app.js exist in index.html."""
        html_path = os.path.abspath("web/templates/index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        required_ids = [
            "select-radarr-default-folder",
            "select-radarr-default-profile",
            "select-sonarr-default-folder",
            "select-sonarr-default-profile",
            "btn-settings",
            "settings-overlay",
            "settings-close",
            "btn-settings-cancel",
            "btn-settings-save",
            "modal-overlay",
            "modal-close",
            "btn-modal-cancel",
            "btn-modal-confirm",
            "btn-modal-back",
            "select-folder",
            "select-profile"
        ]

        for req_id in required_ids:
            el = soup.find(id=req_id)
            assert el is not None, f"Required element #{req_id} missing from index.html"

    def test_language_profile_deprecation_complete_removal(self):
        """Verify that no language profile UI elements or deprecated identifiers exist in HTML or JS."""
        html_path = os.path.abspath("web/templates/index.html")
        js_path = os.path.abspath("web/templates/app.js")

        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        deprecated_tokens = [
            "select-lang-profile",
            "group-lang-profile",
            "select-language-profile",
            "group-language-profile",
            "language_profiles",
            "lang_profile_id"
        ]

        for token in deprecated_tokens:
            assert token not in html_content, f"Deprecated token '{token}' found in index.html"
            assert token not in js_content, f"Deprecated token '{token}' found in app.js"
