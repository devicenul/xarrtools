// Global Application State
let appConfig = null;
let appSettings = null;
let currentDiscoveries = { tv: [], movies: [] };
let selectedItemForAdd = null;
let selectedGenres = new Set();
let selectedNetworks = new Set();

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
async function scanReleases(skipScrape = false) {
    const shouldSkipScrape = (skipScrape === true);
    
    welcomeState.classList.add("hidden");
    contentArea.classList.add("hidden");
    loadingOverlay.classList.remove("hidden");
    loadingText.textContent = shouldSkipScrape ? "Loading cached releases..." : "Scanning feeds...";
    
    const pastMonths = document.getElementById("slider-past").value;
    const futureMonths = document.getElementById("slider-future").value;
    
    try {
        const url = `/api/discover?past_months=${pastMonths}&future_months=${futureMonths}${shouldSkipScrape ? '&skip_scrape=true' : ''}`;
        const response = await fetch(url);
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.message || "Failed to scan releases.");
        }
        
        const data = await response.json();
        currentDiscoveries.tv = data.tv || [];
        currentDiscoveries.movies = data.movies || [];
        
        if (shouldSkipScrape && currentDiscoveries.tv.length === 0 && currentDiscoveries.movies.length === 0) {
            loadingOverlay.classList.add("hidden");
            welcomeState.classList.remove("hidden");
            contentArea.classList.add("hidden");
        } else {
            populateFilterOptions();
            renderMediaLists();
            loadingOverlay.classList.add("hidden");
            contentArea.classList.remove("hidden");
        }
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
    const searchCard = selectedItemForAdd.card || null; // Capture search card ref if from global search
    
    const checkTrackCollection = document.getElementById("check-track-collection");
    const payload = {
        type: type,
        raw_metadata: rawMeta,
        folder: selectFolder.value,
        profile_id: selectProfile.value,
        lang_profile_id: type === "tv" ? selectLangProfile.value : null,
        monitored: checkMonitored.checked,
        search_now: checkSearch.checked,
        add_collection: (type === "movie" && checkTrackCollection && checkTrackCollection.checked)
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

// 5. Refresh Metadata for a single item
async function refreshMetadata(type, item, refreshBtn, card) {
    if (refreshBtn.classList.contains("loading")) return;
    
    refreshBtn.classList.add("loading");
    refreshBtn.disabled = true;
    
    try {
        const response = await fetch("/api/cache/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                type: type,
                title: item.title,
                year: item.year,
                imdbId: item.imdbId || item.imdb_id
            })
        });
        
        const data = await response.json();
        if (response.ok && data.status === "success" && data.item) {
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
        sonarr_url: inputSonarrUrl.value.trim(),
        sonarr_api_key: inputSonarrKey.value.trim(),
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
        if (!matchFilter(item, searchTerm)) return false;

        // Genre multi-select filter
        if (selectedGenres.size > 0) {
            const hasGenre = item.genres && item.genres.some(g => selectedGenres.has(g));
            if (!hasGenre) return false;
        }

        // Network / Studio multi-select filter
        if (selectedNetworks.size > 0) {
            if (!item.network || !selectedNetworks.has(item.network)) return false;
        }

        return true;
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
        if (!matchFilter(item, searchTerm)) return false;

        // Genre multi-select filter
        if (selectedGenres.size > 0) {
            const hasGenre = item.genres && item.genres.some(g => selectedGenres.has(g));
            if (!hasGenre) return false;
        }

        // Network / Studio multi-select filter
        if (selectedNetworks.size > 0) {
            if (!item.network || !selectedNetworks.has(item.network)) return false;
        }

        return true;
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

function buildRatingBadgesHtml(item) {
    let html = '';
    
    // IMDb Rating (out of 10)
    const imdbRating = item.rating_imdb || item.rating_imdb === 0 ? item.rating_imdb : '';
    if (imdbRating && parseFloat(imdbRating) > 0) {
        const val = parseFloat(imdbRating).toFixed(1);
        html += `<span class="badge-rating badge-rating-imdb" title="IMDb Rating"><span class="rating-label">⭐ IMDb</span> <span class="rating-value">${val}</span></span>`;
    }
    
    // Metacritic Score (out of 100)
    const mcScore = item.rating_metacritic || '';
    if (mcScore && parseInt(mcScore) > 0) {
        const val = parseInt(mcScore);
        let mcClass = 'mc-mixed';
        if (val >= 61) mcClass = 'mc-good';
        else if (val <= 39) mcClass = 'mc-bad';
        html += `<span class="badge-rating badge-rating-mc ${mcClass}" title="Metacritic Score"><span class="rating-label">MC</span> <span class="rating-value">${val}</span></span>`;
    }
    
    // Rotten Tomatoes (percentage)
    const rtScore = item.rating_rt || '';
    if (rtScore && parseInt(rtScore) > 0) {
        const val = parseInt(rtScore);
        let rtClass = 'rt-rotten';
        let rtIcon = '🍅';
        if (val >= 75) { rtClass = 'rt-certified'; rtIcon = '🍅'; }
        else if (val >= 60) { rtClass = 'rt-fresh'; rtIcon = '🍅'; }
        else { rtIcon = '🟢'; }
        html += `<span class="badge-rating badge-rating-rt ${rtClass}" title="Rotten Tomatoes"><span class="rating-label">${rtIcon} RT</span> <span class="rating-value">${val}%</span></span>`;
    }
    
    if (!html) return '';
    return `<div class="rating-badges">${html}</div>`;
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
    
    // Construct source chips
    let chipsHtml = "";
    if (item.href) {
        chipsHtml += `<a href="${item.href}" target="_blank" class="chip chip-metacritic">Metacritic</a>`;
    }
    const imdbId = item.imdbId || item.imdb_id;
    if (imdbId) {
        chipsHtml += `<a href="https://www.imdb.com/title/${imdbId}/" target="_blank" class="chip chip-imdb">IMDb</a>`;
    }
    const tmdbId = item.tmdbId || item.tmdb_id;
    if (type === "movie" && tmdbId) {
        chipsHtml += `<a href="https://www.themoviedb.org/movie/${tmdbId}" target="_blank" class="chip chip-tmdb">TMDB</a>`;
    }
    const tvdbId = item.tvdbId || item.tvdb_id;
    if (type === "tv" && tvdbId) {
        chipsHtml += `<a href="https://thetvdb.com/dereferrer/series/${tvdbId}" target="_blank" class="chip chip-tvdb">TVDB</a>`;
    }
    const searchString = encodeURIComponent(`${item.title} ${item.year} ${type === 'tv' ? 'tv show' : 'movie'}`);
    chipsHtml += `<a href="https://www.google.com/search?q=${searchString}" target="_blank" class="chip chip-google">Google Search 🔍</a>`;
        
    // Setup poster image
    let posterHtml = "";
    if (item.poster_url) {
        posterHtml = `
            <div class="card-poster">
                <img src="${item.poster_url}" alt="${item.title} poster" class="poster-img" onerror="this.onerror=null; this.parentElement.innerHTML='<div class=&quot;poster-fallback&quot;><span>${type === 'tv' ? '📺' : '🎬'}</span></div>';">
            </div>
        `;
    } else {
        posterHtml = `
            <div class="card-poster">
                <div class="poster-fallback">
                    <span>${type === 'tv' ? '📺' : '🎬'}</span>
                </div>
            </div>
        `;
    }
        
    card.innerHTML = `
        ${posterHtml}
        <div class="card-info-content">
            <div class="card-title-row">
                <h3>${item.title}</h3>
                <div class="card-year-refresh">
                    <span class="year">${item.year}</span>
                    <button class="btn-refresh-icon" title="Refresh Metadata">🔄</button>
                </div>
            </div>
            <div class="card-badges">
                <span class="badge badge-network">${item.network}</span>
                ${returningBadge}
                ${isAdded ? '<span class="badge badge-in-library">In Library</span>' : ''}
                ${item.is_archived ? '<span class="badge" style="background:rgba(255, 42, 133, 0.1); color:var(--accent-magenta); border:1px solid rgba(255, 42, 133, 0.2);">Archived</span>' : ''}
            </div>
            ${buildRatingBadgesHtml(item)}
            <div class="genres-list">${genres}</div>
            <div class="card-cast"><strong>Cast:</strong> <span>${item.cast}</span></div>
            <div class="card-plot">${plotHtml}</div>
            
            <div class="details-toggle-row" style="margin-top: auto; border-top: 1px dashed var(--border-color); padding-top: 8px; display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 11px; color: var(--text-secondary); font-weight: 500;">External Sources</span>
                <button type="button" class="btn-details-toggle" style="background: transparent; border: none; color: var(--accent-blue); font-size: 12px; cursor: pointer; display: flex; align-items: center; gap: 4px; padding: 0; outline: none; font-weight: 600; transition: var(--transition-smooth);">Show ▾</button>
            </div>
            <div class="card-details-panel hidden" style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px;">
                ${chipsHtml}
            </div>
    
            <div class="card-actions" style="margin-top: 0;">
                <a href="${item.trailer}" target="_blank" class="btn btn-trailer">🎬 Trailer</a>
                <button class="${archiveBtnClass}">${archiveBtnLabel}</button>
                <button class="${buttonClass}" ${isAdded ? 'disabled' : ''} onclick="openAddModal('${type}', ${index})">
                    ${buttonText}
                </button>
            </div>
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
        const collectionName = res.collection ? (res.collection.title || res.collection.name) : null;
        const collectionBadge = (type === "movie" && collectionName)
            ? `<span class="badge" style="background: rgba(0, 210, 255, 0.08); color: var(--accent-blue); border: 1px solid rgba(0, 210, 255, 0.2); font-size: 10px; padding: 2px 6px; border-radius: 4px; display: inline-flex; align-items: center; text-transform: none; margin: 0;">📦 ${collectionName}</span>`
            : '';

        itemRow.innerHTML = `
            <div class="lookup-item-details">
                <div class="lookup-item-title">
                    ${res.title}
                    ${isBestMatch ? '<span class="auto-match-tag">Auto Match</span>' : ''}
                </div>
                <div class="lookup-item-meta" style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 4px;">
                    <span class="year-badge">${res.year || 'N/A'}</span>
                    <span class="id-badge">${idLabel}</span>
                    ${collectionBadge}
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
        document.getElementById("input-match-ignore-year").checked = appSettings.default_match_ignore_year !== "0";
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
        return matchFilter(item, searchTerm);
    }).length;
    
    const movieMatchesCount = currentDiscoveries.movies.filter(item => {
        if (!showLibrary && item.is_in_library) return false;
        if (!showArchived && item.is_archived) return false;
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
            <p>Searching ${type === 'tv' ? 'Sonarr' : 'Radarr'} for "${query}"...</p>
        </div>
    `;
    
    try {
        const response = await fetch(`/api/lookup?type=${type}&title=${encodeURIComponent(query)}`);
        const data = await response.json();
        
        if (response.ok && data.status === "success" && data.results && data.results.length > 0) {
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
                    <p>No results found for "${query}". Try a different title or media type.</p>
                </div>
            `;
            addNotification(`No results found for "${query}".`, "info");
        }
    } catch (error) {
        resultsGrid.innerHTML = `
            <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
                <div class="empty-icon" style="font-size: 40px; margin-bottom: 12px;">⚠️</div>
                <p>Search error: ${error.message}</p>
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
    const genres = (res.genres || []).map(g => `<span class="genre-pill">${g}</span>`).join("");
    const certification = res.certification ? `<span class="badge badge-network">${res.certification}</span>` : "";
    
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
            <span class="plot-visible">${visibleText}</span><span class="plot-ellipsis">...</span><span class="plot-hidden hidden">${hiddenText}</span><button class="plot-more-btn">more</button>
        `;
    } else {
        plotHtml = overview;
    }
    
    // Poster HTML
    let posterHtml = "";
    if (posterUrl) {
        posterHtml = `
            <div class="card-poster">
                <img src="${posterUrl}" alt="${title} poster" class="poster-img" onerror="this.onerror=null; this.parentElement.innerHTML='<div class=&quot;poster-fallback&quot;><span>${type === 'tv' ? '📺' : '🎬'}</span></div>';">
            </div>
        `;
    } else {
        posterHtml = `
            <div class="card-poster">
                <div class="poster-fallback">
                    <span>${type === 'tv' ? '📺' : '🎬'}</span>
                </div>
            </div>
        `;
    }
    
    // External source chips
    let chipsHtml = "";
    if (res.imdbId) {
        chipsHtml += `<a href="https://www.imdb.com/title/${res.imdbId}/" target="_blank" class="chip chip-imdb">IMDb</a>`;
    }
    if (type === "movie" && res.tmdbId) {
        chipsHtml += `<a href="https://www.themoviedb.org/movie/${res.tmdbId}" target="_blank" class="chip chip-tmdb">TMDB</a>`;
    }
    if (type === "tv" && res.tvdbId) {
        chipsHtml += `<a href="https://thetvdb.com/dereferrer/series/${res.tvdbId}" target="_blank" class="chip chip-tvdb">TVDB</a>`;
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
                <h3>${title}</h3>
                <div class="card-year-refresh">
                    <span class="year">${year}</span>
                </div>
            </div>
            <div class="card-badges">
                <span class="badge badge-network">${network}</span>
                ${certification}
                ${runtime ? `<span class="badge badge-network">${runtime}</span>` : ''}
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
        alert(`${type === "tv" ? "Sonarr" : "Radarr"} is not configured. Click settings in the top right to configure it.`);
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

    // Multiselect Dropdowns
    const btnGenres = document.getElementById("btn-genres-filter");
    const contentGenres = document.getElementById("content-genres-filter");
    const btnNetworks = document.getElementById("btn-networks-filter");
    const contentNetworks = document.getElementById("content-networks-filter");
    
    if (btnGenres && contentGenres) {
        btnGenres.addEventListener("click", (e) => {
            e.stopPropagation();
            contentGenres.classList.toggle("hidden");
            if (contentNetworks) contentNetworks.classList.add("hidden");
        });
        contentGenres.addEventListener("click", (e) => e.stopPropagation());
    }
    
    if (btnNetworks && contentNetworks) {
        btnNetworks.addEventListener("click", (e) => {
            e.stopPropagation();
            contentNetworks.classList.toggle("hidden");
            if (contentGenres) contentGenres.classList.add("hidden");
        });
        contentNetworks.addEventListener("click", (e) => e.stopPropagation());
    }
    
    document.addEventListener("click", () => {
        if (contentGenres) contentGenres.classList.add("hidden");
        if (contentNetworks) contentNetworks.classList.add("hidden");
    });
    
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

function populateFilterOptions() {
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
                <input type="checkbox" value="${genre}" ${isChecked ? 'checked' : ''}>
                <span>${genre}</span>
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
                <input type="checkbox" value="${network}" ${isChecked ? 'checked' : ''}>
                <span>${network}</span>
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
