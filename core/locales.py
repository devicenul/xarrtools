"""Helpers to normalise language / country info coming from different sources (TMDB, TVmaze, Radarr).

Conventions used across the app:
  * ``language``: English display name, e.g. "English", "Korean" ('' when unknown)
  * ``country``: ISO 3166-1 alpha-2 code, e.g. "US", "KR" ('' when unknown)
"""
import re
import unicodedata
from typing import Optional

# ISO 639-1 -> English name (covers the languages TMDB/TVmaze report in practice)
LANGUAGE_NAMES = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali", "ca": "Catalan",
    "cs": "Czech", "da": "Danish", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian",
    "is": "Icelandic", "it": "Italian", "ja": "Japanese", "ko": "Korean", "lt": "Lithuanian",
    "lv": "Latvian", "ml": "Malayalam", "mr": "Marathi", "ms": "Malay", "nb": "Norwegian",
    "nl": "Dutch", "no": "Norwegian", "pa": "Punjabi", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sk": "Slovak", "sl": "Slovenian", "sr": "Serbian",
    "sv": "Swedish", "ta": "Tamil", "te": "Telugu", "th": "Thai", "tl": "Filipino",
    "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese", "zh": "Chinese",
    "cn": "Cantonese", "xx": "",
}


def language_name(value: Optional[str]) -> str:
    """Returns an English language name for an ISO 639-1 code or an already-readable name ('' if unknown)."""
    if not value:
        return ""
    v = str(value).strip()
    if not v:
        return ""
    if len(v) <= 3 and v.lower() in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[v.lower()]
    return v[:1].upper() + v[1:]


def country_code(value: Optional[str]) -> str:
    """Normalises a country to an upper-case 2-letter code ('' if it doesn't look like one)."""
    if not value:
        return ""
    v = str(value).strip().upper()
    return v if len(v) == 2 and v.isalpha() else ""


def slug(text: str) -> str:
    """Unicode-aware comparison key: lowercase, accents/punctuation/spaces removed, '&' read as 'and'.

    Non-Latin titles (Greek, Cyrillic, CJK...) keep their letters so they never collapse to an empty key.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    return re.sub(r"[\W_]+", "", text)
