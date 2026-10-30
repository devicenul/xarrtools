import os
import pytest
from unittest.mock import patch, MagicMock
from xarrtools.core.config import Config

def test_config_from_db():
    config = Config()
    with patch("xarrtools.core.db.get_setting") as mock_get:
        mock_get.side_effect = lambda key, default: {
            "radarr_url": "http://localhost:7878/",
            "radarr_api_key": "radarr_key_123",
            "sonarr_url": "http://localhost:8989/",
            "sonarr_api_key": "sonarr_key_123"
        }.get(key, default)

        assert config.radarr_url == "http://localhost:7878"
        assert config.radarr_api_key == "radarr_key_123"
        assert config.sonarr_url == "http://localhost:8989"
        assert config.sonarr_api_key == "sonarr_key_123"
        assert config.validate_radarr() is True
        assert config.validate_sonarr() is True
        assert config.get_missing_radarr_vars() == []
        assert config.get_missing_sonarr_vars() == []

def test_config_fallback_to_env():
    config = Config()
    # If get_setting returns empty or raises an exception
    with patch("xarrtools.core.db.get_setting", side_effect=Exception("DB error")), \
         patch.dict(os.environ, {
             "RADARR_URL": "http://radarr-env:7878/",
             "RADARR_API_KEY": "radarr_env_key",
             "SONARR_URL": "http://sonarr-env:8989/",
             "SONARR_API_KEY": "sonarr_env_key"
         }):
        assert config.radarr_url == "http://radarr-env:7878"
        assert config.radarr_api_key == "radarr_env_key"
        assert config.sonarr_url == "http://sonarr-env:8989"
        assert config.sonarr_api_key == "sonarr_env_key"

def test_config_missing_vars():
    config = Config()
    with patch("xarrtools.core.db.get_setting", return_value=""), \
         patch.dict(os.environ, {}, clear=True):
        assert config.radarr_url == ""
        assert config.radarr_api_key == ""
        assert config.sonarr_url == ""
        assert config.sonarr_api_key == ""
        assert config.validate_radarr() is False
        assert config.validate_sonarr() is False
        assert "RADARR_URL" in config.get_missing_radarr_vars()
        assert "RADARR_API_KEY" in config.get_missing_radarr_vars()
        assert "SONARR_URL" in config.get_missing_sonarr_vars()
        assert "SONARR_API_KEY" in config.get_missing_sonarr_vars()


def test_config_frozen_path():
    import sys
    import importlib
    import xarrtools.core.config
    from xarrtools import core
    
    old_frozen = getattr(sys, 'frozen', None)
    sys.frozen = True
    try:
        importlib.reload(core.config)
        from pathlib import Path
        expected = Path(sys.executable).resolve().parent / ".env"
        assert core.config.dotenv_path == expected
    finally:
        if old_frozen is None:
            if hasattr(sys, 'frozen'):
                del sys.frozen
        else:
            sys.frozen = old_frozen
        importlib.reload(core.config)


def test_config_placeholder_api_keys():
    config = Config()
    with patch("xarrtools.core.db.get_setting") as mock_get:
        mock_get.side_effect = lambda key, default: {
            "radarr_url": "http://localhost:7878",
            "radarr_api_key": "your_radarr_api_key_here",
            "sonarr_url": "http://localhost:8989",
            "sonarr_api_key": "your_sonarr_api_key_here",
        }.get(key, default)

        assert config.radarr_api_key == ""
        assert config.sonarr_api_key == ""
        assert config.validate_radarr() is False
        assert config.validate_sonarr() is False
        assert "RADARR_API_KEY" in config.get_missing_radarr_vars()
        assert "SONARR_API_KEY" in config.get_missing_sonarr_vars()



def _capture_config_logs():
    """Attach a list-collecting handler directly to the config logger.

    caplog listens on the root logger, which other tests can cut off by setting
    propagate=False on the 'xarrtools' logger, so capture on the logger itself.
    """
    import logging

    records = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Collector(level=logging.DEBUG)
    logger = logging.getLogger("xarrtools.config")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    def restore():
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    return records, restore


def test_refresh_missing_settings_table_is_not_an_error():
    """A brand-new DB has no settings table yet; that must not be logged as an error."""
    import logging
    import sqlite3
    from unittest.mock import patch
    from xarrtools.core.config import Config

    records, restore = _capture_config_logs()
    try:
        with patch("xarrtools.core.db.get_all_settings", side_effect=sqlite3.OperationalError("no such table: settings")):
            cfg = Config()
    finally:
        restore()
    assert cfg._cache == {}
    assert not [r for r in records if r.levelno >= logging.ERROR]


def test_refresh_other_db_errors_are_still_logged():
    """Unexpected DB failures keep being reported as errors."""
    import logging
    import sqlite3
    from unittest.mock import patch
    from xarrtools.core.config import Config

    records, restore = _capture_config_logs()
    try:
        with patch("xarrtools.core.db.get_all_settings", side_effect=sqlite3.OperationalError("database is locked")):
            Config()
    finally:
        restore()
    assert any(r.levelno >= logging.ERROR and "database is locked" in r.getMessage() for r in records)
