/**
 * Settings modal, configurations, cache maintenance, backup/restore,
 * and custom feeds UI management.
 */
import { state, setCustomFeeds } from "./state.js";
import type { FeedItem } from "./types.js";
import {
  collectSettingsPayload as moduleCollectSettingsPayload,
  resolveSettingsDefaults as moduleResolveSettingsDefaults,
  validateFeedForm as moduleValidateFeedForm,
  validateTestFeedInput as moduleValidateTestFeedInput,
  formatTestFeedResults as moduleFormatTestFeedResults,
  buildFeedTableRowHtml as moduleBuildFeedTableRowHtml,
  resolveDefaultParserConfig as moduleResolveDefaultParserConfig,
  getFeedEditorFormDefaults as moduleGetFeedEditorFormDefaults
} from "./settings.js";
import { buildSelectOptionsHtml as moduleBuildSelectOptionsHtml } from "./modals.js";
import { escapeHtml } from "./cards.js";
import {
  saveSettings as apiSaveSettings,
  fetchCacheStats as apiFetchCacheStats,
  pruneCache as apiPruneCache,
  clearCache as apiClearCache,
  getBackupExportUrl as apiGetBackupExportUrl,
  importBackup as apiImportBackup,
  fetchFeeds as apiFetchFeeds,
  saveFeed as apiSaveFeed,
  deleteFeed as apiDeleteFeed,
  testFeed as apiTestFeed,
  restoreDefaultFeeds as apiRestoreDefaultFeeds
} from "./api.js";
import { addNotification } from "./notifications.js";
import { emit, on } from "./events.js";

export function initializeSettingsDefaults(): void {
  if (!state.appSettings || typeof document === "undefined") return;
  const defaults = moduleResolveSettingsDefaults(state.appSettings);

  const sliderPast = document.getElementById("slider-past") as HTMLInputElement | null;
  const valPast = document.getElementById("val-past");
  if (sliderPast) sliderPast.value = defaults.default_past_months;
  if (valPast) valPast.textContent = defaults.default_past_months;

  const sliderFuture = document.getElementById("slider-future") as HTMLInputElement | null;
  const valFuture = document.getElementById("val-future");
  if (sliderFuture) sliderFuture.value = defaults.default_future_months;
  if (valFuture) valFuture.textContent = defaults.default_future_months;

  const returningEl = document.getElementById("check-show-returning") as HTMLInputElement | null;
  const libraryEl = document.getElementById("check-show-library") as HTMLInputElement | null;
  const archivedEl = document.getElementById("check-show-archived") as HTMLInputElement | null;
  if (returningEl) returningEl.checked = defaults.default_show_returning;
  if (libraryEl) libraryEl.checked = defaults.default_show_library;
  if (archivedEl) archivedEl.checked = defaults.default_show_archived;
}

export function updateStatusBadges(): void {
  if (!state.appConfig || typeof document === "undefined") return;

  const statusDemo = document.getElementById("status-demo");
  const isUnconfigured = !state.appConfig.radarr.configured && !state.appConfig.sonarr.configured;
  if (statusDemo) {
    if (isUnconfigured) {
      statusDemo.classList.remove("hidden");
    } else {
      statusDemo.classList.add("hidden");
    }
  }

  const statusRadarr = document.getElementById("status-radarr");
  const statusSonarr = document.getElementById("status-sonarr");

  if (statusRadarr) {
    statusRadarr.className = state.appConfig.radarr.configured
      ? "status-badge status-online"
      : "status-badge status-offline";
  }

  if (statusSonarr) {
    statusSonarr.className = state.appConfig.sonarr.configured
      ? "status-badge status-online"
      : "status-badge status-offline";
  }
}

export function populateSettingsSelect(
  selectEl: HTMLSelectElement | null,
  items: unknown[] | undefined,
  valueProp: string,
  textProp: string,
  currentValue: unknown
): void {
  if (!selectEl) return;
  selectEl.innerHTML = moduleBuildSelectOptionsHtml(
    (items as Array<Record<string, unknown>>) || [],
    valueProp,
    textProp,
    currentValue,
    "None (Use Most-Recently-Used)"
  );
  if (currentValue !== undefined && currentValue !== null && String(currentValue).trim() !== "") {
    const matchFound =
      Array.isArray(items) &&
      items.some(
        item =>
          item &&
          typeof item === "object" &&
          String((item as Record<string, unknown>)[valueProp]).trim() === String(currentValue).trim()
      );
    selectEl.value = matchFound ? String(currentValue) : "";
  } else {
    selectEl.value = "";
  }
}

export function openSettingsModal(): void {
  if (typeof document === "undefined") return;

  const inputRadarrUrl = document.getElementById("input-radarr-url") as HTMLInputElement | null;
  const inputRadarrKey = document.getElementById("input-radarr-key") as HTMLInputElement | null;
  const inputSonarrUrl = document.getElementById("input-sonarr-url") as HTMLInputElement | null;
  const inputSonarrKey = document.getElementById("input-sonarr-key") as HTMLInputElement | null;
  const inputTmdbKey = document.getElementById("input-tmdb-key") as HTMLInputElement | null;
  const inputPastMonths = document.getElementById("input-past-months") as HTMLInputElement | null;
  const inputFutureMonths = document.getElementById("input-future-months") as HTMLInputElement | null;
  const inputShowReturning = document.getElementById("input-show-returning") as HTMLInputElement | null;
  const inputShowLibrary = document.getElementById("input-show-library") as HTMLInputElement | null;
  const inputShowArchived = document.getElementById("input-show-archived") as HTMLInputElement | null;
  const inputMatchIgnoreYear = document.getElementById("input-match-ignore-year") as HTMLInputElement | null;

  if (state.appSettings) {
    const defaults = moduleResolveSettingsDefaults(state.appSettings);
    if (inputRadarrUrl) inputRadarrUrl.value = defaults.radarr_url;
    if (inputRadarrKey) inputRadarrKey.value = defaults.radarr_api_key;
    if (inputSonarrUrl) inputSonarrUrl.value = defaults.sonarr_url;
    if (inputSonarrKey) inputSonarrKey.value = defaults.sonarr_api_key;
    if (inputTmdbKey) inputTmdbKey.value = defaults.tmdb_api_key;
    if (inputPastMonths) inputPastMonths.value = defaults.default_past_months;
    if (inputFutureMonths) inputFutureMonths.value = defaults.default_future_months;
    if (inputShowReturning) inputShowReturning.checked = defaults.default_show_returning;
    if (inputShowLibrary) inputShowLibrary.checked = defaults.default_show_library;
    if (inputShowArchived) inputShowArchived.checked = defaults.default_show_archived;
    if (inputMatchIgnoreYear) inputMatchIgnoreYear.checked = defaults.default_match_ignore_year;
  }

  const selectRadarrDefaultFolder = document.getElementById(
    "select-radarr-default-folder"
  ) as HTMLSelectElement | null;
  const selectRadarrDefaultProfile = document.getElementById(
    "select-radarr-default-profile"
  ) as HTMLSelectElement | null;
  const selectSonarrDefaultFolder = document.getElementById(
    "select-sonarr-default-folder"
  ) as HTMLSelectElement | null;
  const selectSonarrDefaultProfile = document.getElementById(
    "select-sonarr-default-profile"
  ) as HTMLSelectElement | null;

  populateSettingsSelect(
    selectRadarrDefaultFolder,
    state.appConfig?.radarr?.folders,
    "path",
    "path",
    state.appSettings ? state.appSettings.radarr_default_root_folder : ""
  );
  populateSettingsSelect(
    selectRadarrDefaultProfile,
    state.appConfig?.radarr?.profiles,
    "id",
    "name",
    state.appSettings
      ? state.appSettings.radarr_default_quality_profile || state.appSettings.radarr_default_profile_id || ""
      : ""
  );
  populateSettingsSelect(
    selectSonarrDefaultFolder,
    state.appConfig?.sonarr?.folders,
    "path",
    "path",
    state.appSettings ? state.appSettings.sonarr_default_root_folder : ""
  );
  populateSettingsSelect(
    selectSonarrDefaultProfile,
    state.appConfig?.sonarr?.profiles,
    "id",
    "name",
    state.appSettings
      ? state.appSettings.sonarr_default_quality_profile || state.appSettings.sonarr_default_profile_id || ""
      : ""
  );

  const selectTheme = document.getElementById("select-theme-mode") as HTMLSelectElement | null;
  if (selectTheme) {
    const currentTheme = typeof localStorage !== "undefined" ? localStorage.getItem("xarrtools-theme") || "dark" : "dark";
    selectTheme.value = currentTheme;
  }

  const firstTabBtn = document.querySelector(
    ".settings-tab-btn[data-tab='panel-connections']"
  ) as HTMLElement | null;
  if (firstTabBtn) {
    firstTabBtn.click();
  }

  loadCacheStats();

  const settingsOverlay = document.getElementById("settings-overlay");
  if (settingsOverlay) settingsOverlay.classList.remove("hidden");
}

export function closeSettingsModal(): void {
  const settingsOverlay = document.getElementById("settings-overlay");
  if (settingsOverlay) settingsOverlay.classList.add("hidden");
}

export async function saveSettings(): Promise<void> {
  const inputRadarrUrl = (document.getElementById("input-radarr-url") as HTMLInputElement | null)?.value || "";
  const inputRadarrKey = (document.getElementById("input-radarr-key") as HTMLInputElement | null)?.value || "";
  const selectRadarrFolder = (document.getElementById("select-radarr-default-folder") as HTMLSelectElement | null)?.value || "";
  const selectRadarrProfile = (document.getElementById("select-radarr-default-profile") as HTMLSelectElement | null)?.value || "";
  const inputSonarrUrl = (document.getElementById("input-sonarr-url") as HTMLInputElement | null)?.value || "";
  const inputSonarrKey = (document.getElementById("input-sonarr-key") as HTMLInputElement | null)?.value || "";
  const inputTmdbKey = (document.getElementById("input-tmdb-key") as HTMLInputElement | null)?.value || "";
  const selectSonarrFolder = (document.getElementById("select-sonarr-default-folder") as HTMLSelectElement | null)?.value || "";
  const selectSonarrProfile = (document.getElementById("select-sonarr-default-profile") as HTMLSelectElement | null)?.value || "";
  const inputPastMonths = (document.getElementById("input-past-months") as HTMLInputElement | null)?.value || "";
  const inputFutureMonths = (document.getElementById("input-future-months") as HTMLInputElement | null)?.value || "";
  const showReturning = (document.getElementById("input-show-returning") as HTMLInputElement | null)?.checked ?? false;
  const showLibrary = (document.getElementById("input-show-library") as HTMLInputElement | null)?.checked ?? false;
  const showArchived = (document.getElementById("input-show-archived") as HTMLInputElement | null)?.checked ?? false;
  const matchIgnoreYear = (document.getElementById("input-match-ignore-year") as HTMLInputElement | null)?.checked ?? false;

  const payload = moduleCollectSettingsPayload({
    radarrUrl: inputRadarrUrl,
    radarrKey: inputRadarrKey,
    radarrDefaultFolder: selectRadarrFolder,
    radarrDefaultProfile: selectRadarrProfile,
    sonarrUrl: inputSonarrUrl,
    sonarrKey: inputSonarrKey,
    tmdbKey: inputTmdbKey,
    sonarrDefaultFolder: selectSonarrFolder,
    sonarrDefaultProfile: selectSonarrProfile,
    pastMonths: inputPastMonths,
    futureMonths: inputFutureMonths,
    showReturning,
    showLibrary,
    showArchived,
    matchIgnoreYear
  });

  closeSettingsModal();
  const loadingOverlay = document.getElementById("loading-overlay");
  const loadingText = document.getElementById("loading-text");
  if (loadingOverlay) loadingOverlay.classList.remove("hidden");
  if (loadingText) loadingText.textContent = "Saving settings...";

  try {
    const resData = await apiSaveSettings(payload);
    if (loadingOverlay) loadingOverlay.classList.add("hidden");

    if ((resData.ok ?? true) && resData.status === "success") {
      addNotification("Configuration settings updated successfully.", "success");
      emit("loadConfig", false);
    } else {
      addNotification(`Failed to save settings: ${resData.message || "Unknown error."}`, "error");
    }
  } catch (error) {
    if (loadingOverlay) loadingOverlay.classList.add("hidden");
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Failed to connect: ${msg}`, "error");
  }
}

export async function loadCacheStats(): Promise<void> {
  try {
    const data = await apiFetchCacheStats();
    if (data.ok) {
      const statTotal = document.getElementById("stat-total-cache");
      const statArchived = document.getElementById("stat-archived-cache");
      const statDbSize = document.getElementById("stat-db-size");
      if (statTotal && data.total_discoveries !== undefined) statTotal.textContent = String(data.total_discoveries);
      if (statArchived && data.archived_discoveries !== undefined) statArchived.textContent = String(data.archived_discoveries);
      if (statDbSize && data.database_size !== undefined) statDbSize.textContent = String(data.database_size);
    }
  } catch (error) {
    console.error("Failed to load cache stats:", error);
  }
}

export async function pruneCacheManually(): Promise<void> {
  if (typeof window !== "undefined" && window.confirm) {
    if (!window.confirm("Are you sure you want to run cache pruning? This deletes cached releases older than 12 months.")) {
      return;
    }
  }
  try {
    const data = await apiPruneCache();
    if ((data.ok ?? true) && data.status === "success") {
      addNotification(data.message || "Pruned old cache successfully", "success");
      await loadCacheStats();
    } else {
      addNotification(`Pruning failed: ${data.message || "Unknown error"}`, "error");
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Connection error: ${msg}`, "error");
  }
}

export async function wipeCacheManually(): Promise<void> {
  if (typeof window !== "undefined" && window.confirm) {
    if (
      !window.confirm(
        "🚨 WARNING: Are you sure you want to wipe all discoveries from the local cache? This will clear all data, and you will need to re-scan to view them."
      )
    ) {
      return;
    }
  }
  try {
    const data = await apiClearCache();
    if ((data.ok ?? true) && data.status === "success") {
      addNotification(data.message || "Cache wiped successfully", "success");
      await loadCacheStats();

      // Clear current view
      state.currentDiscoveries.tv = [];
      state.currentDiscoveries.movies = [];
      emit("render");

      const contentArea = document.getElementById("content-area");
      const welcomeState = document.getElementById("welcome-state");
      if (contentArea) contentArea.classList.add("hidden");
      if (welcomeState) welcomeState.classList.remove("hidden");
    } else {
      addNotification(`Wipe failed: ${data.message || "Unknown error"}`, "error");
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Connection error: ${msg}`, "error");
  }
}

export function exportBackup(): void {
  let includeMedia = false;
  if (typeof window !== "undefined" && window.confirm) {
    includeMedia = window.confirm("Include cached media details (identifiers & library indicators) in the backup JSON file?\n\nNote: The export file contains your API keys in plain text.");
  }
  window.location.href = apiGetBackupExportUrl(includeMedia);
}

export function exportFullBackup(): void {
  let includeMedia = true;
  if (typeof window !== "undefined" && window.confirm) {
    includeMedia = window.confirm("Include cached media details and posters in the full backup archive (.zip)?\n\nNote: The export file contains your API keys in plain text.");
  }
  window.location.href = apiGetBackupExportUrl(includeMedia, "full");
}

export function triggerBackupImport(): void {
  const fileInput = document.getElementById("file-backup-import") as HTMLInputElement | null;
  if (fileInput) fileInput.click();
}

export async function importBackup(e: Event): Promise<void> {
  const target = e.target as HTMLInputElement;
  const file = target.files ? target.files[0] : null;
  if (!file) return;

  const btnImport = document.getElementById("btn-backup-import") as HTMLButtonElement | null;
  const originalText = btnImport ? btnImport.textContent || "" : "";
  if (btnImport) {
    btnImport.textContent = "⏳ Importing...";
    btnImport.disabled = true;
  }

  const formData = new FormData();
  formData.append("file", file);

  try {
    const data = await apiImportBackup(formData);
    if ((data.ok ?? true) && data.status === "success") {
      let details = `Imported/Updated:\n- Settings: ${data.settings_count ?? 0}\n- Media Items: ${data.media_count ?? 0}`;
      if (typeof data.posters_count === "number" && data.posters_count > 0) {
        details += `\n- Posters: ${data.posters_count}`;
      }
      if (typeof data.custom_feeds_count === "number" && data.custom_feeds_count > 0) {
        details += `\n- Custom Feeds: ${data.custom_feeds_count}`;
      }
      alert(`Backup imported successfully!\n\n${details}`);
      location.reload();
    } else {
      alert(`Failed to import backup: ${data.message || "Unknown error"}`);
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    alert(`Error importing backup: ${msg}`);
  } finally {
    if (btnImport) {
      btnImport.textContent = originalText;
      btnImport.disabled = false;
    }
    target.value = "";
  }
}

// --- Custom Feeds Management ---

export async function loadCustomFeeds(): Promise<void> {
  const tableBody = document.getElementById("feeds-table-body");
  if (!tableBody) return;

  tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--text-secondary);"><div class="spinner-small" style="display:inline-block; vertical-align:middle; margin-right:8px;"></div> Loading feeds...</td></tr>`;

  try {
    const data = await apiFetchFeeds();

    if (data.status === "success") {
      const feeds = data.feeds || [];
      setCustomFeeds(feeds);
      if (feeds.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--text-secondary);">No custom feeds configured.</td></tr>`;
        return;
      }

      tableBody.innerHTML = "";
      feeds.forEach(feed => {
        const tr = document.createElement("tr");
        tr.style.borderBottom = "1px solid var(--border-color)";
        tr.innerHTML = moduleBuildFeedTableRowHtml(feed);

        const editBtn = tr.querySelector(".btn-feed-row-edit");
        if (editBtn) {
          editBtn.addEventListener("click", () => {
            openFeedEditor(feed);
          });
        }
        const deleteBtn = tr.querySelector(".btn-feed-row-delete");
        if (deleteBtn) {
          deleteBtn.addEventListener("click", () => {
            deleteCustomFeed(feed.id, feed.name);
          });
        }

        tableBody.appendChild(tr);
      });
    } else {
      tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--accent-magenta);">Error loading feeds: ${escapeHtml(data.message || "")}</td></tr>`;
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    tableBody.innerHTML = `<tr><td colspan="4" style="padding: 12px; text-align: center; color: var(--accent-magenta);">Fetch failed: ${escapeHtml(msg)}</td></tr>`;
  }
}

export function openFeedEditor(feed: FeedItem | null): void {
  const listView = document.getElementById("feeds-list-view");
  const editorView = document.getElementById("feed-editor-view");

  if (!listView || !editorView) return;

  listView.classList.add("hidden");
  editorView.classList.remove("hidden");
  const preview = document.getElementById("feed-test-preview");
  if (preview) preview.classList.add("hidden");

  const defaults = moduleGetFeedEditorFormDefaults(feed);
  const titleEl = document.getElementById("feed-editor-title");
  const idEl = document.getElementById("feed-id") as HTMLInputElement | null;
  const nameEl = document.getElementById("feed-name") as HTMLInputElement | null;
  const urlEl = document.getElementById("feed-url") as HTMLInputElement | null;
  const typeEl = document.getElementById("feed-type") as HTMLSelectElement | null;
  const mediaTypeEl = document.getElementById("feed-media-type") as HTMLSelectElement | null;
  const enabledEl = document.getElementById("feed-enabled") as HTMLInputElement | null;
  const headersEl = document.getElementById("feed-headers") as HTMLTextAreaElement | null;
  const configEl = document.getElementById("feed-parser-config") as HTMLTextAreaElement | null;

  if (titleEl) titleEl.textContent = defaults.title;
  if (idEl) idEl.value = defaults.id;
  if (nameEl) nameEl.value = defaults.name;
  if (urlEl) urlEl.value = defaults.url;
  if (typeEl) typeEl.value = defaults.feed_type;
  if (mediaTypeEl) mediaTypeEl.value = defaults.default_media_type;
  if (enabledEl) enabledEl.checked = defaults.enabled;
  if (headersEl) headersEl.value = defaults.headers_json;
  if (configEl) configEl.value = defaults.parser_config_json;

  switchEditorTab("feed-tab-general");
}

export function closeFeedEditor(): void {
  const listView = document.getElementById("feeds-list-view");
  const editorView = document.getElementById("feed-editor-view");
  if (listView && editorView) {
    editorView.classList.add("hidden");
    listView.classList.remove("hidden");
    loadCustomFeeds();
  }
}

export function switchEditorTab(tabId: string): void {
  const tabButtons = document.querySelectorAll(".feed-tab-btn");
  const tabPanels = document.querySelectorAll(".feed-editor-tab-panel");

  tabButtons.forEach(btn => {
    const btnEl = btn as HTMLElement;
    if (btnEl.getAttribute("data-editor-tab") === tabId) {
      btnEl.classList.add("active");
      btnEl.style.color = "var(--accent-blue)";
    } else {
      btnEl.classList.remove("active");
      btnEl.style.color = "var(--text-secondary)";
    }
  });

  tabPanels.forEach(panel => {
    const pEl = panel as HTMLElement;
    if (pEl.id === tabId) {
      pEl.classList.remove("hidden");
      if (tabId === "feed-tab-mapping") {
        pEl.style.display = "flex";
      } else {
        pEl.style.display = "block";
      }
    } else {
      pEl.classList.add("hidden");
      pEl.style.display = "none";
    }
  });
}

export function handleFeedTypeChange(): void {
  const feedType = (document.getElementById("feed-type") as HTMLSelectElement | null)?.value || "";
  const parserConfigField = document.getElementById("feed-parser-config") as HTMLTextAreaElement | null;
  if (!parserConfigField) return;
  const nextConfig = moduleResolveDefaultParserConfig(feedType, parserConfigField.value);
  if (nextConfig !== null) {
    parserConfigField.value = nextConfig;
  }
}

export async function saveCustomFeed(): Promise<void> {
  const feedId = (document.getElementById("feed-id") as HTMLInputElement | null)?.value || "";
  const name = (document.getElementById("feed-name") as HTMLInputElement | null)?.value || "";
  const url = (document.getElementById("feed-url") as HTMLInputElement | null)?.value || "";
  const feedType = (document.getElementById("feed-type") as HTMLSelectElement | null)?.value || "";
  const defaultMediaType = (document.getElementById("feed-media-type") as HTMLSelectElement | null)?.value || "";
  const enabled = (document.getElementById("feed-enabled") as HTMLInputElement | null)?.checked ?? true;
  const headersRaw = (document.getElementById("feed-headers") as HTMLTextAreaElement | null)?.value || "";
  const configRaw = (document.getElementById("feed-parser-config") as HTMLTextAreaElement | null)?.value || "";

  const validated = moduleValidateFeedForm({
    id: feedId,
    name,
    url,
    feed_type: feedType,
    default_media_type: defaultMediaType,
    enabled,
    headers_raw: headersRaw,
    parser_config_raw: configRaw
  });

  if (!validated.valid || !validated.payload) {
    alert(validated.error || "Please enter a feed name and URL.");
    return;
  }

  const payload = validated.payload;
  const saveBtn = document.getElementById("btn-feed-save") as HTMLButtonElement | null;
  if (saveBtn) saveBtn.disabled = true;

  try {
    const data = await apiSaveFeed(payload);
    if (saveBtn) saveBtn.disabled = false;

    if ((data.ok ?? true) && data.status === "success") {
      addNotification(`Feed '${name}' saved successfully.`, "success");
      closeFeedEditor();
    } else {
      addNotification(`Save failed: ${data.message || "Unknown error"}`, "error");
    }
  } catch (err) {
    if (saveBtn) saveBtn.disabled = false;
    const msg = err instanceof Error ? err.message : String(err);
    addNotification(`Connection error: ${msg}`, "error");
  }
}

export async function deleteCustomFeed(feedId: number, feedName: string): Promise<void> {
  if (typeof window !== "undefined" && window.confirm) {
    if (!window.confirm(`Are you sure you want to delete the custom feed '${feedName}'?`)) {
      return;
    }
  }

  try {
    const data = await apiDeleteFeed(feedId);
    if ((data.ok ?? true) && data.status === "success") {
      addNotification(`Feed '${feedName}' deleted.`, "success");
      loadCustomFeeds();
    } else {
      addNotification(`Delete failed: ${data.message || "Unknown error"}`, "error");
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    addNotification(`Connection error: ${msg}`, "error");
  }
}

export async function testCustomFeed(): Promise<void> {
  const url = (document.getElementById("feed-url") as HTMLInputElement | null)?.value || "";
  const feedType = (document.getElementById("feed-type") as HTMLSelectElement | null)?.value || "";
  const defaultMediaType = (document.getElementById("feed-media-type") as HTMLSelectElement | null)?.value || "";
  const headersRaw = (document.getElementById("feed-headers") as HTMLTextAreaElement | null)?.value || "";
  const configRaw = (document.getElementById("feed-parser-config") as HTMLTextAreaElement | null)?.value || "";

  const validated = moduleValidateTestFeedInput({
    url,
    feed_type: feedType,
    default_media_type: defaultMediaType,
    headers_raw: headersRaw,
    parser_config_raw: configRaw
  });

  if (!validated.valid || !validated.payload) {
    alert(validated.error || "Please enter a feed URL to test.");
    return;
  }

  const previewCard = document.getElementById("feed-test-preview");
  const previewStats = document.getElementById("feed-test-stats");
  const previewResults = document.getElementById("feed-test-results");
  const testBtn = document.getElementById("btn-feed-test") as HTMLButtonElement | null;

  if (previewCard) previewCard.classList.remove("hidden");
  if (previewStats) previewStats.textContent = "Testing...";
  if (previewResults) previewResults.textContent = "Connecting to feed URL and running parsed mapping diagnostics. Please wait...";

  if (testBtn) testBtn.disabled = true;

  try {
    const data = await apiTestFeed(validated.payload);
    if (testBtn) testBtn.disabled = false;

    if ((data.ok ?? true) && data.status === "success") {
      const timeMs = data.fetch_time_ms || 0;
      const itemsCount = data.parsed_items_count || 0;
      if (previewStats) previewStats.textContent = `Success (${timeMs}ms)`;
      if (previewResults) previewResults.textContent = moduleFormatTestFeedResults(data.results, itemsCount, timeMs);
    } else {
      if (previewStats) previewStats.textContent = "Error";
      if (previewResults) previewResults.textContent = `Dry-run test failed:\n${data.message || "Unknown error occurred"}`;
    }
  } catch (err) {
    if (testBtn) testBtn.disabled = false;
    const msg = err instanceof Error ? err.message : String(err);
    if (previewStats) previewStats.textContent = "Connection Failure";
    if (previewResults) previewResults.textContent = `HTTP post request failed: ${msg}`;
  }
}

export async function restoreDefaultFeeds(): Promise<void> {
  if (typeof window !== "undefined" && window.confirm) {
    if (
      !window.confirm(
        "Are you sure you want to restore all feeds to default? This will delete any custom feeds you have configured and bring back Metacritic and DVDs calendars."
      )
    ) {
      return;
    }
  }

  try {
    const data = await apiRestoreDefaultFeeds();
    if ((data.ok ?? true) && data.status === "success") {
      addNotification("Default feeds restored successfully.", "success");
      loadCustomFeeds();
    } else {
      addNotification(`Restore failed: ${data.message || "Unknown error"}`, "error");
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    addNotification(`Connection error: ${msg}`, "error");
  }
}

// Event subscription for opening settings modal
on("openSettingsModal", () => {
  openSettingsModal();
});
