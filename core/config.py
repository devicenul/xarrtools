"""Configuration management and settings cache for xarrtools.

Reads settings from SQLite DB with fallback to environment variables and .env file.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Set

from dotenv import load_dotenv

# Try to find and load a .env file in the workspace directory (or executable directory if compiled)
if getattr(sys, 'frozen', False):
    dotenv_path = Path(sys.executable).resolve().parent / '.env'
else:
    dotenv_path = Path(__file__).resolve().parent.parent / '.env'

load_dotenv(dotenv_path=dotenv_path)

logger = logging.getLogger("xarrtools.config")


class Config:
    """Application configuration container backed by database settings and environment variables."""

    PLACEHOLDER_API_KEYS: Set[str] = {
        "your_radarr_api_key_here",
        "your_sonarr_api_key_here",
        "your_tmdb_api_key_here",
    }

    def __init__(self) -> None:
        """Initializes configuration cache and loads initial settings from DB/environment."""
        self._cache: Dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        """Reloads settings cache from the database."""
        try:
            from core.db import get_all_settings
            self._cache = get_all_settings()
        except Exception as e:
            # We catch generic Exception because get_all_settings could throw sqlite3.Error, 
            # or we could just be in a state where DB isn't fully ready
            logger.error(f"Error while refreshing config from database: {e}")
            self._cache = {}

    def _get_setting(self, key: str, default: str = "") -> str:
        """Fetches a setting value from database, environment variable, or fallback cache."""
        try:
            from core.db import get_setting
            val = get_setting(key, "")
            if val:
                return val
            env_val = os.getenv(key.upper(), "")
            if env_val:
                return env_val
            return default
        except Exception:
            env_val = os.getenv(key.upper(), "")
            if env_val:
                return env_val
            return self._cache.get(key, default)

    @property
    def tmdb_api_key(self) -> str:
        """TMDB v4 read access token or v3 API key ('' when not configured)."""
        val = self._get_setting("tmdb_api_key").strip()
        return "" if val in self.PLACEHOLDER_API_KEYS else val

    @property
    def radarr_url(self) -> str:
        """Radarr server base URL with trailing slash stripped."""
        return self._get_setting("radarr_url").rstrip("/")

    @property
    def radarr_api_key(self) -> str:
        """Radarr API key (empty string if unset or placeholder)."""
        val = self._get_setting("radarr_api_key")
        return "" if val in self.PLACEHOLDER_API_KEYS else val

    @property
    def sonarr_url(self) -> str:
        """Sonarr server base URL with trailing slash stripped."""
        return self._get_setting("sonarr_url").rstrip("/")

    @property
    def sonarr_api_key(self) -> str:
        """Sonarr API key (empty string if unset or placeholder)."""
        val = self._get_setting("sonarr_api_key")
        return "" if val in self.PLACEHOLDER_API_KEYS else val

    @property
    def radarr_default_quality_profile(self) -> str:
        """Default quality profile name or ID configured for Radarr."""
        return self._get_setting("radarr_default_quality_profile") or self._get_setting("radarr_default_profile_id")

    @property
    def radarr_default_profile_id(self) -> str:
        """Alias for radarr_default_quality_profile."""
        return self.radarr_default_quality_profile

    @property
    def radarr_default_root_folder(self) -> str:
        """Default root folder path configured for Radarr."""
        return self._get_setting("radarr_default_root_folder")

    @property
    def sonarr_default_quality_profile(self) -> str:
        """Default quality profile name or ID configured for Sonarr."""
        return self._get_setting("sonarr_default_quality_profile") or self._get_setting("sonarr_default_profile_id")

    @property
    def sonarr_default_profile_id(self) -> str:
        """Alias for sonarr_default_quality_profile."""
        return self.sonarr_default_quality_profile

    @property
    def sonarr_default_root_folder(self) -> str:
        """Default root folder path configured for Sonarr."""
        return self._get_setting("sonarr_default_root_folder")

    @property
    def radarr_mru_quality_profile(self) -> str:
        """Most recently used quality profile for Radarr."""
        return self._get_setting("radarr_mru_quality_profile") or self._get_setting("radarr_mru_profile_id")

    @property
    def radarr_mru_profile_id(self) -> str:
        """Alias for radarr_mru_quality_profile."""
        return self.radarr_mru_quality_profile

    @property
    def radarr_mru_root_folder(self) -> str:
        """Most recently used root folder for Radarr."""
        return self._get_setting("radarr_mru_root_folder")

    @property
    def sonarr_mru_quality_profile(self) -> str:
        """Most recently used quality profile for Sonarr."""
        return self._get_setting("sonarr_mru_quality_profile") or self._get_setting("sonarr_mru_profile_id")

    @property
    def sonarr_mru_profile_id(self) -> str:
        """Alias for sonarr_mru_quality_profile."""
        return self.sonarr_mru_quality_profile

    @property
    def sonarr_mru_root_folder(self) -> str:
        """Most recently used root folder for Sonarr."""
        return self._get_setting("sonarr_mru_root_folder")

    @property
    def scheduler_enabled(self) -> bool:
        """Whether the background metadata refresh scheduler is enabled."""
        val = self._get_setting("scheduler_enabled", "0").strip().lower()
        return val in ("1", "true", "yes", "on")

    @property
    def scheduler_interval_hours(self) -> int:
        """Background scheduler refresh interval in hours (clamped between 1 and 168)."""
        val = self._get_setting("scheduler_interval_hours", "24")
        try:
            h = int(val)
            return max(1, min(168, h))
        except (ValueError, TypeError):
            return 24

    @property
    def scheduler_time_of_day(self) -> str:
        """Optional wall-clock target time ('HH:MM') for daily refresh in local time."""
        return self._get_setting("scheduler_time_of_day", "").strip()

    @property
    def scheduler_last_run(self) -> str:
        """Timestamp string of the most recent scheduler run."""
        return self._get_setting("scheduler_last_run", "").strip()

    @property
    def scheduler_last_result(self) -> str:
        """Outcome or status summary of the most recent scheduler run."""
        return self._get_setting("scheduler_last_result", "").strip()

    @property
    def log_level(self) -> str:
        """Configured logging level ('DEBUG', 'INFO', 'WARNING', or 'ERROR')."""
        val = self._get_setting("log_level", "INFO").strip().upper()
        return val if val in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"

    def validate_radarr(self) -> bool:
        """Returns True if Radarr config is complete, otherwise False."""
        return bool(self.radarr_url and self.radarr_api_key)

    def validate_sonarr(self) -> bool:
        """Returns True if Sonarr config is complete, otherwise False."""
        return bool(self.sonarr_url and self.sonarr_api_key)

    def get_missing_radarr_vars(self) -> List[str]:
        """Returns list of missing configuration keys required for Radarr."""
        missing = []
        if not self.radarr_url:
            missing.append("RADARR_URL")
        if not self.radarr_api_key:
            missing.append("RADARR_API_KEY")
        return missing

    def get_missing_sonarr_vars(self) -> List[str]:
        """Returns list of missing configuration keys required for Sonarr."""
        missing = []
        if not self.sonarr_url:
            missing.append("SONARR_URL")
        if not self.sonarr_api_key:
            missing.append("SONARR_API_KEY")
        return missing

# Global config instance
config = Config()
