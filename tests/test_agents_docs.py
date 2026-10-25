"""Keeps AGENTS.md / docs honest: every repo path and test file they mention must exist."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "AGENTS.md", ROOT / "docs" / "architecture.md", ROOT / "docs" / "decisions.md"]
PATH_RE = re.compile(r"`((?:core|web|cli|gui|tests|docs)/[A-Za-z0-9_./-]+|[A-Za-z0-9_.-]+\.(?:py|sh|ps1|bat|txt|md))`")
IGNORED = {"xarrtools.db", "custom_feeds", "setup.py"}


def test_docs_exist_and_are_linked_from_agents_md():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for doc in DOCS:
        assert doc.is_file(), doc
    assert "docs/architecture.md" in text and "docs/decisions.md" in text


def test_every_mentioned_path_exists():
    missing = []
    for doc in DOCS:
        for match in PATH_RE.findall(doc.read_text(encoding="utf-8")):
            if match in IGNORED or "<" in match or "*" in match:
                continue
            candidate = match.rstrip("/")
            if not (ROOT / candidate).exists() and not any(ROOT.glob(candidate)):
                missing.append((doc.name, match))
    assert not missing, f"Docs reference paths that do not exist: {missing}"


def test_documented_symbols_exist():
    sources = "".join((ROOT / p).read_text(encoding="utf-8") for p in (
        "core/scraper.py", "core/db.py", "core/metadata.py", "core/locales.py", "core/enricher.py",
        "core/tmdb.py", "web/server.py", "web/templates/app.js"))
    for symbol in ("get_discoveries", "dedupe_movies", "merge_movie_lists", "_movie_key", "slug", "normalize_title",
                   "add_cached_item", "evaluate_item_state_transition", "archive_cached_item", "enrich_tv_show",
                   "enrich_movie", "itemPassesFilters", "getFilteredUnarchived", "renderMediaLists",
                   "/api/archive/batch", "manually_archived", "expected_cols"):
        assert symbol in sources, symbol
