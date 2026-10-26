"""Shared test harness for executing frontend code in Node.js.

Provides utilities for checking Node.js and compiled dist assets availability,
generating JavaScript code that dynamically imports compiled ESM modules
(web/static/dist/*.js), and injecting module aliases into the global environment
matching the exact imports used in web/templates/app.js.
"""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "web" / "static" / "dist"
DIST_FILTERS = DIST_DIR / "filters.js"
DIST_API = DIST_DIR / "api.js"
DIST_CARDS = DIST_DIR / "cards.js"
APP_JS_PATH = REPO_ROOT / "web" / "templates" / "app.js"
INDEX_HTML_PATH = REPO_ROOT / "web" / "templates" / "index.html"
APP_JS = APP_JS_PATH
INDEX_HTML = INDEX_HTML_PATH.read_text(encoding="utf-8")

REQUIRED_DIST_FILES = [DIST_FILTERS, DIST_API, DIST_CARDS]


def check_node_and_dist():
    """Skip test if node or compiled dist files are missing."""
    if shutil.which("node") is None:
        pytest.skip("node not available")
    missing = [str(f.relative_to(REPO_ROOT)) for f in REQUIRED_DIST_FILES if not f.is_file()]
    if missing:
        pytest.skip(f"Frontend dist assets missing ({', '.join(missing)}); run 'npm run build' first")


def get_module_injection_code() -> str:
    """Returns JavaScript code using ESM dynamic import to load compiled modules

    and assign their exports to globalThis matching the exact aliases used in app.js:
    - moduleMatchLocale, moduleMatchFilter, moduleItemPassesFilters, moduleGetFilteredUnarchived
    - moduleArchiveBatch, moduleArchiveItem, moduleFetchConfig, moduleFetchSettings, moduleSaveSettings,
      moduleFetchScanProgress, moduleFetchDiscoveries, moduleRefreshCacheItem, moduleLookupMedia,
      moduleAddMedia, moduleLinkLibrary, moduleFetchCacheStats, modulePruneCache, moduleClearCache,
      moduleGetBackupExportUrl, moduleImportBackup, moduleFetchFeeds, moduleSaveFeed, moduleDeleteFeed,
      moduleTestFeed, moduleRestoreDefaultFeeds
    - moduleEscapeHtml, moduleCountryName, moduleLocaleBadge, moduleBuildRatingBadgesHtml,
      moduleGetPosterNavigationUrl, moduleBuildMediaCardHtml
    """
    return f"""
    const [_distFilters, _distApi, _distCards] = await Promise.all([
        import({json.dumps(DIST_FILTERS.as_uri())}),
        import({json.dumps(DIST_API.as_uri())}),
        import({json.dumps(DIST_CARDS.as_uri())})
    ]);

    // filters.js exports
    globalThis.moduleMatchLocale = _distFilters.matchLocale;
    globalThis.moduleMatchFilter = _distFilters.matchFilter;
    globalThis.moduleItemPassesFilters = _distFilters.itemPassesFilters;
    globalThis.moduleGetFilteredUnarchived = _distFilters.getFilteredUnarchived;

    // api.js exports
    globalThis.moduleArchiveBatch = _distApi.archiveBatch;
    globalThis.moduleArchiveItem = _distApi.archiveItem;
    globalThis.moduleFetchConfig = _distApi.fetchConfig;
    globalThis.moduleFetchSettings = _distApi.fetchSettings;
    globalThis.moduleSaveSettings = _distApi.saveSettings;
    globalThis.moduleFetchScanProgress = _distApi.fetchScanProgress;
    globalThis.moduleFetchDiscoveries = _distApi.fetchDiscoveries;
    globalThis.moduleRefreshCacheItem = _distApi.refreshCacheItem;
    globalThis.moduleLookupMedia = _distApi.lookupMedia;
    globalThis.moduleAddMedia = _distApi.addMedia;
    globalThis.moduleLinkLibrary = _distApi.linkLibrary;
    globalThis.moduleFetchCacheStats = _distApi.fetchCacheStats;
    globalThis.modulePruneCache = _distApi.pruneCache;
    globalThis.moduleClearCache = _distApi.clearCache;
    globalThis.moduleGetBackupExportUrl = _distApi.getBackupExportUrl;
    globalThis.moduleImportBackup = _distApi.importBackup;
    globalThis.moduleFetchFeeds = _distApi.fetchFeeds;
    globalThis.moduleSaveFeed = _distApi.saveFeed;
    globalThis.moduleDeleteFeed = _distApi.deleteFeed;
    globalThis.moduleTestFeed = _distApi.testFeed;
    globalThis.moduleRestoreDefaultFeeds = _distApi.restoreDefaultFeeds;

    // cards.js exports
    globalThis.moduleEscapeHtml = _distCards.escapeHtml;
    globalThis.moduleSafeUrl = _distCards.safeUrl;
    globalThis.moduleCountryName = _distCards.countryName;
    globalThis.moduleLocaleBadge = _distCards.localeBadge;
    globalThis.moduleBuildRatingBadgesHtml = _distCards.buildRatingBadgesHtml;
    globalThis.moduleGetPosterNavigationUrl = _distCards.getPosterNavigationUrl;
    globalThis.moduleBuildMediaCardHtml = _distCards.buildMediaCardHtml;
"""


def slice_function(source_text: str, name: str) -> str:
    """Extract a standalone function definition from source JavaScript code."""
    start = source_text.find(f"function {name}(")
    if start == -1:
        raise AssertionError(f"Function {name} not found in source")
    if source_text[max(0, start - 6):start] == "async ":
        start -= 6
    i = source_text.index("{", source_text.index(")", start))
    depth = 0
    for j in range(i, len(source_text)):
        if source_text[j] == "{":
            depth += 1
        elif source_text[j] == "}":
            depth -= 1
        if depth == 0:
            return source_text[start:j + 1]
    raise AssertionError(f"Could not parse full body for function {name}")
