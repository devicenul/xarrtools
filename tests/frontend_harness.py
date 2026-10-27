"""Shared test harness for executing frontend code in Node.js.

Provides utilities for checking Node.js and compiled dist assets availability,
generating JavaScript code that dynamically imports compiled ESM modules
(web/static/dist/*.js), and injecting module aliases into the global environment.
"""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "src" / "xarrtools" / "web" / "static" / "dist"
DIST_FILTERS = DIST_DIR / "filters.js"
DIST_API = DIST_DIR / "api.js"
DIST_CARDS = DIST_DIR / "cards.js"
DIST_SETTINGS = DIST_DIR / "settings.js"
DIST_MODALS = DIST_DIR / "modals.js"
DIST_RENDER = DIST_DIR / "render.js"
DIST_STATE = DIST_DIR / "state.js"
DIST_MAIN = DIST_DIR / "main.js"
SRC_DIR = REPO_ROOT / "src" / "xarrtools" / "web" / "static" / "src"
INDEX_HTML_PATH = REPO_ROOT / "src" / "xarrtools" / "web" / "templates" / "index.html"
INDEX_HTML = INDEX_HTML_PATH.read_text(encoding="utf-8")

REQUIRED_DIST_FILES = [
    DIST_FILTERS,
    DIST_API,
    DIST_CARDS,
    DIST_SETTINGS,
    DIST_MODALS,
    DIST_RENDER,
    DIST_STATE,
    DIST_MAIN,
]


def check_node_and_dist():
    """Skip test if node or compiled dist files are missing."""
    if shutil.which("node") is None:
        pytest.skip("node not available")
    missing = [str(f.relative_to(REPO_ROOT)) for f in REQUIRED_DIST_FILES if not f.is_file()]
    if missing:
        pytest.skip(f"Frontend dist assets missing ({', '.join(missing)}); run 'npm run build' first")


def get_module_injection_code() -> str:
    """Returns JavaScript code using ESM dynamic import to load compiled modules

    and assign their exports to globalThis matching the exact aliases used across frontend modules:
    - moduleMatchLocale, moduleMatchFilter, moduleItemPassesFilters, moduleGetFilteredUnarchived
    - moduleArchiveBatch, moduleArchiveItem, moduleFetchConfig, moduleFetchSettings, moduleSaveSettings,
      moduleFetchScanProgress, moduleFetchDiscoveries, moduleRefreshCacheItem, moduleLookupMedia,
      moduleAddMedia, moduleLinkLibrary, moduleFetchCacheStats, modulePruneCache, moduleClearCache,
      moduleGetBackupExportUrl, moduleImportBackup, moduleFetchFeeds, moduleSaveFeed, moduleDeleteFeed,
      moduleTestFeed, moduleRestoreDefaultFeeds
    - moduleEscapeHtml, moduleCountryName, moduleLocaleBadge, moduleBuildRatingBadgesHtml,
      moduleGetPosterNavigationUrl, moduleBuildMediaCardHtml
    - moduleCollectSettingsPayload, moduleResolveSettingsDefaults, moduleResolveHybridPreset,
      moduleUpdateMRUCache, moduleValidateFeedForm, moduleValidateTestFeedInput,
      moduleFormatTestFeedResults, moduleBuildFeedStatusBadgeHtml, moduleBuildFeedTableRowHtml,
      moduleResolveDefaultParserConfig, moduleDefaultParserConfigs
    - moduleBuildSelectOptionsHtml, moduleIsIndexerBestMatch, moduleGetCollectionName,
      moduleBuildCollectionBadgeHtml, moduleBuildLookupItemHtml, moduleBuildExternalChipsHtml,
      moduleGetLookupPosterUrl, moduleBuildRatingItemFromLookup, moduleBuildSearchCardPlotHtml,
      moduleBuildSearchCardPosterHtml, moduleBuildSearchCardHtml, moduleBuildSearchLoadingHtml,
      moduleBuildSearchEmptyStateHtml, moduleBuildSearchErrorHtml, moduleBuildLookupStatusHtml,
      moduleFormatSearchResultNotification
    """
    return f"""
    const [_distFilters, _distApi, _distCards, _distSettings, _distModals, _distRender, _distState] = await Promise.all([
        import({json.dumps(DIST_FILTERS.as_uri())}),
        import({json.dumps(DIST_API.as_uri())}),
        import({json.dumps(DIST_CARDS.as_uri())}),
        import({json.dumps(DIST_SETTINGS.as_uri())}),
        import({json.dumps(DIST_MODALS.as_uri())}),
        import({json.dumps(DIST_RENDER.as_uri())}),
        import({json.dumps(DIST_STATE.as_uri())})
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
    globalThis.moduleTriggerFileDownload = _distApi.triggerFileDownload;
    globalThis.moduleDownloadLogs = _distApi.downloadLogs;

    // cards.js exports
    globalThis.moduleEscapeHtml = _distCards.escapeHtml;
    globalThis.moduleSafeUrl = _distCards.safeUrl;
    globalThis.moduleCountryName = _distCards.countryName;
    globalThis.moduleLocaleBadge = _distCards.localeBadge;
    globalThis.moduleBuildRatingBadgesHtml = _distCards.buildRatingBadgesHtml;
    globalThis.moduleGetPosterNavigationUrl = _distCards.getPosterNavigationUrl;
    globalThis.moduleBuildMediaCardHtml = _distCards.buildMediaCardHtml;

    // settings.js exports
    globalThis.moduleCollectSettingsPayload = _distSettings.collectSettingsPayload;
    globalThis.moduleResolveSettingsDefaults = _distSettings.resolveSettingsDefaults;
    globalThis.moduleResolveHybridPreset = _distSettings.resolveHybridPreset;
    globalThis.moduleUpdateMRUCache = _distSettings.updateMRUCache;
    globalThis.moduleValidateFeedForm = _distSettings.validateFeedForm;
    globalThis.moduleValidateTestFeedInput = _distSettings.validateTestFeedInput;
    globalThis.moduleFormatTestFeedResults = _distSettings.formatTestFeedResults;
    globalThis.moduleBuildFeedStatusBadgeHtml = _distSettings.buildFeedStatusBadgeHtml;
    globalThis.moduleBuildFeedTableRowHtml = _distSettings.buildFeedTableRowHtml;
    globalThis.moduleResolveDefaultParserConfig = _distSettings.resolveDefaultParserConfig;
    globalThis.moduleDefaultParserConfigs = _distSettings.DEFAULT_PARSER_CONFIGS;
    globalThis.moduleGetFeedEditorFormDefaults = _distSettings.getFeedEditorFormDefaults;

    // modals.js exports
    globalThis.moduleBuildSelectOptionsHtml = _distModals.buildSelectOptionsHtml;
    globalThis.moduleIsIndexerBestMatch = _distModals.isIndexerBestMatch;
    globalThis.moduleGetCollectionName = _distModals.getCollectionName;
    globalThis.moduleBuildCollectionBadgeHtml = _distModals.buildCollectionBadgeHtml;
    globalThis.moduleBuildLookupItemHtml = _distModals.buildLookupItemHtml;
    globalThis.moduleBuildExternalChipsHtml = _distModals.buildExternalChipsHtml;
    globalThis.moduleGetLookupPosterUrl = _distModals.getLookupPosterUrl;
    globalThis.moduleBuildRatingItemFromLookup = _distModals.buildRatingItemFromLookup;
    globalThis.moduleBuildSearchCardPlotHtml = _distModals.buildSearchCardPlotHtml;
    globalThis.moduleBuildSearchCardPosterHtml = _distModals.buildSearchCardPosterHtml;
    globalThis.moduleBuildSearchCardHtml = _distModals.buildSearchCardHtml;
    globalThis.moduleBuildSearchLoadingHtml = _distModals.buildSearchLoadingHtml;
    globalThis.moduleBuildSearchEmptyStateHtml = _distModals.buildSearchEmptyStateHtml;
    globalThis.moduleBuildSearchErrorHtml = _distModals.buildSearchErrorHtml;
    globalThis.moduleBuildLookupStatusHtml = _distModals.buildLookupStatusHtml;
    globalThis.moduleFormatSearchResultNotification = _distModals.formatSearchResultNotification;
    globalThis.moduleGetDemoSearchResults = _distModals.getDemoSearchResults;
    globalThis.moduleBuildAddMediaPayload = _distModals.buildAddMediaPayload;

    // render.js exports
    globalThis.moduleCreateMediaCard = _distRender.createMediaCard;
    globalThis.moduleRenderMediaLists = _distRender.renderMediaLists;
    globalThis.moduleToggleArchive = _distRender.toggleArchive;
    globalThis.moduleRefreshMetadata = _distRender.refreshMetadata;
    globalThis.moduleInvertMultiselect = _distRender.invertMultiselect;
    globalThis.moduleApplyTabFilter = _distRender.applyTabFilter;

    // state.js exports
    globalThis.moduleState = _distState.state;
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
