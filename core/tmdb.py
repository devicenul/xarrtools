"""Minimal TMDB (The Movie Database) client used for movie discovery and enrichment.

Supports either a v4 "API Read Access Token" (a JWT, sent as a Bearer token) or a
classic v3 API key (sent as the ``api_key`` query parameter). The credential is read
from the ``tmdb_api_key`` setting / ``TMDB_API_KEY`` environment variable.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.locales import country_code, language_name, slug

logger = logging.getLogger("xarrtools.tmdb")

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_MOVIE_URL = "https://www.themoviedb.org/movie/{id}"

_session = requests.Session()
_session.mount("https://", HTTPAdapter(
    pool_connections=5, pool_maxsize=10,
    max_retries=Retry(total=3, status_forcelist=[429, 500, 502, 503, 504],
                      backoff_factor=1.0, allowed_methods=["GET"])
))

_genre_cache: Dict[int, str] = {}


class TMDBError(Exception):
    """Raised when the TMDB API cannot be used (missing key, auth failure, HTTP error)."""


def get_api_key() -> str:
    """Returns the configured TMDB credential ('' when not set)."""
    from core.config import config
    return config.tmdb_api_key


def _is_bearer_token(key: str) -> bool:
    # v4 read access tokens are JWTs: three dot-separated base64 segments starting with 'eyJ'
    return key.startswith("eyJ") and key.count(".") == 2


def _get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
    key = get_api_key()
    if not key:
        raise TMDBError("TMDB API key is not set (Settings -> TMDB API Key)")
    params = dict(params or {})
    headers = {"Accept": "application/json"}
    if _is_bearer_token(key):
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    try:
        resp = _session.get(f"{TMDB_API_BASE}{path}", params=params, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise TMDBError(f"TMDB request failed: {e}") from e
    if resp.status_code == 401:
        raise TMDBError("TMDB rejected the API key (401 Unauthorized)")
    if resp.status_code == 404:
        return {}
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise TMDBError(f"TMDB returned an error: {e}") from e
    return resp.json()


def _norm(title: str) -> str:
    return slug(title or "")


def _genre_names(genre_ids: List[int]) -> List[str]:
    if not _genre_cache:
        for g in _get("/genre/movie/list", {"language": "en-US"}).get("genres", []):
            _genre_cache[g["id"]] = g["name"]
    return [_genre_cache[i] for i in genre_ids if i in _genre_cache]


def _discover_page(start: datetime, end: datetime, page: int) -> Dict[str, Any]:
    return _get("/discover/movie", {
        "include_adult": "false",
        "include_video": "false",
        "language": "en-US",
        "sort_by": "popularity.desc",
        "primary_release_date.gte": start.strftime("%Y-%m-%d"),
        "primary_release_date.lte": end.strftime("%Y-%m-%d"),
        "page": page,
    })


def _movie_item(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    release = r.get("release_date")
    title = (r.get("title") or "").strip()
    if not release or not title:
        return None
    try:
        date_obj = datetime.strptime(release, "%Y-%m-%d")
    except ValueError:
        return None
    poster = r.get("poster_path")
    return {
        "title": title,
        "date_obj": date_obj,
        "date_str": date_obj.strftime("%b %d, %Y"),
        "href": TMDB_MOVIE_URL.format(id=r["id"]),
        "description": (r.get("overview") or "").strip() or "No plot summary available.",
        "is_returning": False,
        "tmdbId": r["id"],
        "poster_url": f"{TMDB_IMAGE_BASE}{poster}" if poster else "",
        "genres": _genre_names(r.get("genre_ids") or []),
        "popularity": r.get("popularity", 0),
        "language": language_name(r.get("original_language")),
    }


def discover_movies(start_date: datetime, end_date: datetime, chunk_days: int = 7,
                    pages_per_chunk: int = 2) -> List[Dict[str, Any]]:
    """Returns popular movies with a primary release date in [start_date, end_date].

    The range is split into ``chunk_days`` windows and the most popular ``pages_per_chunk`` pages
    (20 movies each) are taken from every window, so a few blockbusters in one week cannot crowd
    out everything else in the range. Results are de-duplicated and sorted by release date.

    Raises TMDBError if the key is missing/invalid or TMDB is unreachable.
    """
    items: Dict[int, Dict[str, Any]] = {}
    window_start = start_date
    while window_start <= end_date:
        window_end = min(window_start + timedelta(days=chunk_days - 1), end_date)
        for page in range(1, pages_per_chunk + 1):
            data = _discover_page(window_start, window_end, page)
            results = data.get("results") or []
            for r in results:
                item = _movie_item(r)
                if item and item["tmdbId"] not in items:
                    items[item["tmdbId"]] = item
            if page >= (data.get("total_pages") or 1) or not results:
                break
        window_start = window_end + timedelta(days=1)
    return sorted(items.values(), key=lambda i: i["date_obj"])


def _find_movie_id(title: str, year: Optional[int], imdb_id: Optional[str]) -> Optional[int]:
    if imdb_id:
        found = _get(f"/find/{imdb_id}", {"external_source": "imdb_id"}).get("movie_results") or []
        if found:
            return found[0]["id"]
    wanted = _norm(title)
    years = [None]
    if year:
        years = [year, year - 1, year + 1]
    for y in years:
        params = {"query": title, "include_adult": "false", "language": "en-US"}
        if y:
            params["primary_release_year"] = y
        for r in (_get("/search/movie", params).get("results") or []):
            if _norm(r.get("title")) == wanted or _norm(r.get("original_title")) == wanted:
                return r["id"]
    return None


def get_movie_enrichment(title: str, year: Optional[int] = None, imdb_id: Optional[str] = None,
                         tmdb_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Fetches rich details for a movie. Returns None if no key is set, no match is found, or on any error.

    Result keys (only populated when TMDB has data): tmdbId, imdbId, plot, cast, director, producer,
    genres, trailer, poster_url, studio, language (original language name), country (ISO 3166 code).
    """
    if not get_api_key():
        return None
    try:
        movie_id = tmdb_id or _find_movie_id(title, year, imdb_id)
        if not movie_id:
            return None
        d = _get(f"/movie/{movie_id}", {
            "append_to_response": "credits,videos,external_ids",
            "language": "en-US",
        })
        if not d:
            return None
    except TMDBError as e:
        logger.warning("TMDB enrichment failed for %r: %s", title, e)
        return None

    out: Dict[str, Any] = {"tmdbId": d.get("id")}
    lang = language_name(d.get("original_language"))
    if lang:
        out["language"] = lang
    origin = (d.get("origin_country") or [])
    countries = origin or [c.get("iso_3166_1") for c in d.get("production_countries") or []]
    country = next((country_code(c) for c in countries if country_code(c)), "")
    if country:
        out["country"] = country
    imdb = d.get("imdb_id") or (d.get("external_ids") or {}).get("imdb_id")
    if imdb:
        out["imdbId"] = imdb
    if (d.get("overview") or "").strip():
        out["plot"] = d["overview"].strip()
    if d.get("poster_path"):
        out["poster_url"] = f"{TMDB_IMAGE_BASE}{d['poster_path']}"
    genres = [g["name"] for g in d.get("genres") or [] if g.get("name")]
    if genres:
        out["genres"] = genres
    companies = d.get("production_companies") or []
    if companies and companies[0].get("name"):
        out["studio"] = companies[0]["name"]

    credits = d.get("credits") or {}
    cast = [c["name"] for c in (credits.get("cast") or [])[:8] if c.get("name")]
    if cast:
        out["cast"] = ", ".join(cast)
    crew = credits.get("crew") or []
    directors = [c["name"] for c in crew if c.get("job") == "Director" and c.get("name")]
    if directors:
        out["director"] = ", ".join(dict.fromkeys(directors))
    producers = [c["name"] for c in crew if c.get("job") == "Producer" and c.get("name")]
    if producers:
        out["producer"] = ", ".join(list(dict.fromkeys(producers))[:3])

    videos = [v for v in (d.get("videos") or {}).get("results") or []
              if v.get("site") == "YouTube" and v.get("key")]
    trailers = [v for v in videos if v.get("type") == "Trailer"]
    # Prefer official trailers, then any trailer, then teasers
    for pool in ([v for v in trailers if v.get("official")], trailers,
                 [v for v in videos if v.get("type") == "Teaser"]):
        if pool:
            out["trailer"] = f"https://www.youtube.com/watch?v={pool[0]['key']}"
            break
    return out
