import requests
import urllib.parse
from bs4 import BeautifulSoup
import re
from typing import Dict, Any, Optional

from xarrtools.client import RadarrClient, SonarrClient, ArrAPIError
from xarrtools.config import config

def clean_html(text: str) -> str:
    """Removes HTML tags from a text string."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]*>', '', text)
    # Normalize whitespaces
    return re.sub(r'\s+', ' ', clean).strip()

def get_wikipedia_cast(title: str, year: int, is_tv: bool = False) -> Optional[str]:
    """Queries Wikipedia search API to locate a page and parses the 'Starring' cast from the infobox."""
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
        res = requests.get(search_url, params=search_params, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        search_data = res.json()
        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            return None
            
        page_title = search_results[0]["title"]
        
        parse_params = {
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json"
        }
        res2 = requests.get(search_url, params=parse_params, headers=headers, timeout=10)
        if res2.status_code != 200:
            return None
            
        parse_data = res2.json()
        html = parse_data.get("parse", {}).get("text", {}).get("*", "")
        
        soup = BeautifulSoup(html, "html.parser")
        
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
                return ", ".join(names[:6]) # Return top 6 actors
    except Exception:
        pass
    return None

def enrich_tv_show(title: str, year: int, sonarr_client: Optional[SonarrClient] = None) -> Dict[str, Any]:
    """Retrieves plot, cast, genres, trailer and TVDB ID for a TV show using TVMaze and Sonarr API."""
    data = {
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
    
    # 1. Query TVMaze
    tvmaze_url = "https://api.tvmaze.com/singlesearch/shows"
    try:
        res = requests.get(tvmaze_url, params={"q": title, "embed": "cast"}, timeout=10)
        if res.status_code == 200:
            maze_data = res.json()
            data["genres"] = maze_data.get("genres", [])
            data["plot"] = clean_html(maze_data.get("summary", ""))
            
            # Extract TVMaze poster image
            if maze_data.get("image"):
                data["poster_url"] = maze_data["image"].get("medium") or maze_data["image"].get("original") or ""
                
            # Extract TVDB ID
            tvdb_id = maze_data.get("externals", {}).get("thetvdb")
            if tvdb_id:
                data["tvdbId"] = tvdb_id
                
            # Extract Network / Streaming Service
            if maze_data.get("network"):
                data["network"] = maze_data["network"].get("name", "Unknown Network")
            elif maze_data.get("webChannel"):
                data["network"] = maze_data["webChannel"].get("name", "Unknown Network")

            # Extract TVMaze rating
            if maze_data.get("rating", {}).get("average"):
                data["rating_imdb"] = str(maze_data["rating"]["average"])

            # Extract Cast
            cast_list = []
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
            lookup_results = sonarr_client.lookup_series(title)
            # Find the best year match
            best_match = None
            for item in lookup_results:
                if str(item.get("year")) == str(year) or item.get("title", "").lower() == title.lower():
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
                if (not data["plot"] or len(data["plot"]) < 50) and best_match.get("overview"):
                    data["plot"] = best_match.get("overview")
                
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
                                    elif sonarr_client:
                                        base = sonarr_client.base_url.rstrip("/")
                                        sep = "&" if "?" in url else "?"
                                        data["poster_url"] = f"{base}{url}{sep}apikey={sonarr_client.api_key}"
        except ArrAPIError:
            pass

    # 3. Fallback: Parse Wikipedia for cast if still missing
    if data["cast"] == "Cast details not available.":
        wiki_cast = get_wikipedia_cast(title, year, is_tv=True)
        if wiki_cast:
            data["cast"] = wiki_cast
            
    return data

def enrich_movie(title: str, year: int, radarr_client: Optional[RadarrClient] = None, imdb_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves plot, cast, genres, trailer and TMDB ID for a movie using Radarr and Wikipedia."""
    data = {
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
        "rating_rt": ""
    }
    
    # 1. Query Radarr lookup
    if radarr_client:
        try:
            best_match = None
            if imdb_id:
                # Search by IMDb ID
                lookup_results = radarr_client.lookup_movie(f"imdb:{imdb_id}")
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
                data["plot"] = best_match.get("overview", "")
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
                                elif radarr_client:
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

    # 2. Get Cast from Wikipedia
    wiki_cast = get_wikipedia_cast(title, year, is_tv=False)
    if wiki_cast:
        data["cast"] = wiki_cast
        
    return data
