"""Tests for XARRTOOLS_CONFIG_DIR and cross-environment backup/restore portability."""
import io
import importlib
import json
import os
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

import xarrtools.core.db; from xarrtools import core
import xarrtools.core.config; from xarrtools import core
import xarrtools.core.posters; from xarrtools import core
import xarrtools.core.logging_setup; from xarrtools import core
from xarrtools.core.db import init_db, set_setting, get_setting, add_cached_item, get_cached_item, export_to_dict, import_from_dict, verify_backup_checksum as db_verify_checksum
from xarrtools.core.backup import export_full_backup, import_full_backup, verify_backup_checksum
from xarrtools.core.posters import store_poster, get_cached_poster, get_posters_dir


def test_config_dir_env_resolution(tmp_path):
    """When XARRTOOLS_CONFIG_DIR is set (and not sys.frozen), DB, .env, posters, and logs resolve into it."""
    config_dir = tmp_path / "custom_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    old_db = core.db.DB_PATH
    old_env = core.config.dotenv_path
    old_config_env = os.environ.get("XARRTOOLS_CONFIG_DIR")
    old_log_env = os.environ.get("XARRTOOLS_LOG_DIR")
    
    try:
        os.environ["XARRTOOLS_CONFIG_DIR"] = str(config_dir)
        os.environ.pop("XARRTOOLS_LOG_DIR", None)
        
        importlib.reload(core.db)
        importlib.reload(core.config)
        importlib.reload(core.posters)
        importlib.reload(core.logging_setup)
        
        assert core.db.DB_PATH == config_dir.resolve() / "xarrtools.db"
        assert core.config.dotenv_path == config_dir.resolve() / ".env"
        assert core.posters.get_posters_dir() == config_dir.resolve() / "posters"
        assert core.logging_setup.get_log_dir() == config_dir.resolve() / "logs"
    finally:
        if old_config_env is None:
            os.environ.pop("XARRTOOLS_CONFIG_DIR", None)
        else:
            os.environ["XARRTOOLS_CONFIG_DIR"] = old_config_env
        if old_log_env is not None:
            os.environ["XARRTOOLS_LOG_DIR"] = old_log_env
            
        importlib.reload(core.db)
        core.db.DB_PATH = old_db
        importlib.reload(core.config)
        importlib.reload(core.posters)
        importlib.reload(core.logging_setup)
        core.config.dotenv_path = old_env


def test_sys_frozen_precedes_config_dir(tmp_path):
    """sys.frozen takes precedence over XARRTOOLS_CONFIG_DIR."""
    config_dir = tmp_path / "custom_config"
    old_frozen = getattr(sys, "frozen", None)
    old_config_env = os.environ.get("XARRTOOLS_CONFIG_DIR")
    old_db = core.db.DB_PATH
    old_env = core.config.dotenv_path
    
    try:
        os.environ["XARRTOOLS_CONFIG_DIR"] = str(config_dir)
        sys.frozen = True
        
        importlib.reload(core.db)
        importlib.reload(core.config)
        
        expected_db = Path(sys.executable).resolve().parent / "xarrtools.db"
        expected_env = Path(sys.executable).resolve().parent / ".env"
        assert core.db.DB_PATH == expected_db
        assert core.config.dotenv_path == expected_env
    finally:
        if old_frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = old_frozen
            
        if old_config_env is None:
            os.environ.pop("XARRTOOLS_CONFIG_DIR", None)
        else:
            os.environ["XARRTOOLS_CONFIG_DIR"] = old_config_env
            
        importlib.reload(core.db)
        core.db.DB_PATH = old_db
        importlib.reload(core.config)
        core.config.dotenv_path = old_env


def test_cross_environment_backup_and_restore(tmp_path):
    """Backups exported from one config dir must restore into a different config dir and default layout.
    
    Verifies:
    1. Backups do not embed host environment paths (DB path, config dir).
    2. Backups do not embed or overwrite basic auth env credentials.
    3. format_version and checksum verification succeed.
    4. Posters and database records restore properly relative to target active directory.
    """
    config_a = tmp_path / "docker_config"
    config_b = tmp_path / "standalone_config"
    config_a.mkdir(parents=True)
    config_b.mkdir(parents=True)

    saved_db_path = core.db.DB_PATH

    # Set up basic auth in environment to verify it is NEVER leaked into backups or overwritten
    env_patch = {
        "XARRTOOLS_AUTH_USER": "docker_user_99",
        "XARRTOOLS_AUTH_PASSWORD": "secret_password_never_leak_99"
    }

    try:
        with patch.dict(os.environ, env_patch, clear=False):
            # --- 1. Populate and Export from Environment A (e.g. Docker /config) ---
            core.db.DB_PATH = config_a / "xarrtools.db"
            init_db()

            set_setting("radarr_url", "http://radarr.docker:7878")
            set_setting("custom_portability_key", "portability_test_value")

            poster_url = "https://images.example.com/poster123.jpg"
            poster_data = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"A" * 128
            assert store_poster(poster_url, poster_data, "image/jpeg") is True

            sample_movie = {
                "type": "movie",
                "title": "Cross Platform Movie",
                "year": 2024,
                "date_str": "2024-11-01",
                "date_obj": "2024-11-01",
                "description": "A film testing cross-platform portability.",
                "href": "https://example.com/movie",
                "imdb_id": "tt9999999",
                "genres": json.dumps(["Action", "Sci-Fi"]),
                "cast": "Actor One, Actor Two",
                "poster_url": poster_url,
                "is_archived": 0,
                "manually_archived": 0,
                "is_in_library": 0,
                "rating_imdb": "8.5"
            }
            add_cached_item("movie", sample_movie)

            # Export Full Backup (ZIP)
            zip_buf = io.BytesIO()
            full_stats = export_full_backup(zip_buf, include_media=True)
            assert full_stats["media_count"] >= 1
            assert full_stats["posters_count"] == 1
            zip_bytes = zip_buf.getvalue()

            # Export JSON Backup
            json_backup_data = export_to_dict(include_media=True)
            assert json_backup_data["format_version"] == 1
            assert db_verify_checksum(json_backup_data) is True

            # Verify NO environment paths or auth secrets are in ZIP or JSON
            assert str(config_a).encode("utf-8") not in zip_bytes
            assert b"docker_user_99" not in zip_bytes
            assert b"secret_password_never_leak_99" not in zip_bytes

            json_str = json.dumps(json_backup_data)
            assert str(config_a) not in json_str
            assert "docker_user_99" not in json_str
            assert "secret_password_never_leak_99" not in json_str

            # --- 2. Restore Full Backup into Environment B (e.g. Standalone) ---
            core.db.DB_PATH = config_b / "xarrtools.db"
            init_db()

            import_res = import_full_backup(io.BytesIO(zip_bytes))
            assert import_res["status"] == "success"
            assert import_res["posters_count"] == 1

            # Settings restored
            assert get_setting("radarr_url") == "http://radarr.docker:7878"
            assert get_setting("custom_portability_key") == "portability_test_value"

            # Cache item restored
            restored_item = get_cached_item("movie", "Cross Platform Movie", 2024, imdb_id="tt9999999")
            assert restored_item is not None
            assert restored_item["rating_imdb"] == "8.5"

            # Poster restored into config_b/posters
            expected_poster_dir = config_b / "posters"
            assert expected_poster_dir.is_dir()
            cached_poster = get_cached_poster(poster_url)
            assert cached_poster is not None
            assert cached_poster[0] == poster_data
            assert cached_poster[1] == "image/jpeg"

            # Environment basic auth credentials were NOT modified or overwritten
            assert os.environ.get("XARRTOOLS_AUTH_USER") == "docker_user_99"
            assert os.environ.get("XARRTOOLS_AUTH_PASSWORD") == "secret_password_never_leak_99"

            # --- 3. Restore JSON Backup into Environment C ---
            config_c = tmp_path / "json_restore_config"
            config_c.mkdir(parents=True)
            core.db.DB_PATH = config_c / "xarrtools.db"
            init_db()

            settings_count, media_count = import_from_dict(json_backup_data)
            assert settings_count > 0
            assert media_count >= 1
            assert get_setting("custom_portability_key") == "portability_test_value"
            item_c = get_cached_item("movie", "Cross Platform Movie", 2024, imdb_id="tt9999999")
            assert item_c is not None

    finally:
        core.db.DB_PATH = saved_db_path
