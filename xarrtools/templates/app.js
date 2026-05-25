// Global Application State
let appConfig = null;
let appSettings = null;
let currentDiscoveries = { tv: [], movies: [] };
let selectedItemForAdd = null;

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
        <div>${message}</div>
        <span class="notification-time">${timeStr}</span>
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

const selectFolder = document.getElementById("select-folder");
const selectProfile = document.getElementById("select-profile");
const selectLangProfile = document.getElementById("select-lang-profile");
const groupLangProfile = document.getElementById("group-lang-profile");
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
const inputSonarrUrl = document.getElementById("input-sonarr-url");
const inputSonarrKey = document.getElementById("input-sonarr-key");
const inputPastMonths = document.getElementById("input-past-months");
const inputFutureMonths = document.getElementById("input-future-months");

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
    loadSettingsAndConfig();
    setupEventListeners();
});

// --- API Calls ---

// 1. Fetch server configs, status, and settings on startup
async function loadSettingsAndConfig() {
    try {
        // Fetch Settings
        const settingsResponse = await fetch("/api/settings");
        appSettings = await settingsResponse.json();
        
        // Fetch Configs
        const configResponse = await fetch("/api/config");
        appConfig = await configResponse.json();
        
        // Initialize UI Elements with Settings Defaults
        initializeSettingsDefaults();
        updateStatusBadges();
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

// 2. Scan Metacritic and DVD calendar releases
async function scanReleases() {
    welcomeState.classList.add("hidden");
    contentArea.classList.add("hidden");
    loadingOverlay.classList.remove("hidden");
    loadingText.textContent = "Scanning feeds...";
    
    const pastMonths = document.getElementById("slider-past").value;
    const futureMonths = document.getElementById("slider-future").value;
    
    try {
        const response = await fetch(`/api/discover?past_months=${pastMonths}&future_months=${futureMonths}`);
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.message || "Failed to scan releases.");
        }
        
        const data = await response.json();
        currentDiscoveries.tv = data.tv || [];
        currentDiscoveries.movies = data.movies || [];
        
        renderMediaLists();
        
        loadingOverlay.classList.add("hidden");
        contentArea.classList.remove("hidden");
    } catch (error) {
        loadingOverlay.classList.add("hidden");
        welcomeState.classList.remove("hidden");
        alert(`Error: ${error.message}`);
    }
}

// 3. Add item to *Arr
async function addMediaItem() {
    if (!selectedItemForAdd || !selectedItemForAdd.raw_metadata) return;

    const type = selectedItemForAdd.type;
    const rawMeta = selectedItemForAdd.raw_metadata;
    const discoveryItem = selectedItemForAdd.item; // Capture reference before closing modal clears selectedItemForAdd
    
    const payload = {
        type: type,
        raw_metadata: rawMeta,
        folder: selectFolder.value,
        profile_id: selectProfile.value,
        lang_profile_id: type === "tv" ? selectLangProfile.value : null,
        monitored: checkMonitored.checked,
        search_now: checkSearch.checked
    };

    // Close options modal and show spinner
    closeModal();
    loadingOverlay.classList.remove("hidden");
    loadingText.textContent = `Adding '${rawMeta.title}'...`;

    try {
        const response = await fetch("/api/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const resData = await response.json();
        loadingOverlay.classList.add("hidden");

        if (response.ok && resData.status === "success") {
            addNotification(resData.message || `Successfully queued '${rawMeta.title}' for download!`, "success");
            // Mark item as added in memory and re-render using the captured reference
            discoveryItem.is_in_library = true;
            renderMediaLists();
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
        const response = await fetch("/api/archive", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                type: type,
                title: item.title,
                year: item.year,
                archive: isArchiving,
                raw_item: item
            })
        });
        
        const resData = await response.json();
        if (response.ok && resData.status === "success") {
            item.is_archived = isArchiving;
            addNotification(`Successfully ${isArchiving ? 'archived' : 'unarchived'} '${item.title}'.`, "success");
            renderMediaLists();
        } else {
            addNotification(`Failed to archive '${item.title}': ${resData.message || "Unknown error."}`, "error");
        }
    } catch (error) {
        addNotification(`Archive error: ${error.message}`, "error");
    }
}

// 5. Save settings to server
async function saveSettings() {
    const payload = {
        radarr_url: inputRadarrUrl.value.trim(),
        radarr_api_key: inputRadarrKey.value.trim(),
        sonarr_url: inputSonarrUrl.value.trim(),
        sonarr_api_key: inputSonarrKey.value.trim(),
        default_past_months: inputPastMonths.value,
        default_future_months: inputFutureMonths.value,
        default_show_returning: document.getElementById("input-show-returning").checked ? "1" : "0",
        default_show_library: document.getElementById("input-show-library").checked ? "1" : "0",
        default_show_archived: document.getElementById("input-show-archived").checked ? "1" : "0"
    };
    
    closeSettingsModal();
    loadingOverlay.classList.remove("hidden");
    loadingText.textContent = "Saving settings...";
    
    try {
        const response = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        const resData = await response.json();
        loadingOverlay.classList.add("hidden");
        
        if (response.ok && resData.status === "success") {
            addNotification("Configuration settings updated successfully.", "success");
            // Reload settings and configurations from server
            await loadSettingsAndConfig();
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
    const tvMatches = currentDiscoveries.tv.filter(item => {
        if (!showReturning && item.is_returning) return false;
        if (!showLibrary && item.is_in_library) return false;
        if (!showArchived && item.is_archived) return false;
        return matchFilter(item, searchTerm);
    });
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
    const movieMatches = currentDiscoveries.movies.filter(item => {
        if (!showLibrary && item.is_in_library) return false;
        if (!showArchived && item.is_archived) return false;
        return matchFilter(item, searchTerm);
    });
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

function matchFilter(item, term) {
    if (!term) return true;
    
    const titleMatch = item.title.toLowerCase().includes(term);
    const networkMatch = item.network && item.network.toLowerCase().includes(term);
    const castMatch = item.cast && item.cast.toLowerCase().includes(term);
    const genreMatch = item.genres && item.genres.some(g => g.toLowerCase().includes(term));
    
    return titleMatch || networkMatch || castMatch || genreMatch;
}

function createMediaCard(item, type, index) {
    const card = document.createElement("div");
    card.className = "media-card";
    
    const isAdded = item.is_in_library;
    const genres = item.genres.map(g => `<span class="genre-pill">${g}</span>`).join("");
    const buttonText = isAdded ? "Added to Library" : (type === "tv" ? "Add to Sonarr" : "Add to Radarr");
    const buttonClass = isAdded ? "btn btn-secondary btn-added" : "btn btn-primary";
    
    // Setup expandable plot
    const maxChars = 140;
    const needsTruncation = item.plot && item.plot.length > maxChars;
    let plotHtml = "";
    if (needsTruncation) {
        const visibleText = item.plot.slice(0, maxChars);
        const hiddenText = item.plot.slice(maxChars);
        plotHtml = `
            <span class="plot-visible">${visibleText}</span><span class="plot-ellipsis">...</span><span class="plot-hidden hidden">${hiddenText}</span><button class="plot-more-btn">more</button>
        `;
    } else {
        plotHtml = item.plot;
    }
    
    const returningBadge = (type === "tv" && item.is_returning) 
        ? '<span class="badge badge-network" style="background:rgba(138,43,226,0.1); color:#bc8cf2; border-color:rgba(138,43,226,0.2);">Returning</span>' 
        : '';
        
    // Dynamic Archive classes
    const archiveBtnClass = item.is_archived ? "btn btn-archive archived" : "btn btn-archive";
    const archiveBtnLabel = item.is_archived ? "📁 Unarchive" : "🗄️ Archive";
        
    card.innerHTML = `
        <div class="card-title-row">
            <h3>${item.title}</h3>
            <span class="year">${item.year}</span>
        </div>
        <div class="card-badges">
            <span class="badge badge-network">${item.network}</span>
            ${returningBadge}
            ${isAdded ? '<span class="badge badge-in-library">In Library</span>' : ''}
            ${item.is_archived ? '<span class="badge" style="background:rgba(255, 42, 133, 0.1); color:var(--accent-magenta); border:1px solid rgba(255, 42, 133, 0.2);">Archived</span>' : ''}
        </div>
        <div class="genres-list">${genres}</div>
        <div class="card-cast"><strong>Cast:</strong> <span>${item.cast}</span></div>
        <div class="card-plot">${plotHtml}</div>
        <div class="card-actions">
            <a href="${item.trailer}" target="_blank" class="btn btn-trailer">🎬 Trailer</a>
            <button class="${archiveBtnClass}">${archiveBtnLabel}</button>
            <button class="${buttonClass}" ${isAdded ? 'disabled' : ''} onclick="openAddModal('${type}', ${index})">
                ${buttonText}
            </button>
        </div>
    `;
    
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
        alert(`${type === "tv" ? "Sonarr" : "Radarr"} is not configured. Click settings in the top right to configure it.`);
        return;
    }

    // Step 1 UI Setup: Show Search match list, hide Options select
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
        const response = await fetch(`/api/lookup?type=${type}&title=${encodeURIComponent(item.title)}`);
        const data = await response.json();
        
        lookupLoading.classList.add("hidden");
        lookupResultsList.classList.remove("hidden");
        
        if (response.ok && data.status === "success" && data.results && data.results.length > 0) {
            renderLookupResults(data.results, type, item);
        } else {
            lookupResultsList.innerHTML = `<div class="lookup-status">No results found on indexers. Please check title manually.</div>`;
        }
    } catch (error) {
        lookupLoading.classList.add("hidden");
        lookupResultsList.innerHTML = `<div class="lookup-status">Error loading indexers: ${error.message}</div>`;
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
        
        if (discoveryId && resId && String(discoveryId) === String(resId)) {
            isBestMatch = true;
        } else if (discoveryImdbId && resImdbId && String(discoveryImdbId).toLowerCase() === String(resImdbId).toLowerCase()) {
            isBestMatch = true;
        } else if (res.title.toLowerCase() === discoveryItem.title.toLowerCase() && Math.abs(res.year - discoveryItem.year) <= 1) {
            isBestMatch = true;
        }

        if (isBestMatch) {
            itemRow.classList.add("best-match");
        }

        const idLabel = type === "tv" ? `TVDB ID: ${res.tvdbId || 'N/A'}` : `TMDB ID: ${res.tmdbId || 'N/A'}`;

        itemRow.innerHTML = `
            <div class="lookup-item-details">
                <div class="lookup-item-title">
                    ${res.title}
                    ${isBestMatch ? '<span class="auto-match-tag">Auto Match</span>' : ''}
                </div>
                <div class="lookup-item-meta">
                    <span class="year-badge">${res.year || 'N/A'}</span>
                    <span class="id-badge">${idLabel}</span>
                </div>
            </div>
            ${statusBadge}
        `;
        
        // Bind Click handler to select and transition to Step 2
        itemRow.addEventListener("click", () => {
            if (inLibrary) {
                alert(`'${res.title}' is already in your library!`);
                return;
            }
            goToOptionsStep(res);
        });
        
        lookupResultsList.appendChild(itemRow);
    });
}

// Transition to Step 2 (Download path and profile options)
function goToOptionsStep(metadataItem) {
    selectedItemForAdd.raw_metadata = metadataItem;
    const type = selectedItemForAdd.type;
    const targetConfig = type === "tv" ? appConfig.sonarr : appConfig.radarr;

    modalTitle.textContent = `Configure Download: ${metadataItem.title}`;
    
    // Clear selects
    selectFolder.innerHTML = "";
    selectProfile.innerHTML = "";
    selectLangProfile.innerHTML = "";

    // Populate Folder Paths
    targetConfig.folders.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.path;
        opt.textContent = f.path;
        selectFolder.appendChild(opt);
    });

    // Populate Quality Profiles
    targetConfig.profiles.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        selectProfile.appendChild(opt);
    });

    // Populate Languages (Sonarr TV only)
    if (type === "tv" && targetConfig.language_profiles && targetConfig.language_profiles.length > 0) {
        groupLangProfile.classList.remove("hidden");
        targetConfig.language_profiles.forEach(l => {
            const opt = document.createElement("option");
            opt.value = l.id;
            opt.textContent = l.name;
            selectLangProfile.appendChild(opt);
        });
    } else {
        groupLangProfile.classList.add("hidden");
    }

    // Transition Screens
    modalStepSearch.classList.add("hidden");
    modalStepOptions.classList.remove("hidden");
    btnModalBack.classList.remove("hidden");
    btnModalConfirm.classList.remove("hidden");
}

function goBackToSearchStep() {
    if (!selectedItemForAdd) return;
    
    modalTitle.textContent = `Search Indexer for '${selectedItemForAdd.item.title}'`;
    modalStepSearch.classList.remove("hidden");
    modalStepOptions.classList.add("hidden");
    btnModalBack.classList.add("hidden");
    btnModalConfirm.classList.add("hidden");
}

window.openAddModal = openAddModal; // Expose to global window scope for inline onclicks

function closeModal() {
    modalOverlay.classList.add("hidden");
    selectedItemForAdd = null;
}

// Settings Modal controls
function openSettingsModal() {
    if (appSettings) {
        inputRadarrUrl.value = appSettings.radarr_url || "";
        inputRadarrKey.value = appSettings.radarr_api_key || "";
        inputSonarrUrl.value = appSettings.sonarr_url || "";
        inputSonarrKey.value = appSettings.sonarr_api_key || "";
        inputPastMonths.value = appSettings.default_past_months || "1";
        inputFutureMonths.value = appSettings.default_future_months || "2";
        document.getElementById("input-show-returning").checked = appSettings.default_show_returning === "1";
        document.getElementById("input-show-library").checked = appSettings.default_show_library === "1";
        document.getElementById("input-show-archived").checked = appSettings.default_show_archived === "1";
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
        const response = await fetch("/api/cache/stats");
        if (response.ok) {
            const data = await response.json();
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
        const response = await fetch("/api/cache/prune", { method: "POST" });
        const data = await response.json();
        if (response.ok && data.status === "success") {
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
        const response = await fetch("/api/cache/clear", { method: "POST" });
        const data = await response.json();
        if (response.ok && data.status === "success") {
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

function applyTabFilter() {
    const activeTab = document.querySelector(".tab-btn.active").getAttribute("data-tab");
    
    if (activeTab === "all") {
        sectionTv.classList.remove("hidden");
        sectionMovies.classList.remove("hidden");
    } else if (activeTab === "tv") {
        sectionTv.classList.remove("hidden");
        sectionMovies.classList.add("hidden");
    } else if (activeTab === "movies") {
        sectionTv.classList.add("hidden");
        sectionMovies.classList.remove("hidden");
    }
}

function setupEventListeners() {
    btnScan.addEventListener("click", scanReleases);
    modalClose.addEventListener("click", closeModal);
    btnModalCancel.addEventListener("click", closeModal);
    btnModalConfirm.addEventListener("click", addMediaItem);
    btnModalBack.addEventListener("click", goBackToSearchStep);

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
        });
    });

    // Maintenance button clicks
    document.getElementById("btn-cache-prune").addEventListener("click", pruneCacheManually);
    document.getElementById("btn-cache-clear").addEventListener("click", wipeCacheManually);

    // Tab buttons
    tabButtons.forEach(btn => {
        btn.addEventListener("click", (e) => {
            tabButtons.forEach(b => b.classList.remove("active"));
            e.target.classList.add("active");
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
}
