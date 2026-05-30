import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from typing import List, Dict, Any, Tuple

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Connection": "keep-alive"
}

def parse_date(date_str: str) -> datetime:
    """Parses date string like 'May 22, 2026' into a datetime object."""
    date_str = date_str.strip()
    try:
        # Expected: "May 22, 2026"
        return datetime.strptime(date_str, "%b %d, %Y")
    except ValueError:
        pass
    
    try:
        # Fallback: try "May 2026" (if exact day is missing)
        return datetime.strptime(date_str, "%b %Y")
    except ValueError:
        pass

    # Return a distant past date as a fallback to avoid crash
    return datetime(1900, 1, 1)

def parse_dvd_date(date_str: str) -> datetime:
    """Parses date string from dvdsreleasedates.com (e.g. 'Tuesday May 5, 2026')"""
    date_str = date_str.strip()
    # Remove any extra spaces
    date_str = re.sub(r'\s+', ' ', date_str)
    
    formats = [
        "%A %B %d, %Y",  # Tuesday May 5, 2026
        "%B %d, %Y",     # May 5, 2026
        "%A, %B %d, %Y", # Tuesday, May 5, 2026
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
            
    # Fallback to try finding Month Year
    match = re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\b\s+\d{4}', date_str)
    if match:
        try:
            return datetime.strptime(match.group(0), "%B %Y")
        except ValueError:
            pass
            
    return datetime(1900, 1, 1)

def clean_movie_title(title: str) -> str:
    """Strips common release format suffixes that might be appended in link text."""
    title = title.strip()
    suffixes = [" DVD", " Blu-ray", " BluRay", " 4K", " 3D", " Steelbook"]
    for suffix in suffixes:
        if title.lower().endswith(suffix.lower()):
            title = title[:-len(suffix)].strip()
    return title

def is_tv_series(title: str) -> bool:
    """Identifies and filters out TV seasons/series/episodes from movie listings."""
    # TV shows on DVD/Blu-ray usually contain Season, Series, Complete, or Episode keywords
    pattern = r'\b(season|series|episodes?|complete\s+\d+|complete\s+first|complete\s+second|complete\s+third|complete\s+fourth|complete\s+fifth|complete\s+sixth|complete\s+seventh|complete\s+eighth|complete\s+ninth|complete\s+tenth)\b'
    if re.search(pattern, title.lower()):
        return True
    return False

def normalize_title(title: str) -> str:
    """Normalizes title for case-insensitive and punctuation-insensitive comparisons."""
    return re.sub(r'[^a-z0-9]', '', title.lower())

def scrape_new_releases(url: str, is_tv: bool = True) -> List[Dict[str, Any]]:
    """Scrapes Metacritic's new list and returns a list of items."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"\n[Warning] Failed to fetch page {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    containers = soup.find_all('div', **{"data-testid": "filter-results"})
    
    results = []
    for c in containers:
        a_tag = c.find('a', href=True)
        if not a_tag:
            continue
            
        href = a_tag['href']
        
        is_returning = False
        if is_tv:
            # Metacritic links for returning seasons usually look like /tv/rivals/season-2/ or /tv/good-omens/season-3/
            if "/season-" in href.lower() or "-season" in href.lower():
                is_returning = True

        title_span = c.find('h3', **{"data-testid": "product-title"})
        title = title_span.get_text(strip=True) if title_span else "Unknown"

        # Find the text container containing dates and description
        text_container = c.find('div', class_="relative max-w-full flex flex-col")
        date_str = ""
        description = ""
        
        if text_container:
            spans = [span.get_text(strip=True) for span in text_container.find_all('span')]
            
            # Look for a date string in the spans
            for s in spans:
                if re.search(r'[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}', s) or re.search(r'[A-Za-z]{3,9}\s+\d{4}', s):
                    date_str = s.split('•')[0].strip() # Clean off any metadata like rating
                    break
            
            # Look for the description
            desc_div = text_container.find('div', class_=lambda x: x and ('line-clamp-2' in x or 'line-clamp' in x))
            if desc_div:
                description = desc_div.get_text(strip=True)
            elif len(spans) > 1:
                description = max(spans, key=len)
                if len(description) < 15:
                    description = ""

        # Cleanup returning TV show keywords in the title/desc just in case
        if is_tv:
            title_lower = title.lower()
            desc_lower = description.lower()
            if any(k in title_lower or k in desc_lower for k in ["season 2", "season 3", "season 4", "returning series", "season two", "season three"]):
                is_returning = True

        date_obj = parse_date(date_str) if date_str else datetime(1900, 1, 1)

        results.append({
            "title": title,
            "href": f"https://www.metacritic.com{href}" if href.startswith('/') else href,
            "date_str": date_str or "Unknown Release Date",
            "date_obj": date_obj,
            "description": description or "No plot summary available.",
            "is_returning": is_returning
        })
        
    return results

def scrape_dvds_releases(year: int, month: int) -> List[Dict[str, Any]]:
    """Scrapes dvdsreleasedates.com for a given year and month."""
    url = f"https://www.dvdsreleasedates.com/releases/{year}/{month:02d}/"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"\n[Warning] Failed to fetch page {url}: Status {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"\n[Warning] Failed to fetch page {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    movies = []
    
    for table in soup.find_all("table", class_="fieldtable-inner"):
        current_date = None
        
        for tr in table.find_all("tr"):
            date_td = tr.find("td", class_=lambda x: x and "reldate" in x)
            if date_td:
                raw_text = date_td.get_text()
                clean_date = raw_text.split("(")[0].strip()
                current_date = clean_date
                continue
                
            dvdcells = tr.find_all("td", class_="dvdcell")
            for cell in dvdcells:
                title_a = cell.find("a", style="color:#000;")
                if not title_a:
                    for a in cell.find_all("a", href=True):
                        text = a.get_text(strip=True)
                        if text and text not in ["", "DVD", "Blu-ray", "4K", "Digital"]:
                            title_a = a
                            break
                if not title_a:
                    continue
                    
                title = title_a.get_text(strip=True)
                href = title_a["href"]
                
                title = clean_movie_title(title)
                
                if is_tv_series(title):
                    continue
                
                imdb_id = None
                imdb_a = cell.find("a", href=lambda h: h and "imdb.com/title/" in h)
                if imdb_a:
                    match = re.search(r'tt\d+', imdb_a["href"])
                    if match:
                        imdb_id = match.group(0)
                
                date_obj = parse_dvd_date(current_date) if current_date else datetime(1900, 1, 1)
                
                movies.append({
                    "title": title,
                    "date_str": current_date or "Unknown Date",
                    "date_obj": date_obj,
                    "href": f"https://www.dvdsreleasedates.com{href}" if href.startswith("/") else href,
                    "imdbId": imdb_id,
                    "description": "No plot summary available.",
                    "is_returning": False
                })
                
    return movies

def merge_movie_lists(meta_movies: List[Dict[str, Any]], dvd_movies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges and deduplicates movies from Metacritic and DVDsReleaseDates."""
    merged = []
    
    # Start with Metacritic movies
    for item in meta_movies:
        merged.append(dict(item))
        
    for item in dvd_movies:
        norm_title = normalize_title(item["title"])
        year = item["date_obj"].year
        
        # Search for a match in the merged list
        match = None
        for existing in merged:
            existing_norm = normalize_title(existing["title"])
            existing_year = existing["date_obj"].year
            # Match if normalized titles are identical AND years are within 1 year
            if existing_norm == norm_title and abs(existing_year - year) <= 1:
                match = existing
                break
                
        if match:
            # Prefer/merge fields
            if item.get("imdbId") and not match.get("imdbId"):
                match["imdbId"] = item["imdbId"]
            if match["date_obj"].year == 1900 and item["date_obj"].year != 1900:
                match["date_obj"] = item["date_obj"]
                match["date_str"] = item["date_str"]
        else:
            merged.append(dict(item))
            
    return merged

def get_discoveries(past_days: int = 30, future_days: int = 60) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retrieves new TV shows and movies released within the specified past/future days window."""
    tv_url = "https://www.metacritic.com/browse/tv/all/all/all-time/new/"
    movie_url = "https://www.metacritic.com/browse/movie/all/all/all-time/new/"
    
    tv_raw = scrape_new_releases(tv_url, is_tv=True)
    movie_raw = scrape_new_releases(movie_url, is_tv=False)
    
    now = datetime.now()
    start_date = now - timedelta(days=past_days)
    end_date = now + timedelta(days=future_days)
    
    # Spanning months for DVD releases
    current = start_date
    dvd_movies = []
    while current <= end_date:
        year_month = (current.year, current.month)
        # Fetch for this month
        month_movies = scrape_dvds_releases(year_month[0], year_month[1])
        dvd_movies.extend(month_movies)
        
        # Advance to first day of next month
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)
            
    # Include end_date month if not fully covered
    end_ym = (end_date.year, end_date.month)
    if (end_date.year, end_date.month) != (current.year, current.month):
        month_movies = scrape_dvds_releases(end_ym[0], end_ym[1])
        dvd_movies.extend(month_movies)
        
    # Merge movie lists
    combined_movies = merge_movie_lists(movie_raw, dvd_movies)
    
    # Filter by date range
    tv_filtered = [item for item in tv_raw if start_date <= item["date_obj"] <= end_date]
    movie_filtered = [item for item in combined_movies if start_date <= item["date_obj"] <= end_date]
    
    # Sort by release date (descending: newest first)
    tv_filtered.sort(key=lambda x: x["date_obj"], reverse=True)
    movie_filtered.sort(key=lambda x: x["date_obj"], reverse=True)
    
    return tv_filtered, movie_filtered
