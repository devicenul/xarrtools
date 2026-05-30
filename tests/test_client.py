import pytest
import requests
from unittest.mock import patch, MagicMock
from core.client import RadarrClient, SonarrClient, ArrAPIError

def test_client_request_success():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_req.return_value = mock_response
        
        res = radarr.get_root_folders()
        assert res == {"status": "ok"}
        mock_req.assert_called_once_with(
            method="GET",
            url="http://localhost:7878/api/v3/rootfolder",
            headers={"X-Api-Key": "radarrkey", "Content-Type": "application/json"},
            params=None,
            json=None,
            timeout=15
        )

def test_client_request_204():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_req.return_value = mock_response
        
        res = radarr._request("POST", "test")
        assert res is None

def test_client_http_error_json_list():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Error detail text"
        mock_response.json.return_value = [{"errorMessage": "Validation failed"}]
        # Setup raise_for_status to raise HTTPError
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Bad Request")
        mock_req.return_value = mock_response
        
        with pytest.raises(ArrAPIError) as exc_info:
            radarr.get_root_folders()
            
        assert "Validation failed" in str(exc_info.value)
        assert exc_info.value.status_code == 400
        assert exc_info.value.response_text == "Error detail text"

def test_client_http_error_json_dict():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error text"
        mock_response.json.return_value = {"message": "Database locked"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Internal Server Error")
        mock_req.return_value = mock_response
        
        with pytest.raises(ArrAPIError) as exc_info:
            radarr.get_root_folders()
            
        assert "Database locked" in str(exc_info.value)

def test_client_http_error_json_other_type():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error text"
        # json returns integer to bypass both list and dict checks
        mock_response.json.return_value = 123
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Internal Server Error")
        mock_req.return_value = mock_response
        
        with pytest.raises(ArrAPIError) as exc_info:
            radarr.get_root_folders()
            
        assert "Internal error text" in str(exc_info.value)

def test_client_http_error_fallback_text():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden raw text"
        # json raises exception to fall back to text
        mock_response.json.side_effect = Exception("Not JSON")
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Forbidden")
        mock_req.return_value = mock_response
        
        with pytest.raises(ArrAPIError) as exc_info:
            radarr.get_root_folders()
            
        assert "Forbidden raw text" in str(exc_info.value)

def test_client_connection_error():
    radarr = RadarrClient("http://localhost:7878", "radarrkey")
    
    with patch("requests.request", side_effect=requests.exceptions.RequestException("Connection refused")):
        with pytest.raises(ArrAPIError) as exc_info:
            radarr.get_root_folders()
            
        assert "Connection to Radarr failed" in str(exc_info.value)

def test_radarr_client_methods():
    radarr = RadarrClient("http://localhost:7878/", "radarrkey")
    
    # 1. lookup_movie
    with patch.object(radarr, "_request", return_value=[]) as mock_req:
        res = radarr.lookup_movie("Antigravity")
        assert res == []
        mock_req.assert_called_once_with("GET", "movie/lookup", params={"term": "Antigravity"})
        
    # 2. get_library
    with patch.object(radarr, "_request", return_value=[]) as mock_req:
        res = radarr.get_library()
        assert res == []
        mock_req.assert_called_once_with("GET", "movie")
        
    # 3. get_quality_profiles
    with patch.object(radarr, "_request", return_value=[]) as mock_req:
        res = radarr.get_quality_profiles()
        assert res == []
        mock_req.assert_called_once_with("GET", "qualityprofile")
        
    # 4. add_movie (no collection)
    with patch.object(radarr, "_request", return_value={}) as mock_req:
        movie_data = {"title": "Antigravity Movie", "tmdbId": 123}
        radarr.add_movie(movie_data, 1, "/movies", monitored=True, search_now=True, add_collection=False)
        mock_req.assert_called_once_with(
            "POST", "movie", json_data={
                "title": "Antigravity Movie",
                "tmdbId": 123,
                "qualityProfileId": 1,
                "rootFolderPath": "/movies",
                "monitored": True,
                "addOptions": {
                    "searchForMovie": True,
                    "monitor": "movieOnly"
                }
            }
        )

    # 5. add_movie (with collection)
    with patch.object(radarr, "_request", return_value={}) as mock_req:
        movie_data = {"title": "Antigravity Movie", "tmdbId": 123}
        radarr.add_movie(movie_data, 1, "/movies", monitored=True, search_now=True, add_collection=True)
        mock_req.assert_called_once_with(
            "POST", "movie", json_data={
                "title": "Antigravity Movie",
                "tmdbId": 123,
                "qualityProfileId": 1,
                "rootFolderPath": "/movies",
                "monitored": True,
                "addOptions": {
                    "searchForMovie": True,
                    "monitor": "movieAndCollection"
                }
            }
        )

def test_sonarr_client_methods():
    sonarr = SonarrClient("http://localhost:8989/", "sonarrkey")
    
    # 1. lookup_series
    with patch.object(sonarr, "_request", return_value=[]) as mock_req:
        res = sonarr.lookup_series("Antigravity")
        assert res == []
        mock_req.assert_called_once_with("GET", "series/lookup", params={"term": "Antigravity"})
        
    # 2. get_library
    with patch.object(sonarr, "_request", return_value=[]) as mock_req:
        res = sonarr.get_library()
        assert res == []
        mock_req.assert_called_once_with("GET", "series")
        
    # 3. get_quality_profiles
    with patch.object(sonarr, "_request", return_value=[]) as mock_req:
        res = sonarr.get_quality_profiles()
        assert res == []
        mock_req.assert_called_once_with("GET", "qualityprofile")
        
    # 4. get_root_folders
    with patch.object(sonarr, "_request", return_value=[]) as mock_req:
        res = sonarr.get_root_folders()
        assert res == []
        mock_req.assert_called_once_with("GET", "rootfolder")
        
    # 5. get_language_profiles (success)
    with patch.object(sonarr, "_request", return_value=[{"name": "English"}]) as mock_req:
        res = sonarr.get_language_profiles()
        assert res == [{"name": "English"}]
        mock_req.assert_called_once_with("GET", "languageprofile")
        
    # 6. get_language_profiles (exception fallback)
    with patch.object(sonarr, "_request", side_effect=ArrAPIError("Not supported")):
        res = sonarr.get_language_profiles()
        assert res == []
        
    # 7. add_series
    with patch.object(sonarr, "_request", return_value={}) as mock_req:
        series_data = {"title": "Antigravity Show", "tvdbId": 456}
        sonarr.add_series(series_data, 1, "/tv", monitored=True, search_now=True, language_profile_id=1)
        mock_req.assert_called_once_with(
            "POST", "series", json_data={
                "title": "Antigravity Show",
                "tvdbId": 456,
                "qualityProfileId": 1,
                "rootFolderPath": "/tv",
                "monitored": True,
                "addOptions": {
                    "searchForMissingEpisodes": True
                },
                "languageProfileId": 1
            }
        )

    # 8. add_series (no language profile ID)
    with patch.object(sonarr, "_request", return_value={}) as mock_req:
        series_data = {"title": "Antigravity Show", "tvdbId": 456}
        sonarr.add_series(series_data, 1, "/tv", monitored=True, search_now=True, language_profile_id=None)
        mock_req.assert_called_once_with(
            "POST", "series", json_data={
                "title": "Antigravity Show",
                "tvdbId": 456,
                "qualityProfileId": 1,
                "rootFolderPath": "/tv",
                "monitored": True,
                "addOptions": {
                    "searchForMissingEpisodes": True
                }
            }
        )
