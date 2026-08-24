import requests
from typing import List, Dict, Any, Optional

class ArrAPIError(Exception):
    """Custom exception for Sonarr/Radarr API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

class BaseArrClient:
    """Base class sharing request logic for *Arr APIs."""
    def __init__(self, base_url: str, api_key: str, name: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = name
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }

    def _discover_protocol(self) -> str:
        raw_host = self.base_url
        https_url = f"https://{raw_host}"
        http_url = f"http://{raw_host}"
        
        for test_url in (https_url, http_url):
            url = f"{test_url}/api/v3/system/status"
            try:
                response = requests.request(
                    method="GET",
                    url=url,
                    headers=self.headers,
                    timeout=5
                )
                from core.db import set_setting
                setting_key = "radarr_url" if self.name.lower() == "radarr" else "sonarr_url"
                set_setting(setting_key, test_url)
                return test_url
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                continue
            except requests.exceptions.RequestException:
                from core.db import set_setting
                setting_key = "radarr_url" if self.name.lower() == "radarr" else "sonarr_url"
                set_setting(setting_key, test_url)
                return test_url
                
        return http_url

    def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, json_data: Optional[Dict[str, Any]] = None) -> Any:
        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            self.base_url = self._discover_protocol()
            
        url = f"{self.base_url}/api/v3/{endpoint.lstrip('/')}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=json_data,
                timeout=15
            )
            response.raise_for_status()
            if response.status_code == 204:
                return None
            return response.json()
        except requests.exceptions.HTTPError as e:
            err_msg = f"{self.name} API HTTP Error {response.status_code}"
            detail = response.text
            try:
                detail_json = response.json()
                if isinstance(detail_json, list) and len(detail_json) > 0:
                    detail = detail_json[0].get("errorMessage", detail)
                elif isinstance(detail_json, dict):
                    detail = detail_json.get("message", detail)
            except Exception:
                pass
            raise ArrAPIError(f"{err_msg}: {detail}", status_code=response.status_code, response_text=response.text) from e
        except requests.exceptions.RequestException as e:
            raise ArrAPIError(f"Connection to {self.name} failed: {e}") from e

class RadarrClient(BaseArrClient):
    """Client for Radarr API v3."""
    def __init__(self, base_url: str, api_key: str):
        super().__init__(base_url, api_key, "Radarr")

    def lookup_movie(self, term: str) -> List[Dict[str, Any]]:
        """Search for movies using a search term (looks up in TMDB)."""
        return self._request("GET", "movie/lookup", params={"term": term})

    def get_library(self) -> List[Dict[str, Any]]:
        """Retrieve all movies currently in the Radarr library."""
        return self._request("GET", "movie")

    def get_quality_profiles(self) -> List[Dict[str, Any]]:
        """Retrieve all quality profiles configured in Radarr."""
        return self._request("GET", "qualityprofile")

    def get_root_folders(self) -> List[Dict[str, Any]]:
        """Retrieve all root folder paths configured in Radarr."""
        return self._request("GET", "rootfolder")

    def add_movie(self, movie_data: Dict[str, Any], quality_profile_id: int, root_folder_path: str, monitored: bool = True, search_now: bool = True, add_collection: bool = False) -> Dict[str, Any]:
        """Add a movie to the Radarr library."""
        # Create a copy so we don't modify the input dict in-place
        payload = dict(movie_data)
        payload.update({
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {
                "searchForMovie": search_now,
                "monitor": "movieAndCollection" if add_collection else "movieOnly"
            }
        })
        return self._request("POST", "movie", json_data=payload)

class SonarrClient(BaseArrClient):
    """Client for Sonarr API v3."""
    def __init__(self, base_url: str, api_key: str):
        super().__init__(base_url, api_key, "Sonarr")

    def lookup_series(self, term: str) -> List[Dict[str, Any]]:
        """Search for series using a search term (looks up in TVDB)."""
        return self._request("GET", "series/lookup", params={"term": term})

    def get_library(self) -> List[Dict[str, Any]]:
        """Retrieve all series currently in the Sonarr library."""
        return self._request("GET", "series")

    def get_quality_profiles(self) -> List[Dict[str, Any]]:
        """Retrieve all quality profiles configured in Sonarr."""
        return self._request("GET", "qualityprofile")

    def get_root_folders(self) -> List[Dict[str, Any]]:
        """Retrieve all root folder paths configured in Sonarr."""
        return self._request("GET", "rootfolder")

    def add_series(self, series_data: Dict[str, Any], quality_profile_id: int, root_folder_path: str, monitored: bool = True, search_now: bool = True) -> Dict[str, Any]:
        """Add a TV series to the Sonarr library."""
        payload = dict(series_data)
        payload.update({
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {
                "searchForMissingEpisodes": search_now
            }
        })
        return self._request("POST", "series", json_data=payload)
