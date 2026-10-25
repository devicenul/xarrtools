import pytest
import requests
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from core.scraper import (
    parse_date,
    parse_dvd_date,
    clean_movie_title,
    is_tv_series,
    normalize_title,
    scrape_new_releases,
    scrape_dvds_releases,
    merge_movie_lists,
    get_discoveries
)

class MockDatetime(datetime):
    @classmethod
    def now(cls):
        return datetime(2026, 12, 20)

def test_parse_date():
    assert parse_date("May 22, 2026") == datetime(2026, 5, 22)
    assert parse_date("May 2026") == datetime(2026, 5, 1)
    assert parse_date("Invalid Date") == datetime(1900, 1, 1)

def test_parse_dvd_date():
    assert parse_dvd_date("Tuesday May 5, 2026") == datetime(2026, 5, 5)
    assert parse_dvd_date("May 5, 2026") == datetime(2026, 5, 5)
    assert parse_dvd_date("Tuesday, May 5, 2026") == datetime(2026, 5, 5)
    assert parse_dvd_date("2026-05-05") == datetime(2026, 5, 5)
    assert parse_dvd_date("Released in May 2026") == datetime(2026, 5, 1)
    assert parse_dvd_date("Unknown Date String") == datetime(1900, 1, 1)
    # Test regex month match value error (invalid date number inside month fallback)
    assert parse_dvd_date("Released in May 0000") == datetime(1900, 1, 1)

def test_clean_movie_title():
    assert clean_movie_title("Gladiator II DVD") == "Gladiator II"
    assert clean_movie_title("Gladiator II Blu-ray") == "Gladiator II"
    assert clean_movie_title("Gladiator II BluRay") == "Gladiator II"
    assert clean_movie_title("Gladiator II 4K") == "Gladiator II"
    assert clean_movie_title("Gladiator II 3D") == "Gladiator II"
    assert clean_movie_title("Gladiator II Steelbook") == "Gladiator II"
    assert clean_movie_title("Gladiator II [Digital]") == "Gladiator II"
    assert clean_movie_title("Gladiator II (4K Ultra HD)") == "Gladiator II"
    assert clean_movie_title("Gladiator II (Blu-ray + DVD)") == "Gladiator II"
    assert clean_movie_title("The Movie (2024)") == "The Movie"
    assert clean_movie_title("Gladiator II") == "Gladiator II"

def test_is_tv_series():
    assert is_tv_series("Friends Season 10") is True
    assert is_tv_series("Rivals Series") is True
    assert is_tv_series("Breaking Bad Complete Episodes") is True
    assert is_tv_series("The Movie") is False

def test_normalize_title():
    assert normalize_title("The-Movie, Part 2!") == "themoviepart2"
    assert normalize_title("Gladiator II [Digital]", is_tv=False) == "gladiatorii"
    assert normalize_title("Gladiator II (Blu-ray + DVD)", is_tv=False) == "gladiatorii"

def test_scrape_new_releases_success():
    mock_html = """
    <div data-testid="filter-results">
        <a href="/tv/rivals/season-2/">Rivals: Season 2</a>
        <h3 data-testid="product-title">Rivals</h3>
        <div class="relative max-w-full flex flex-col">
            <span>May 22, 2026 • Rating TV-MA</span>
            <div class="line-clamp-2">A great TV show.</div>
        </div>
    </div>
    <div data-testid="filter-results">
        <a href="/tv/newshow/">New Show</a>
        <h3 data-testid="product-title">New Show</h3>
        <div class="relative max-w-full flex flex-col">
            <span>May 2026</span>
            <span>A short span.</span>
        </div>
    </div>
    <div data-testid="filter-results">
        <!-- Missing title span and div class, but contains spans > 1 to test short description reset -->
        <a href="/tv/missing/">Missing</a>
        <div class="relative max-w-full flex flex-col">
            <span>Short Desc</span>
            <span>Short</span>
        </div>
    </div>
    <div data-testid="filter-results">
        <!-- Contains spans > 1 to test long description (>= 15) -->
        <a href="/tv/longdesc/">Long Desc</a>
        <div class="relative max-w-full flex flex-col">
            <span>May 2026</span>
            <span>This description is longer than fifteen characters.</span>
        </div>
    </div>
    <div data-testid="filter-results">
        <!-- Contains only 1 span to test len(spans) > 1 is False branch -->
        <a href="/tv/onespan/">One Span</a>
        <div class="relative max-w-full flex flex-col">
            <span>May 2026</span>
        </div>
    </div>
    <div data-testid="filter-results">
        <!-- Keyword show to test is_returning from title keywords (season two) -->
        <a href="/tv/keywordshow/">Keyword Show</a>
        <h3 data-testid="product-title">Keyword Show season two</h3>
    </div>
    <div data-testid="filter-results">
        <!-- Missing text_container -->
        <a href="/tv/nocontainer/">No Container</a>
        <h3 data-testid="product-title">No Container</h3>
    </div>
    <div data-testid="filter-results">
        <!-- Missing link tag -->
    </div>
    """
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_get.return_value = mock_resp
        
        # Test TV Scraper
        results = scrape_new_releases("http://metacritic-mock", is_tv=True)
        
        assert len(results) == 7
        assert results[0]["title"] == "Rivals"
        assert results[0]["is_returning"] is True
        assert results[0]["date_obj"] == datetime(2026, 5, 22)
        
        assert results[1]["title"] == "New Show"
        assert results[1]["is_returning"] is False
        assert results[1]["date_obj"] == datetime(2026, 5, 1)
        
        assert results[2]["title"] == "Unknown"
        assert results[2]["description"] == "No plot summary available."
        
        assert results[3]["title"] == "Unknown"
        assert results[3]["description"] == "This description is longer than fifteen characters."
        
        assert results[4]["title"] == "Unknown"
        assert results[4]["description"] == "No plot summary available."
        
        assert results[5]["title"] == "Keyword Show"
        assert results[5]["is_returning"] is True
        
        assert results[6]["title"] == "No Container"
        assert results[6]["description"] == "No plot summary available."

        # Test Movie Scraper
        results_movies = scrape_new_releases("http://metacritic-mock", is_tv=False)
        assert len(results_movies) == 7
        assert results_movies[0]["is_returning"] is False

def test_scrape_new_releases_http_error():
    with patch("requests.get", side_effect=requests.exceptions.RequestException("Conn error")):
        results = scrape_new_releases("http://metacritic-mock")
        assert results == []

def test_scrape_dvds_releases_success():
    mock_html = """
    <table class="fieldtable-inner">
        <tr>
            <td class="reldate">Tuesday May 5, 2026 (DVD)</td>
        </tr>
        <tr>
            <td class="dvdcell">
                <a style="color:#000;" href="/movies/test-movie-dvd">Test Movie DVD</a>
                <a href="https://www.imdb.com/title/tt1234567/">IMDb</a>
            </td>
        </tr>
        <tr>
            <td class="dvdcell">
                <!-- Fallback link search (no color style) -->
                <a href="/movies/fallback-movie">Fallback Movie</a>
            </td>
        </tr>
        <tr>
            <td class="dvdcell">
                <!-- DVD link containing tag name to test filtering out DVD/Blu-ray -->
                <a href="/movies/dvd-text">DVD</a>
                <a href="/movies/valid-movie">Valid Movie</a>
            </td>
        </tr>
        <tr>
            <td class="dvdcell">
                <!-- IMDb link with missing tt ID -->
                <a href="/movies/no-imdb-match">No IMDb Match</a>
                <a href="https://www.imdb.com/title/invalid_id/">IMDb</a>
            </td>
        </tr>
        <tr>
            <td class="dvdcell">
                <!-- Should skip TV series -->
                <a style="color:#000;" href="/movies/friends-season-1">Friends Season 1</a>
            </td>
        </tr>
        <tr>
            <td class="dvdcell">
                <!-- No link cell -->
                <span>No title link</span>
            </td>
        </tr>
    </table>
    """
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_get.return_value = mock_resp
        
        movies = scrape_dvds_releases(2026, 5)
        assert len(movies) == 4
        assert movies[0]["title"] == "Test Movie"
        assert movies[0]["imdbId"] == "tt1234567"
        assert movies[0]["date_obj"] == datetime(2026, 5, 5)
        
        assert movies[1]["title"] == "Fallback Movie"
        assert movies[1]["imdbId"] is None

        assert movies[2]["title"] == "Valid Movie"
        assert movies[3]["title"] == "No IMDb Match"
        assert movies[3]["imdbId"] is None

def test_scrape_dvds_releases_non_200():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        
        movies = scrape_dvds_releases(2026, 5)
        assert movies == []

def test_scrape_dvds_releases_exception():
    with patch("requests.get", side_effect=requests.exceptions.RequestException()):
        movies = scrape_dvds_releases(2026, 5)
        assert movies == []

def test_merge_movie_lists():
    meta = [
        {"title": "Movie A", "date_obj": datetime(2026, 5, 5), "date_str": "May 5, 2026", "imdbId": None},
        {"title": "Movie B", "date_obj": datetime(1900, 1, 1), "date_str": "Unknown", "imdbId": "tt0000002"},
        {"title": "Movie D", "date_obj": datetime(2026, 5, 5), "date_str": "May 5, 2026", "imdbId": "tt0000004"}
    ]
    dvd = [
        {"title": "Movie A", "date_obj": datetime(2026, 5, 6), "date_str": "May 6, 2026", "imdbId": "tt0000001"},
        {"title": "Movie B", "date_obj": datetime(1901, 5, 10), "date_str": "May 10, 1901", "imdbId": None},
        {"title": "Movie C", "date_obj": datetime(2026, 5, 20), "date_str": "May 20, 2026", "imdbId": "tt0000003"},
        {"title": "Movie D", "date_obj": datetime(2026, 5, 6), "date_str": "May 6, 2026", "imdbId": "tt0000004"} # item.get("imdbId") matches match.get("imdbId")
    ]
    
    merged = merge_movie_lists(meta, dvd)
    
    assert len(merged) == 4
    # Movie A merged IMDb ID
    movie_a = [m for m in merged if m["title"] == "Movie A"][0]
    assert movie_a["imdbId"] == "tt0000001"
    
    # Movie B merged date_obj
    movie_b = [m for m in merged if m["title"] == "Movie B"][0]
    assert movie_b["date_obj"] == datetime(1901, 5, 10)
    assert movie_b["date_str"] == "May 10, 1901"
    
    # Movie C added
    movie_c = [m for m in merged if m["title"] == "Movie C"][0]
    assert movie_c["imdbId"] == "tt0000003"

def test_get_discoveries():
    # Set current date to Dec 20, 2026 to cover December spanning (current.month == 12 branch)
    fixed_now = datetime(2026, 12, 20)
    
    mock_tv = [
        {"title": "TV 1", "date_obj": datetime(2026, 12, 15), "date_str": "Dec 15, 2026", "description": "Desc 1", "is_returning": False, "href": ""},
        {"title": "TV 2", "date_obj": datetime(2026, 12, 25), "date_str": "Dec 25, 2026", "description": "Desc 2", "is_returning": False, "href": ""},
        {"title": "TV 3", "date_obj": datetime(2027, 1, 5), "date_str": "Jan 5, 2027", "description": "Desc 3", "is_returning": False, "href": ""}
    ]
    mock_movies = [
        {"title": "Movie 1", "date_obj": datetime(2026, 12, 18), "date_str": "Dec 18, 2026", "description": "Desc 1", "is_returning": False, "href": ""},
    ]
    
    with patch("core.scraper.scrape_new_releases") as mock_scrape_new, \
         patch("core.scraper.scrape_dvds_releases") as mock_scrape_dvd, \
         patch("core.scraper.safe_fetch_feed", return_value=""), \
         patch("core.scraper.scrape_tvmaze_schedule", return_value=[]), \
         patch("core.scraper.datetime", MockDatetime):
         
        # Scrape new releases returns mock_tv and mock_movies
        mock_scrape_new.side_effect = lambda url, is_tv=True, **kw: mock_tv if is_tv else mock_movies
        mock_scrape_dvd.return_value = [] # mock dvd releases empty
        
        # Ranges spans 10 days in past (Dec 10) and 20 days in future (Jan 9, 2027) which spans December
        tv, movies = get_discoveries(past_days=10, future_days=20)
        
        assert len(tv) == 3
        assert tv[0]["title"] == "TV 3" # Jan 5, 2027 (newest first)
        assert tv[1]["title"] == "TV 2"
        assert tv[2]["title"] == "TV 1"
        
        assert len(movies) == 1
        assert movies[0]["title"] == "Movie 1"

        # Test negative ranges to cover the loop bypass and equal year/month branch (284->289 False)
        tv_neg, movies_neg = get_discoveries(past_days=-5, future_days=-10)
        assert tv_neg == []

def test_custom_feed_url_discovery():
    # Mock SQLite DB, requests, and safe_fetch_feed
    mock_feed = {
        "id": 1,
        "name": "Custom JSON Feed",
        "url": "my-feed.local/json",
        "feed_type": "json",
        "enabled": 1,
        "http_headers": '{"Authorization": "Bearer token"}',
        "parser_config": '{"item_selector": "items", "mappings": {"title": {"selector": "title"}}}',
        "default_media_type": "movie"
    }
    
    with patch("core.db.get_db_connection") as mock_conn_func, \
         patch("core.scraper.safe_fetch_feed") as mock_fetch, \
         patch("core.scraper.requests.get") as mock_req_get:
         
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn_func.return_value = mock_conn
        
        # SQLite table check returns custom_feeds table exists, and then returns mock_feed
        mock_cursor.fetchone.return_value = ("custom_feeds",)
        mock_cursor.fetchall.return_value = [mock_feed]
        
        # First test_url (https://my-feed.local/json) fails, second (http) succeeds,
        # third (the actual fetch during processing) also succeeds.
        mock_fetch.side_effect = [
            ValueError("Private range or connection failure"), # https fails
            '{"items": [{"title": "My Discovered Movie"}]}',   # http succeeds
            '{"items": [{"title": "My Discovered Movie"}]}'    # actual fetch succeeds
        ]
        
        tv, movies = get_discoveries(past_days=100, future_days=100)
        
        # Check that we performed the update query
        mock_cursor.execute.assert_any_call(
            "UPDATE custom_feeds SET url = ? WHERE id = ?",
            ("http://my-feed.local/json", 1)
        )
        assert len(movies) == 1
        assert movies[0]["title"] == "My Discovered Movie"




def test_scrape_tvmaze_schedule_filters_and_maps():
    from core.scraper import scrape_tvmaze_schedule

    def ep(show_id, name, airdate, number, type_="regular", season=1, stype="Scripted", lang="English"):
        return {
            "airdate": airdate, "number": number, "season": season, "type": type_,
            "summary": "<p>ep</p>",
            "_embedded": {"show": {
                "id": show_id, "name": name, "type": stype, "language": lang,
                "premiered": "2026-12-01", "url": f"https://tvmaze/{show_id}",
                "summary": "<p>Plot <b>text</b></p>", "genres": ["Drama"],
                "externals": {"imdb": f"tt{show_id}", "thetvdb": show_id},
                "network": {"name": "NBC", "country": {"code": "us"}}, "webChannel": None,
            }},
        }

    payload = [
        ep(1, "New Series", "2026-12-01", 1),                      # series premiere -> kept
        ep(1, "New Series", "2026-12-08", 2),                      # later episode -> ignored
        ep(2, "Returning Show", "2026-12-03", 1, season=3),        # season premiere -> returning
        ep(3, "Holiday Special", "2026-12-24", 5, "significant_special"),  # special -> kept
        ep(4, "Big Game", "2026-12-05", 1, stype="Sports"),        # excluded type
        ep(5, "Foreign Show", "2026-12-06", 1, lang="Russian"),    # excluded language
        ep(6, "Too Late", "2027-06-01", 1),                        # outside window
    ]
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    with patch("core.scraper.requests.get", return_value=resp):
        items = scrape_tvmaze_schedule("https://api.tvmaze.com/schedule/full",
                                       datetime(2026, 11, 25), datetime(2027, 1, 31))
    by_title = {i["title"]: i for i in items}
    assert set(by_title) == {"New Series", "Returning Show", "Holiday Special"}
    assert by_title["New Series"]["imdbId"] == "tt1" and by_title["New Series"]["tvdbId"] == 1
    assert by_title["New Series"]["description"] == "Plot text"
    assert by_title["New Series"]["is_returning"] is False
    assert by_title["Returning Show"]["is_returning"] is True
    assert by_title["Holiday Special"]["special"] is True
    assert by_title["Holiday Special"]["network"] == "NBC"
    assert by_title["New Series"]["country"] == "US" and by_title["New Series"]["language"] == "English"


def test_get_discoveries_tmdb_feed_without_key_is_flagged_as_error_not_crash(tmp_path, monkeypatch):
    """The TMDB feed with no API key must record a clear error on the feed and not break the scan."""
    import core.db
    from core.scraper import get_discoveries
    from core.tmdb import TMDBError

    # Isolated temp database: never touch the developer's real xarrtools.db
    monkeypatch.setattr(core.db, "DB_PATH", tmp_path / "isolated.db")
    core.db.init_db()
    conn = core.db.get_db_connection()
    conn.execute("UPDATE custom_feeds SET enabled = 0")
    conn.execute("UPDATE custom_feeds SET enabled = 1 WHERE feed_type = 'tmdb_movies'")
    conn.close()

    with patch("core.tmdb._get", side_effect=TMDBError("TMDB API key is not set (Settings -> TMDB API Key)")):
        tv, movies = get_discoveries(past_days=10, future_days=10)
    assert tv == [] and movies == []

    conn = core.db.get_db_connection()
    row = conn.execute("SELECT last_status, last_error_message FROM custom_feeds WHERE feed_type = 'tmdb_movies'").fetchone()
    conn.close()
    assert row["last_status"] == "error" and "not set" in row["last_error_message"]


# --- de-duplication ----------------------------------------------------------

def _mv(title, date="2026-11-10", **extra):
    d = datetime.strptime(date, "%Y-%m-%d")
    return dict({"title": title, "date_obj": d, "date_str": d.strftime("%b %d, %Y"), "description": ""}, **extra)


def test_slug_keeps_non_latin_titles_distinct():
    from core.locales import slug
    assert slug("Οβολός") == "οβολος" and slug("Очарованные") == "очарованные"
    assert slug("Οβολός") != slug("Αλλη Ταινία")
    assert slug("Amélie") == slug("Amelie")
    assert slug("Above & Below") == slug("Above and Below")
    from core.scraper import normalize_title
    assert normalize_title("Οβολός") != normalize_title("Άλλη")


def test_dedupe_movies_non_latin_titles_not_collapsed():
    from core.scraper import dedupe_movies
    items = [_mv("Οβολός", tmdbId=1), _mv("Άλλη Ταινία", tmdbId=2), _mv("Οβολός", tmdbId=1)]
    out = dedupe_movies(items)
    assert sorted(i["tmdbId"] for i in out) == [1, 2]


def test_dedupe_movies_merges_same_film_across_sources():
    from core.scraper import dedupe_movies
    out = dedupe_movies([
        _mv("The Mandalorian and Grogu", "2026-10-13"),
        _mv("Star Wars: The Mandalorian and Grogu", "2026-10-25", tmdbId=5, language="English"),
        _mv("Above & Below", imdbId="tt1"),
        _mv("Above and Below", tmdbId=9),
        _mv("Mad Bills to Pay (or Destiny, dile que no soy malo)"),
        _mv("Mad Bills to Pay", tmdbId=7),
    ])
    assert len(out) == 3
    mando = out[0]
    assert mando["title"] == "The Mandalorian and Grogu"     # first source wins
    assert mando["tmdbId"] == 5 and mando["language"] == "English"   # gaps filled from the duplicate
    above = [i for i in out if i["title"].startswith("Above")][0]
    assert above["imdbId"] == "tt1" and above["tmdbId"] == 9


def test_dedupe_movies_keeps_distinct_films():
    from core.scraper import dedupe_movies
    out = dedupe_movies([
        _mv("The Beast", tmdbId=1), _mv("Beast", tmdbId=2),            # conflicting ids
        _mv("Heart"), _mv("The Heart of the Sea", "2026-11-12"),       # short title: no containment merge
        _mv("Dune Part Two", "2024-03-01"), _mv("Dune Part Two", "2026-03-01"),  # years too far apart
        _mv("Saw Origins Special", "2026-01-01"), _mv("Saw Origins Special Edition", "2026-09-01"),  # dates far apart
    ])
    assert len(out) == 8


def test_dedupe_movies_same_title_same_year_collapses_and_input_unmodified():
    from core.scraper import dedupe_movies
    a = _mv("Ink"); b = _mv("Ink", poster_url="http://p")
    out = dedupe_movies([a, b])
    assert len(out) == 1 and out[0]["poster_url"] == "http://p"
    assert "poster_url" not in a and "_dk" not in out[0]
