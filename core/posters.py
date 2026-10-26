"""Poster disk cache and download helpers with SSRF protection."""
import os
import re
import socket
import urllib.parse
import ipaddress
import hashlib
import json
from pathlib import Path
import logging
import requests

logger = logging.getLogger("xarrtools.posters")

import core.db
from core.config import config

MAX_POSTER_SIZE = 10 * 1024 * 1024  # 10 MB limit


def get_posters_dir() -> Path:
    """Returns the posters cache directory next to the database file."""
    return Path(os.path.dirname(core.db.DB_PATH)) / "posters"


def get_extension_for_mimetype(content_type: str) -> str:
    """Returns a file extension based on MIME type."""
    if not content_type:
        return ".bin"
    ct = content_type.lower().split(";")[0].strip()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
    }
    return mapping.get(ct, ".bin")


def get_mimetype_for_filename(filename: str) -> str:
    """Deduces MIME content type from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
    }
    return mapping.get(ext, "image/jpeg")


def validate_poster_url(url: str, allowed_server_urls: list[str] = None) -> tuple[bool, str, int]:
    """Validates poster URL for scheme and SSRF protection.
    
    Returns:
        (True, "", 200) on success
        (False, error_message, http_status_code) on failure
    """
    if not url:
        return False, "Missing URL", 400

    if not re.match(r"^https?://", url):
        return False, "Invalid URL scheme", 400

    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid URL", 400

        # Resolve IP to protect against SSRF to private/internal networks
        ip = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or str(ip_obj) == "169.254.169.254":
            allowed = False
            servers = allowed_server_urls if allowed_server_urls is not None else [config.radarr_url, config.sonarr_url]
            for srv_url in servers:
                if srv_url:
                    srv_parsed = urllib.parse.urlparse(srv_url)
                    if srv_parsed.hostname == hostname:
                        allowed = True
                        break
            if not allowed:
                return False, "Forbidden destination IP", 403
    except Exception:
        return False, "Error fetching image", 500

    return True, "", 200


def get_cached_poster(url: str) -> tuple[bytes, str] | None:
    """Retrieves cached poster bytes and content-type if present on disk."""
    if not url:
        return None
    try:
        p_dir = get_posters_dir()
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        meta_file = p_dir / f"{key}.meta"
        if not meta_file.is_file():
            return None
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        content_type = meta.get("content_type", "image/jpeg")
        bin_file = p_dir / f"{key}.bin"
        if not bin_file.is_file():
            ext = meta.get("ext", "")
            if ext and (p_dir / f"{key}{ext}").is_file():
                bin_file = p_dir / f"{key}{ext}"
            else:
                return None
        data = bin_file.read_bytes()
        return data, content_type
    except Exception:
        return None


def store_poster(url: str, data: bytes, content_type: str = "image/jpeg") -> bool:
    """Stores poster bytes and metadata sidecar in the poster cache directory.
    
    Caps size to 10MB and requires image/* content-type.
    """
    if not url or not data:
        return False
    if len(data) > MAX_POSTER_SIZE:
        return False
    ct = (content_type or "").lower().split(";")[0].strip()
    if not ct.startswith("image/"):
        return False

    try:
        p_dir = get_posters_dir()
        p_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        ext = get_extension_for_mimetype(ct)
        bin_file = p_dir / f"{key}.bin"
        meta_file = p_dir / f"{key}.meta"

        bin_file.write_bytes(data)
        meta_file.write_text(json.dumps({
            "url": url,
            "content_type": ct,
            "ext": ext
        }), encoding="utf-8")
        return True
    except Exception:
        return False


def download_poster(url: str) -> tuple[bytes, str] | None:
    """Downloads poster using SSRF protection and write-through caching.
    
    Timeout is 5s. Returns (bytes, content_type) or None on failure.
    """
    cached = get_cached_poster(url)
    if cached:
        return cached

    valid, _, _ = validate_poster_url(url)
    if not valid:
        return None

    try:
        resp = requests.get(url, stream=True, timeout=5)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        ct = content_type.lower().split(";")[0].strip()
        if not ct.startswith("image/"):
            return None

        chunks = []
        total_size = 0
        for chunk in resp.iter_content(chunk_size=4096):
            chunks.append(chunk)
            total_size += len(chunk)
            if total_size > MAX_POSTER_SIZE:
                return None

        data = b"".join(chunks)
        store_poster(url, data, ct)
        return data, ct
    except Exception as e:
        logger.warning(f"Failed to download poster from {url}: {e}")
        return None
