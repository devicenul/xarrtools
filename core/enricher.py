"""Metadata enrichment pipeline for TV shows and movies via external APIs and fallbacks."""

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, cast
import urllib.parse

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.client import ArrAPIError, RadarrClient, SonarrClient
from core.config import config
from core.metadata import is_cast_missing
from core.tmdb import get_movie_enrichment

logger = logging.getLogger("xarrtools.enricher")

# Global session with connection pooling and retry strategy for external metadata requests.
# Reuses TCP connections and retries idempotent requests on transient 429/5xx status codes.
enricher_session = requests.Session()
retry_strategy = Retry(
    total=4,
    status_forcelist=[429, 500, 502, 503, 504],
    backoff_factor=1.0,
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry_strategy)
enricher_session.mount("https://", adapter)
enricher_session.mount("http://", adapter)


class RateLimiter:
    """Sliding-window thread-safe rate limiter."""

    def __init__(self, calls: int, period: float) -> None:
        """Initialize the rate limiter with allowed call count and time period in seconds."""
        self.calls: int = calls
        self.period: float = period
        self.timestamps: List[float] = []
        self.lock: threading.Lock = threading.Lock()

    def wait(self) -> None:
        """Block caller until a request slot is available within the rolling time window."""
        with self.lock:
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < self.period]
            if len(self.timestamps) >= self.calls:
                sleep_time = self.period - (now - self.timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                now = time.time()
            self.timestamps.append(now)


# Rate limiters to adhere to Wikipedia (10 req/s) and TVmaze (~2 req/s) API policies
wiki_limiter: RateLimiter = RateLimiter(10, 1.0)
tvmaze_limiter: RateLimiter = RateLimiter(2, 1.0)


def clean_html(text: str) -> str:
    """Remove HTML tags from a text string and normalize whitespace."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]*>', '', text)
    # Normalize whitespaces
    return re.sub(r'\s+', ' ', clean).strip()


def get_wikipedia_cast(title: str, year: int, is_tv: bool = False) -> Optional[str]:
    """Query Wikipedia search API to locate a page and parse the 'Starring' cast from the infobox."""
    search_url = "https://en.wikipedia.org/w/api.php"
    search_query = f"{title} {year} {'TV series' if is_tv else 'film'}"

    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": search_query,
        "format": "json"
    }

    headers = {
        "User-Agent": "xarrtools/0.1.0 (mercurius@example.com)"
    }

    try:
        # Step 1: Search Wikipedia for the page title with rate limiting
        wiki_limiter.wait()
        res = enricher_session.get(search_url, params=search_params, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        search_data: Dict[str, Any] = res.json()
        search_results: List[Dict[str, Any]] = search_data.get("query", {}).get("search", [])
        if not search_results:
            return None

        page_title: str = search_results[0]["title"]

        # Step 2: Fetch and parse the page wikitext HTML
        parse_params = {
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json"
        }
        wiki_limiter.wait()
        res2 = enricher_session.get(search_url, params=parse_params, headers=headers, timeout=10)
        if res2.status_code != 200:
            return None

        parse_data: Dict[str, Any] = res2.json()
        html: str = parse_data.get("parse", {}).get("text", {}).get("*", "")

        soup = BeautifulSoup(html, "html.parser")

        # Step 3: Extract the starring actors from the infobox-label row
        starring_td = None
        for th in soup.find_all("th", class_="infobox-label"):
            if th.get_text(strip=True).lower() == "starring":
                starring_td = th.find_next_sibling("td", class_="infobox-data")
                break

        if starring_td:
            names = [a.get_text(strip=True) for a in starring_td.find_all("a")]
            if not names:
                names = [li.get_text(strip=True) for li in starring_td.find_all("li")]
            if not names:
                names = [starring_td.get_text(separator=", ", strip=True)]
            # Filter out empty strings and clean up names
            names = [n for n in names if n]
            if names:
                return ", ".join(names[:6])  # Return top 6 actors
    except Exception:
        pass
    return None


def enrich_tv_show(title: str, year: int, sonarr_client: Optional[SonarrClient] = None) -> Dict[str, Any]:
    """Retrieve plot, cast, genres, trailer and TVDB ID for a TV show using TVMaze and Sonarr API."""
    logger.debug(f"Enriching TV show: {title} ({year})")
    title = re.sub(r'\((\d{4})$', r'(\1)', title.strip()) if title else title
    base_title = re.sub(r'\s*[\(\[]\d{4}[\)\]]?$', '', title).strip() if title else ""
    data: Dict[str, Any] = {
        "language": "",
        "country": "",
        "title": title,
        "year": year,
        "plot": "No plot summary available.",
        "cast": "Cast details not available.",
        "genres": [],
        "trailer": f"https://www.youtube.com/results?search_query={urllib.parse.quote(title + ' ' + str(year) + ' tv show trailer')}",
        "tvdbId": None,
        "imdbId": None,
        "network": "Unknown Network",
        "poster_url": "",
        "is_in_library": False,
        "raw_metadata": None,
        "rating_imdb": "",
        "rating_metacritic": "",
        "rating_rt": ""
    }

    # 1. Query TVMaze singlesearch API with cast embedded
    tvmaze_url = "https://api.tvmaze.com/singlesearch/shows"
    try:
        tvmaze_limiter.wait()
        res = enricher_session.get(tvmaze_url, params={"q": title, "embed": "cast"}, timeout=10)
        if res.status_code == 200:
            maze_data: Dict[str, Any] = res.json()
            data["genres"] = maze_data.get("genres", [])
            data["plot"] = clean_html(maze_data.get("summary", ""))

            # Extract TVMaze poster image
            if maze_data.get("image"):
                data["poster_url"] = maze_data["image"].get("medium") or maze_data["image"].get("original") or ""

            # Extract TVDB ID
            tvdb_id = maze_data.get("externals", {}).get("thetvdb")
            if tvdb_id:
                data["tvdbId"] = tvdb_id

            from core.locales import country_code, language_name
            data["language"] = language_name(maze_data.get("language"))
            _net = maze_data.get("network") or maze_data.get("webChannel") or {}
            data["country"] = country_code((_net.get("country") or {}).get("code"))

            # Extract Network / Streaming Service
            if maze_data.get("network"):
                data["network"] = maze_data["network"].get("name", "Unknown Network")
            elif maze_data.get("webChannel"):
                data["network"] = maze_data["webChannel"].get("name", "Unknown Network")

            # Extract TVMaze rating
            if maze_data.get("rating", {}).get("average"):
                data["rating_imdb"] = str(maze_data["rating"]["average"])

            # Extract Cast
            cast_list: List[str] = []
            for item in maze_data.get("_embedded", {}).get("cast", [])[:5]:
                name = item.get("person", {}).get("name")
                if name:
                    cast_list.append(name)
            if cast_list:
                data["cast"] = ", ".join(cast_list)
    except Exception:
        pass

    # 2. Query Sonarr lookup to verify library status and correct metadata
    if sonarr_client:
        try:
            lookup_results: List[Dict[str, Any]] = sonarr_client.lookup_series(title)
            if not lookup_results and base_title and base_title != title:
                lookup_results = sonarr_client.lookup_series(base_title)
            # Find the best year match
            best_match: Optional[Dict[str, Any]] = None
            valid_titles = {title.lower()}
            if base_title:
                valid_titles.add(base_title.lower())
            for item in lookup_results:
                if str(item.get("year")) == str(year) or item.get("title", "").lower() in valid_titles:
                    best_match = item
                    break
            if not best_match and lookup_results:
                best_match = lookup_results[0]

            if best_match:
                data["raw_metadata"] = best_match
                if best_match.get("id"):
                    data["is_in_library"] = True
                if best_match.get("tvdbId"):
                    data["tvdbId"] = best_match.get("tvdbId")
                if best_match.get("imdbId"):
                    data["imdbId"] = best_match.get("imdbId")
                if not data["genres"] and best_match.get("genres"):
                    data["genres"] = best_match.get("genres")
                plot_str = str(data.get("plot", ""))
                if (not plot_str or len(plot_str) < 50) and best_match.get("overview"):
                    data["plot"] = best_match.get("overview")
                if (not data.get("network") or data["network"] in ("Unknown Network", "Unknown")) and best_match.get("network"):
                    data["network"] = best_match.get("network")

                # Extract Sonarr ratings
                sonarr_ratings = best_match.get("ratings", {})
                if sonarr_ratings.get("value") and not data["rating_imdb"]:
                    data["rating_imdb"] = str(sonarr_ratings["value"])

                # Try to get poster URL from Sonarr images
                if not data.get("poster_url"):
                    for img in best_match.get("images", []):
                        if img.get("coverType") == "poster":
                            remote = img.get("remoteUrl")
                            if remote:
                                data["poster_url"] = remote
                            else:
                                url = img.get("url")
                                if url:
                                    if url.startswith("http"):
                                        data["poster_url"] = url
                                    else:
                                        base = sonarr_client.base_url.rstrip("/")
                                        sep = "&" if "?" in url else "?"
                                        data["poster_url"] = f"{base}{url}{sep}apikey={sonarr_client.api_key}"
        except ArrAPIError:
            pass

    # 3. Fallback: Parse Wikipedia for cast if still missing
    if is_cast_missing(data.get("cast")):
        wiki_cast = get_wikipedia_cast(title, year, is_tv=True)
        if wiki_cast:
            data["cast"] = wiki_cast

    return data


def get_wikipedia_movie_details(title: str, year: int) -> Dict[str, str]:
    """Query Wikipedia search API to locate a page and parse Starring, Directed by, and Produced by from the infobox."""
    details: Dict[str, str] = {"cast": "", "director": "", "producer": ""}
    search_url = "https://en.wikipedia.org/w/api.php"
    search_query = f"{title} {year} film"

    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": search_query,
        "format": "json"
    }

    headers = {
        "User-Agent": "xarrtools/0.1.0 (mercurius@example.com)"
    }

    try:
        # Step 1: Search Wikipedia for the matching movie article
        res = requests.get(search_url, params=search_params, headers=headers, timeout=10)
        if res.status_code != 200:
            return details
        search_data: Dict[str, Any] = res.json()
        search_results: List[Dict[str, Any]] = search_data.get("query", {}).get("search", [])
        if not search_results:
            return details

        page_title: str = search_results[0]["title"]

        # Step 2: Parse infobox wikitext HTML
        parse_params = {
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json"
        }
        res2 = requests.get(search_url, params=parse_params, headers=headers, timeout=10)
        if res2.status_code != 200:
            return details

        parse_data: Dict[str, Any] = res2.json()
        html: str = parse_data.get("parse", {}).get("text", {}).get("*", "")

        soup = BeautifulSoup(html, "html.parser")

        # Step 3: Scan infobox rows for starring cast, director, and producer
        for th in soup.find_all("th", class_="infobox-label"):
            label_text = th.get_text(strip=True).lower()
            if label_text in ("starring", "directed by", "produced by"):
                td = th.find_next_sibling("td", class_="infobox-data")
                if td:
                    names = [a.get_text(strip=True) for a in td.find_all("a")]
                    if not names:
                        names = [li.get_text(strip=True) for li in td.find_all("li")]
                    if not names:
                        names = [td.get_text(separator=", ", strip=True)]
                    names = [n for n in names if n]
                    if label_text == "starring":
                        details["cast"] = ", ".join(names[:6])
                    elif label_text == "directed by":
                        details["director"] = ", ".join(names[:3])
                    elif label_text == "produced by":
                        details["producer"] = ", ".join(names[:3])
    except Exception:
        pass
    return details


def enrich_movie(
    title: str,
    year: int,
    radarr_client: Optional[RadarrClient] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None
) -> Dict[str, Any]:
    """Retrieve plot, cast, genres, trailer and TMDB ID for a movie using Radarr, TMDB (if keyed) and Wikipedia."""
    logger.debug(f"Enriching movie: {title} ({year})")
    data: Dict[str, Any] = {
        "language": "",
        "country": "",
        "title": title,
        "year": year,
        "plot": "No plot summary available.",
        "cast": "Cast details not available.",
        "genres": [],
        "trailer": f"https://www.youtube.com/results?search_query={urllib.parse.quote(title + ' ' + str(year) + ' movie trailer')}",
        "tmdbId": None,
        "imdbId": imdb_id,
        "network": "Unknown Studio",
        "poster_url": "",
        "is_in_library": False,
        "raw_metadata": None,
        "rating_imdb": "",
        "rating_metacritic": "",
        "rating_rt": "",
        "director": "",
        "producer": ""
    }

    # 1. Query Radarr lookup
    if radarr_client:
        try:
            best_match: Optional[Dict[str, Any]] = None
            if imdb_id:
                # Search by IMDb ID
                lookup_results: List[Dict[str, Any]] = radarr_client.lookup_movie(f"imdb:{imdb_id}")
                if lookup_results:
                    best_match = lookup_results[0]

            if not best_match:
                # Fallback to search by title
                lookup_results = radarr_client.lookup_movie(title)
                # Find best match
                for item in lookup_results:
                    if str(item.get("year")) == str(year) or item.get("title", "").lower() == title.lower():
                        best_match = item
                        break
                if not best_match and lookup_results:
                    best_match = lookup_results[0]

            if best_match:
                data["raw_metadata"] = best_match
                data["tmdbId"] = best_match.get("tmdbId")
                if best_match.get("imdbId"):
                    data["imdbId"] = best_match.get("imdbId")
                data["genres"] = best_match.get("genres", [])
                if best_match.get("overview"):
                    data["plot"] = best_match["overview"]
                data["network"] = best_match.get("studio") or "Unknown Studio"

                if best_match.get("id"):
                    data["is_in_library"] = True

                # Try to get poster URL from Radarr images
                for img in best_match.get("images", []):
                    if img.get("coverType") == "poster":
                        remote = img.get("remoteUrl")
                        if remote:
                            data["poster_url"] = remote
                        else:
                            url = img.get("url")
                            if url:
                                if url.startswith("http"):
                                    data["poster_url"] = url
                                else:
                                    base = radarr_client.base_url.rstrip("/")
                                    sep = "&" if "?" in url else "?"
                                    data["poster_url"] = f"{base}{url}{sep}apikey={radarr_client.api_key}"

                # Extract Radarr ratings
                ratings = best_match.get("ratings", {})
                if ratings.get("imdb", {}).get("value"):
                    data["rating_imdb"] = str(ratings["imdb"]["value"])
                if ratings.get("metacritic", {}).get("value"):
                    data["rating_metacritic"] = str(int(ratings["metacritic"]["value"]))
                if ratings.get("rottenTomatoes", {}).get("value"):
                    data["rating_rt"] = str(int(ratings["rottenTomatoes"]["value"]))

                yt_id = best_match.get("youTubeTrailerId")
                if yt_id:
                    data["trailer"] = f"https://www.youtube.com/watch?v={yt_id}"
        except ArrAPIError:
            pass

    # 2. Enrich from TMDB (if an API key is configured): fills gaps left by Radarr
    lookup_imdb: Optional[str] = cast(Optional[str], data.get("imdbId"))
    lookup_tmdb: Optional[int] = tmdb_id or cast(Optional[int], data.get("tmdbId"))
    tmdb = get_movie_enrichment(title, year, imdb_id=lookup_imdb, tmdb_id=lookup_tmdb)
    if tmdb:
        data["tmdbId"] = data["tmdbId"] or tmdb.get("tmdbId")
        if tmdb.get("imdbId") and not data["imdbId"]:
            data["imdbId"] = tmdb["imdbId"]
        if tmdb.get("plot") and data["plot"] == "No plot summary available.":
            data["plot"] = tmdb["plot"]
        if tmdb.get("poster_url") and not data["poster_url"]:
            data["poster_url"] = tmdb["poster_url"]
        if tmdb.get("genres") and not data["genres"]:
            data["genres"] = tmdb["genres"]
        if tmdb.get("studio") and data["network"] == "Unknown Studio":
            data["network"] = tmdb["studio"]
        if tmdb.get("trailer") and "youtube.com/results" in str(data.get("trailer", "")):
            data["trailer"] = tmdb["trailer"]
        for field in ("cast", "director", "producer"):
            if tmdb.get(field):
                data[field] = tmdb[field]
        for field in ("language", "country"):
            if tmdb.get(field) and not data.get(field):
                data[field] = tmdb[field]

    # 3. Get Cast, Director, and Producer from Wikipedia for anything still missing
    needs_wiki = (data["cast"] == "Cast details not available."
                  or not data["director"] or not data["producer"])
    wiki_details = get_wikipedia_movie_details(title, year) if needs_wiki else {}
    if wiki_details.get("cast") and data["cast"] == "Cast details not available.":
        data["cast"] = wiki_details["cast"]
    if wiki_details.get("director") and not data["director"]:
        data["director"] = wiki_details["director"]
    if wiki_details.get("producer") and not data["producer"]:
        data["producer"] = wiki_details["producer"]

    return data
