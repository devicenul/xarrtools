"""
core/metadata.py
----------------
Centralized metadata evaluation engine for xarrtools.
Evaluates completeness of core metadata fields (Title, Studio/Network, Cast, Plot),
determines low-metadata status, and computes item state transitions for auto-archiving,
smart unarchiving, and badge management.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# ---------------------------------------------------------------------------
# Sentinel Sets for Missing Metadata
# ---------------------------------------------------------------------------

MISSING_TITLE_STRINGS: Set[str] = {
    "",
    "unknown",
    "tbd",
    "none",
    "null",
    "n/a",
    "na",
}

MISSING_NETWORK_STRINGS: Set[str] = {
    "",
    "unknown",
    "unknown network",
    "unknown studio",
    "n/a",
    "na",
    "none",
    "null",
    "tbd",
}

MISSING_CAST_STRINGS: Set[str] = {
    "",
    "cast details not available.",
    "cast details not available",
    "unknown",
    "n/a",
    "na",
    "none",
    "null",
    "tbd",
    "error getting details.",
}

MISSING_PLOT_STRINGS: Set[str] = {
    "",
    "no plot summary available.",
    "no plot summary available",
    "unknown",
    "n/a",
    "na",
    "none",
    "null",
    "tbd",
}

# ---------------------------------------------------------------------------
# Field Validator Functions
# ---------------------------------------------------------------------------

def is_title_missing(val: Any) -> bool:
    """
    Checks if a title value is missing or matches a missing sentinel.
    Returns True if val is None, empty/whitespace, boolean, empty collection,
    or matches any string in MISSING_TITLE_STRINGS (case-insensitive, trimmed).
    """
    if val is None:
        return True
    if isinstance(val, bool):
        return True
    if isinstance(val, (list, dict, set, tuple)) and not val:
        return True
    if isinstance(val, str):
        return val.strip().lower() in MISSING_TITLE_STRINGS
    return str(val).strip().lower() in MISSING_TITLE_STRINGS


def is_network_missing(val: Any) -> bool:
    """
    Checks if a studio/network value is missing or matches a missing sentinel.
    Handles strings, dictionary objects (e.g. {'name': '...'}, TVMaze network objects), lists, None.
    Returns True if missing or matches MISSING_NETWORK_STRINGS.
    """
    if val is None:
        return True
    if isinstance(val, bool):
        return True
    if isinstance(val, (list, tuple, set)):
        if not val:
            return True
        return all(is_network_missing(item) for item in val)
    if isinstance(val, dict):
        if not val:
            return True
        name = val.get("name") or val.get("network") or val.get("studio")
        return is_network_missing(name)
    if isinstance(val, str):
        return val.strip().lower() in MISSING_NETWORK_STRINGS
    return str(val).strip().lower() in MISSING_NETWORK_STRINGS


def is_cast_missing(val: Any) -> bool:
    """
    Checks if a cast value is missing or matches a missing sentinel.
    Handles strings (comma-separated or single), lists of strings or dicts, None.
    Returns True if missing or matches MISSING_CAST_STRINGS.
    """
    if val is None:
        return True
    if isinstance(val, bool):
        return True
    if isinstance(val, (list, tuple, set)):
        if not val:
            return True
        valid_members = []
        for member in val:
            if isinstance(member, dict):
                member_name = member.get("name") or (member.get("person", {}).get("name") if isinstance(member.get("person"), dict) else None)
                if not is_cast_missing(member_name):
                    valid_members.append(member_name)
            elif not is_cast_missing(member):
                valid_members.append(member)
        return len(valid_members) == 0
    if isinstance(val, dict):
        if not val:
            return True
        name = val.get("name") or (val.get("person", {}).get("name") if isinstance(val.get("person"), dict) else None)
        return is_cast_missing(name)
    if isinstance(val, str):
        return val.strip().lower() in MISSING_CAST_STRINGS
    return str(val).strip().lower() in MISSING_CAST_STRINGS


def is_plot_missing(val: Any) -> bool:
    """
    Checks if a plot/description/summary value is missing or matches a missing sentinel.
    Returns True if val is None, empty/whitespace, or matches MISSING_PLOT_STRINGS.
    """
    if val is None:
        return True
    if isinstance(val, bool):
        return True
    if isinstance(val, (list, dict, set, tuple)) and not val:
        return True
    if isinstance(val, str):
        return val.strip().lower() in MISSING_PLOT_STRINGS
    return str(val).strip().lower() in MISSING_PLOT_STRINGS


# ---------------------------------------------------------------------------
# High-Level Evaluation & Transition Functions
# ---------------------------------------------------------------------------

def evaluate_metadata(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates the 4 core metadata fields (Title, Studio/Network, Cast, Plot) for a media item.
    
    Supports key aliases:
      - Title: 'title', 'name', 'clean_title'
      - Network: 'network', 'studio', 'network_name', 'studio_name'
      - Cast: 'cast', 'actors', 'starring', 'cast_list'
      - Plot: 'plot', 'description', 'overview', 'summary'
      
    Returns:
        {
            "missing_fields": List[str],  # subset of ["title", "network", "cast", "plot"]
            "missing_count": int,         # 0 to 4
            "is_low_metadata": bool,      # True if missing_count >= 2
            "fields": {
                "title": {"value": Any, "is_missing": bool},
                "network": {"value": Any, "is_missing": bool},
                "cast": {"value": Any, "is_missing": bool},
                "plot": {"value": Any, "is_missing": bool}
            }
        }
    """
    if not item or not isinstance(item, (dict, object)):
        return {
            "missing_fields": ["title", "network", "cast", "plot"],
            "missing_count": 4,
            "is_low_metadata": True,
            "fields": {
                "title": {"value": None, "is_missing": True},
                "network": {"value": None, "is_missing": True},
                "cast": {"value": None, "is_missing": True},
                "plot": {"value": None, "is_missing": True},
            }
        }

    def _extract_field(aliases: List[str], validator_func: Callable[[Any], bool]) -> Tuple[Any, bool]:
        """Extracts candidate value among alias keys and validates completeness."""
        best_val = None
        for alias in aliases:
            if hasattr(item, "get"):
                val = item.get(alias)
            else:
                try:
                    val = item[alias]
                except (KeyError, IndexError, TypeError):
                    val = None
            if val is not None:
                if not validator_func(val):
                    return val, False
                if best_val is None:
                    best_val = val
        if best_val is not None:
            return best_val, validator_func(best_val)
        return None, True

    title_val, title_missing = _extract_field(["title", "name", "clean_title"], is_title_missing)
    network_val, network_missing = _extract_field(["network", "studio", "network_name", "studio_name"], is_network_missing)
    cast_val, cast_missing = _extract_field(["cast", "actors", "starring", "cast_list"], is_cast_missing)
    plot_val, plot_missing = _extract_field(["plot", "description", "overview", "summary"], is_plot_missing)

    missing_fields = []
    if title_missing:
        missing_fields.append("title")
    if network_missing:
        missing_fields.append("network")
    if cast_missing:
        missing_fields.append("cast")
    if plot_missing:
        missing_fields.append("plot")

    missing_count = len(missing_fields)
    is_low_metadata = missing_count >= 2

    return {
        "missing_fields": missing_fields,
        "missing_count": missing_count,
        "is_low_metadata": is_low_metadata,
        "fields": {
            "title": {"value": title_val, "is_missing": title_missing},
            "network": {"value": network_val, "is_missing": network_missing},
            "cast": {"value": cast_val, "is_missing": cast_missing},
            "plot": {"value": plot_val, "is_missing": plot_missing},
        }
    }


def should_auto_archive(item: Optional[Dict[str, Any]]) -> bool:
    """
    Determines if an item should be automatically archived due to low metadata.
    Returns True if 2 or more of the 4 core fields are missing.
    """
    if not item or not isinstance(item, (dict, object)):
        return True
    eval_result = evaluate_metadata(item)
    return eval_result["is_low_metadata"]


def evaluate_item_state_transition(
    existing_item: Optional[Dict[str, Any]],
    new_item: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Computes (is_archived, has_new_metadata) for an item being inserted or updated in cache.
    """
    if not new_item or not isinstance(new_item, (dict, object)):
        return (1, 0)

    is_low_now = should_auto_archive(new_item)
    
    def _get_val(obj: Any, key: str, default: Any = None) -> Any:
        """Safely extracts a key from a dictionary or subscriptable object with default fallback."""
        if hasattr(obj, "get"):
            return obj.get(key, default)
        try:
            return obj[key]
        except (KeyError, IndexError, TypeError):
            return default

    if existing_item is None:
        if is_low_now or bool(_get_val(new_item, "is_archived", 0)):
            return (1, 0)
        return (0, 0)

    was_archived = bool(_get_val(existing_item, "is_archived", 0))
    existing_badge = int(bool(_get_val(existing_item, "has_new_metadata", 0)))

    if is_low_now or bool(_get_val(new_item, "is_archived", 0)):
        return (1, 0)
    elif was_archived:
        return (0, 1)
    else:
        return (0, existing_badge)
