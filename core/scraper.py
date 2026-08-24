import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import socket
import ipaddress
import urllib.parse
import json
from typing import List, Dict, Any, Tuple, Optional
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import PoolManager
from defusedxml.ElementTree import fromstring as secure_fromstring
import xml.etree.ElementTree as ET

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Connection": "keep-alive"
}

# --- SSRF & DNS Rebinding Defenses ---

class SafeHTTPConnection(HTTPConnection):
    def __init__(self, *args, **kwargs):
        self.safe_ip = kwargs.pop('safe_ip', None)
        super().__init__(*args, **kwargs)
        
    def _new_conn(self):
        if self.safe_ip:
            original_host = self.host
            self.host = self.safe_ip
            conn = super()._new_conn()
            self.host = original_host
            return conn
        return super()._new_conn()

class SafeHTTPSConnection(HTTPSConnection):
    def __init__(self, *args, **kwargs):
        self.safe_ip = kwargs.pop('safe_ip', None)
        super().__init__(*args, **kwargs)
        
    def _new_conn(self):
        if self.safe_ip:
            original_host = self.host
            self.host = self.safe_ip
            conn = super()._new_conn()
            self.host = original_host
            return conn
        return super()._new_conn()

class SafeHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = SafeHTTPConnection

class SafeHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = SafeHTTPSConnection

class SafePoolManager(PoolManager):
    def __init__(self, safe_ip, *args, **kwargs):
        self.safe_ip = safe_ip
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {
            'http': SafeHTTPConnectionPool,
            'https': SafeHTTPSConnectionPool,
        }
        
    def _new_pool(self, scheme, host, port, request_context=None):
        request_context = request_context or {}
        request_context['safe_ip'] = self.safe_ip
        return super()._new_pool(scheme, host, port, request_context)

class SafeIPHTTPAdapter(HTTPAdapter):
    def __init__(self, safe_ip, *args, **kwargs):
        self.safe_ip = safe_ip
        super().__init__(*args, **kwargs)
        
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = SafePoolManager(
            safe_ip=self.safe_ip,
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs
        )

def safe_fetch_feed(url: str, headers: dict = None, timeout: int = 15, max_redirects: int = 3) -> str:
    """Fetches a URL safely enforcing SSRF/DNS Rebinding protections and payload limit restrictions."""
    current_url = url
    session = requests.Session()
    headers = headers or {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = HEADERS["User-Agent"]

    for _ in range(max_redirects + 1):
        parsed = urllib.parse.urlparse(current_url)
        host = parsed.hostname
        if not host:
            raise ValueError("Malformed URL")

        if parsed.scheme not in ('http', 'https'):
            raise ValueError("Forbidden scheme. Only http/https are allowed.")

        # Resolve and validate IP address
        try:
            addr_info = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80))
            target_ip = addr_info[0][4][0]
        except Exception as e:
            raise ValueError(f"DNS Resolution failed for {host}: {e}")

        ip_obj = ipaddress.ip_address(target_ip)
        if hasattr(ip_obj, 'ipv4_mapped') and ip_obj.ipv4_mapped:
            ip_obj = ip_obj.ipv4_mapped
            target_ip = str(ip_obj)

        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local or target_ip.startswith("0.") or (ip_obj.version == 6 and ip_obj.is_private):
            raise ValueError(f"Access to private/local network ranges is forbidden: {target_ip}")

        # Mount connection adapter pinned to pre-validated IP
        adapter = SafeIPHTTPAdapter(target_ip)
        session.mount(f"{parsed.scheme}://{host}", adapter)

        # Fetch (streaming chunks to enforce size limits)
        response = session.get(current_url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)

        if response.status_code in (301, 302, 303, 307, 308):
            redirect_url = response.headers.get("Location")
            if not redirect_url:
                break
            current_url = urllib.parse.urljoin(current_url, redirect_url)
            continue
        
        response.raise_for_status()
        
        # Enforce payload size limits during chunk retrieval
        content = []
        downloaded_bytes = 0
        for chunk in response.iter_content(chunk_size=4096):
            downloaded_bytes += len(chunk)
            if downloaded_bytes > 10 * 1024 * 1024:  # 10 MB Max Limit
                raise ValueError("Payload size limit (10MB) exceeded")
            content.append(chunk)
            
        return b"".join(content).decode("utf-8", errors="replace")

    raise ValueError("Too many redirects")

# --- Custom Feed Parser Mechanics ---

def is_safe_regex(pattern: str) -> bool:
    """Statically verifies regex pattern is safe from catastrophic nesting (ReDoS defense)."""
    if not pattern:
        return True
    # 1. Reject direct nested quantifiers like *+, ++, *?, etc.
    if re.search(r'[\*\+\?\{\}][\*\+\?\{\}]', pattern):
        return False
    # 2. Track parenthetical nesting and reject repetitions on groups with nested repetitions
    paren_depth = 0
    group_has_quantifier = {}
    for idx, char in enumerate(pattern):
        if char == '(' and (idx == 0 or pattern[idx-1] != '\\'):
            paren_depth += 1
            group_has_quantifier[paren_depth] = False
        elif char == ')' and (idx == 0 or pattern[idx-1] != '\\'):
            if paren_depth > 0:
                next_idx = idx + 1
                is_quantified = False
                if next_idx < len(pattern) and pattern[next_idx] in ('*', '+', '?'):
                    is_quantified = True
                elif next_idx + 1 < len(pattern) and pattern[next_idx] == '{':
                    is_quantified = True
                if is_quantified and group_has_quantifier[paren_depth]:
                    return False
                paren_depth -= 1
        elif char in ('*', '+', '?') and (idx == 0 or pattern[idx-1] != '\\'):
            for d in list(group_has_quantifier.keys()):
                group_has_quantifier[d] = True
    return True

def apply_transforms(val: str, transforms: list) -> str:
    """Applies cleanups and regex mappings safely with ReDoS guards and index bounds checks."""
    if val is None:
        val = ""
    if not transforms:
        return val
    for t in transforms:
        t_type = t.get("type")
        if t_type == "strip":
            val = val.strip()
        elif t_type == "split":
            delim = t.get("delimiter", "")
            idx = t.get("index", 0)
            if delim:
                parts = val.split(delim)
                if 0 <= idx < len(parts):
                    val = parts[idx]
                elif -len(parts) <= idx < 0:
                    val = parts[idx]
                else:
                    val = ""
        elif t_type == "regex_search":
            pattern = t.get("pattern", "")
            if pattern and is_safe_regex(pattern):
                if len(val) > 500:
                    val = val[:500]
                try:
                    match = re.search(pattern, val)
                    val = match.group(0) if match else ""
                except re.error:
                    val = ""
        elif t_type == "regex_replace":
            pattern = t.get("pattern", "")
            repl = t.get("replacement", "")
            if pattern and is_safe_regex(pattern):
                if len(val) > 500:
                    val = val[:500]
                try:
                    val = re.sub(pattern, repl, val)
                except re.error:
                    pass
        elif t_type == "default":
            if not val or val.strip() == "":
                val = t.get("value", "")
    return val

def evaluate_json_path(data: any, path: str) -> any:
    """Safely traverses nested JSON maps and lists, with safe type checking and wildcards."""
    if not path or path == "$":
        return data
    parts = path.replace("$.", "").split(".")
    current = data
    for idx, part in enumerate(parts):
        try:
            if part == "*":
                if isinstance(current, list):
                    remaining_path = ".".join(parts[idx+1:])
                    res = []
                    for item in current:
                        found = evaluate_json_path(item, remaining_path)
                        if isinstance(found, list):
                            res.extend(found)
                        elif found is not None:
                            res.append(found)
                    return res
                return current
            
            if isinstance(current, list):
                i = int(part)
                current = current[i]
            else:
                current = current[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    return current

def parse_xml_safely(raw_xml: str) -> ET.Element:
    """Parses XML securely using defusedxml to block XXE and DTD expansion."""
    root = secure_fromstring(raw_xml)
    strip_namespaces(root)
    return root

def strip_namespaces(el):
    """Recursively removes namespace URI prefixes from XML element tags."""
    if el.tag.startswith("{"):
        el.tag = el.tag.split("}", 1)[1]
    for child in el:
        strip_namespaces(child)

def safe_int(val) -> Optional[int]:
    """Extracts digits and casts to integer safely, avoiding ValueError crashes."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    try:
        digits = re.findall(r'\d+', str(val))
        return int(digits[0]) if digits else None
    except (ValueError, IndexError):
        return None

def standardize_item(raw_item: dict, default_type: str, base_url: str) -> dict:
    """Standardizes a parsed item dictionary into expected format structures."""
    title = raw_item.get("title", "").strip()
    href = raw_item.get("href", "").strip()
    if href and base_url:
        href = urllib.parse.urljoin(base_url, href)
        
    date_str = raw_item.get("date_str", "").strip()
    date_obj = parse_date(date_str) if date_str else datetime.now()
    if date_obj == datetime(1900, 1, 1):
        date_obj = datetime.now()
        
    network = raw_item.get("network") or raw_item.get("studio") or "Unknown"
    cast = raw_item.get("cast") or raw_item.get("actors") or "Cast details not available."
        
    return {
        "title": title,
        "year": safe_int(raw_item.get("year")),
        "type": raw_item.get("type", default_type),
        "date_str": date_str or date_obj.strftime("%b %d, %Y"),
        "date_obj": date_obj,
        "href": href,
        "imdb_id": raw_item.get("imdb_id", ""),
        "tvdb_id": safe_int(raw_item.get("tvdb_id")),
        "tmdb_id": safe_int(raw_item.get("tmdb_id")),
        "description": raw_item.get("description", "No plot summary available."),
        "network": network,
        "cast": cast
    }

def parse_custom_feed(feed_config: dict, raw_payload: str) -> list:
    """Parses custom RSS, JSON, or HTML feeds using declarative mapping schemas."""
    feed_type = feed_config.get("feed_type") or "rss"
    item_selector = feed_config.get("item_selector")
    mappings = feed_config.get("mappings") or {}
    default_media_type = feed_config.get("default_media_type", "movie")
    base_url = feed_config.get("url")
    
    parsed_items = []
    
    # 1. JSON Parsing
    if feed_type == "json":
        data = json.loads(raw_payload)
        items = evaluate_json_path(data, item_selector)
        if not isinstance(items, list):
            items = [items] if items else []
        for item in items:
            parsed_item = {}
            for field, rule in mappings.items():
                val = evaluate_json_path(item, rule.get("selector", ""))
                val = apply_transforms(val, rule.get("transforms"))
                parsed_item[field] = val
            parsed_items.append(standardize_item(parsed_item, default_media_type, base_url))
            
    # 2. RSS/XML Parsing
    elif feed_type == "rss":
        root = parse_xml_safely(raw_payload)
        items = root.findall(f".//{item_selector}")
        for item in items:
            parsed_item = {}
            for field, rule in mappings.items():
                sel = rule.get("selector", "")
                if not sel:
                    continue
                el = item.find(sel)
                val = el.text if el is not None else ""
                val = apply_transforms(val, rule.get("transforms"))
                parsed_item[field] = val
            parsed_items.append(standardize_item(parsed_item, default_media_type, base_url))
            
    # 3. HTML Parsing
    elif feed_type == "html":
        soup = BeautifulSoup(raw_payload, "html.parser")
        items = soup.select(item_selector)
        for item in items:
            parsed_item = {}
            for field, rule in mappings.items():
                sel = rule.get("selector", "")
                if not sel:
                    continue
                el = item.select_one(sel)
                if not el:
                    continue
                
                extract_type = rule.get("extract", "text")
                if extract_type == "text":
                    val = el.get_text()
                elif extract_type == "attribute":
                    val = el.get(rule.get("attribute_name", ""))
                else:
                    val = ""
                    
                val = apply_transforms(val, rule.get("transforms"))
                parsed_item[field] = val
            parsed_items.append(standardize_item(parsed_item, default_media_type, base_url))
            
    return parsed_items


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
    """Strips common release format suffixes, brackets, or parenthetical packaging descriptors."""
    title = title.strip()
    
    # 1. Strip common formats inside brackets or parentheses at the end:
    # E.g. " [Digital]", " (Digital)", " [4K UHD]", " (4K Ultra HD)", " (Blu-ray + DVD)"
    pattern_brackets = r'\s*[\[\(][^\]\)]*(digital|4k|uhd|ultra\s+hd|blu-ray|bluray|dvd|steelbook|hd|sd|rip|edition|cut|screen|combo|pack|disc|special)[^\]\)]*[\]\)]'
    title = re.sub(pattern_brackets, '', title, flags=re.IGNORECASE)
    
    # 2. Strip common raw suffixes that are not inside brackets/parentheses:
    suffixes = [" DVD", " Blu-ray", " BluRay", " 4K", " 3D", " Steelbook", " Digital", " 4K Ultra HD", " 4K UHD", " UHD"]
    for suffix in suffixes:
        if title.lower().endswith(suffix.lower()):
            title = title[:-len(suffix)].strip()
            
    # 3. Remove year suffixes like (2024) or [2024] at the end
    title = re.sub(r'\s*[\[\(\s]\d{4}[\]\)]?$', '', title)
            
    # 4. Clean any trailing punctuation or whitespace
    title = re.sub(r'[\s:\-\(\),\[\]]+$', '', title).strip()
    return title

def is_tv_series(title: str) -> bool:
    """Identifies and filters out TV seasons/series/episodes from movie listings."""
    # TV shows on DVD/Blu-ray usually contain Season, Series, Complete, or Episode keywords
    pattern = r'\b(season|series|episodes?|complete\s+\d+|complete\s+first|complete\s+second|complete\s+third|complete\s+fourth|complete\s+fifth|complete\s+sixth|complete\s+seventh|complete\s+eighth|complete\s+ninth|complete\s+tenth)\b'
    if re.search(pattern, title.lower()):
        return True
    return False

def clean_tv_title(title: str) -> str:
    """Strips season descriptors, years, or format suffixes from TV show titles."""
    title = title.strip()
    # 1. Remove "Season X" patterns: e.g. ": Season 1", " - Season 2", " (Season 3)"
    # Also handles words like "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"
    # Case-insensitive
    pattern = r'\s*[:\-\(]?\s*season\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*\)?'
    title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    
    # 2. Remove other common TV series qualifiers: " Series 1", " The Complete Series", " - Series", " (Series)"
    pattern_series = r'\s*[:\-\(]?\s*(the\s+)?complete\s+series\s*\)?'
    title = re.sub(pattern_series, '', title, flags=re.IGNORECASE)
    
    pattern_series_num = r'\s*[:\-\(]?\s*series\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*\)?'
    title = re.sub(pattern_series_num, '', title, flags=re.IGNORECASE)
    
    # 3. Clean any trailing punctuation or whitespace
    title = re.sub(r'[\s:\-\(\),]+$', '', title).strip()
    return title

def normalize_title(title: str, is_tv: bool = False) -> str:
    """Normalizes title for case-insensitive and punctuation-insensitive comparisons."""
    if is_tv:
        title = clean_tv_title(title)
    else:
        title = clean_movie_title(title)
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
        raw_title = title_span.get_text(strip=True) if title_span else "Unknown"
        title = raw_title
        if is_tv:
            title = clean_tv_title(title)

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
            title_lower = raw_title.lower()
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

def scrape_dvds_releases(year: int, month: int, url_template: str = None) -> List[Dict[str, Any]]:
    """Scrapes dvdsreleasedates.com for a given year and month."""
    if url_template:
        url = url_template.format(year=year, month=month)
    else:
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
    """Retrieves new TV shows and movies released within the specified past/future days window, merging custom feeds."""
    tv_raw = []
    movie_raw = []
    dvd_enabled = False
    dvd_url_template = None
    
    # 1. Fetch enabled custom feeds from database
    from core.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_feeds'")
    if cursor.fetchone():
        cursor.execute("SELECT * FROM custom_feeds WHERE enabled = 1")
        feeds = [dict(row) for row in cursor.fetchall()]
    else:
        feeds = []
        
    for feed in feeds:
        try:
            url = feed["url"]
            feed_type = feed["feed_type"]
            if not (url.startswith("http://") or url.startswith("https://")):
                https_url = f"https://{url}"
                http_url = f"http://{url}"
                discovered_url = http_url
                for test_url in (https_url, http_url):
                    try:
                        if feed_type in ("metacritic_tv", "metacritic_movie", "dvds_releases"):
                            requests.get(test_url, headers=HEADERS, timeout=5)
                        else:
                            headers_dict = json.loads(feed["http_headers"]) if feed["http_headers"] else {}
                            safe_fetch_feed(test_url, headers=headers_dict, timeout=5)
                        discovered_url = test_url
                        break
                    except Exception:
                        continue
                
                cursor.execute("UPDATE custom_feeds SET url = ? WHERE id = ?", (discovered_url, feed["id"]))
                conn.commit()
                feed["url"] = discovered_url
                
            # Built-in custom scrapers
            if feed_type == "metacritic_tv":
                items = scrape_new_releases(feed["url"], is_tv=True)
                for item in items:
                    item["source_feed_id"] = feed["id"]
                    tv_raw.append(item)
            elif feed_type == "metacritic_movie":
                items = scrape_new_releases(feed["url"], is_tv=False)
                for item in items:
                    item["source_feed_id"] = feed["id"]
                    movie_raw.append(item)
            elif feed_type == "dvds_releases":
                dvd_enabled = True
                dvd_url_template = feed["url"]
            else:
                # Custom dynamic parser types
                headers_dict = json.loads(feed["http_headers"]) if feed["http_headers"] else {}
                parser_cfg = json.loads(feed["parser_config"])
                parser_cfg["url"] = feed["url"]
                parser_cfg["default_media_type"] = feed["default_media_type"]
                parser_cfg["feed_type"] = feed["feed_type"]
                
                raw_payload = safe_fetch_feed(feed["url"], headers=headers_dict)
                items = parse_custom_feed(parser_cfg, raw_payload)
                
                for item in items:
                    item["source_feed_id"] = feed["id"]
                    if item["type"] == "tv":
                        tv_raw.append(item)
                    else:
                        movie_raw.append(item)
                        
            cursor.execute(
                "UPDATE custom_feeds SET last_run = ?, last_status = ?, last_error_message = NULL WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "success", feed["id"])
            )
        except Exception as e:
            # Feed Loop Isolation: catch error, log, and proceed
            cursor.execute(
                "UPDATE custom_feeds SET last_run = ?, last_status = ?, last_error_message = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error", str(e), feed["id"])
            )
            
    conn.close()
    
    now = datetime.now()
    start_date = now - timedelta(days=past_days)
    end_date = now + timedelta(days=future_days)
    
    # 2. DVDs Release Dates scraper (if enabled)
    dvd_movies = []
    if dvd_enabled:
        current = start_date
        while current <= end_date:
            year_month = (current.year, current.month)
            month_movies = scrape_dvds_releases(year_month[0], year_month[1], url_template=dvd_url_template)
            dvd_movies.extend(month_movies)
            
            # Advance to first day of next month
            if current.month == 12:
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)
                
        # Include end_date month if not fully covered
        end_ym = (end_date.year, end_date.month)
        if (end_date.year, end_date.month) != (current.year, current.month):
            month_movies = scrape_dvds_releases(end_ym[0], end_ym[1], url_template=dvd_url_template)
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
