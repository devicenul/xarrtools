import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Try to find and load a .env file in the workspace directory (or executable directory if compiled)
if getattr(sys, 'frozen', False):
    dotenv_path = Path(sys.executable).resolve().parent / '.env'
else:
    dotenv_path = Path(__file__).resolve().parent.parent / '.env'

load_dotenv(dotenv_path=dotenv_path)

class Config:
    def _get_setting(self, key: str, default: str = "") -> str:
        val = ""
        try:
            from core.db import get_setting
            val = get_setting(key, "")
        except Exception:
            pass
        if not val:
            return os.getenv(key.upper(), default)
        return val

    @property
    def radarr_url(self) -> str:
        return self._get_setting("radarr_url").rstrip("/")

    @property
    def radarr_api_key(self) -> str:
        return self._get_setting("radarr_api_key")

    @property
    def sonarr_url(self) -> str:
        return self._get_setting("sonarr_url").rstrip("/")

    @property
    def sonarr_api_key(self) -> str:
        return self._get_setting("sonarr_api_key")

    def validate_radarr(self) -> bool:
        """Returns True if Radarr config is complete, otherwise False."""
        return bool(self.radarr_url and self.radarr_api_key)

    def validate_sonarr(self) -> bool:
        """Returns True if Sonarr config is complete, otherwise False."""
        return bool(self.sonarr_url and self.sonarr_api_key)

    def get_missing_radarr_vars(self) -> list:
        missing = []
        if not self.radarr_url:
            missing.append("RADARR_URL")
        if not self.radarr_api_key:
            missing.append("RADARR_API_KEY")
        return missing

    def get_missing_sonarr_vars(self) -> list:
        missing = []
        if not self.sonarr_url:
            missing.append("SONARR_URL")
        if not self.sonarr_api_key:
            missing.append("SONARR_API_KEY")
        return missing

# Global config instance
config = Config()
