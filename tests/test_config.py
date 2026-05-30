import os
import pytest
from unittest.mock import patch, MagicMock
from core.config import Config

def test_config_from_db():
    config = Config()
    with patch("core.db.get_setting") as mock_get:
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
    with patch("core.db.get_setting", side_effect=Exception("DB error")), \
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
    with patch("core.db.get_setting", return_value=""), \
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
