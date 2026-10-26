/**
 * Main application entry point for xarrtools frontend.
 * Initializes theme, loads configs/settings, configures event listeners and API key interceptor.
 */
import { state, setConfig, setSettings, setDiscoveries } from "./state.js";
import {
  fetchSettings,
  fetchConfig,
  fetchScanProgress,
  fetchDiscoveries
} from "./api.js";
import { initTheme, toggleTheme, updateThemeToggleUI } from "./theme.js";
import { addNotification } from "./notifications.js";
import {
  renderMediaLists,
  applyTabFilter,
  populateFilterOptions,
  updateGenreFilterBtnText,
  updateNetworkFilterBtnText,
  invertMultiselect,
  archiveAllFiltered
} from "./render.js";
import {
  openSettingsModal,
  closeSettingsModal,
  saveSettings,
  initializeSettingsDefaults,
  updateStatusBadges,
  loadCacheStats,
  pruneCacheManually,
  wipeCacheManually,
  exportBackup,
  triggerBackupImport,
  importBackup,
  loadCustomFeeds,
  openFeedEditor,
  closeFeedEditor,
  switchEditorTab,
  handleFeedTypeChange,
  saveCustomFeed,
  deleteCustomFeed,
  testCustomFeed,
  restoreDefaultFeeds,
  populateSettingsSelect
} from "./settings-ui.js";
import {
  openAddModal,
  closeModal,
  addMediaItem,
  goBackToSearchStep
} from "./modals-ui.js";
import { runGlobalSearch } from "./search-ui.js";
import { resolveHybridPreset, updateMRUCache } from "./settings.js";
import { on, emit } from "./events.js";

// Setup API Key Interceptor for all fetch requests
export function setupApiKeyInterceptor(): void {
  if (typeof window === "undefined" || !window.fetch) return;
  const originalFetch = window.fetch;
  window.fetch = async function(resource: RequestInfo | URL, config?: RequestInit) {
    if (typeof resource === "string" && resource.startsWith("/api/")) {
      config = config || {};
      const apiKeyMeta = document.querySelector('meta[name="x-api-key"]') as HTMLMetaElement | null;
      if (apiKeyMeta && apiKeyMeta.content) {
        if (!config.headers) {
          config.headers = {};
        }
        if (config.headers instanceof Headers) {
          config.headers.set("X-API-Key", apiKeyMeta.content);
        } else if (Array.isArray(config.headers)) {
          config.headers.push(["X-API-Key", apiKeyMeta.content]);
        } else {
          (config.headers as Record<string, string>)["X-API-Key"] = apiKeyMeta.content;
        }
      }
    }
    return originalFetch.call(this, resource, config);
  };
}

export function startProgressPolling(): void {
  if (state.progressInterval) {
    clearInterval(state.progressInterval as number);
    state.progressInterval = null;
  }

  const popover = document.getElementById("scan-progress-popover");
  const statusMsg = document.getElementById("progress-status-msg");
  const percentText = document.getElementById("progress-percent-text");
  const barFill = document.getElementById("progress-bar-fill");

  if (popover) popover.classList.remove("hidden");
  if (statusMsg) statusMsg.textContent = "Initiating scan...";
  if (percentText) percentText.textContent = "0%";
  if (barFill) barFill.style.width = "0%";

  let hasStarted = false;

  const intervalId = setInterval(async () => {
    try {
      const data = await fetchScanProgress();
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

  state.progressInterval = intervalId;
}

export function stopProgressPolling(): void {
  if (state.progressInterval) {
    clearInterval(state.progressInterval as number);
    state.progressInterval = null;
  }
  const popover = document.getElementById("scan-progress-popover");
  if (popover) popover.classList.add("hidden");
}

export async function scanReleases(skipScrape = false): Promise<void> {
  const shouldSkipScrape = skipScrape === true;
  const popover = document.getElementById("scan-progress-popover");
  const statusMsg = document.getElementById("progress-status-msg");
  const percentText = document.getElementById("progress-percent-text");
  const barFill = document.getElementById("progress-bar-fill");
  const welcomeState = document.getElementById("welcome-state");
  const contentArea = document.getElementById("content-area");

  if (shouldSkipScrape) {
    if (popover) popover.classList.remove("hidden");
    if (statusMsg) statusMsg.textContent = "Loading cached releases...";
    if (percentText) percentText.textContent = "Please wait...";
    if (barFill) barFill.style.width = "50%";

    if (welcomeState) welcomeState.classList.add("hidden");
    if (contentArea) contentArea.classList.remove("hidden");
  } else {
    startProgressPolling();
    if (welcomeState) welcomeState.classList.add("hidden");
    if (contentArea) contentArea.classList.remove("hidden");
  }

  const sliderPast = document.getElementById("slider-past") as HTMLInputElement | null;
  const sliderFuture = document.getElementById("slider-future") as HTMLInputElement | null;
  const pastMonths = sliderPast ? sliderPast.value : "1";
  const futureMonths = sliderFuture ? sliderFuture.value : "2";

  try {
    const data = await fetchDiscoveries({ pastMonths, futureMonths, skipScrape: shouldSkipScrape });
    setDiscoveries({
      tv: data.tv || [],
      movies: data.movies || []
    });

    populateFilterOptions();
    renderMediaLists();

    const tvEmpty = state.currentDiscoveries.tv.length === 0;
    const moviesEmpty = state.currentDiscoveries.movies.length === 0;

    if (tvEmpty && moviesEmpty) {
      if (welcomeState) welcomeState.classList.remove("hidden");
      if (contentArea) contentArea.classList.add("hidden");
    } else {
      if (welcomeState) welcomeState.classList.add("hidden");
      if (contentArea) contentArea.classList.remove("hidden");
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    if (typeof alert !== "undefined") {
      alert(`Error: ${msg}`);
    }
  } finally {
    if (shouldSkipScrape) {
      if (popover) popover.classList.add("hidden");
    } else {
      stopProgressPolling();
    }
  }
}

export async function loadSettingsAndConfig(isInitialLoad = true): Promise<void> {
  try {
    const settings = await fetchSettings();
    setSettings(settings);

    const config = await fetchConfig();
    setConfig(config);

    initializeSettingsDefaults();
    updateStatusBadges();

    if (config?.radarr?.error) {
      addNotification(`Radarr offline: ${config.radarr.error}`, "error");
    }
    if (config?.sonarr?.error) {
      addNotification(`Sonarr offline: ${config.sonarr.error}`, "error");
    }

    if (isInitialLoad && config && !config.radarr.configured && !config.sonarr.configured) {
      openSettingsModal();
    }

    await scanReleases(true);
  } catch (error) {
    console.error("Failed to load application configs:", error);
  }
}

export function posterFallback(img: HTMLImageElement | null): void {
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
  titleP.style.cssText =
    "font-size: 11px; padding: 0 8px; font-weight: 500; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;";
  titleP.textContent = title;

  fallbackDiv.appendChild(iconSpan);
  fallbackDiv.appendChild(titleP);

  parent.innerHTML = "";
  parent.appendChild(fallbackDiv);
}

export function setupEventListeners(): void {
  if (typeof document === "undefined") return;

  const btnThemeToggle = document.getElementById("btn-theme-toggle");
  if (btnThemeToggle) {
    btnThemeToggle.addEventListener("click", toggleTheme);
  }

  const notificationsHeader = document.getElementById("notifications-header");
  const notificationsCard = document.getElementById("notifications-card");
  if (notificationsHeader && notificationsCard) {
    notificationsHeader.addEventListener("click", () => {
      notificationsCard.classList.toggle("collapsed");
    });
  }

  const btnCloseProgress = document.getElementById("btn-close-progress");
  if (btnCloseProgress) {
    btnCloseProgress.addEventListener("click", () => {
      const popover = document.getElementById("scan-progress-popover");
      if (popover) popover.classList.add("hidden");
    });
  }

  const btnScan = document.getElementById("btn-scan");
  if (btnScan) {
    btnScan.addEventListener("click", () => scanReleases(false));
  }

  const modalClose = document.getElementById("modal-close");
  const btnModalCancel = document.getElementById("btn-modal-cancel");
  const btnModalConfirm = document.getElementById("btn-modal-confirm");
  const btnModalAddOnly = document.getElementById("btn-modal-add-only");
  const btnModalBack = document.getElementById("btn-modal-back");
  const btnModalMarkLibrary = document.getElementById("btn-modal-mark-library");
  const linkHelperBanner = document.getElementById("link-helper-banner");

  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (btnModalCancel) btnModalCancel.addEventListener("click", closeModal);
  if (btnModalConfirm) btnModalConfirm.addEventListener("click", () => addMediaItem(true));
  if (btnModalAddOnly) btnModalAddOnly.addEventListener("click", () => addMediaItem(false));
  if (btnModalBack) btnModalBack.addEventListener("click", goBackToSearchStep);

  if (btnModalMarkLibrary) {
    btnModalMarkLibrary.addEventListener("click", () => {
      state.isMarkInLibraryMode = !state.isMarkInLibraryMode;
      if (state.isMarkInLibraryMode) {
        btnModalMarkLibrary.classList.add("btn-modal-mark-library-active");
        btnModalMarkLibrary.textContent = "Cancel Link Mode";
        if (linkHelperBanner) linkHelperBanner.classList.remove("hidden");
      } else {
        btnModalMarkLibrary.classList.remove("btn-modal-mark-library-active");
        btnModalMarkLibrary.textContent = "Mark In Library";
        if (linkHelperBanner) linkHelperBanner.classList.add("hidden");
      }
    });
  }

  const selectSort = document.getElementById("select-sort");
  if (selectSort) {
    selectSort.addEventListener("change", renderMediaLists);
  }

  const searchBar = document.getElementById("search-bar") as HTMLInputElement | null;
  const clearSearchBarBtn = document.getElementById("btn-clear-search");

  if (searchBar) {
    searchBar.addEventListener("input", () => {
      renderMediaLists();
      if (clearSearchBarBtn) {
        if (searchBar.value) {
          clearSearchBarBtn.classList.remove("hidden");
        } else {
          clearSearchBarBtn.classList.add("hidden");
        }
      }
    });
  }

  if (clearSearchBarBtn && searchBar) {
    clearSearchBarBtn.addEventListener("click", () => {
      searchBar.value = "";
      clearSearchBarBtn.classList.add("hidden");
      renderMediaLists();
      searchBar.focus();
    });
  }

  const sliderPast = document.getElementById("slider-past") as HTMLInputElement | null;
  const valPast = document.getElementById("val-past");
  if (sliderPast && valPast) {
    sliderPast.addEventListener("input", () => {
      valPast.textContent = sliderPast.value;
    });
  }

  const sliderFuture = document.getElementById("slider-future") as HTMLInputElement | null;
  const valFuture = document.getElementById("val-future");
  if (sliderFuture && valFuture) {
    sliderFuture.addEventListener("input", () => {
      valFuture.textContent = sliderFuture.value;
    });
  }

  const returningCb = document.getElementById("check-show-returning");
  const libraryCb = document.getElementById("check-show-library");
  const archivedCb = document.getElementById("check-show-archived");
  if (returningCb) returningCb.addEventListener("change", renderMediaLists);
  if (libraryCb) libraryCb.addEventListener("change", renderMediaLists);
  if (archivedCb) archivedCb.addEventListener("change", renderMediaLists);

  const btnSettings = document.getElementById("btn-settings");
  const settingsClose = document.getElementById("settings-close");
  const btnSettingsCancel = document.getElementById("btn-settings-cancel");
  const btnSettingsSave = document.getElementById("btn-settings-save");

  if (btnSettings) btnSettings.addEventListener("click", openSettingsModal);
  if (settingsClose) settingsClose.addEventListener("click", closeSettingsModal);
  if (btnSettingsCancel) btnSettingsCancel.addEventListener("click", closeSettingsModal);
  if (btnSettingsSave) btnSettingsSave.addEventListener("click", saveSettings);

  const selectTheme = document.getElementById("select-theme-mode") as HTMLSelectElement | null;
  if (selectTheme) {
    selectTheme.addEventListener("change", (e: Event) => {
      const selected = (e.target as HTMLSelectElement).value;
      const isLight = selected === "light";
      if (document.body) {
        if (isLight) {
          document.body.classList.add("light-theme");
        } else {
          document.body.classList.remove("light-theme");
        }
      }
      if (typeof localStorage !== "undefined") {
        localStorage.setItem("xarrtools-theme", selected);
      }
      updateThemeToggleUI(isLight);
    });
  }

  const settingsTabButtons = document.querySelectorAll(".settings-tab-btn");
  const settingsTabPanels = document.querySelectorAll(".settings-tab-panel");

  settingsTabButtons.forEach(btn => {
    btn.addEventListener("click", (e: Event) => {
      const targetEl = e.currentTarget as HTMLElement;
      const targetTab = targetEl.getAttribute("data-tab");

      settingsTabButtons.forEach(b => b.classList.remove("active"));
      targetEl.classList.add("active");

      settingsTabPanels.forEach(p => {
        const pEl = p as HTMLElement;
        if (pEl.id === targetTab) {
          pEl.classList.remove("hidden");
        } else {
          pEl.classList.add("hidden");
        }
      });

      if (targetTab === "panel-feeds") {
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

  const btnCachePrune = document.getElementById("btn-cache-prune");
  const btnCacheClear = document.getElementById("btn-cache-clear");
  if (btnCachePrune) btnCachePrune.addEventListener("click", pruneCacheManually);
  if (btnCacheClear) btnCacheClear.addEventListener("click", wipeCacheManually);

  const btnBackupExport = document.getElementById("btn-backup-export");
  if (btnBackupExport) btnBackupExport.addEventListener("click", exportBackup);

  const btnBackupImport = document.getElementById("btn-backup-import");
  if (btnBackupImport) btnBackupImport.addEventListener("click", triggerBackupImport);

  const fileBackupImport = document.getElementById("file-backup-import");
  if (fileBackupImport) fileBackupImport.addEventListener("change", importBackup);

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

  const btnGlobalSearch = document.getElementById("btn-global-search");
  const globalSearchInput = document.getElementById("global-search-input") as HTMLInputElement | null;
  const clearGlobalSearchBtn = document.getElementById("btn-clear-global-search");

  if (btnGlobalSearch) btnGlobalSearch.addEventListener("click", runGlobalSearch);
  if (globalSearchInput) {
    globalSearchInput.addEventListener("keyup", (e: KeyboardEvent) => {
      if (e.key === "Enter") runGlobalSearch();
    });
    globalSearchInput.addEventListener("input", () => {
      if (clearGlobalSearchBtn) {
        if (globalSearchInput.value) {
          clearGlobalSearchBtn.classList.remove("hidden");
        } else {
          clearGlobalSearchBtn.classList.add("hidden");
        }
      }
    });
  }

  if (clearGlobalSearchBtn && globalSearchInput) {
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

  const tabButtons = document.querySelectorAll(".tab-btn");
  tabButtons.forEach(btn => {
    btn.addEventListener("click", (e: Event) => {
      tabButtons.forEach(b => b.classList.remove("active"));
      (e.currentTarget as HTMLElement).classList.add("active");
      applyTabFilter();
    });
  });

  const modalOverlay = document.getElementById("modal-overlay");
  if (modalOverlay) {
    modalOverlay.addEventListener("click", (e: Event) => {
      if (e.target === modalOverlay) {
        closeModal();
      }
    });
  }

  const settingsOverlay = document.getElementById("settings-overlay");
  if (settingsOverlay) {
    settingsOverlay.addEventListener("click", (e: Event) => {
      if (e.target === settingsOverlay) {
        closeSettingsModal();
      }
    });
  }

  // Multiselect dropdown toggling
  const dropdownContents = ["genres", "networks", "country", "language"]
    .map(k => ({
      btn: document.getElementById("btn-" + k + "-filter"),
      content: document.getElementById("content-" + k + "-filter")
    }))
    .filter(d => d.btn && d.content);

  dropdownContents.forEach(d => {
    if (!d.btn || !d.content) return;
    d.btn.addEventListener("click", (e: Event) => {
      e.stopPropagation();
      dropdownContents.forEach(o => {
        if (o !== d && o.content) o.content.classList.add("hidden");
      });
      d.content?.classList.toggle("hidden");
    });
    d.content.addEventListener("click", (e: Event) => e.stopPropagation());
  });

  document.addEventListener("click", () => {
    dropdownContents.forEach(o => {
      if (o.content) o.content.classList.add("hidden");
    });
  });

  const clearCountryBtn = document.getElementById("clear-country-filter");
  if (clearCountryBtn) {
    clearCountryBtn.addEventListener("click", () => {
      state.selectedCountries.clear();
      document.querySelectorAll("#options-country-filter input").forEach(node => {
        (node as HTMLInputElement).checked = false;
      });
      const btn = document.getElementById("btn-country-filter");
      if (btn) {
        btn.textContent = "Country (All)";
        btn.classList.remove("active");
      }
      renderMediaLists();
    });
  }

  const clearLanguageBtn = document.getElementById("clear-language-filter");
  if (clearLanguageBtn) {
    clearLanguageBtn.addEventListener("click", () => {
      state.selectedLanguages.clear();
      document.querySelectorAll("#options-language-filter input").forEach(node => {
        (node as HTMLInputElement).checked = false;
      });
      const btn = document.getElementById("btn-language-filter");
      if (btn) {
        btn.textContent = "Language (All)";
        btn.classList.remove("active");
      }
      renderMediaLists();
    });
  }

  // Invert buttons
  const invertGenres = document.getElementById("invert-genres-filter");
  if (invertGenres) {
    invertGenres.addEventListener("click", () => {
      invertMultiselect("genres", state.selectedGenres, updateGenreFilterBtnText);
    });
  }
  const invertNetworks = document.getElementById("invert-networks-filter");
  if (invertNetworks) {
    invertNetworks.addEventListener("click", () => {
      invertMultiselect("networks", state.selectedNetworks, updateNetworkFilterBtnText);
    });
  }
  const invertCountry = document.getElementById("invert-country-filter");
  if (invertCountry) {
    invertCountry.addEventListener("click", () => {
      invertMultiselect("country", state.selectedCountries, null);
    });
  }
  const invertLanguage = document.getElementById("invert-language-filter");
  if (invertLanguage) {
    invertLanguage.addEventListener("click", () => {
      invertMultiselect("language", state.selectedLanguages, null);
    });
  }

  const btnArchiveFiltered = document.getElementById("btn-archive-filtered");
  if (btnArchiveFiltered) btnArchiveFiltered.addEventListener("click", archiveAllFiltered);

  const clearGenresBtn = document.getElementById("clear-genres-filter");
  if (clearGenresBtn) {
    clearGenresBtn.addEventListener("click", () => {
      state.selectedGenres.clear();
      document.querySelectorAll("#options-genres-filter input").forEach(cb => {
        (cb as HTMLInputElement).checked = false;
      });
      updateGenreFilterBtnText();
      renderMediaLists();
    });
  }

  const clearNetworksBtn = document.getElementById("clear-networks-filter");
  if (clearNetworksBtn) {
    clearNetworksBtn.addEventListener("click", () => {
      state.selectedNetworks.clear();
      document.querySelectorAll("#options-networks-filter input").forEach(cb => {
        (cb as HTMLInputElement).checked = false;
      });
      updateNetworkFilterBtnText();
      renderMediaLists();
    });
  }
}

// Global window assignments for inline HTML handlers, backwards compatibility, and test suites
if (typeof window !== "undefined") {
  const win = window as unknown as Record<string, unknown>;
  win.openAddModal = openAddModal;
  win.populateSettingsSelect = populateSettingsSelect;
  win.resolveHybridPreset = resolveHybridPreset;
  win.updateMRUCache = updateMRUCache;
  win.renderDiscoveries = renderMediaLists;
  win.xarrtoolsPosterFallback = posterFallback;
}

// Listen for scan / config reload events
on("loadConfig", (isInitialLoad?: boolean) => {
  loadSettingsAndConfig(isInitialLoad);
});

on("scan", (skipScrape?: boolean) => {
  scanReleases(skipScrape);
});

// Auto-initialize on DOM ready
if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    setupApiKeyInterceptor();
    initTheme();
    loadSettingsAndConfig();
    setupEventListeners();
  });
}
