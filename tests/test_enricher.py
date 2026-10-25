import pytest
import requests
from unittest.mock import patch, MagicMock
from core.client import SonarrClient, RadarrClient, ArrAPIError
from core.enricher import clean_html, get_wikipedia_cast, enrich_tv_show, enrich_movie

def test_clean_html():
    assert clean_html("<p>Hello <b>World</b>!</p>") == "Hello World!"
    assert clean_html("") == ""

def test_get_wikipedia_cast_success():
    search_mock = {
        "query": {
            "search": [{"title": "Gladiator II"}]
        }
    }
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Directed by</th>
                        <td class="infobox-data">Ridley Scott</td>
                    </tr>
                    <tr>
                        <th class="infobox-label">Starring</th>
                        <td class="infobox-data">
                            <a href="/wiki/Paul_Mescal">Paul Mescal</a><br/>
                            <a href="/wiki/Pedro_Pascal">Pedro Pascal</a>
                        </td>
                    </tr>
                </table>
                """
            }
        }
    }
    
    with patch("core.enricher.enricher_session.get") as mock_get:
        # First request returns search query, second returns parsed text
        r1 = MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        
        r2 = MagicMock()
        r2.status_code = 200
        r2.json.return_value = parse_mock
        
        mock_get.side_effect = [r1, r2]
        
        cast = get_wikipedia_cast("Gladiator II", 2024, is_tv=False)
        assert cast == "Paul Mescal, Pedro Pascal"

def test_get_wikipedia_cast_empty_starring():
    search_mock = {"query": {"search": [{"title": "Rivals"}]}}
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Starring</th>
                        <td class="infobox-data"></td>
                    </tr>
                </table>
                """
            }
        }
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r1, r2 = MagicMock(), MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        r2.status_code = 200
        r2.json.return_value = parse_mock
        mock_get.side_effect = [r1, r2]
        
        cast = get_wikipedia_cast("Rivals", 2026)
        assert cast is None

def test_get_wikipedia_cast_no_infobox_td():
    search_mock = {"query": {"search": [{"title": "Rivals"}]}}
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Starring</th>
                    </tr>
                </table>
                """
            }
        }
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r1, r2 = MagicMock(), MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        r2.status_code = 200
        r2.json.return_value = parse_mock
        mock_get.side_effect = [r1, r2]
        
        cast = get_wikipedia_cast("Rivals", 2026)
        assert cast is None

def test_get_wikipedia_cast_no_starring_label():
    search_mock = {"query": {"search": [{"title": "Rivals"}]}}
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Directed by</th>
                        <td class="infobox-data">Alex</td>
                    </tr>
                </table>
                """
            }
        }
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r1, r2 = MagicMock(), MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        r2.status_code = 200
        r2.json.return_value = parse_mock
        mock_get.side_effect = [r1, r2]
        
        cast = get_wikipedia_cast("Rivals", 2026)
        assert cast is None

def test_get_wikipedia_cast_li_list():
    search_mock = {"query": {"search": [{"title": "Rivals"}]}}
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Starring</th>
                        <td class="infobox-data">
                            <ul>
                                <li>Alex Hassell</li>
                                <li>David Tennant</li>
                            </ul>
                        </td>
                    </tr>
                </table>
                """
            }
        }
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r1, r2 = MagicMock(), MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        r2.status_code = 200
        r2.json.return_value = parse_mock
        mock_get.side_effect = [r1, r2]
        
        cast = get_wikipedia_cast("Rivals", 2026, is_tv=True)
        assert cast == "Alex Hassell, David Tennant"

def test_get_wikipedia_cast_plain_text():
    search_mock = {"query": {"search": [{"title": "Rivals"}]}}
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Starring</th>
                        <td class="infobox-data">Alex Hassell, David Tennant</td>
                    </tr>
                </table>
                """
            }
        }
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r1, r2 = MagicMock(), MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        r2.status_code = 200
        r2.json.return_value = parse_mock
        mock_get.side_effect = [r1, r2]
        
        cast = get_wikipedia_cast("Rivals", 2026, is_tv=True)
        assert cast == "Alex Hassell, David Tennant"

def test_get_wikipedia_cast_failures():
    # 1. Non-200 search status
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        assert get_wikipedia_cast("Rivals", 2026) is None

    # 2. Empty search results
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"query": {"search": []}}
        mock_get.return_value = r
        assert get_wikipedia_cast("Rivals", 2026) is None

    # 3. Non-200 parse status
    with patch("core.enricher.enricher_session.get") as mock_get:
        r1 = MagicMock()
        r1.status_code = 200
        r1.json.return_value = {"query": {"search": [{"title": "Rivals"}]}}
        r2 = MagicMock()
        r2.status_code = 500
        mock_get.side_effect = [r1, r2]
        assert get_wikipedia_cast("Rivals", 2026) is None

    # 4. Exception raised during request
    with patch("core.enricher.enricher_session.get", side_effect=Exception("Network down")):
        assert get_wikipedia_cast("Rivals", 2026) is None

def test_enrich_tv_show_tvmaze_success():
    maze_mock = {
        "genres": ["Drama", "Thriller"],
        "summary": "<p>A story about rivals.</p>",
        "image": {"medium": "http://tvmaze/medium.jpg"},
        "externals": {"thetvdb": 11111},
        "network": {"name": "Hulu"},
        "rating": {"average": 8.2},
        "_embedded": {
            "cast": [
                {"person": {"name": "Actor A"}},
                {"person": {"name": "Actor B"}},
                {"person": {}} # Missing name to test branch
            ]
        }
    }
    
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = maze_mock
        mock_get.return_value = r
        
        data = enrich_tv_show("Rivals", 2026)
        assert data["genres"] == ["Drama", "Thriller"]
        assert data["plot"] == "A story about rivals."
        assert data["poster_url"] == "http://tvmaze/medium.jpg"
        assert data["tvdbId"] == 11111
        assert data["network"] == "Hulu"
        assert data["rating_imdb"] == "8.2"
        assert data["cast"] == "Actor A, Actor B"

def test_enrich_tv_show_webchannel_and_failures():
    # Test webChannel fallback + image original fallback
    maze_mock = {
        "summary": None,
        "image": {"original": "http://tvmaze/original.jpg"},
        "webChannel": {"name": "Netflix"}
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = maze_mock
        mock_get.return_value = r
        
        data = enrich_tv_show("Rivals", 2026)
        assert data["network"] == "Netflix"
        assert data["poster_url"] == "http://tvmaze/original.jpg"
        assert data["plot"] == ""

    # Test missing image and missing network/webChannel
    maze_mock_empty = {
        "summary": ""
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = maze_mock_empty
        mock_get.return_value = r
        
        data = enrich_tv_show("Rivals", 2026)
        assert data["network"] == "Unknown Network"
        assert data["poster_url"] == ""

    # Test request failure fallback
    with patch("core.enricher.enricher_session.get", side_effect=Exception("TVMaze offline")):
        data = enrich_tv_show("Rivals", 2026)
        assert data["network"] == "Unknown Network"
        assert data["plot"] == "No plot summary available."

def test_enrich_tv_show_sonarr_sync():
    sonarr = MagicMock(spec=SonarrClient)
    sonarr.base_url = "http://sonarr:8989"
    sonarr.api_key = "sonarr_key"
    
    # 1. Test Sonarr match by year and title lookup
    lookup_mock = [
        {
            "title": "Rivals",
            "year": 2026,
            "id": 12,
            "tvdbId": 11111,
            "imdbId": "tt111111",
            "genres": ["Drama"],
            "overview": "Sonarr overview text description.",
            "ratings": {"value": 8.0},
            "images": [
                {"coverType": "banner", "remoteUrl": "http://remote/banner.jpg"}, # Not a poster coverType
                {"coverType": "poster", "remoteUrl": "http://remote/poster.jpg"}
            ]
        }
    ]
    sonarr.lookup_series.return_value = lookup_mock
    
    # Mock requests.get (TVMaze returns empty/404)
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["is_in_library"] is True
        assert data["imdbId"] == "tt111111"
        assert data["genres"] == ["Drama"]
        assert data["plot"] == "Sonarr overview text description."
        assert data["rating_imdb"] == "8.0"
        assert data["poster_url"] == "http://remote/poster.jpg"

    # 2. Test relative image path resolution with API keys (checks for ? in url parameter separator)
    lookup_mock_relative_img = [
        {
            "title": "Rivals",
            "year": 2025, # Different year but matching title
            "images": [
                {"coverType": "poster", "url": "/api/v3/media/12.jpg?width=250"}
            ]
        }
    ]
    sonarr.lookup_series.return_value = lookup_mock_relative_img
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["poster_url"] == "http://sonarr:8989/api/v3/media/12.jpg?width=250&apikey=sonarr_key"

    # 2b. Test relative image url with missing url attribute or empty cover image list
    lookup_mock_missing_img_url = [
        {
            "title": "Rivals",
            "year": 2025,
            "images": [
                {"coverType": "poster"} # Missing url
            ]
        }
    ]
    sonarr.lookup_series.return_value = lookup_mock_missing_img_url
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["poster_url"] == ""

    # 3. Test absolute fallback image url resolution (url starts with http)
    lookup_mock_absolute_img = [
        {
            "title": "Rivals",
            "year": 2025,
            "images": [
                {"coverType": "poster", "url": "http://other-site/cover.jpg"}
            ]
        }
    ]
    sonarr.lookup_series.return_value = lookup_mock_absolute_img
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["poster_url"] == "http://other-site/cover.jpg"

    # 3b. Test Sonarr client returns no matches (evaluates if best_match is None)
    sonarr.lookup_series.return_value = []
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["poster_url"] == ""

    # 3c. Test Sonarr client returns matches, but none have matching year or title (takes first fallback)
    lookup_mock_first_fallback = [
        {
            "title": "Other Title",
            "year": 2000,
            "tvdbId": 999
        }
    ]
    sonarr.lookup_series.return_value = lookup_mock_first_fallback
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["tvdbId"] == 999

    # 4. Test Sonarr lookup raising ArrAPIError
    sonarr.lookup_series.side_effect = ArrAPIError("Sonarr error")
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["is_in_library"] is False

def test_enrich_tv_show_wikipedia_cast_fallback():
    # If cast is still missing, trigger Wikipedia search for cast
    with patch("core.enricher.enricher_session.get") as mock_get:
        r_maze = MagicMock()
        r_maze.status_code = 404
        
        # Wikipedia search & parse mock
        r_wiki_search = MagicMock()
        r_wiki_search.status_code = 200
        r_wiki_search.json.return_value = {"query": {"search": [{"title": "Rivals"}]}}
        
        r_wiki_parse = MagicMock()
        r_wiki_parse.status_code = 200
        r_wiki_parse.json.return_value = {
            "parse": {
                "text": {"*": '<th class="infobox-label">Starring</th><td class="infobox-data">Alex, David</td>'}
            }
        }
        mock_get.side_effect = [r_maze, r_wiki_search, r_wiki_parse]
        
        data = enrich_tv_show("Rivals", 2026)
        assert data["cast"] == "Alex, David"

def test_enrich_movie_radarr_sync():
    radarr = MagicMock(spec=RadarrClient)
    radarr.base_url = "http://radarr:7878"
    radarr.api_key = "radarr_key"
    
    # 1. Test Radarr lookup by IMDb ID
    lookup_mock_imdb = [
        {
            "title": "Gladiator II",
            "year": 2024,
            "tmdbId": 12345,
            "imdbId": "tt1234567",
            "genres": ["Action", "History"],
            "overview": "Rome Gladiator movie.",
            "studio": "Paramount",
            "id": 5,
            "images": [
                {"coverType": "poster", "remoteUrl": "http://remote/gladiator.jpg"}
            ],
            "ratings": {
                "imdb": {"value": 7.5},
                "metacritic": {"value": 64.0},
                "rottenTomatoes": {"value": 78.0}
            },
            "youTubeTrailerId": "trailer_id"
        }
    ]
    radarr.lookup_movie.return_value = lookup_mock_imdb
    
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "Paul Mescal", "director": "Ridley Scott", "producer": "Douglas Wick"}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr, imdb_id="tt1234567")
        assert data["is_in_library"] is True
        assert data["tmdbId"] == 12345
        assert data["imdbId"] == "tt1234567"
        assert data["genres"] == ["Action", "History"]
        assert data["plot"] == "Rome Gladiator movie."
        assert data["network"] == "Paramount"
        assert data["poster_url"] == "http://remote/gladiator.jpg"
        assert data["rating_imdb"] == "7.5"
        assert data["rating_metacritic"] == "64"
        assert data["rating_rt"] == "78"
        assert data["trailer"] == "https://www.youtube.com/watch?v=trailer_id"
        assert data["cast"] == "Paul Mescal"
        assert data["director"] == "Ridley Scott"
        assert data["producer"] == "Douglas Wick"

    # 2. Test Radarr lookup by title fallback, relative poster image cover, and ArrAPIError handling
    lookup_mock_title = [
        {
            "title": "Gladiator II",
            "year": 2024,
            "images": [
                {"coverType": "poster", "url": "/api/v3/media/5.jpg"}
            ]
        }
    ]
    radarr.lookup_movie.side_effect = [None, lookup_mock_title] # First IMDb fails, fallback to title search succeeds
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "", "director": "", "producer": ""}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr, imdb_id="tt1234567")
        assert data["poster_url"] == "http://radarr:7878/api/v3/media/5.jpg?apikey=radarr_key"

    # 2b. Test Radarr relative poster url image resolution with missing URL parameters
    lookup_mock_relative_no_params = [
        {
            "title": "Gladiator II",
            "year": 2024,
            "images": [
                {"coverType": "poster", "url": "/api/v3/media/5.jpg?width=250"}
            ]
        }
    ]
    radarr.lookup_movie.side_effect = [None, lookup_mock_relative_no_params]
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "", "director": "", "producer": ""}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr, imdb_id="tt1234567")
        assert data["poster_url"] == "http://radarr:7878/api/v3/media/5.jpg?width=250&apikey=radarr_key"

    # 3. Test absolute cover url starting with http, and no title matching returns first result
    lookup_mock_no_year_match = [
        {
            "title": "Gladiator I",
            "year": 2000,
            "images": [
                {"coverType": "poster", "url": "http://other-site/cover.jpg"}
            ]
        }
    ]
    # Reset mock call side effects
    radarr.lookup_movie.side_effect = None
    radarr.lookup_movie.return_value = lookup_mock_no_year_match
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "", "director": "", "producer": ""}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr)
        assert data["poster_url"] == "http://other-site/cover.jpg"

    # 3b. Test Radarr lookup returns empty results
    radarr.lookup_movie.return_value = []
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "", "director": "", "producer": ""}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr)
        assert data["poster_url"] == ""

    # 4. Test Radarr raising ArrAPIError
    radarr.lookup_movie.side_effect = ArrAPIError("Radarr lookup error")
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "", "director": "", "producer": ""}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr)
        assert data["is_in_library"] is False

def test_enrich_tv_show_skip_poster_when_already_populated():
    sonarr = MagicMock(spec=SonarrClient)
    sonarr.lookup_series.return_value = [{
        "title": "Rivals",
        "year": 2026,
        "images": [{"coverType": "poster", "remoteUrl": "http://sonarr/poster.jpg"}]
    }]
    # TVMaze returns a poster:
    maze_mock = {
        "image": {"medium": "http://tvmaze/medium.jpg"},
    }
    with patch("core.enricher.enricher_session.get") as mock_get:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = maze_mock
        mock_get.return_value = r
        
        # When calling enrich_tv_show, TVMaze will populate data["poster_url"].
        # Sonarr lookup will find the show, but since data["poster_url"] is already populated,
        # it will NOT run the poster extraction loop from Sonarr images.
        data = enrich_tv_show("Rivals", 2026, sonarr_client=sonarr)
        assert data["poster_url"] == "http://tvmaze/medium.jpg"

def test_enrich_movie_no_radarr_client():
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "Some Cast", "director": "Some Director", "producer": "Some Producer"}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=None)
        assert data["is_in_library"] is False
        assert data["cast"] == "Some Cast"
        assert data["director"] == "Some Director"
        assert data["producer"] == "Some Producer"

def test_enrich_movie_images_edge_cases():
    radarr = MagicMock(spec=RadarrClient)
    radarr.base_url = "http://radarr:7878"
    radarr.api_key = "radarr_key"
    
    # Test cases:
    # 1. Non-poster image type: coverType != "poster"
    # 2. Poster image type, but no remoteUrl and no url
    lookup_mock = [
        {
            "title": "Gladiator II",
            "year": 2024,
            "images": [
                {"coverType": "banner", "remoteUrl": "http://remote/banner.jpg"},
                {"coverType": "poster"} # missing remoteUrl and url
            ]
        }
    ]
    radarr.lookup_movie.return_value = lookup_mock
    with patch("core.enricher.get_wikipedia_movie_details", return_value={"cast": "", "director": "", "producer": ""}):
        data = enrich_movie("Gladiator II", 2024, radarr_client=radarr)
        assert data["poster_url"] == ""

def test_get_wikipedia_movie_details_success():
    from core.enricher import get_wikipedia_movie_details
    search_mock = {
        "query": {
            "search": [{"title": "Gladiator II"}]
        }
    }
    parse_mock = {
        "parse": {
            "text": {
                "*": """
                <table class="infobox">
                    <tr>
                        <th class="infobox-label">Directed by</th>
                        <td class="infobox-data">Ridley Scott</td>
                    </tr>
                    <tr>
                        <th class="infobox-label">Produced by</th>
                        <td class="infobox-data">Douglas Wick, Lucy Fisher</td>
                    </tr>
                    <tr>
                        <th class="infobox-label">Starring</th>
                        <td class="infobox-data">
                            <a href="/wiki/Paul_Mescal">Paul Mescal</a><br/>
                            <a href="/wiki/Pedro_Pascal">Pedro Pascal</a>
                        </td>
                    </tr>
                </table>
                """
            }
        }
    }
    
    with patch("requests.get") as mock_get:
        r1 = MagicMock()
        r1.status_code = 200
        r1.json.return_value = search_mock
        
        r2 = MagicMock()
        r2.status_code = 200
        r2.json.return_value = parse_mock
        
        mock_get.side_effect = [r1, r2]
        
        details = get_wikipedia_movie_details("Gladiator II", 2024)
        assert details["cast"] == "Paul Mescal, Pedro Pascal"
        assert details["director"] == "Ridley Scott"
        assert details["producer"] == "Douglas Wick, Lucy Fisher"

def test_get_wikipedia_movie_details_failures():
    from core.enricher import get_wikipedia_movie_details
    # Search request fails
    with patch("requests.get") as mock_get:
        r = MagicMock()
        r.status_code = 500
        mock_get.return_value = r
        details = get_wikipedia_movie_details("Gladiator II", 2024)
        assert details == {"cast": "", "director": "", "producer": ""}




def _tv_maze_response(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    return r


def test_enrich_tv_show_extracts_language_and_country():
    network = {"name": "BBC One", "country": {"code": "GB"}}
    with patch("core.enricher.enricher_session.get",
               return_value=_tv_maze_response({"language": "English", "network": network})):
        data = enrich_tv_show("Rivals", 2026)
    assert data["language"] == "English" and data["country"] == "GB"

    web = {"name": "Netflix", "country": None}
    with patch("core.enricher.enricher_session.get",
               return_value=_tv_maze_response({"language": "Korean", "network": None, "webChannel": web})):
        data = enrich_tv_show("Rivals", 2026)
    assert data["language"] == "Korean" and data["country"] == ""   # global streamer: no country

    with patch("core.enricher.enricher_session.get", return_value=_tv_maze_response({})):
        data = enrich_tv_show("Rivals", 2026)
    assert data["language"] == "" and data["country"] == ""
