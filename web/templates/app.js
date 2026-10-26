import { matchLocale as moduleMatchLocale, matchFilter as moduleMatchFilter, itemPassesFilters as moduleItemPassesFilters, getFilteredUnarchived as moduleGetFilteredUnarchived } from '/static/dist/filters.js';
import { archiveBatch as moduleArchiveBatch, archiveItem as moduleArchiveItem, fetchConfig as moduleFetchConfig, fetchSettings as moduleFetchSettings, saveSettings as moduleSaveSettings, fetchScanProgress as moduleFetchScanProgress, fetchDiscoveries as moduleFetchDiscoveries, refreshCacheItem as moduleRefreshCacheItem, lookupMedia as moduleLookupMedia, addMedia as moduleAddMedia, linkLibrary as moduleLinkLibrary, fetchCacheStats as moduleFetchCacheStats, pruneCache as modulePruneCache, clearCache as moduleClearCache, getBackupExportUrl as moduleGetBackupExportUrl, importBackup as moduleImportBackup, fetchFeeds as moduleFetchFeeds, saveFeed as moduleSaveFeed, deleteFeed as moduleDeleteFeed, testFeed as moduleTestFeed, restoreDefaultFeeds as moduleRestoreDefaultFeeds } from '/static/dist/api.js';
import { escapeHtml as moduleEscapeHtml, safeUrl as moduleSafeUrl, countryName as moduleCountryName, localeBadge as moduleLocaleBadge, buildRatingBadgesHtml as moduleBuildRatingBadgesHtml, getPosterNavigationUrl as moduleGetPosterNavigationUrl, buildMediaCardHtml as moduleBuildMediaCardHtml } from '/static/dist/cards.js';

// Global Application State
let appConfig = null;
let appSettings = null;
let currentDiscoveries = { tv: [], movies: [] };
let selectedItemForAdd = null;
let selectedGenres = new Set();
let selectedNetworks = new Set();
let selectedCountries = new Set();
let selectedLanguages = new Set();

// Setup API Key Interceptor for all fetch requests
const originalFetch = window.fetch;
window.fetch = async function() {
    let [resource, config] = arguments;
    
    if (typeof resource === 'string' && resource.startsWith('/api/')) {
        config = config || {};
        
        const apiKeyMeta = document.querySelector('meta[name="x-api-key"]');
        if (apiKeyMeta && apiKeyMeta.content) {
            if (!config.headers) {
                config.headers = {};
            }
            if (config.headers instanceof Headers) {
                config.headers.set("X-API-Key", apiKeyMeta.content);
            } else {
                config.headers["X-API-Key"] = apiKeyMeta.content;
            }
        }
    }
    
    return originalFetch.call(this, resource, config);
};

// Notification log helper
function addNotification(message, type = "info") {
    const list = document.getElementById("notifications-list");
    if (!list) return;
    
    // Remove empty placeholder
    const empty = list.querySelector(".empty");
    if (empty) {
        empty.remove();
    }
    
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const item = document.createElement("div");
    item.className = `notification-item ${type}`;
    item.innerHTML = `
        <div>${escapeHtml(message)}</div>
        <span class="notification-time">${escapeHtml(timeStr)}</span>
    `;
    
    list.insertBefore(item, list.firstChild);
    
    while (list.childNodes.length > 5) {
        list.removeChild(list.lastChild);
    }
}

// DOM Elements
const btnScan = document.getElementById("btn-scan");
const searchBar = document.getElementById("search-bar");
const tabButtons = document.querySelectorAll(".tab-btn");

const loadingOverlay = document.getElementById("loading-overlay");
const loadingText = document.getElementById("loading-text");
const welcomeState = document.getElementById("welcome-state");
const contentArea = document.getElementById("content-area");

const gridTv = document.getElementById("grid-tv");
const gridMovies = document.getElementById("grid-movies");
const sectionTv = document.getElementById("section-tv");
const sectionMovies = document.getElementById("section-movies");

const statusRadarr = document.getElementById("status-radarr");
const statusSonarr = document.getElementById("status-sonarr");

// Modal Add Elements
const modalOverlay = document.getElementById("modal-overlay");
const modalTitle = document.getElementById("modal-title");
const modalClose = document.getElementById("modal-close");
const btnModalCancel = document.getElementById("btn-modal-cancel");
const btnModalConfirm = document.getElementById("btn-modal-confirm");
const btnModalBack = document.getElementById("btn-modal-back");

const modalStepSearch = document.getElementById("modal-step-search");
const modalStepOptions = document.getElementById("modal-step-options");
const lookupLoading = document.getElementById("lookup-loading");
const lookupResultsList = document.getElementById("lookup-results-list");
const btnModalMarkLibrary = document.getElementById("btn-modal-mark-library");
const linkHelperBanner = document.getElementById("link-helper-banner");
let isMarkInLibraryMode = false;


const selectFolder = document.getElementById("select-folder");
const selectProfile = document.getElementById("select-profile");
const checkMonitored = document.getElementById("check-monitored");
const checkSearch = document.getElementById("check-search");

// Settings Modal Elements
const btnSettings = document.getElementById("btn-settings");
const settingsOverlay = document.getElementById("settings-overlay");
const settingsClose = document.getElementById("settings-close");
const btnSettingsCancel = document.getElementById("btn-settings-cancel");
const btnSettingsSave = document.getElementById("btn-settings-save");

const inputRadarrUrl = document.getElementById("input-radarr-url");
const inputRadarrKey = document.getElementById("input-radarr-key");
const selectRadarrDefaultFolder = document.getElementById("select-radarr-default-folder");
const selectRadarrDefaultProfile = document.getElementById("select-radarr-default-profile");
const inputSonarrUrl = document.getElementById("input-sonarr-url");
const inputSonarrKey = document.getElementById("input-sonarr-key");
const inputTmdbKey = document.getElementById("input-tmdb-key");
const selectSonarrDefaultFolder = document.getElementById("select-sonarr-default-folder");
const selectSonarrDefaultProfile = document.getElementById("select-sonarr-default-profile");
const inputPastMonths = document.getElementById("input-past-months");
const inputFutureMonths = document.getElementById("input-future-months");
const btnModalAddOnly = document.getElementById("btn-modal-add-only");
const selectSort = document.getElementById("select-sort");

// --- Theme Helpers ---
function initTheme() {
    const savedTheme = localStorage.getItem("xarrtools-theme");
    const isLight = savedTheme === "light";
    if (isLight) {
        document.body.classList.add("light-theme");
    } else {
        document.body.classList.remove("light-theme");
    }
    // Defer UI updates slightly to ensure elements exist
    setTimeout(() => updateThemeToggleUI(isLight), 0);
}

function updateThemeToggleUI(isLight) {
    const themeBtn = document.getElementById("btn-theme-toggle");
    const logoImg = document.getElementById("app-logo");
    if (themeBtn) {
        themeBtn.textContent = isLight ? "🌙" : "☀️";
        const tip = isLight ? "Switch to Dark Theme" : "Switch to Light Theme";
        themeBtn.setAttribute("data-tooltip", tip);
        themeBtn.setAttribute("aria-label", tip);
        themeBtn.removeAttribute("title");
    }
    if (logoImg) {
        logoImg.src = isLight ? "/static/favicon_light.png" : "/static/favicon.png";
    }
}

function toggleTheme() {
    const isLight = document.body.classList.toggle("light-theme");
    const themeStr = isLight ? "light" : "dark";
    localStorage.setItem("xarrtools-theme", themeStr);
    updateThemeToggleUI(isLight);
    
    // Synchronize select theme dropdown if open or loaded
    const selectTheme = document.getElementById("select-theme-mode");
    if (selectTheme) {
        selectTheme.value = themeStr;
    }
}

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    loadSettingsAndConfig();
    setupEventListeners();
});

// --- API Calls ---

// 1. Fetch server configs, status, and settings on startup
async function loadSettingsAndConfig(isInitialLoad = true) {
    try {
        // Fetch Settings
        appSettings = await moduleFetchSettings();
        
        // Fetch Configs
        appConfig = await moduleFetchConfig();
        
        // Initialize UI Elements with Settings Defaults
        initializeSettingsDefaults();
        updateStatusBadges();
        
        // Surface connection errors if credentials were configured but servers are unreachable
        if (appConfig?.radarr?.error) {
            addNotification(`Radarr offline: ${appConfig.radarr.error}`, "error");
        }
        if (appConfig?.sonarr?.error) {
            addNotification(`Sonarr offline: ${appConfig.sonarr.error}`, "error");
        }
        
        // Check if unconfigured (both offline) on initial startup only
        if (isInitialLoad && appConfig && !appConfig.radarr.configured && !appConfig.sonarr.configured) {
            openSettingsModal();
        }
        
        // Load cached discoveries from database on initial setup (skip_scrape=true)
        await scanReleases(true);
    } catch (error) {
        console.error("Failed to load application configs:", error);
    }
}

function initializeSettingsDefaults() {
    if (!appSettings) return;
    
    // Sliders Past / Future
    const sliderPast = document.getElementById("slider-past");
    const valPast = document.getElementById("val-past");
    const pastVal = appSettings.default_past_months || "1";
    sliderPast.value = pastVal;
    valPast.textContent = pastVal;
    
    const sliderFuture = document.getElementById("slider-future");
    const valFuture = document.getElementById("val-future");
    const futureVal = appSettings.default_future_months || "2";
    sliderFuture.value = futureVal;
    valFuture.textContent = futureVal;
    
    // Filter Checkboxes
    document.getElementById("check-show-returning").checked = appSettings.default_show_returning === "1";
    document.getElementById("check-show-library").checked = appSettings.default_show_library === "1";
    document.getElementById("check-show-archived").checked = appSettings.default_show_archived === "1";
}

function updateStatusBadges() {
    if (!appConfig) return;

    const statusDemo = document.getElementById("status-demo");
    const isUnconfigured = !appConfig.radarr.configured && !appConfig.sonarr.configured;
    if (statusDemo) {
        if (isUnconfigured) {
            statusDemo.classList.remove("hidden");
        } else {
            statusDemo.classList.add("hidden");
        }
    }

    // Radarr status
    if (appConfig.radarr.configured) {
        statusRadarr.className = "status-badge status-online";
    } else {
        statusRadarr.className = "status-badge status-offline";
    }

    // Sonarr status
    if (appConfig.sonarr.configured) {
        statusSonarr.className = "status-badge status-online";
    } else {
        statusSonarr.className = "status-badge status-offline";
    }
}

let progressInterval = null;

function startProgressPolling() {
    if (progressInterval) clearInterval(progressInterval);
    
    const popover = document.getElementById("scan-progress-popover");
    const statusMsg = document.getElementById("progress-status-msg");
    const percentText = document.getElementById("progress-percent-text");
    const barFill = document.getElementById("progress-bar-fill");
    
    if (popover) popover.classList.remove("hidden");
    if (statusMsg) statusMsg.textContent = "Initiating scan...";
    if (percentText) percentText.textContent = "0%";
    if (barFill) barFill.style.width = "0%";
    
    let hasStarted = false;
    
    progressInterval = setInterval(async () => {
        try {
            const data = await moduleFetchScanProgress();
            if (!data.ok) return;
            
            if (data.status === "scraping") {
                hasStarted = true;
                if (statusMsg) statusMsg.textContent = data.message;
                if (percentText) percentText.textContent = "Scraping...";
                if (barFill) barFill.style.width = "5%";
            } else if (data.status === "enriching") {
                hasStarted = true;
                if (statusMsg) statusMsg.textContent = data.message;
                if (data.total > 0) {
                    const percent = Math.round((data.current / data.total) * 100);
                    if (percentText) percentText.textContent = `${percent}% (${data.current}/${data.total})`;
                    if (barFill) barFill.style.width = `${percent}%`;
                } else {
                    if (percentText) percentText.textContent = "Enriching...";
                }
            } else if (data.status === "idle") {
                if (hasStarted) {
                    stopProgressPolling();
                }
            }
        } catch (e) {
            console.error("Error polling scan progress:", e);
        }
    }, 500);
}

function stopProgressPolling() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    const popover = document.getElementById("scan-progress-popover");
    if (popover) popover.classList.add("hidden");
}

// 2. Scan Metacritic and DVD calendar releases
async function scanReleases(skipScrape = false) {
    const shouldSkipScrape = (skipScrape === true);
    const popover = document.getElementById("scan-progress-popover");
    const statusMsg = document.getElementById("progress-status-msg");
    const percentText = document.getElementById("progress-percent-text");
    const barFill = document.getElementById("progress-bar-fill");
    
    if (shouldSkipScrape) {
        // Show progress pop-over for cache loading on startup
        if (popover) popover.classList.remove("hidden");
        if (statusMsg) statusMsg.textContent = "Loading cached releases...";
        if (percentText) percentText.textContent = "Please wait...";
        if (barFill) barFill.style.width = "50%";
        
        welcomeState.classList.add("hidden");
        contentArea.classList.remove("hidden");
    } else {
        // Non-blocking scan pop-over and polling
        startProgressPolling();
        welcomeState.classList.add("hidden");
        contentArea.classList.remove("hidden");
    }
    
    const pastMonths = document.getElementById("slider-past").value;
    const futureMonths = document.getElementById("slider-future").value;
    
    try {
        const data = await moduleFetchDiscoveries({ pastMonths, futureMonths, skipScrape: shouldSkipScrape });
        currentDiscoveries.tv = data.tv || [];
        currentDiscoveries.movies = data.movies || [];
        
        populateFilterOptions();
        renderMediaLists();
        
        if (currentDiscoveries.tv.length === 0 && currentDiscoveries.movies.length === 0) {
            welcomeState.classList.remove("hidden");
            contentArea.classList.add("hidden");
        } else {
            welcomeState.classList.add("hidden");
            contentArea.classList.remove("hidden");
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    } finally {
        if (shouldSkipScrape) {
            if (popover) popover.classList.add("hidden");
        } else {
            stopProgressPolling();
        }
    }
}

// --- Hybrid Preset Resolution & MRU Engine ---

/**
 * Resolves the quality profile or root folder selection using a 3-tier hybrid strategy:
 * Tier 1: Explicit Settings Default (appSettings[explicitSettingKey])
 * Tier 2: Most-Recently-Used Fallback (localStorage[mruKey] or appSettings[mruKey])
 * Tier 3: Safety Fallback (First available option)
 */
function resolveHybridPreset(optionsList, valueKey, explicitSettingValue, mruKey) {
    if (!optionsList || !Array.isArray(optionsList) || optionsList.length === 0) {
        return "";
    }

    const findOption = (val) => {
        if (val === undefined || val === null) return null;
        const valStr = String(val).trim();
        if (valStr === "") return null;
        return optionsList.find(opt => opt && String(opt[valueKey]).trim() === valStr) || null;
    };

    // Tier 1: Explicit Server Setting
    const explicitMatch = findOption(explicitSettingValue);
    if (explicitMatch) {
        return String(explicitMatch[valueKey]);
    }

    // Tier 2: Most-Recently-Used (MRU) Fallback
    let mruVal = null;
    if (mruKey) {
        try {
            mruVal = localStorage.getItem(mruKey);
        } catch (e) {
            // ignore localStorage error
        }
    }
    let mruMatch = findOption(mruVal);
    if (mruMatch) {
        return String(mruMatch[valueKey]);
    }

    if (mruKey && typeof appSettings !== "undefined" && appSettings) {
        mruMatch = findOption(appSettings[mruKey]);
        if (mruMatch) {
            return String(mruMatch[valueKey]);
        }
        const backendKeyMap = {
            "xarrtools_mru_radarr_folder": "radarr_mru_root_folder",
            "xarrtools_mru_radarr_profile": "radarr_mru_quality_profile",
            "xarrtools_mru_sonarr_folder": "sonarr_mru_root_folder",
            "xarrtools_mru_sonarr_profile": "sonarr_mru_quality_profile"
        };
        const altKey = backendKeyMap[mruKey];
        if (altKey) {
            mruMatch = findOption(appSettings[altKey]);
            if (mruMatch) {
                return String(mruMatch[valueKey]);
            }
        }
    }

    // Tier 3: Safety Fallback (First Available Option)
    if (optionsList[0] && optionsList[0][valueKey] !== undefined) {
        return String(optionsList[0][valueKey]);
    }

    return "";
}

/**
 * Immediately updates the localStorage MRU cache upon media addition.
 */
function updateMRUCache(type, folder, profileId) {
    const prefix = type === "tv" ? "xarrtools_mru_sonarr" : "xarrtools_mru_radarr";
    try {
        if (folder !== undefined && folder !== null && String(folder).trim() !== "") {
            localStorage.setItem(`${prefix}_folder`, String(folder).trim());
        }
        if (profileId !== undefined && profileId !== null && String(profileId).trim() !== "") {
            localStorage.setItem(`${prefix}_profile`, String(profileId).trim());
        }
    } catch (e) {
        console.warn("Failed to update localStorage MRU cache:", e);
    }
}

window.resolveHybridPreset = resolveHybridPreset;
window.updateMRUCache = updateMRUCache;

// 3. Add item to *Arr
async function addMediaItem(searchNow = null) {
    if (!selectedItemForAdd || !selectedItemForAdd.raw_metadata) return;

    const type = selectedItemForAdd.type;
    const rawMeta = selectedItemForAdd.raw_metadata;
    const discoveryItem = selectedItemForAdd.item; // Capture reference before closing modal clears selectedItemForAdd
    const searchCard = selectedItemForAdd.card || null; // Capture search card ref if from global search
    
    // Update MRU cache immediately upon item addition
    const chosenFolder = selectFolder ? selectFolder.value : "";
    const chosenProfile = selectProfile ? selectProfile.value : "";
    updateMRUCache(type, chosenFolder, chosenProfile);

    // Intercept for Demo Mode simulation
    if (selectedItemForAdd.isDemo) {
        closeModal();
        loadingOverlay.classList.remove("hidden");
        loadingText.textContent = `[Demo Mode] Adding '${rawMeta.title}'...`;
        
        try {
            const resData = await moduleAddMedia({
                type: type,
                raw_metadata: rawMeta,
                folder: chosenFolder || "demo",
                profile_id: chosenProfile || 1,
                demo: true
            });
            loadingOverlay.classList.add("hidden");
            if ((resData.ok ?? true) && resData.status === "success") {
                addNotification(resData.message || `[Demo Sandbox] Successfully added ${type === 'tv' ? 'TV Show' : 'Movie'} '${rawMeta.title}' to sandbox library!`, "success");
                if (discoveryItem) {
                    discoveryItem.is_in_library = true;
                    renderMediaLists();
                }
                if (searchCard) {
                    const addBtn = searchCard.querySelector(".btn-search-add");
                    if (addBtn) {
                        addBtn.textContent = "In Library";
                        addBtn.disabled = true;
                        addBtn.className = "btn btn-secondary btn-added btn-search-add";
                    }
                    const badges = searchCard.querySelector(".card-badges");
                    if (badges && !badges.querySelector(".badge-in-library")) {
                        const badge = document.createElement("span");
                        badge.className = "badge badge-in-library";
                        badge.textContent = "In Library";
                        badges.appendChild(badge);
                    }
                }
            } else {
                addNotification(`Failed to add '${rawMeta.title}': ${resData.message || "Unknown error."}`, "error");
            }
        } catch (error) {
            loadingOverlay.classList.add("hidden");
            addNotification(`Connection error: ${error.message}`, "error");
        }
        return;
    }


    const checkTrackCollection = document.getElementById("check-track-collection");
    const payload = {
        type: type,
        raw_metadata: rawMeta,
        folder: selectFolder.value,
        profile_id: selectProfile.value,
        monitored: checkMonitored.checked,
        search_now: (searchNow !== null) ? searchNow : checkSearch.checked,
        add_collection: (type === "movie" && checkTrackCollection && checkTrackCollection.checked)
    };

    // Close options modal and show spinner
    closeModal();
    loadingOverlay.classList.remove("hidden");
    loadingText.textContent = `Adding '${rawMeta.title}'...`;

    try {
        const resData = await moduleAddMedia(payload);
        loadingOverlay.classList.add("hidden");

        if ((resData.ok ?? true) && resData.status === "success") {
            addNotification(resData.message || `Successfully queued '${rawMeta.title}' for download!`, "success");
            // Mark item as added in memory and re-render using the captured reference
            discoveryItem.is_in_library = true;
            renderMediaLists();
            
            // If this was from a global search card, update the card's button in-place
            if (searchCard) {
                const addBtn = searchCard.querySelector(".btn-search-add");
                if (addBtn) {
                    addBtn.textContent = "In Library";
                    addBtn.disabled = true;
                    addBtn.className = "btn btn-secondary btn-added btn-search-add";
                }
                // Add an "In Library" badge
                const badges = searchCard.querySelector(".card-badges");
                if (badges && !badges.querySelector(".badge-in-library")) {
                    const badge = document.createElement("span");
                    badge.className = "badge badge-in-library";
                    badge.textContent = "In Library";
                    badges.appendChild(badge);
                }
            }
        } else {
            addNotification(`Failed to add '${rawMeta.title}': ${resData.message || "Unknown error."}`, "error");
        }
    } catch (error) {
        loadingOverlay.classList.add("hidden");
        addNotification(`Connection error: ${error.message}`, "error");
    }
}

// 4. Archive / Unarchive Item
async function toggleArchive(type, item) {
    const isArchiving = !item.is_archived;
    
    try {
        const resData = await moduleArchiveItem({
            type: type,
            title: item.title,
            year: item.year,
            archive: isArchiving,
            raw_item: item
        });
        
        if ((resData.ok ?? true) && resData.status === "success") {
            item.is_archived = isArchiving;
            if (isArchiving) {
                item.has_new_metadata = false;
            }
            addNotification(`Successfully ${isArchiving ? 'archived' : 'unarchived'} '${item.title}'.`, "success");
            renderMediaLists();
        } else {
            addNotification(`Failed to archive '${item.title}': ${resData.message || "Unknown error."}`, "error");
        }
    } catch (error) {
        addNotification(`Archive error: ${error.message}`, "error");
    }
}

// 5. Refresh Metadata for a single item
async function refreshMetadata(type, item, refreshBtn, card) {
    if (refreshBtn.classList.contains("loading")) return;
    
    refreshBtn.classList.add("loading");
    refreshBtn.disabled = true;
    
    try {
        const data = await moduleRefreshCacheItem({
            type: type,
            title: item.title,
            year: item.year,
            imdbId: item.imdbId || item.imdb_id
        });
        
        if ((data.ok ?? true) && data.status === "success" && data.item) {
            // Find the item index in currentDiscoveries
            const list = type === "tv" ? currentDiscoveries.tv : currentDiscoveries.movies;
            const index = list.findIndex(i => i.title === item.title && i.year === item.year);
            if (index !== -1) {
                // Keep the date_str and is_returning and other scraper fields if the refreshed object missed them
                const updated = data.item;
                if (!updated.date_str && item.date_str) {
                    updated.date_str = item.date_str;
                }
                if (updated.is_returning === undefined && item.is_returning !== undefined) {
                    updated.is_returning = item.is_returning;
                }
                list[index] = updated;
            }
            addNotification(`Successfully refreshed metadata for '${item.title}'.`, "success");
            renderMediaLists();
        } else {
            addNotification(`Failed to refresh metadata for '${item.title}': ${data.message || "Unknown error."}`, "error");
        }
    } catch (error) {
        addNotification(`Refresh error: ${error.message}`, "error");
    } finally {
        refreshBtn.classList.remove("loading");
        refreshBtn.disabled = false;
    }
}

// 6. Save settings to server
async function saveSettings() {
    const payload = {
        radarr_url: inputRadarrUrl.value.trim(),
        radarr_api_key: inputRadarrKey.value.trim(),
        radarr_default_root_folder: selectRadarrDefaultFolder ? selectRadarrDefaultFolder.value : "",
        radarr_default_quality_profile: selectRadarrDefaultProfile ? selectRadarrDefaultProfile.value : "",
        sonarr_url: inputSonarrUrl.value.trim(),
        sonarr_api_key: inputSonarrKey.value.trim(),
        tmdb_api_key: inputTmdbKey ? inputTmdbKey.value.trim() : "",
        sonarr_default_root_folder: selectSonarrDefaultFolder ? selectSonarrDefaultFolder.value : "",
        sonarr_default_quality_profile: selectSonarrDefaultProfile ? selectSonarrDefaultProfile.value : "",
        default_past_months: inputPastMonths.value,
        default_future_months: inputFutureMonths.value,
        default_show_returning: document.getElementById("input-show-returning").checked ? "1" : "0",
        default_show_library: document.getElementById("input-show-library").checked ? "1" : "0",
        default_show_archived: document.getElementById("input-show-archived").checked ? "1" : "0",
        default_match_ignore_year: document.getElementById("input-match-ignore-year").checked ? "1" : "0"
    };
    
    closeSettingsModal();
    loadingOverlay.classList.remove("hidden");
    loadingText.textContent = "Saving settings...";
    
    try {
        const resData = await moduleSaveSettings(payload);
        loadingOverlay.classList.add("hidden");
        
        if ((resData.ok ?? true) && resData.status === "success") {
            addNotification("Configuration settings updated successfully.", "success");
            // Reload settings and configurations from server without reopening settings modal
            await loadSettingsAndConfig(false);
        } else {
            addNotification(`Failed to save settings: ${resData.message || "Unknown error."}`, "error");
        }
    } catch (error) {
        loadingOverlay.classList.add("hidden");
        addNotification(`Failed to connect: ${error.message}`, "error");
    }
}

// --- DOM Rendering ---

function renderMediaLists() {
    gridTv.innerHTML = "";
    gridMovies.innerHTML = "";

    const searchTerm = searchBar.value.toLowerCase().trim();
    const showReturning = document.getElementById("check-show-returning").checked;
    const showLibrary = document.getElementById("check-show-library").checked;
    const showArchived = document.getElementById("check-show-archived").checked;

    // 1. Render TV shows
    const tvMatches = currentDiscoveries.tv.filter(item => itemPassesFilters(item, "tv"));

    const sortVal = selectSort ? selectSort.value : "date-asc";
    const sortItems = (a, b) => {
        if (sortVal.startsWith("date")) {
            const dateA = a.date_obj || "";
            const dateB = b.date_obj || "";
            if (sortVal === "date-asc") {
                return dateA.localeCompare(dateB) || a.title.localeCompare(b.title);
            } else {
                return dateB.localeCompare(dateA) || a.title.localeCompare(b.title);
            }
        } else if (sortVal.startsWith("title")) {
            const titleA = a.title || "";
            const titleB = b.title || "";
            if (sortVal === "title-asc") {
                return titleA.localeCompare(titleB);
            } else {
                return titleB.localeCompare(titleA);
            }
        } else if (sortVal.startsWith("studio")) {
            const netA = a.network || "";
            const netB = b.network || "";
            if (sortVal === "studio-asc") {
                return netA.localeCompare(netB) || a.title.localeCompare(b.title);
            } else {
                return netB.localeCompare(netA) || a.title.localeCompare(b.title);
            }
        }
        return 0;
    };
    tvMatches.sort(sortItems);

    tvMatches.forEach((item, index) => {
        // Since we filtered tvMatches, the index in tvMatches is different from currentDiscoveries.tv.
        // We find the original index in currentDiscoveries.tv
        const origIndex = currentDiscoveries.tv.indexOf(item);
        const card = createMediaCard(item, "tv", origIndex);
        gridTv.appendChild(card);
    });
    
    if (tvMatches.length === 0) {
        gridTv.innerHTML = `<div class="empty-state">No matching TV shows found.</div>`;
    }

    // 2. Render Movies
    const movieMatches = currentDiscoveries.movies.filter(item => itemPassesFilters(item, "movie"));
    movieMatches.sort(sortItems);
    movieMatches.forEach((item, index) => {
        const origIndex = currentDiscoveries.movies.indexOf(item);
        const card = createMediaCard(item, "movie", origIndex);
        gridMovies.appendChild(card);
    });

    if (movieMatches.length === 0) {
        gridMovies.innerHTML = `<div class="empty-state">No matching movies found.</div>`;
    }

    // Apply active view tab filters
    applyTabFilter();
}

function getFilterState() {
    const searchInput = document.getElementById("search-bar");
    const term = searchInput ? searchInput.value : (typeof searchBar !== "undefined" && searchBar ? searchBar.value : "");
    const returningEl = document.getElementById("check-show-returning");
    const libraryEl = document.getElementById("check-show-library");
    const archivedEl = document.getElementById("check-show-archived");
    return {
        showReturning: returningEl ? returningEl.checked : false,
        showLibrary: libraryEl ? libraryEl.checked : false,
        showArchived: archivedEl ? archivedEl.checked : false,
        searchTerm: term ? term.toLowerCase().trim() : "",
        genres: typeof selectedGenres !== "undefined" ? selectedGenres : new Set(),
        networks: typeof selectedNetworks !== "undefined" ? selectedNetworks : new Set(),
        countries: typeof selectedCountries !== "undefined" ? selectedCountries : new Set(),
        languages: typeof selectedLanguages !== "undefined" ? selectedLanguages : new Set()
    };
}

// Every sidebar filter (toggles, search, genre, studio, country, language) in one place.
function itemPassesFilters(item, type) {
    return moduleItemPassesFilters(item, type, getFilterState());
}

// Items the user currently sees (respecting the active tab) that are not archived yet.
function getFilteredUnarchived() {
    const activeTabEl = document.querySelector(".tab-btn.active");
    const activeTab = activeTabEl ? activeTabEl.getAttribute("data-tab") : "all";
    return moduleGetFilteredUnarchived(currentDiscoveries, activeTab, getFilterState());
}

async function archiveAllFiltered() {
    const targets = getFilteredUnarchived();
    if (targets.length === 0) {
        addNotification("No un-archived items match the current filters.", "info");
        return;
    }
    if (!confirm(`Archive ${targets.length} filtered item${targets.length === 1 ? "" : "s"}?`)) return;
    try {
        const batchItems = targets.map(t => ({ type: t.type, title: t.item.title, year: t.item.year, raw_item: t.item }));
        const res = await moduleArchiveBatch(batchItems, true);
        const failedTitles = new Set((res.failed || []).map(f => f.title));
        targets.forEach(t => {
            if (!failedTitles.has(t.item.title)) {
                t.item.is_archived = true;
                t.item.has_new_metadata = false;
            }
        });
        if (res.failed && res.failed.length) {
            addNotification(`Archived ${res.archived}, failed ${res.failed.length}.`, "error");
        } else {
            addNotification(`Archived ${res.archived} item${res.archived === 1 ? "" : "s"}.`, "success");
        }
        renderMediaLists();
    } catch (error) {
        addNotification(`Archive error: ${error.message}`, "error");
    }
}

function matchFilter(item, term) {
    return moduleMatchFilter(item, term);
}

function buildRatingBadgesHtml(item) {
    return moduleBuildRatingBadgesHtml(item);
}

// Badge template reference: item.has_new_metadata ? '<span class="badge badge-new-metadata">New metadata</span>' : ''
function createMediaCard(item, type, index) {
    const card = document.createElement("div");
    card.className = "media-card";
    
    const isAdded = item.is_in_library;
    card.innerHTML = moduleBuildMediaCardHtml(item, type, { isAdded, index });
    
    // Add click handler for plot expansion
    const plotDiv = card.querySelector(".card-plot");
    const moreBtn = card.querySelector(".plot-more-btn");
    if (moreBtn && plotDiv) {
        moreBtn.addEventListener("click", () => {
            const isExpanded = plotDiv.classList.contains("expanded");
            const hiddenSpan = plotDiv.querySelector(".plot-hidden");
            const ellipsis = plotDiv.querySelector(".plot-ellipsis");
            if (isExpanded) {
                plotDiv.classList.remove("expanded");
                hiddenSpan.classList.add("hidden");
                ellipsis.classList.remove("hidden");
                moreBtn.textContent = "more";
            } else {
                plotDiv.classList.add("expanded");
                hiddenSpan.classList.remove("hidden");
                ellipsis.classList.add("hidden");
                moreBtn.textContent = "less";
            }
        });
    }
    
    // Bind click event on Details Toggle
    const toggleBtn = card.querySelector(".btn-details-toggle");
    const detailsPanel = card.querySelector(".card-details-panel");
    if (toggleBtn && detailsPanel) {
        toggleBtn.addEventListener("click", () => {
            const isHidden = detailsPanel.classList.contains("hidden");
            if (isHidden) {
                detailsPanel.classList.remove("hidden");
                toggleBtn.textContent = "Hide ▴";
                toggleBtn.style.color = "var(--accent-magenta)";
            } else {
                detailsPanel.classList.add("hidden");
                toggleBtn.textContent = "Show ▾";
                toggleBtn.style.color = "var(--accent-blue)";
            }
        });
    }

    // Bind click event on Refresh Metadata
    const refreshBtn = card.querySelector(".btn-refresh-icon");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            refreshMetadata(type, item, refreshBtn, card);
        });
    }

    // Bind click event on Archive
    const archiveBtn = card.querySelector(".btn-archive");
    if (archiveBtn) {
        archiveBtn.addEventListener("click", () => {
            toggleArchive(type, item);
        });
    }
    
    return card;
}

// --- Event Handlers & Modal Controllers ---

async function openAddModal(type, index) {
    const item = type === "tv" ? currentDiscoveries.tv[index] : currentDiscoveries.movies[index];
    selectedItemForAdd = { type, item };

    if (!appConfig) {
        alert("Server configuration is not loaded yet.");
        return;
    }

    const targetConfig = type === "tv" ? appConfig.sonarr : appConfig.radarr;
    if (!targetConfig.configured) {
        openDemoAddModal(type, item, index, null);
        return;
    }

    // Step 1 UI Setup: Show Search match list, hide Options select
    isMarkInLibraryMode = false;
    linkHelperBanner.classList.add("hidden");
    btnModalMarkLibrary.classList.remove("hidden");
    btnModalMarkLibrary.classList.remove("btn-modal-mark-library-active");
    btnModalMarkLibrary.textContent = "Mark In Library";

    modalTitle.textContent = `Search Indexer for '${item.title}'`;
    modalStepSearch.classList.remove("hidden");
    modalStepOptions.classList.add("hidden");
    btnModalBack.classList.add("hidden");
    btnModalConfirm.classList.add("hidden");
    
    lookupLoading.classList.remove("hidden");
    lookupResultsList.classList.add("hidden");
    lookupResultsList.innerHTML = "";

    modalOverlay.classList.remove("hidden");

    // Perform Live Indexer Lookup
    try {
        const data = await moduleLookupMedia(type, item.title);
        
        lookupLoading.classList.add("hidden");
        lookupResultsList.classList.remove("hidden");
        
        if ((data.ok ?? true) && data.status === "success" && data.results && data.results.length > 0) {
            renderLookupResults(data.results, type, item);
        } else {
            lookupResultsList.innerHTML = `<div class="lookup-status">No results found on indexers. Please check title manually.</div>`;
        }
    } catch (error) {
        lookupLoading.classList.add("hidden");
        lookupResultsList.innerHTML = `<div class="lookup-status">Error loading indexers: ${escapeHtml(error.message)}</div>`;
    }
}

function renderLookupResults(results, type, discoveryItem) {
    lookupResultsList.innerHTML = "";
    
    results.forEach(res => {
        const itemRow = document.createElement("div");
        itemRow.className = "lookup-item";
        
        // 1. Library Status check
        const inLibrary = res.id ? true : false;
        const statusBadge = inLibrary 
            ? `<span class="lookup-item-status status-exists">In Library</span>` 
            : `<span class="lookup-item-status status-not-exists">Not Added</span>`;
            
        // 2. Best Match Logic
        let isBestMatch = false;
        const resId = type === "tv" ? res.tvdbId : res.tmdbId;
        const discoveryId = type === "tv" ? discoveryItem.tvdbId : discoveryItem.tmdbId;
        
        const resImdbId = res.imdbId;
        const discoveryImdbId = discoveryItem.imdbId;
        
        const stripYearSuffix = (t) => (t || "").replace(/\s*[\(\[]\d{4}[\)\]]?$/, "").trim().toLowerCase();
        if (discoveryId && resId && String(discoveryId) === String(resId)) {
            isBestMatch = true;
        } else if (discoveryImdbId && resImdbId && String(discoveryImdbId).toLowerCase() === String(resImdbId).toLowerCase()) {
            isBestMatch = true;
        } else if (
            (res.title.toLowerCase() === discoveryItem.title.toLowerCase() ||
             stripYearSuffix(res.title) === stripYearSuffix(discoveryItem.title)) &&
            Math.abs(res.year - discoveryItem.year) <= 1
        ) {
            isBestMatch = true;
        }

        if (isBestMatch) {
            itemRow.classList.add("best-match");
        }

        const idLabel = type === "tv" ? `TVDB ID: ${res.tvdbId || 'N/A'}` : `TMDB ID: ${res.tmdbId || 'N/A'}`;
        const collectionName = res.collection ? (res.collection.title || res.collection.name) : null;
        const collectionBadge = (type === "movie" && collectionName)
            ? `<span class="badge" style="background: rgba(0, 210, 255, 0.08); color: var(--accent-blue); border: 1px solid rgba(0, 210, 255, 0.2); font-size: 10px; padding: 2px 6px; border-radius: 4px; display: inline-flex; align-items: center; text-transform: none; margin: 0;">📦 ${escapeHtml(collectionName)}</span>`
            : '';

        itemRow.innerHTML = `
            <div class="lookup-item-details">
                <div class="lookup-item-title">
                    ${escapeHtml(res.title)}
                    ${isBestMatch ? '<span class="auto-match-tag">Auto Match</span>' : ''}
                </div>
                <div class="lookup-item-meta" style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 4px;">
                    <span class="year-badge">${escapeHtml(res.year || 'N/A')}</span>
                    <span class="id-badge">${escapeHtml(idLabel)}</span>
                    ${collectionBadge}
                </div>
            </div>
            ${statusBadge}
        `;
        
        // Bind Click handler to select and transition to Step 2
        // Bind Click handler to select and transition to Step 2
        itemRow.addEventListener("click", () => {
            if (isMarkInLibraryMode) {
                linkDiscoveryToLibrary(res, discoveryItem);
                return;
            }
            if (inLibrary) {
                alert(`'${res.title}' is already in your library!`);
                return;
            }
            goToOptionsStep(res);
        });
        
        lookupResultsList.appendChild(itemRow);
    });
}

async function linkDiscoveryToLibrary(metadataItem, discoveryItem) {
    const type = selectedItemForAdd.type;
    try {
        const data = await moduleLinkLibrary({
            type: type,
            title: discoveryItem.title,
            year: discoveryItem.year,
            imdbId: discoveryItem.imdbId,
            link_metadata: metadataItem
        });
        if ((data.ok ?? true) && data.status === "success") {
            // Update local memory
            discoveryItem.is_in_library = true;
            discoveryItem.tvdbId = metadataItem.tvdbId || discoveryItem.tvdbId;
            discoveryItem.tmdbId = metadataItem.tmdbId || discoveryItem.tmdbId;
            discoveryItem.imdbId = metadataItem.imdbId || discoveryItem.imdbId;
            
            modalOverlay.classList.add("hidden");
            alert(data.message);
            renderMediaLists();
        } else {
            alert(`Link failed: ${data.message}`);
        }
    } catch (error) {
        alert(`Link error: ${error.message}`);
    }
}

const renderDiscoveries = renderMediaLists;

// Transition to Step 2 (Download path and profile options)
function goToOptionsStep(metadataItem) {
    selectedItemForAdd.raw_metadata = metadataItem;
    const type = selectedItemForAdd.type;
    
    let targetConfig;
    if (selectedItemForAdd.isDemo) {
        targetConfig = {
            folders: [
                { path: "/data/media/Movies" },
                { path: "/data/media/Kids" }
            ],
            profiles: [
                { id: 1, name: "Any (Default)" },
                { id: 2, name: "Ultra-HD 4K" },
                { id: 3, name: "HD - 1080p/720p" }
            ]
        };
    } else {
        targetConfig = type === "tv" ? appConfig.sonarr : appConfig.radarr;
    }

    modalTitle.textContent = `${selectedItemForAdd.isDemo ? '[Demo Sandbox] ' : ''}Configure Download: ${metadataItem.title}`;
    
    // Clear selects
    selectFolder.innerHTML = "";
    selectProfile.innerHTML = "";

    // Populate Folder Paths
    if (targetConfig && targetConfig.folders) {
        targetConfig.folders.forEach(f => {
            const opt = document.createElement("option");
            opt.value = f.path;
            opt.textContent = f.path;
            selectFolder.appendChild(opt);
        });
    }

    if (targetConfig && targetConfig.profiles) {
        targetConfig.profiles.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p.id;
            opt.textContent = p.name;
            selectProfile.appendChild(opt);
        });
    }

    // Pre-select Quality Profile and Root Folder using 3-tier Hybrid Preset Algorithm
    const prefix = type === "tv" ? "sonarr" : "radarr";
    const explicitFolder = appSettings ? appSettings[`${prefix}_default_root_folder`] : null;
    const explicitProfile = appSettings ? appSettings[`${prefix}_default_quality_profile`] : null;

    const selectedFolder = resolveHybridPreset(
        targetConfig ? targetConfig.folders : [],
        "path",
        explicitFolder,
        `xarrtools_mru_${prefix}_folder`
    );
    if (selectedFolder) {
        selectFolder.value = selectedFolder;
    }

    const selectedProfile = resolveHybridPreset(
        targetConfig ? targetConfig.profiles : [],
        "id",
        explicitProfile,
        `xarrtools_mru_${prefix}_profile`
    );
    if (selectedProfile) {
        selectProfile.value = selectedProfile;
    }

    // Handle Track Collection Box Set options (Radarr movie collections)
    const groupTrackCollection = document.getElementById("group-track-collection");
    const checkTrackCollection = document.getElementById("check-track-collection");
    const lblCollectionName = document.getElementById("lbl-collection-name");
    
    const collectionName = metadataItem.collection ? (metadataItem.collection.title || metadataItem.collection.name) : null;
    if (type === "movie" && collectionName) {
        if (groupTrackCollection && checkTrackCollection && lblCollectionName) {
            lblCollectionName.textContent = collectionName;
            checkTrackCollection.checked = false; // Default to false
            groupTrackCollection.classList.remove("hidden");
        }
    } else {
        if (groupTrackCollection && checkTrackCollection) {
            groupTrackCollection.classList.add("hidden");
            checkTrackCollection.checked = false;
        }
    }

    // Transition Screens
    modalStepSearch.classList.add("hidden");
    modalStepOptions.classList.remove("hidden");
    btnModalBack.classList.remove("hidden");
    btnModalMarkLibrary.classList.add("hidden");
    if (btnModalAddOnly) btnModalAddOnly.classList.remove("hidden");
    btnModalConfirm.classList.remove("hidden");
}

function goBackToSearchStep() {
    if (!selectedItemForAdd) return;
    
    modalTitle.textContent = `Search Indexer for '${selectedItemForAdd.item.title}'`;
    modalStepSearch.classList.remove("hidden");
    modalStepOptions.classList.add("hidden");
    btnModalBack.classList.add("hidden");
    btnModalMarkLibrary.classList.remove("hidden");
    if (btnModalAddOnly) btnModalAddOnly.classList.add("hidden");
    btnModalConfirm.classList.add("hidden");
}

window.openAddModal = openAddModal; // Expose to global window scope for inline onclicks

function closeModal() {
    modalOverlay.classList.add("hidden");
    selectedItemForAdd = null;
}

// Helper to populate settings select elements
function populateSettingsSelect(selectEl, items, valueProp, textProp, currentValue) {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "None (Use Most-Recently-Used)";
    selectEl.appendChild(defaultOpt);

    let matchFound = false;
    if (items && Array.isArray(items)) {
        items.forEach(item => {
            const opt = document.createElement("option");
            opt.value = item[valueProp];
            opt.textContent = item[textProp];
            selectEl.appendChild(opt);
            if (currentValue !== undefined && currentValue !== null && String(item[valueProp]).trim() === String(currentValue).trim()) {
                matchFound = true;
            }
        });
    }

    if (matchFound && currentValue !== undefined && currentValue !== null && String(currentValue).trim() !== "") {
        selectEl.value = String(currentValue);
    } else {
        selectEl.value = "";
    }
}

window.populateSettingsSelect = populateSettingsSelect;

// Settings Modal controls
function openSettingsModal() {
    if (appSettings) {
        inputRadarrUrl.value = appSettings.radarr_url || "";
        inputRadarrKey.value = appSettings.radarr_api_key || "";
        inputSonarrUrl.value = appSettings.sonarr_url || "";
        inputSonarrKey.value = appSettings.sonarr_api_key || "";
        if (inputTmdbKey) inputTmdbKey.value = appSettings.tmdb_api_key || "";
        inputPastMonths.value = appSettings.default_past_months || "1";
        inputFutureMonths.value = appSettings.default_future_months || "2";
        document.getElementById("input-show-returning").checked = appSettings.default_show_returning === "1";
        document.getElementById("input-show-library").checked = appSettings.default_show_library === "1";
        document.getElementById("input-show-archived").checked = appSettings.default_show_archived === "1";
        document.getElementById("input-match-ignore-year").checked = appSettings.default_match_ignore_year !== "0";
    }

    // Populate Radarr & Sonarr default folder and quality profile dropdowns
    populateSettingsSelect(
        selectRadarrDefaultFolder,
        appConfig?.radarr?.folders,
        "path",
        "path",
        appSettings ? appSettings.radarr_default_root_folder : ""
    );
    populateSettingsSelect(
        selectRadarrDefaultProfile,
        appConfig?.radarr?.profiles,
        "id",
        "name",
        appSettings ? (appSettings.radarr_default_quality_profile || appSettings.radarr_default_profile_id || "") : ""
    );
    populateSettingsSelect(
        selectSonarrDefaultFolder,
        appConfig?.sonarr?.folders,
        "path",
        "path",
        appSettings ? appSettings.sonarr_default_root_folder : ""
    );
    populateSettingsSelect(
        selectSonarrDefaultProfile,
        appConfig?.sonarr?.profiles,
        "id",
        "name",
        appSettings ? (appSettings.sonarr_default_quality_profile || appSettings.sonarr_default_profile_id || "") : ""
    );
    
    // Set theme selector value inside View Options tab to current theme
    const selectTheme = document.getElementById("select-theme-mode");
    if (selectTheme) {
        const currentTheme = localStorage.getItem("xarrtools-theme") || "dark";
        selectTheme.value = currentTheme;
    }
    
    // Reset active tab to Servers
    const firstTabBtn = document.querySelector(".settings-tab-btn[data-tab='panel-connections']");
    if (firstTabBtn) {
        firstTabBtn.click();
    }
    
    // Refresh stats
    loadCacheStats();
    
    settingsOverlay.classList.remove("hidden");
}

function closeSettingsModal() {
    settingsOverlay.classList.add("hidden");
}

async function loadCacheStats() {
    try {
        const data = await moduleFetchCacheStats();
        if (data.ok) {
            document.getElementById("stat-total-cache").textContent = data.total_discoveries;
            document.getElementById("stat-archived-cache").textContent = data.archived_discoveries;
            document.getElementById("stat-db-size").textContent = data.database_size;
        }
    } catch (error) {
        console.error("Failed to load cache stats:", error);
    }
}

async function pruneCacheManually() {
    if (!confirm("Are you sure you want to run cache pruning? This deletes cached releases older than 12 months.")) {
        return;
    }
    
    try {
        const data = await modulePruneCache();
        if ((data.ok ?? true) && data.status === "success") {
            addNotification(data.message, "success");
            await loadCacheStats();
        } else {
            addNotification(`Pruning failed: ${data.message}`, "error");
        }
    } catch (error) {
        addNotification(`Connection error: ${error.message}`, "error");
    }
}

async function wipeCacheManually() {
    if (!confirm("🚨 WARNING: Are you sure you want to wipe all discoveries from the local cache? This will clear all data, and you will need to re-scan to view them.")) {
        return;
    }
    
    try {
        const data = await moduleClearCache();
        if ((data.ok ?? true) && data.status === "success") {
            addNotification(data.message, "success");
            await loadCacheStats();
            
            // Clear current view
            currentDiscoveries.tv = [];
            currentDiscoveries.movies = [];
            renderMediaLists();
            
            // If they are wiped, show the welcome state again since there's no data
            document.getElementById("content-area").classList.add("hidden");
            document.getElementById("welcome-state").classList.remove("hidden");
        } else {
            addNotification(`Wipe failed: ${data.message}`, "error");
        }
    } catch (error) {
        addNotification(`Connection error: ${error.message}`, "error");
    }
}

function exportBackup() {
    const includeMedia = confirm("Include cached media details (identifiers & library indicators) in the backup JSON file?");
    window.location.href = moduleGetBackupExportUrl(includeMedia);
}

function triggerBackupImport() {
    const fileInput = document.getElementById("file-backup-import");
    if (fileInput) fileInput.click();
}

async function importBackup(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    const btnImport = document.getElementById("btn-backup-import");
    const originalText = btnImport.textContent;
    btnImport.textContent = "⏳ Importing...";
    btnImport.disabled = true;
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
        const data = await moduleImportBackup(formData);
        if ((data.ok ?? true) && data.status === "success") {
            alert(`Backup imported successfully!\n\nImported/Updated:\n- Settings: ${data.settings_count}\n- Media Items: ${data.media_count}`);
            location.reload();
        } else {
            alert(`Failed to import backup: ${data.message}`);
        }
    } catch (error) {
        alert(`Error importing backup: ${error.message}`);
    } finally {
        btnImport.textContent = originalText;
        btnImport.disabled = false;
        e.target.value = "";
    }
}


// --- Custom Feeds Management ---

const DEFAULT_PARSER_CONFIGS = {
    rss: {
        item_selector: "item",
        mappings: {
            title: { selector: "title" },
            year: { selector: "filmYear", transforms: [{ type: "regex_search", pattern: "\\d{4}" }] },
            date_str: { selector: "pubDate" },
            href: { selector: "link" }
        }
    },
    json: {
        item_selector: "$",
        mappings: {
            title: { selector: "title" },
            year: { selector: "year" },
            href: { selector: "url" }
        }
    },
    html: {
        item_selector: "table.wikitable tbody tr",
        mappings: {
            title: { selector: "td i a", extract: "text" },
            year: { selector: "td", extract: "text", transforms: [{ type: "regex_search", pattern: "\\d{4}" }] },
            href: { selector: "td i a", extract: "attribute", attribute_name: "href" }
        }
    }
};

let customFeedsList = [];

async function loadCustomFeeds() {
    const tableBody = document.getElementById("feeds-table-body");
    if (!tableBody) return;
    
    tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--text-secondary);"><div class="spinner-small" style="display:inline-block; vertical-align:middle; margin-right:8px;"></div> Loading feeds...</td></tr>`;
    
    try {
        const data = await moduleFetchFeeds();
        
        if (data.status === "success") {
            customFeedsList = data.feeds || [];
            if (customFeedsList.length === 0) {
                tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--text-secondary);">No custom feeds configured.</td></tr>`;
                return;
            }
            
            tableBody.innerHTML = "";
            customFeedsList.forEach(feed => {
                const tr = document.createElement("tr");
                tr.style.borderBottom = "1px solid var(--border-color)";
                
                // Status Badge
                let statusBadge = "";
                let errorTooltip = "";
                if (feed.last_status === "success") {
                    statusBadge = `<span class="badge" style="background: rgba(0, 255, 135, 0.1); color: var(--accent-green); border: 1px solid rgba(0, 255, 135, 0.25); font-size:10px; padding:2px 6px;">Success</span>`;
                } else if (feed.last_status === "error") {
                    errorTooltip = feed.last_error_message ? `title="${escapeHtml(feed.last_error_message)}"` : "";
                    statusBadge = `<span class="badge" style="background: rgba(255, 0, 80, 0.1); color: #ff0050; border: 1px solid rgba(255, 0, 80, 0.25); font-size:10px; padding:2px 6px; cursor:help;" ${errorTooltip}>Error ⚠️</span>`;
                } else {
                    statusBadge = `<span class="badge" style="background: rgba(255, 255, 255, 0.05); color: var(--text-secondary); border: 1px solid var(--border-color); font-size:10px; padding:2px 6px;">Never</span>`;
                }
                
                // Enabled style indicator
                const enabledStyle = feed.enabled === 1 ? "" : "opacity: 0.5; text-decoration: line-through;";
                
                tr.innerHTML = `
                    <td style="padding: 8px; font-weight: 500; color: var(--text-primary); max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; ${enabledStyle}">${escapeHtml(feed.name)}</td>
                    <td style="padding: 8px; text-transform: uppercase; font-size: 11px; color: var(--text-secondary);">${escapeHtml(feed.feed_type)}</td>
                    <td style="padding: 8px;">${statusBadge}</td>
                    <td style="padding: 8px; text-align: right; white-space: nowrap;">
                        <button type="button" class="btn btn-secondary btn-feed-row-edit" data-feed-id="${escapeHtml(feed.id)}" style="font-size:11px; padding:2px 6px; margin:0 4px 0 0; width:auto; display:inline-block;">Edit</button>
                        <button type="button" class="btn btn-feed-row-delete" data-feed-id="${escapeHtml(feed.id)}" data-feed-name="${escapeHtml(feed.name)}" style="background: rgba(255, 42, 133, 0.1); border: 1px solid rgba(255, 42, 133, 0.3); color: var(--accent-magenta); font-size:11px; padding:2px 6px; margin:0; width:auto; display:inline-block;">&times;</button>
                    </td>
                `;
                
                tr.querySelector(".btn-feed-row-edit").addEventListener("click", () => {
                    openFeedEditor(feed);
                });
                tr.querySelector(".btn-feed-row-delete").addEventListener("click", () => {
                    deleteCustomFeed(feed.id, feed.name);
                });
                
                tableBody.appendChild(tr);
            });
        } else {
            tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--accent-magenta);">Error loading feeds: ${escapeHtml(data.message)}</td></tr>`;
        }
    } catch (err) {
        tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--accent-magenta);">Fetch failed: ${escapeHtml(err.message)}</td></tr>`;
    }
}

function openFeedEditor(feed) {
    const listView = document.getElementById("feeds-list-view");
    const editorView = document.getElementById("feed-editor-view");
    
    if (!listView || !editorView) return;
    
    listView.classList.add("hidden");
    editorView.classList.remove("hidden");
    
    const feedId = document.getElementById("feed-id");
    const feedName = document.getElementById("feed-name");
    const feedUrl = document.getElementById("feed-url");
    const feedType = document.getElementById("feed-type");
    const feedMediaType = document.getElementById("feed-media-type");
    const feedEnabled = document.getElementById("feed-enabled");
    const feedHeaders = document.getElementById("feed-headers");
    const feedParserConfig = document.getElementById("feed-parser-config");
    const editorTitle = document.getElementById("feed-editor-title");
    
    // Hide diagnostics preview card
    document.getElementById("feed-test-preview").classList.add("hidden");
    
    if (feed) {
        editorTitle.textContent = "Edit Custom Feed";
        feedId.value = feed.id;
        feedName.value = feed.name || "";
        feedUrl.value = feed.url || "";
        feedType.value = feed.feed_type || "rss";
        feedMediaType.value = feed.default_media_type || "movie";
        feedEnabled.checked = feed.enabled === 1;
        
        let headersObj = {};
        try {
            headersObj = typeof feed.http_headers === 'string' ? JSON.parse(feed.http_headers) : (feed.http_headers || {});
        } catch (e) {
            headersObj = {};
        }
        feedHeaders.value = JSON.stringify(headersObj, null, 2);
        
        let configObj = {};
        try {
            configObj = typeof feed.parser_config === 'string' ? JSON.parse(feed.parser_config) : (feed.parser_config || {});
        } catch (e) {
            configObj = {};
        }
        feedParserConfig.value = JSON.stringify(configObj, null, 2);
    } else {
        editorTitle.textContent = "Add Custom Feed";
        feedId.value = "";
        feedName.value = "";
        feedUrl.value = "";
        feedType.value = "rss";
        feedMediaType.value = "movie";
        feedEnabled.checked = true;
        feedHeaders.value = "{}";
        feedParserConfig.value = JSON.stringify(DEFAULT_PARSER_CONFIGS.rss, null, 2);
    }
    
    switchEditorTab("feed-tab-general");
}

function closeFeedEditor() {
    const listView = document.getElementById("feeds-list-view");
    const editorView = document.getElementById("feed-editor-view");
    if (listView && editorView) {
        editorView.classList.add("hidden");
        listView.classList.remove("hidden");
        loadCustomFeeds();
    }
}

function switchEditorTab(tabId) {
    const tabButtons = document.querySelectorAll(".feed-tab-btn");
    const tabPanels = document.querySelectorAll(".feed-editor-tab-panel");
    
    tabButtons.forEach(btn => {
        if (btn.getAttribute("data-editor-tab") === tabId) {
            btn.classList.add("active");
            btn.style.color = "var(--accent-blue)";
        } else {
            btn.classList.remove("active");
            btn.style.color = "var(--text-secondary)";
        }
    });
    
    tabPanels.forEach(panel => {
        if (panel.id === tabId) {
            panel.classList.remove("hidden");
            if (tabId === "feed-tab-mapping") {
                panel.style.display = "flex";
            } else {
                panel.style.display = "block";
            }
        } else {
            panel.classList.add("hidden");
            panel.style.display = "none";
        }
    });
}

function handleFeedTypeChange() {
    const feedType = document.getElementById("feed-type").value;
    const parserConfigField = document.getElementById("feed-parser-config");
    
    // Clear parser config for built-in types
    if (["metacritic_tv", "metacritic_movie", "dvds_releases", "tvmaze_schedule", "tmdb_movies"].includes(feedType)) {
        parserConfigField.value = "{}";
        return;
    }
    
    const currentValue = parserConfigField.value.trim();
    let matchesDefault = false;
    
    try {
        const parsedCurrent = JSON.parse(currentValue);
        if (Object.keys(parsedCurrent).length === 0 || 
            (currentValue.includes("filmYear") && feedType !== "rss") ||
            (currentValue.includes("tbody tr") && feedType !== "html") ||
            (currentValue.includes("item_selector\": \"$\"") && feedType !== "json")
        ) {
            matchesDefault = true;
        }
    } catch (e) {
        matchesDefault = true;
    }
    
    if (matchesDefault && DEFAULT_PARSER_CONFIGS[feedType]) {
        parserConfigField.value = JSON.stringify(DEFAULT_PARSER_CONFIGS[feedType], null, 2);
    }
}

async function saveCustomFeed() {
    const feedId = document.getElementById("feed-id").value;
    const name = document.getElementById("feed-name").value.trim();
    const url = document.getElementById("feed-url").value.trim();
    const feedType = document.getElementById("feed-type").value;
    const defaultMediaType = document.getElementById("feed-media-type").value;
    const enabled = document.getElementById("feed-enabled").checked ? 1 : 0;
    const headersRaw = document.getElementById("feed-headers").value.trim();
    const configRaw = document.getElementById("feed-parser-config").value.trim();
    
    if (!name || !url) {
        alert("Please enter a feed name and URL.");
        return;
    }
    
    let httpHeaders = {};
    if (headersRaw) {
        try {
            httpHeaders = JSON.parse(headersRaw);
        } catch (e) {
            alert("HTTP Headers must be valid JSON object. Error: " + e.message);
            return;
        }
    }
    
    let parserConfig = {};
    try {
        parserConfig = JSON.parse(configRaw);
    } catch (e) {
        alert("Parser Config must be valid JSON object. Error: " + e.message);
        return;
    }
    
    if (!["metacritic_tv", "metacritic_movie", "dvds_releases", "tvmaze_schedule", "tmdb_movies"].includes(feedType)) {
        if (!parserConfig.mappings || !parserConfig.mappings.title) {
            alert("Parser config mappings must contain at least a 'title' selector rule.");
            return;
        }
    }
    
    const payload = {
        id: feedId ? parseInt(feedId) : null,
        name: name,
        url: url,
        feed_type: feedType,
        default_media_type: defaultMediaType,
        enabled: enabled,
        http_headers: httpHeaders,
        parser_config: parserConfig
    };
    
    try {
        const saveBtn = document.getElementById("btn-feed-save");
        if (saveBtn) saveBtn.disabled = true;
        
        const data = await moduleSaveFeed(payload);
        if (saveBtn) saveBtn.disabled = false;
        
        if ((data.ok ?? true) && data.status === "success") {
            addNotification(`Feed '${name}' saved successfully.`, "success");
            closeFeedEditor();
        } else {
            addNotification(`Save failed: ${data.message}`, "error");
        }
    } catch (err) {
        addNotification(`Connection error: ${err.message}`, "error");
        const saveBtn = document.getElementById("btn-feed-save");
        if (saveBtn) saveBtn.disabled = false;
    }
}

async function deleteCustomFeed(feedId, feedName) {
    if (!confirm(`Are you sure you want to delete the custom feed '${feedName}'?`)) {
        return;
    }
    
    try {
        const data = await moduleDeleteFeed(feedId);
        
        if ((data.ok ?? true) && data.status === "success") {
            addNotification(`Feed '${feedName}' deleted.`, "success");
            loadCustomFeeds();
        } else {
            addNotification(`Delete failed: ${data.message}`, "error");
        }
    } catch (err) {
        addNotification(`Connection error: ${err.message}`, "error");
    }
}

async function testCustomFeed() {
    const url = document.getElementById("feed-url").value.trim();
    const feedType = document.getElementById("feed-type").value;
    const defaultMediaType = document.getElementById("feed-media-type").value;
    const headersRaw = document.getElementById("feed-headers").value.trim();
    const configRaw = document.getElementById("feed-parser-config").value.trim();
    
    if (!url) {
        alert("Please enter a feed URL to test.");
        return;
    }
    
    let httpHeaders = {};
    if (headersRaw) {
        try {
            httpHeaders = JSON.parse(headersRaw);
        } catch (e) {
            alert("HTTP Headers must be valid JSON object. Error: " + e.message);
            return;
        }
    }
    
    let parserConfig = {};
    try {
        parserConfig = JSON.parse(configRaw);
    } catch (e) {
        alert("Parser Config must be valid JSON object. Error: " + e.message);
        return;
    }
    
    const previewCard = document.getElementById("feed-test-preview");
    const previewStats = document.getElementById("feed-test-stats");
    const previewResults = document.getElementById("feed-test-results");
    const testBtn = document.getElementById("btn-feed-test");
    
    previewCard.classList.remove("hidden");
    previewStats.textContent = "Testing...";
    previewResults.textContent = "Connecting to feed URL and running parsed mapping diagnostics. Please wait...";
    
    if (testBtn) testBtn.disabled = true;
    
    try {
        const data = await moduleTestFeed({
            url: url,
            feed_type: feedType,
            default_media_type: defaultMediaType,
            http_headers: httpHeaders,
            parser_config: parserConfig
        });
        if (testBtn) testBtn.disabled = false;
        
        if ((data.ok ?? true) && data.status === "success") {
            const timeMs = data.fetch_time_ms;
            const itemsCount = data.parsed_items_count;
            previewStats.textContent = `Success (${timeMs}ms)`;
            
            if (data.results && data.results.length > 0) {
                let text = `Total parsed: ${itemsCount} items. Showing first ${data.results.length}:\n\n`;
                data.results.forEach((item, idx) => {
                    const yearStr = item.year ? ` (${item.year})` : "";
                    const imdbStr = item.imdb_id ? ` [IMDb: ${item.imdb_id}]` : "";
                    text += `${idx + 1}. Title: "${item.title}"${yearStr}${imdbStr}\n`;
                    text += `   Link:  ${item.href || "N/A"}\n`;
                    if (item.description) {
                        text += `   Plot:  ${item.description}\n`;
                    }
                    text += `\n`;
                });
                previewResults.textContent = text;
            } else {
                previewResults.textContent = "Fetched successfully, but 0 items matched your mapping selectors.";
            }
        } else {
            previewStats.textContent = "Error";
            previewResults.textContent = `Dry-run test failed:\n${data.message || "Unknown error occurred"}`;
        }
    } catch (err) {
        if (testBtn) testBtn.disabled = false;
        previewStats.textContent = "Connection Failure";
        previewResults.textContent = `HTTP post request failed: ${err.message}`;
    }
}

async function restoreDefaultFeeds() {
    if (!confirm("Are you sure you want to restore all feeds to default? This will delete any custom feeds you have configured and bring back Metacritic and DVDs calendars.")) {
        return;
    }
    
    try {
        const data = await moduleRestoreDefaultFeeds();
        
        if ((data.ok ?? true) && data.status === "success") {
            addNotification("Default feeds restored successfully.", "success");
            loadCustomFeeds();
        } else {
            addNotification(`Restore failed: ${data.message}`, "error");
        }
    } catch (err) {
        addNotification(`Connection error: ${err.message}`, "error");
    }
}

function applyTabFilter() {
    const activeTab = document.querySelector(".tab-btn.active").getAttribute("data-tab");
    const noResultsContainer = document.getElementById("no-results-container");
    const sectionSearch = document.getElementById("section-search");
    
    // Handle Global Search tab
    if (activeTab === "search") {
        sectionTv.classList.add("hidden");
        sectionMovies.classList.add("hidden");
        if (noResultsContainer) noResultsContainer.classList.add("hidden");
        if (sectionSearch) sectionSearch.classList.remove("hidden");
        // Ensure content-area is visible even if no scan has been done
        contentArea.classList.remove("hidden");
        welcomeState.classList.add("hidden");
        return;
    }
    
    // Hide search section for non-search tabs
    if (sectionSearch) sectionSearch.classList.add("hidden");
    
    const searchTerm = searchBar.value.toLowerCase().trim();
    const showReturning = document.getElementById("check-show-returning").checked;
    const showLibrary = document.getElementById("check-show-library").checked;
    const showArchived = document.getElementById("check-show-archived").checked;
    
    const tvMatchesCount = currentDiscoveries.tv.filter(item => {
        if (!showReturning && item.is_returning) return false;
        if (!showLibrary && item.is_in_library) return false;
        if (!showArchived && item.is_archived) return false;
        if (!matchLocale(item)) return false;
        return matchFilter(item, searchTerm);
    }).length;
    
    const movieMatchesCount = currentDiscoveries.movies.filter(item => {
        if (!showLibrary && item.is_in_library) return false;
        if (!showArchived && item.is_archived) return false;
        if (!matchLocale(item)) return false;
        return matchFilter(item, searchTerm);
    }).length;
    
    let showTv = false;
    let showMovies = false;
    
    if (activeTab === "all") {
        showTv = tvMatchesCount > 0;
        showMovies = movieMatchesCount > 0;
    } else if (activeTab === "tv") {
        showTv = tvMatchesCount > 0;
        showMovies = false;
    } else if (activeTab === "movies") {
        showTv = false;
        showMovies = movieMatchesCount > 0;
    }
    
    if (showTv) {
        sectionTv.classList.remove("hidden");
    } else {
        sectionTv.classList.add("hidden");
    }
    
    if (showMovies) {
        sectionMovies.classList.remove("hidden");
    } else {
        sectionMovies.classList.add("hidden");
    }
    
    // If both sections are hidden, show the global "No Results" message
    if (!showTv && !showMovies) {
        if (noResultsContainer) {
            noResultsContainer.classList.remove("hidden");
        }
    } else {
        if (noResultsContainer) {
            noResultsContainer.classList.add("hidden");
        }
    }
}

// --- Global Media Search ---

async function runGlobalSearch() {
    const input = document.getElementById("global-search-input");
    const typeSelect = document.getElementById("global-search-type");
    const resultsGrid = document.getElementById("grid-search-results");
    const query = input.value.trim();
    
    if (!query) return;
    
    const type = typeSelect.value; // "movie" or "tv"
    
    // Show loading state
    resultsGrid.innerHTML = `
        <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
            <div class="spinner-small" style="margin: 0 auto 12px;"></div>
            <p>Searching ${type === 'tv' ? 'Sonarr' : 'Radarr'} for "${escapeHtml(query)}"...</p>
        </div>
    `;
    
    // Intercept if unconfigured to return demo search results
    const isConfigured = type === "tv" ? (appConfig && appConfig.sonarr.configured) : (appConfig && appConfig.radarr.configured);
    if (!isConfigured) {
        setTimeout(() => {
            const demoResults = getDemoSearchResults(query, type);
            resultsGrid.innerHTML = "";
            demoResults.forEach(res => {
                const card = createSearchCard(res, type);
                resultsGrid.appendChild(card);
            });
            addNotification(`[Demo Mode] Found ${demoResults.length} simulated result(s) for "${query}".`, "info");
        }, 600);
        return;
    }
    
    try {
        const data = await moduleLookupMedia(type, query);
        
        if ((data.ok ?? true) && data.status === "success" && data.results && data.results.length > 0) {
            resultsGrid.innerHTML = "";
            data.results.forEach(res => {
                const card = createSearchCard(res, type);
                resultsGrid.appendChild(card);
            });
            addNotification(`Found ${data.results.length} result(s) for "${query}".`, "info");
        } else {
            resultsGrid.innerHTML = `
                <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
                    <div class="empty-icon" style="font-size: 40px; margin-bottom: 12px;">🤷</div>
                    <p>No results found for "${escapeHtml(query)}". Try a different title or media type.</p>
                </div>
            `;
            addNotification(`No results found for "${query}".`, "info");
        }
    } catch (error) {
        resultsGrid.innerHTML = `
            <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
                <div class="empty-icon" style="font-size: 40px; margin-bottom: 12px;">⚠️</div>
                <p>Search error: ${escapeHtml(error.message)}</p>
            </div>
        `;
        addNotification(`Global search error: ${error.message}`, "error");
    }
}

function getLookupPosterUrl(res) {
    // 1. Check the convenience remotePoster field
    if (res.remotePoster) return res.remotePoster;
    
    // 2. Search the images array for a poster with a remoteUrl
    if (res.images && res.images.length > 0) {
        const poster = res.images.find(img => img.coverType === "poster");
        if (poster && poster.remoteUrl) return poster.remoteUrl;
    }
    
    return null;
}

function createSearchCard(res, type) {
    const card = document.createElement("div");
    card.className = "media-card";
    
    const inLibrary = (res.id != null && res.id !== 0);
    const posterUrl = getLookupPosterUrl(res);
    const overview = res.overview || "No overview available.";
    const year = res.year || "N/A";
    const title = res.title || "Unknown Title";
    const network = type === "tv" ? (res.network || "Unknown Network") : (res.studio || "Unknown Studio");
    const runtime = res.runtime ? `${res.runtime} min` : "";
    const genres = (res.genres || []).map(g => `<span class="genre-pill">${escapeHtml(g)}</span>`).join("");
    const certification = res.certification ? `<span class="badge badge-network">${escapeHtml(res.certification)}</span>` : "";
    
    // Extract ratings for badge helper
    const ratingItem = {
        rating_imdb: "",
        rating_metacritic: "",
        rating_rt: ""
    };
    if (type === "movie" && res.ratings) {
        if (res.ratings.imdb && res.ratings.imdb.value) {
            ratingItem.rating_imdb = String(res.ratings.imdb.value);
        }
        if (res.ratings.metacritic && res.ratings.metacritic.value) {
            ratingItem.rating_metacritic = String(Math.round(res.ratings.metacritic.value));
        }
        if (res.ratings.rottenTomatoes && res.ratings.rottenTomatoes.value) {
            ratingItem.rating_rt = String(Math.round(res.ratings.rottenTomatoes.value));
        }
    } else if (type === "tv" && res.ratings) {
        if (res.ratings.value) {
            ratingItem.rating_imdb = String(res.ratings.value);
        }
    }
    
    // Setup expandable plot
    const maxChars = 140;
    const needsTruncation = overview.length > maxChars;
    let plotHtml = "";
    if (needsTruncation) {
        const visibleText = overview.slice(0, maxChars);
        const hiddenText = overview.slice(maxChars);
        plotHtml = `
            <span class="plot-visible">${escapeHtml(visibleText)}</span><span class="plot-ellipsis">...</span><span class="plot-hidden hidden">${escapeHtml(hiddenText)}</span><button class="plot-more-btn">more</button>
        `;
    } else {
        plotHtml = escapeHtml(overview);
    }
    
    // Poster HTML
    const navUrl = safeUrl(getPosterNavigationUrl(res, type));
    let posterHtml = "";
    if (posterUrl) {
        posterHtml = `
            <a href="${escapeHtml(navUrl)}" target="_blank" class="card-poster-link" title="Click to view external page">
                <div class="card-poster">
                    <img src="${escapeHtml(safeUrl(posterUrl))}" alt="${escapeHtml(title)} poster" class="poster-img" data-fallback-title="${escapeHtml(title)}" data-fallback-icon="${type === 'tv' ? 'tv' : 'movie'}" onerror="xarrtoolsPosterFallback(this)">
                </div>
            </a>
        `;
    } else {
        posterHtml = `
            <a href="${escapeHtml(navUrl)}" target="_blank" class="card-poster-link" title="Click to view external page">
                <div class="card-poster">
                    <div class="poster-fallback">
                        <span>${type === 'tv' ? '📺' : '🎬'}</span>
                        <p style="font-size: 11px; padding: 0 8px; font-weight: 500; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;">${escapeHtml(title)}</p>
                    </div>
                </div>
            </a>
        `;
    }
    
    // External source chips
    let chipsHtml = "";
    if (res.imdbId) {
        chipsHtml += `<a href="https://www.imdb.com/title/${encodeURIComponent(String(res.imdbId))}/" target="_blank" class="chip chip-imdb">IMDb</a>`;
    }
    if (type === "movie" && res.tmdbId) {
        chipsHtml += `<a href="https://www.themoviedb.org/movie/${encodeURIComponent(String(res.tmdbId))}" target="_blank" class="chip chip-tmdb">TMDB</a>`;
    }
    if (type === "tv" && res.tvdbId) {
        chipsHtml += `<a href="https://thetvdb.com/dereferrer/series/${encodeURIComponent(String(res.tvdbId))}" target="_blank" class="chip chip-tvdb">TVDB</a>`;
    }
    const searchString = encodeURIComponent(`${title} ${year} ${type === 'tv' ? 'tv show' : 'movie'}`);
    chipsHtml += `<a href="https://www.google.com/search?q=${searchString}" target="_blank" class="chip chip-google">Google Search 🔍</a>`;
    
    // Action button
    const buttonText = inLibrary ? "In Library" : (type === "tv" ? "Add to Sonarr" : "Add to Radarr");
    const buttonClass = inLibrary ? "btn btn-secondary btn-added" : "btn btn-primary";
    
    card.innerHTML = `
        ${posterHtml}
        <div class="card-info-content">
            <div class="card-title-row">
                <h3>${escapeHtml(title)}</h3>
                <div class="card-year-refresh">
                    <span class="year">${escapeHtml(year)}</span>
                </div>
            </div>
            <div class="card-badges">
                <span class="badge badge-network">${escapeHtml(network)}</span>
                ${certification}
                ${runtime ? `<span class="badge badge-network">${escapeHtml(runtime)}</span>` : ''}
                ${inLibrary ? '<span class="badge badge-in-library">In Library</span>' : ''}
            </div>
            ${buildRatingBadgesHtml(ratingItem)}
            <div class="genres-list">${genres}</div>
            <div class="card-plot">${plotHtml}</div>
            
            <div class="details-toggle-row" style="margin-top: auto; border-top: 1px dashed var(--border-color); padding-top: 8px; display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 11px; color: var(--text-secondary); font-weight: 500;">External Sources</span>
                <button type="button" class="btn-details-toggle" style="background: transparent; border: none; color: var(--accent-blue); font-size: 12px; cursor: pointer; display: flex; align-items: center; gap: 4px; padding: 0; outline: none; font-weight: 600; transition: var(--transition-smooth);">Show ▾</button>
            </div>
            <div class="card-details-panel hidden" style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px;">
                ${chipsHtml}
            </div>
    
            <div class="card-actions" style="margin-top: 0;">
                <button class="${buttonClass} btn-search-add" ${inLibrary ? 'disabled' : ''}>
                    ${buttonText}
                </button>
            </div>
        </div>
    `;
    
    // Plot expansion handler
    const plotDiv = card.querySelector(".card-plot");
    const moreBtn = card.querySelector(".plot-more-btn");
    if (moreBtn && plotDiv) {
        moreBtn.addEventListener("click", () => {
            const isExpanded = plotDiv.classList.contains("expanded");
            const hiddenSpan = plotDiv.querySelector(".plot-hidden");
            const ellipsis = plotDiv.querySelector(".plot-ellipsis");
            if (isExpanded) {
                plotDiv.classList.remove("expanded");
                hiddenSpan.classList.add("hidden");
                ellipsis.classList.remove("hidden");
                moreBtn.textContent = "more";
            } else {
                plotDiv.classList.add("expanded");
                hiddenSpan.classList.remove("hidden");
                ellipsis.classList.add("hidden");
                moreBtn.textContent = "less";
            }
        });
    }
    
    // Details toggle handler
    const toggleBtn = card.querySelector(".btn-details-toggle");
    const detailsPanel = card.querySelector(".card-details-panel");
    if (toggleBtn && detailsPanel) {
        toggleBtn.addEventListener("click", () => {
            const isHidden = detailsPanel.classList.contains("hidden");
            if (isHidden) {
                detailsPanel.classList.remove("hidden");
                toggleBtn.textContent = "Hide ▴";
                toggleBtn.style.color = "var(--accent-magenta)";
            } else {
                detailsPanel.classList.add("hidden");
                toggleBtn.textContent = "Show ▾";
                toggleBtn.style.color = "var(--accent-blue)";
            }
        });
    }
    
    // Add button handler
    const addBtn = card.querySelector(".btn-search-add");
    if (addBtn && !inLibrary) {
        addBtn.addEventListener("click", () => {
            openAddModalFromLookup(res, type, card);
        });
    }
    
    return card;
}

function openAddModalFromLookup(res, type, card) {
    if (!appConfig) {
        alert("Server configuration is not loaded yet.");
        return;
    }
    
    const targetConfig = type === "tv" ? appConfig.sonarr : appConfig.radarr;
    if (!targetConfig.configured) {
        openDemoAddModal(type, { title: res.title, year: res.year }, null, card, res);
        return;
    }
    
    // Set selected item for add - use the lookup result as the raw_metadata directly,
    // and create a synthetic "item" for reference
    selectedItemForAdd = {
        type: type,
        item: { title: res.title, year: res.year },
        raw_metadata: res,
        card: card  // keep a reference so we can update the card on success
    };
    
    // Skip Step 1 (indexer search) entirely since we already have the full metadata.
    // Go directly to Step 2 (options).
    goToOptionsStep(res);
    
    modalOverlay.classList.remove("hidden");
}

window.xarrtoolsPosterFallback = function(img) {
    if (!img) return;
    img.onerror = null;
    const parent = img.parentElement;
    if (!parent) return;

    const title = img.getAttribute("data-fallback-title") || "";
    const iconType = img.getAttribute("data-fallback-icon");
    const emoji = iconType === "tv" ? "📺" : "🎬";

    const fallbackDiv = document.createElement("div");
    fallbackDiv.className = "poster-fallback";

    const iconSpan = document.createElement("span");
    iconSpan.textContent = emoji;

    const titleP = document.createElement("p");
    titleP.style.cssText = "font-size: 11px; padding: 0 8px; font-weight: 500; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;";
    titleP.textContent = title;

    fallbackDiv.appendChild(iconSpan);
    fallbackDiv.appendChild(titleP);

    parent.innerHTML = "";
    parent.appendChild(fallbackDiv);
};

function getPosterNavigationUrl(item, type) {
    return moduleGetPosterNavigationUrl(item, type);
}

function getDemoSearchResults(query, type) {
    if (type === "movie") {
        return [
            {
                title: query,
                year: 2026,
                tmdbId: 88801,
                imdbId: "tt1234567",
                overview: `[Demo Sandbox] Simulated movie result matching your query "${query}".`,
                studio: "Demo Studios",
                genres: ["Action", "Sci-Fi"]
            },
            {
                title: `${query}: Part II`,
                year: 2027,
                tmdbId: 88802,
                imdbId: "tt2345678",
                overview: `[Demo Sandbox] Futuristic sequel to "${query}".`,
                studio: "Demo Studios",
                genres: ["Action", "Sci-Fi", "Adventure"]
            }
        ];
    } else {
        return [
            {
                title: query,
                year: 2026,
                tvdbId: 99901,
                imdbId: "tt3456789",
                overview: `[Demo Sandbox] Simulated TV series matching your query "${query}".`,
                network: "Demo Network",
                genres: ["Drama", "Mystery"]
            },
            {
                title: `${query} (Spinoff)`,
                year: 2028,
                tvdbId: 99902,
                imdbId: "tt4567890",
                overview: `[Demo Sandbox] Popular television spinoff based on "${query}".`,
                network: "Demo Streaming",
                genres: ["Comedy"]
            }
        ];
    }
}

function openDemoAddModal(type, item, index, searchCard = null, rawMetadata = null) {
    selectedItemForAdd = { 
        type, 
        item, 
        isDemo: true, 
        card: searchCard,
        raw_metadata: rawMetadata
    };
    
    // Setup Step 1 UI
    isMarkInLibraryMode = false;
    if (linkHelperBanner) linkHelperBanner.classList.add("hidden");
    if (btnModalMarkLibrary) {
        btnModalMarkLibrary.classList.remove("hidden");
        btnModalMarkLibrary.classList.remove("btn-modal-mark-library-active");
        btnModalMarkLibrary.textContent = "Mark In Library";
    }
    modalTitle.textContent = `[Demo Sandbox] Search Indexer for '${item.title}'`;
    modalStepSearch.classList.remove("hidden");
    modalStepOptions.classList.add("hidden");
    btnModalBack.classList.add("hidden");
    btnModalConfirm.classList.add("hidden");
    
    lookupLoading.classList.remove("hidden");
    lookupResultsList.classList.add("hidden");
    lookupResultsList.innerHTML = "";
    
    modalOverlay.classList.remove("hidden");
    
    // Simulate indexing search delay
    setTimeout(() => {
        lookupLoading.classList.add("hidden");
        lookupResultsList.classList.remove("hidden");
        
        const fakeResults = [
            {
                title: item.title,
                year: item.year,
                tvdbId: type === "tv" ? 99901 : null,
                tmdbId: type === "movie" ? 88801 : null,
                imdbId: item.imdbId || "tt1234567",
                overview: `[Demo Mode] Simulated match for '${item.title}'. In sandbox mode, you can select this to preview the settings configurations.`,
                collection: type === "movie" ? { title: `${item.title} Collection`, name: `${item.title} Collection` } : null,
                id: null
            },
            {
                title: `${item.title} (Sandbox Spinoff)`,
                year: item.year - 1,
                tvdbId: type === "tv" ? 99902 : null,
                tmdbId: type === "movie" ? 88802 : null,
                imdbId: "tt2345678",
                overview: "[Demo Mode] Alternative simulated release for testing multiselection flows.",
                id: null
            }
        ];
        
        renderLookupResults(fakeResults, type, item);
    }, 600);
}


function setupEventListeners() {
    // Theme toggle button click
    const btnThemeToggle = document.getElementById("btn-theme-toggle");
    if (btnThemeToggle) {
        btnThemeToggle.addEventListener("click", toggleTheme);
    }
    
    // Collapsible Notifications click
    const notificationsHeader = document.getElementById("notifications-header");
    const notificationsCard = document.getElementById("notifications-card");
    if (notificationsHeader && notificationsCard) {
        notificationsHeader.addEventListener("click", () => {
            notificationsCard.classList.toggle("collapsed");
        });
    }

    // Floating Progress Pop-over Close button
    const btnCloseProgress = document.getElementById("btn-close-progress");
    if (btnCloseProgress) {
        btnCloseProgress.addEventListener("click", () => {
            document.getElementById("scan-progress-popover").classList.add("hidden");
        });
    }

    btnScan.addEventListener("click", scanReleases);
    modalClose.addEventListener("click", closeModal);
    btnModalCancel.addEventListener("click", closeModal);
    btnModalConfirm.addEventListener("click", () => addMediaItem(true));
    if (btnModalAddOnly) {
        btnModalAddOnly.addEventListener("click", () => addMediaItem(false));
    }
    btnModalBack.addEventListener("click", goBackToSearchStep);
    if (btnModalMarkLibrary) {
        btnModalMarkLibrary.addEventListener("click", () => {
            isMarkInLibraryMode = !isMarkInLibraryMode;
            if (isMarkInLibraryMode) {
                btnModalMarkLibrary.classList.add("btn-modal-mark-library-active");
                btnModalMarkLibrary.textContent = "Cancel Link Mode";
                linkHelperBanner.classList.remove("hidden");
            } else {
                btnModalMarkLibrary.classList.remove("btn-modal-mark-library-active");
                btnModalMarkLibrary.textContent = "Mark In Library";
                linkHelperBanner.classList.add("hidden");
            }
        });
    }

    
    // Sort Select change handler
    if (selectSort) {
        selectSort.addEventListener("change", renderMediaLists);
    }

    // Instant Search
    searchBar.addEventListener("input", renderMediaLists);

    // Sliders
    const sliderPast = document.getElementById("slider-past");
    const valPast = document.getElementById("val-past");
    sliderPast.addEventListener("input", () => {
        valPast.textContent = sliderPast.value;
    });

    const sliderFuture = document.getElementById("slider-future");
    const valFuture = document.getElementById("val-future");
    sliderFuture.addEventListener("input", () => {
        valFuture.textContent = sliderFuture.value;
    });

    // Checkbox Filters Change Listeners
    document.getElementById("check-show-returning").addEventListener("change", renderMediaLists);
    document.getElementById("check-show-library").addEventListener("change", renderMediaLists);
    document.getElementById("check-show-archived").addEventListener("change", renderMediaLists);

    // Settings Modal Triggers
    btnSettings.addEventListener("click", openSettingsModal);
    settingsClose.addEventListener("click", closeSettingsModal);
    btnSettingsCancel.addEventListener("click", closeSettingsModal);
    btnSettingsSave.addEventListener("click", saveSettings);
    
    // Theme Selector inside settings dropdown
    const selectTheme = document.getElementById("select-theme-mode");
    if (selectTheme) {
        selectTheme.addEventListener("change", (e) => {
            const selectedTheme = e.target.value;
            const isLight = (selectedTheme === "light");
            if (isLight) {
                document.body.classList.add("light-theme");
            } else {
                document.body.classList.remove("light-theme");
            }
            localStorage.setItem("xarrtools-theme", selectedTheme);
            updateThemeToggleUI(isLight);
        });
    }

    // Tab switching inside settings
    const settingsTabButtons = document.querySelectorAll(".settings-tab-btn");
    const settingsTabPanels = document.querySelectorAll(".settings-tab-panel");
    
    settingsTabButtons.forEach(btn => {
        btn.addEventListener("click", (e) => {
            const targetTab = e.target.getAttribute("data-tab");
            
            settingsTabButtons.forEach(b => b.classList.remove("active"));
            e.target.classList.add("active");
            
            settingsTabPanels.forEach(p => {
                if (p.id === targetTab) {
                    p.classList.remove("hidden");
                } else {
                    p.classList.add("hidden");
                }
            });
            
            if (targetTab === "panel-feeds") {
                // If in editor view, return to list view
                const editorView = document.getElementById("feed-editor-view");
                const listView = document.getElementById("feeds-list-view");
                if (editorView && listView) {
                    editorView.classList.add("hidden");
                    listView.classList.remove("hidden");
                }
                loadCustomFeeds();
            }
        });
    });

    // Maintenance button clicks
    document.getElementById("btn-cache-prune").addEventListener("click", pruneCacheManually);
    document.getElementById("btn-cache-clear").addEventListener("click", wipeCacheManually);

    // Backup & Restore controls
    const btnBackupExport = document.getElementById("btn-backup-export");
    if (btnBackupExport) btnBackupExport.addEventListener("click", exportBackup);
    
    const btnBackupImport = document.getElementById("btn-backup-import");
    if (btnBackupImport) btnBackupImport.addEventListener("click", triggerBackupImport);
    
    const fileBackupImport = document.getElementById("file-backup-import");
    if (fileBackupImport) fileBackupImport.addEventListener("change", importBackup);

    // Custom Feed Events
    const btnFeedRestore = document.getElementById("btn-feed-restore");
    if (btnFeedRestore) btnFeedRestore.addEventListener("click", restoreDefaultFeeds);

    const btnFeedAdd = document.getElementById("btn-feed-add");
    if (btnFeedAdd) btnFeedAdd.addEventListener("click", () => openFeedEditor(null));
    
    const btnFeedSave = document.getElementById("btn-feed-save");
    if (btnFeedSave) btnFeedSave.addEventListener("click", saveCustomFeed);
    
    const btnFeedCancel = document.getElementById("btn-feed-cancel");
    if (btnFeedCancel) btnFeedCancel.addEventListener("click", closeFeedEditor);
    
    const btnFeedTest = document.getElementById("btn-feed-test");
    if (btnFeedTest) btnFeedTest.addEventListener("click", testCustomFeed);
    
    const selectFeedType = document.getElementById("feed-type");
    if (selectFeedType) selectFeedType.addEventListener("change", handleFeedTypeChange);
    
    const feedTabGeneral = document.getElementById("btn-feed-tab-general");
    if (feedTabGeneral) feedTabGeneral.addEventListener("click", () => switchEditorTab("feed-tab-general"));
    
    const feedTabMapping = document.getElementById("btn-feed-tab-mapping");
    if (feedTabMapping) feedTabMapping.addEventListener("click", () => switchEditorTab("feed-tab-mapping"));

    // Global Search event listeners
    const btnGlobalSearch = document.getElementById("btn-global-search");
    const globalSearchInput = document.getElementById("global-search-input");
    if (btnGlobalSearch) {
        btnGlobalSearch.addEventListener("click", runGlobalSearch);
    }
    if (globalSearchInput) {
        globalSearchInput.addEventListener("keyup", (e) => {
            if (e.key === "Enter") runGlobalSearch();
        });
    }

    // Tab buttons
    tabButtons.forEach(btn => {
        btn.addEventListener("click", (e) => {
            tabButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            applyTabFilter();
        });
    });

    // Close modal on click outside card
    modalOverlay.addEventListener("click", (e) => {
        if (e.target === modalOverlay) {
            closeModal();
        }
    });

    settingsOverlay.addEventListener("click", (e) => {
        if (e.target === settingsOverlay) {
            closeSettingsModal();
        }
    });

    // Search Bar clear option
    const clearSearchBarBtn = document.getElementById("btn-clear-search");
    const clearGlobalSearchBtn = document.getElementById("btn-clear-global-search");
    
    searchBar.addEventListener("input", () => {
        if (searchBar.value) {
            clearSearchBarBtn.classList.remove("hidden");
        } else {
            clearSearchBarBtn.classList.add("hidden");
        }
    });
    
    clearSearchBarBtn.addEventListener("click", () => {
        searchBar.value = "";
        clearSearchBarBtn.classList.add("hidden");
        renderMediaLists();
        searchBar.focus();
    });
    
    if (globalSearchInput) {
        globalSearchInput.addEventListener("input", () => {
            if (globalSearchInput.value) {
                clearGlobalSearchBtn.classList.remove("hidden");
            } else {
                clearGlobalSearchBtn.classList.add("hidden");
            }
        });
    }
    
    if (clearGlobalSearchBtn) {
        clearGlobalSearchBtn.addEventListener("click", () => {
            globalSearchInput.value = "";
            clearGlobalSearchBtn.classList.add("hidden");
            const gridSearchResults = document.getElementById("grid-search-results");
            if (gridSearchResults) {
                gridSearchResults.innerHTML = `
                    <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
                        <div class="empty-icon" style="font-size: 40px; margin-bottom: 12px;">🔎</div>
                        <p>Search for any movie or TV show globally using the bar above.</p>
                    </div>
                `;
            }
            globalSearchInput.focus();
        });
    }

    // Multiselect Dropdowns (opening one closes the others)
    const dropdownContents = ["genres", "networks", "country", "language"]
        .map(k => ({ btn: document.getElementById("btn-" + k + "-filter"), content: document.getElementById("content-" + k + "-filter") }))
        .filter(d => d.btn && d.content);
    dropdownContents.forEach(d => {
        d.btn.addEventListener("click", (e) => {
            e.stopPropagation();
            dropdownContents.forEach(o => { if (o !== d) o.content.classList.add("hidden"); });
            d.content.classList.toggle("hidden");
        });
        d.content.addEventListener("click", (e) => e.stopPropagation());
    });
    document.addEventListener("click", () => {
        dropdownContents.forEach(o => o.content.classList.add("hidden"));
    });

    [["country", selectedCountries, "Country"], ["language", selectedLanguages, "Language"]].forEach(([k, set, label]) => {
        const clearBtn = document.getElementById("clear-" + k + "-filter");
        if (clearBtn) {
            clearBtn.addEventListener("click", () => {
                set.clear();
                document.querySelectorAll("#options-" + k + "-filter input").forEach(cb => cb.checked = false);
                const btn = document.getElementById("btn-" + k + "-filter");
                btn.textContent = `${label} (All)`;
                btn.classList.remove("active");
                renderMediaLists();
            });
        }
    });

    // Invert selection: flips every checkbox in a dropdown
    [["genres", selectedGenres, updateGenreFilterBtnText],
     ["networks", selectedNetworks, updateNetworkFilterBtnText],
     ["country", selectedCountries, null],
     ["language", selectedLanguages, null]].forEach(([k, set, update]) => {
        const invertBtn = document.getElementById("invert-" + k + "-filter");
        if (invertBtn) invertBtn.addEventListener("click", () => invertMultiselect(k, set, update));
    });

    const btnArchiveFiltered = document.getElementById("btn-archive-filtered");
    if (btnArchiveFiltered) btnArchiveFiltered.addEventListener("click", archiveAllFiltered);

    const clearGenresBtn = document.getElementById("clear-genres-filter");
    if (clearGenresBtn) {
        clearGenresBtn.addEventListener("click", () => {
            selectedGenres.clear();
            const checkboxes = document.querySelectorAll("#options-genres-filter input");
            checkboxes.forEach(cb => cb.checked = false);
            updateGenreFilterBtnText();
            renderMediaLists();
        });
    }
    
    const clearNetworksBtn = document.getElementById("clear-networks-filter");
    if (clearNetworksBtn) {
        clearNetworksBtn.addEventListener("click", () => {
            selectedNetworks.clear();
            const checkboxes = document.querySelectorAll("#options-networks-filter input");
            checkboxes.forEach(cb => cb.checked = false);
            updateNetworkFilterBtnText();
            renderMediaLists();
        });
    }
}

function invertMultiselect(key, set, update) {
    document.querySelectorAll("#options-" + key + "-filter input").forEach(cb => {
        cb.checked = !cb.checked;
        if (cb.checked) set.add(cb.value); else set.delete(cb.value);
    });
    if (update) {
        update();
    } else {
        const btn = document.getElementById("btn-" + key + "-filter");
        const label = key === "country" ? "Country" : "Language";
        btn.textContent = set.size === 0 ? `${label} (All)` : `${label} (${set.size})`;
        btn.classList.toggle("active", set.size > 0);
    }
    renderMediaLists();
}

function escapeHtml(v) {
    return moduleEscapeHtml(v);
}

function safeUrl(u) {
    return moduleSafeUrl(u);
}

function countryName(code) {
    return moduleCountryName(code);
}

function matchLocale(item, countries, languages) {
    const c = countries !== undefined ? countries : (typeof selectedCountries !== "undefined" ? selectedCountries : new Set());
    const l = languages !== undefined ? languages : (typeof selectedLanguages !== "undefined" ? selectedLanguages : new Set());
    return moduleMatchLocale(item, c, l);
}

function localeBadge(item) {
    return moduleLocaleBadge(item);
}

// Builds a checkbox multi-select (same look as Genres / Studios) from a set of values.
function buildLocaleMultiselect(key, values, selected, label, text) {
    const container = document.querySelector("#options-" + key + "-filter");
    const btn = document.querySelector("#btn-" + key + "-filter");
    if (!container || !btn) return;
    selected.forEach(v => { if (!values.includes(v)) selected.delete(v); });
    const updateBtn = () => {
        btn.textContent = selected.size === 0 ? `${label} (All)` : `${label} (${selected.size})`;
        btn.classList.toggle("active", selected.size > 0);
    };
    container.innerHTML = "";
    values.forEach(value => {
        const option = document.createElement("label");
        option.className = "multiselect-option";
        option.innerHTML = `
            <input type="checkbox" value="${escapeHtml(value)}" ${selected.has(value) ? "checked" : ""}>
            <span>${escapeHtml(text(value))}</span>
        `;
        option.querySelector("input").addEventListener("change", (e) => {
            if (e.target.checked) selected.add(value); else selected.delete(value);
            updateBtn();
            renderMediaLists();
        });
        container.appendChild(option);
    });
    updateBtn();
}

function populateLocaleFilters() {
    const countries = new Set();
    const languages = new Set();
    [...currentDiscoveries.tv, ...currentDiscoveries.movies].forEach(item => {
        if (item.country) countries.add(item.country);
        if (item.language) languages.add(item.language);
    });
    buildLocaleMultiselect("country", Array.from(countries).sort((a, b) => countryName(a).localeCompare(countryName(b))),
        selectedCountries, "Country", countryName);
    buildLocaleMultiselect("language", Array.from(languages).sort(), selectedLanguages, "Language", v => v);
}

function populateFilterOptions() {
    populateLocaleFilters();
    const allGenres = new Set();
    const allNetworks = new Set();
    
    currentDiscoveries.tv.forEach(item => {
        if (item.genres) item.genres.forEach(g => allGenres.add(g));
        if (item.network) allNetworks.add(item.network);
    });
    
    currentDiscoveries.movies.forEach(item => {
        if (item.genres) item.genres.forEach(g => allGenres.add(g));
        if (item.network) allNetworks.add(item.network);
    });
    
    const sortedGenres = Array.from(allGenres).sort();
    const sortedNetworks = Array.from(allNetworks).sort();
    
    // Cleanup stale filter selections
    selectedGenres.forEach(g => {
        if (!allGenres.has(g)) selectedGenres.delete(g);
    });
    selectedNetworks.forEach(n => {
        if (!allNetworks.has(n)) selectedNetworks.delete(n);
    });
    
    // Genres options
    const genresContainer = document.getElementById("options-genres-filter");
    if (genresContainer) {
        genresContainer.innerHTML = "";
        sortedGenres.forEach(genre => {
            const option = document.createElement("label");
            option.className = "multiselect-option";
            const isChecked = selectedGenres.has(genre);
            option.innerHTML = `
                <input type="checkbox" value="${escapeHtml(genre)}" ${isChecked ? 'checked' : ''}>
                <span>${escapeHtml(genre)}</span>
            `;
            option.querySelector("input").addEventListener("change", (e) => {
                if (e.target.checked) {
                    selectedGenres.add(genre);
                } else {
                    selectedGenres.delete(genre);
                }
                updateGenreFilterBtnText();
                renderMediaLists();
            });
            genresContainer.appendChild(option);
        });
    }
    
    // Networks options
    const networksContainer = document.getElementById("options-networks-filter");
    if (networksContainer) {
        networksContainer.innerHTML = "";
        sortedNetworks.forEach(network => {
            const option = document.createElement("label");
            option.className = "multiselect-option";
            const isChecked = selectedNetworks.has(network);
            option.innerHTML = `
                <input type="checkbox" value="${escapeHtml(network)}" ${isChecked ? 'checked' : ''}>
                <span>${escapeHtml(network)}</span>
            `;
            option.querySelector("input").addEventListener("change", (e) => {
                if (e.target.checked) {
                    selectedNetworks.add(network);
                } else {
                    selectedNetworks.delete(network);
                }
                updateNetworkFilterBtnText();
                renderMediaLists();
            });
            networksContainer.appendChild(option);
        });
    }
    
    updateGenreFilterBtnText();
    updateNetworkFilterBtnText();
}

function updateGenreFilterBtnText() {
    const btn = document.getElementById("btn-genres-filter");
    if (!btn) return;
    if (selectedGenres.size === 0) {
        btn.textContent = "Genres (All)";
        btn.classList.remove("active");
    } else {
        btn.textContent = `Genres (${selectedGenres.size})`;
        btn.classList.add("active");
    }
}

function updateNetworkFilterBtnText() {
    const btn = document.getElementById("btn-networks-filter");
    if (!btn) return;
    if (selectedNetworks.size === 0) {
        btn.textContent = "Studios/Nets (All)";
        btn.classList.remove("active");
    } else {
        btn.textContent = `Studios/Nets (${selectedNetworks.size})`;
        btn.classList.add("active");
    }
}
