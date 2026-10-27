from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

import xarrtools.core.tmdb as tmdb; from xarrtools import core
from xarrtools.core.enricher import enrich_movie


JWT = "eyJhbGciOiJIUzI1NiJ9.payload.signature"


def _resp(json_data=None, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {}
    if status >= 400 and status != 404:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status}")
    else:
        r.raise_for_status.return_value = None
    return r


@pytest.fixture(autouse=True)
def _reset_genre_cache():
    tmdb._genre_cache.clear()
    yield
    tmdb._genre_cache.clear()


# --- auth -------------------------------------------------------------------

def test_missing_key_raises():
    with patch("xarrtools.core.tmdb.get_api_key", return_value=""):
        with pytest.raises(tmdb.TMDBError, match="not set"):
            tmdb._get("/genre/movie/list")


def test_bearer_token_sent_as_header_and_v3_key_as_param():
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", return_value=_resp({"ok": 1})) as g:
        tmdb._get("/x", {"a": 1})
    _, kwargs = g.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {JWT}"
    assert "api_key" not in kwargs["params"]

    with patch("xarrtools.core.tmdb.get_api_key", return_value="abc123"), \
         patch.object(tmdb._session, "get", return_value=_resp({"ok": 1})) as g:
        tmdb._get("/x")
    _, kwargs = g.call_args
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["params"]["api_key"] == "abc123"


def test_unauthorized_raises_clear_error():
    with patch("xarrtools.core.tmdb.get_api_key", return_value="bad"), \
         patch.object(tmdb._session, "get", return_value=_resp(status=401)):
        with pytest.raises(tmdb.TMDBError, match="rejected"):
            tmdb._get("/x")


# --- discovery --------------------------------------------------------------

def test_discover_movies_maps_fields_and_skips_undated():
    genres = {"genres": [{"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"}]}
    page1 = {"total_pages": 1, "results": [
        {"id": 10, "title": "Big Movie", "release_date": "2026-12-25", "overview": "Plot.",
         "poster_path": "/p.jpg", "genre_ids": [28, 12], "popularity": 99.5},
        {"id": 11, "title": "No Date", "release_date": "", "overview": "x"},
    ]}

    def fake_get(url, params=None, headers=None, timeout=None):
        return _resp(genres if url.endswith("/genre/movie/list") else page1)

    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", side_effect=fake_get):
        items = tmdb.discover_movies(datetime(2026, 11, 1), datetime(2027, 1, 1))

    assert len(items) == 1
    m = items[0]
    assert m["title"] == "Big Movie" and m["tmdbId"] == 10
    assert m["date_obj"] == datetime(2026, 12, 25) and m["date_str"] == "Dec 25, 2026"
    assert m["poster_url"] == "https://image.tmdb.org/t/p/w500/p.jpg"
    assert m["genres"] == ["Action", "Adventure"]
    assert m["href"] == "https://www.themoviedb.org/movie/10"
    assert m["is_returning"] is False


# --- enrichment -------------------------------------------------------------

DETAILS = {
    "id": 10, "imdb_id": "tt100", "overview": "TMDB plot.", "poster_path": "/p.jpg",
    "genres": [{"id": 28, "name": "Action"}],
    "production_companies": [{"name": "Acme Pictures"}],
    "credits": {
        "cast": [{"name": f"Actor {i}"} for i in range(12)],
        "crew": [
            {"job": "Director", "name": "Dana Director"},
            {"job": "Producer", "name": "Pat One"}, {"job": "Producer", "name": "Pat Two"},
            {"job": "Producer", "name": "Pat Three"}, {"job": "Producer", "name": "Pat Four"},
            {"job": "Editor", "name": "Ed"},
        ],
    },
    "videos": {"results": [
        {"site": "YouTube", "key": "teaser1", "type": "Teaser", "official": True},
        {"site": "YouTube", "key": "unofficial", "type": "Trailer", "official": False},
        {"site": "YouTube", "key": "official1", "type": "Trailer", "official": True},
        {"site": "Vimeo", "key": "v", "type": "Trailer", "official": True},
    ]},
}


def test_get_movie_enrichment_by_tmdb_id():
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", return_value=_resp(DETAILS)):
        out = tmdb.get_movie_enrichment("Anything", 2026, tmdb_id=10)
    assert out["tmdbId"] == 10 and out["imdbId"] == "tt100"
    assert out["plot"] == "TMDB plot."
    assert out["cast"] == ", ".join(f"Actor {i}" for i in range(8))  # top 8
    assert out["director"] == "Dana Director"
    assert out["producer"] == "Pat One, Pat Two, Pat Three"  # top 3 producers
    assert out["studio"] == "Acme Pictures"
    assert out["genres"] == ["Action"]
    assert out["trailer"] == "https://www.youtube.com/watch?v=official1"  # official trailer preferred
    assert out["poster_url"].endswith("/p.jpg")


def test_search_requires_matching_title_and_falls_back_on_year():
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/search/movie" in url:
            calls.append(params.get("primary_release_year"))
            if params.get("primary_release_year") == 2025:
                return _resp({"results": [{"id": 99, "title": "Some Other Film"},
                                          {"id": 10, "title": "The Film!"}]})
            return _resp({"results": []})
        return _resp(DETAILS)

    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", side_effect=fake_get):
        out = tmdb.get_movie_enrichment("The Film", 2026)
    assert out["tmdbId"] == 10          # matched by normalized title, not first result
    assert calls[:2] == [2026, 2025]    # exact year first, then year-1


def test_enrichment_returns_none_without_key_or_on_error_or_no_match():
    with patch("xarrtools.core.tmdb.get_api_key", return_value=""):
        assert tmdb.get_movie_enrichment("X", 2026) is None
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", return_value=_resp(status=500)):
        assert tmdb.get_movie_enrichment("X", 2026, tmdb_id=1) is None
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", return_value=_resp({"results": []})):
        assert tmdb.get_movie_enrichment("Nope", 2026) is None


# --- enrich_movie integration ----------------------------------------------

def test_enrich_movie_uses_tmdb_and_skips_wikipedia_when_complete():
    tmdb_data = {"tmdbId": 10, "imdbId": "tt100", "plot": "TMDB plot.", "poster_url": "http://p",
                 "genres": ["Action"], "studio": "Acme", "trailer": "https://www.youtube.com/watch?v=abc",
                 "cast": "A, B", "director": "D", "producer": "P"}
    with patch("xarrtools.core.enricher.get_movie_enrichment", return_value=tmdb_data) as g, \
         patch("xarrtools.core.enricher.get_wikipedia_movie_details") as wiki:
        data = enrich_movie("Film", 2026, None, None, tmdb_id=10)
    assert g.call_args.kwargs["tmdb_id"] == 10
    assert data["plot"] == "TMDB plot." and data["cast"] == "A, B"
    assert data["director"] == "D" and data["producer"] == "P"
    assert data["network"] == "Acme" and data["tmdbId"] == 10 and data["imdbId"] == "tt100"
    assert data["trailer"].endswith("abc")
    wiki.assert_not_called()


def test_enrich_movie_wikipedia_fills_what_tmdb_lacks():
    with patch("xarrtools.core.enricher.get_movie_enrichment", return_value={"tmdbId": 10, "cast": "A, B"}), \
         patch("xarrtools.core.enricher.get_wikipedia_movie_details",
               return_value={"cast": "WIKI CAST", "director": "Wiki Dir", "producer": "Wiki Prod"}):
        data = enrich_movie("Film", 2026)
    assert data["cast"] == "A, B"          # TMDB wins when it has data
    assert data["director"] == "Wiki Dir"  # Wikipedia fills the gaps
    assert data["producer"] == "Wiki Prod"


def test_enrich_movie_without_tmdb_behaves_as_before():
    with patch("xarrtools.core.enricher.get_movie_enrichment", return_value=None), \
         patch("xarrtools.core.enricher.get_wikipedia_movie_details",
               return_value={"cast": "WIKI CAST", "director": "Wiki Dir", "producer": "Wiki Prod"}):
        data = enrich_movie("Film", 2026)
    assert (data["cast"], data["director"], data["producer"]) == ("WIKI CAST", "Wiki Dir", "Wiki Prod")
    assert data["network"] == "Unknown Studio"


# --- chunked discovery, language & country ---------------------------------

def _discover_fake(per_window):
    """Fake TMDB: returns the movies registered for the window's start date; records requests."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/genre/movie/list"):
            return _resp({"genres": []})
        calls.append((params["primary_release_date.gte"], params["primary_release_date.lte"], params["page"]))
        return _resp(per_window.get((params["primary_release_date.gte"], params["page"]),
                                    {"total_pages": 1, "results": []}))
    return fake_get, calls


def test_discover_movies_queries_each_window_and_dedupes():
    def movie(i, date, lang="ko"):
        return {"id": i, "title": f"M{i}", "release_date": date, "original_language": lang}

    fake, calls = _discover_fake({
        ("2026-11-01", 1): {"total_pages": 2, "results": [movie(1, "2026-11-03")]},
        ("2026-11-01", 2): {"total_pages": 2, "results": [movie(2, "2026-11-05")]},
        ("2026-11-08", 1): {"total_pages": 1, "results": [movie(1, "2026-11-03"), movie(3, "2026-11-09")]},
    })
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", side_effect=fake):
        items = tmdb.discover_movies(datetime(2026, 11, 1), datetime(2026, 11, 10))

    # two windows (Nov 1-7, Nov 8-10); first window fetched 2 pages, second stops at total_pages
    assert calls == [("2026-11-01", "2026-11-07", 1), ("2026-11-01", "2026-11-07", 2),
                     ("2026-11-08", "2026-11-10", 1)]
    assert [i["tmdbId"] for i in items] == [1, 2, 3]          # deduped, date ordered
    assert items[0]["language"] == "Korean"


def test_discover_movies_stops_on_empty_page_and_respects_page_limit():
    fake, calls = _discover_fake({})
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", side_effect=fake):
        assert tmdb.discover_movies(datetime(2026, 11, 1), datetime(2026, 11, 3)) == []
    assert len(calls) == 1   # empty results -> no second page requested

    many = {("2026-11-01", p): {"total_pages": 9, "results": [
        {"id": p, "title": f"T{p}", "release_date": "2026-11-02"}]} for p in range(1, 10)}
    fake, calls = _discover_fake(many)
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", side_effect=fake):
        items = tmdb.discover_movies(datetime(2026, 11, 1), datetime(2026, 11, 3), pages_per_chunk=3)
    assert len(calls) == 3 and len(items) == 3


def test_movie_enrichment_returns_language_and_country():
    details = dict(DETAILS, original_language="fr", origin_country=["FR", "BE"])
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", return_value=_resp(details)):
        out = tmdb.get_movie_enrichment("Anything", 2026, tmdb_id=10)
    assert out["language"] == "French" and out["country"] == "FR"

    details = dict(DETAILS, original_language="xx",
                   production_countries=[{"iso_3166_1": "jp"}])
    with patch("xarrtools.core.tmdb.get_api_key", return_value=JWT), \
         patch.object(tmdb._session, "get", return_value=_resp(details)):
        out = tmdb.get_movie_enrichment("Anything", 2026, tmdb_id=10)
    assert not out.get("language") and out["country"] == "JP"   # falls back to production countries


def test_enrich_movie_copies_language_and_country_from_tmdb():
    with patch("xarrtools.core.enricher.get_movie_enrichment",
               return_value={"tmdbId": 10, "language": "Japanese", "country": "JP"}), \
         patch("xarrtools.core.enricher.get_wikipedia_movie_details", return_value={}):
        data = enrich_movie("Film", 2026)
    assert data["language"] == "Japanese" and data["country"] == "JP"

    with patch("xarrtools.core.enricher.get_movie_enrichment", return_value=None), \
         patch("xarrtools.core.enricher.get_wikipedia_movie_details", return_value={}):
        data = enrich_movie("Film", 2026)
    assert data["language"] == "" and data["country"] == ""


# --- locales ----------------------------------------------------------------

def test_locales_helpers():
    from xarrtools.core.locales import country_code, language_name
    assert language_name("en") == "English" and language_name("KO") == "Korean"
    assert language_name("Korean") == "Korean"
    assert language_name("zz") == "Zz" and language_name(None) == "" and language_name("") == ""
    assert country_code("us") == "US" and country_code(" gb ") == "GB"
    assert country_code("USA") == "" and country_code(None) == "" and country_code("") == ""
