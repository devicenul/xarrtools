/**
 * Add to *Arr modal flow, indexer lookup, and library linking controllers.
 */
import { state } from "./state.js";
import type { MediaItem, LookupResultItem, ServiceConfig, AddMediaPayload } from "./types.js";
import {
  lookupMedia as apiLookupMedia,
  addMedia as apiAddMedia,
  linkLibrary as apiLinkLibrary
} from "./api.js";
import {
  buildSelectOptionsHtml as moduleBuildSelectOptionsHtml,
  isIndexerBestMatch as moduleIsIndexerBestMatch,
  getCollectionName as moduleGetCollectionName,
  buildLookupItemHtml as moduleBuildLookupItemHtml,
  buildLookupStatusHtml as moduleBuildLookupStatusHtml,
  buildAddMediaPayload as moduleBuildAddMediaPayload
} from "./modals.js";
import {
  resolveHybridPreset,
  updateMRUCache
} from "./settings.js";
import { addNotification } from "./notifications.js";
import { emit, on } from "./events.js";

export async function openAddModal(type: string, index: number): Promise<void> {
  const item = type === "tv" ? state.currentDiscoveries.tv[index] : state.currentDiscoveries.movies[index];
  if (!item) return;

  state.selectedItemForAdd = { type, item };

  if (!state.appConfig) {
    if (typeof alert !== "undefined") {
      alert("Server configuration is not loaded yet.");
    }
    return;
  }

  const targetConfig = type === "tv" ? state.appConfig.sonarr : state.appConfig.radarr;
  if (!targetConfig || !targetConfig.configured) {
    openDemoAddModal(type, item, index, null);
    return;
  }

  if (typeof document === "undefined") return;

  const modalOverlay = document.getElementById("modal-overlay");
  const modalTitle = document.getElementById("modal-title");
  const modalStepSearch = document.getElementById("modal-step-search");
  const modalStepOptions = document.getElementById("modal-step-options");
  const btnModalBack = document.getElementById("btn-modal-back");
  const btnModalConfirm = document.getElementById("btn-modal-confirm");
  const lookupLoading = document.getElementById("lookup-loading");
  const lookupResultsList = document.getElementById("lookup-results-list");
  const btnModalMarkLibrary = document.getElementById("btn-modal-mark-library");
  const linkHelperBanner = document.getElementById("link-helper-banner");

  state.isMarkInLibraryMode = false;
  if (linkHelperBanner) linkHelperBanner.classList.add("hidden");
  if (btnModalMarkLibrary) {
    btnModalMarkLibrary.classList.remove("hidden");
    btnModalMarkLibrary.classList.remove("btn-modal-mark-library-active");
    btnModalMarkLibrary.textContent = "Mark In Library";
  }

  if (modalTitle) modalTitle.textContent = `Search Indexer for '${item.title}'`;
  if (modalStepSearch) modalStepSearch.classList.remove("hidden");
  if (modalStepOptions) modalStepOptions.classList.add("hidden");
  if (btnModalBack) btnModalBack.classList.add("hidden");
  if (btnModalConfirm) btnModalConfirm.classList.add("hidden");

  if (lookupLoading) lookupLoading.classList.remove("hidden");
  if (lookupResultsList) {
    lookupResultsList.classList.add("hidden");
    lookupResultsList.innerHTML = "";
  }

  if (modalOverlay) modalOverlay.classList.remove("hidden");

  try {
    const data = await apiLookupMedia(type, item.title);
    if (lookupLoading) lookupLoading.classList.add("hidden");
    if (lookupResultsList) {
      lookupResultsList.classList.remove("hidden");
      if ((data.ok ?? true) && data.status === "success" && data.results && data.results.length > 0) {
        renderLookupResults(data.results, type, item);
      } else {
        lookupResultsList.innerHTML = moduleBuildLookupStatusHtml("No results found on indexers. Please check title manually.");
      }
    }
  } catch (error) {
    if (lookupLoading) lookupLoading.classList.add("hidden");
    const msg = error instanceof Error ? error.message : String(error);
    if (lookupResultsList) {
      lookupResultsList.innerHTML = moduleBuildLookupStatusHtml(`Error loading indexers: ${msg}`);
    }
  }
}

export function renderLookupResults(results: LookupResultItem[], type: string, discoveryItem: MediaItem): void {
  const lookupResultsList = document.getElementById("lookup-results-list");
  if (!lookupResultsList) return;

  lookupResultsList.innerHTML = "";

  results.forEach(res => {
    const itemRow = document.createElement("div");
    itemRow.className = "lookup-item";

    const inLibrary = Boolean(res.id);
    const isBestMatch = moduleIsIndexerBestMatch(discoveryItem, res, type);
    if (isBestMatch) {
      itemRow.classList.add("best-match");
    }

    itemRow.innerHTML = moduleBuildLookupItemHtml(res, type, isBestMatch, inLibrary);

    itemRow.addEventListener("click", () => {
      if (state.isMarkInLibraryMode) {
        linkDiscoveryToLibrary(res, discoveryItem);
        return;
      }
      if (inLibrary) {
        if (typeof alert !== "undefined") {
          alert(`'${res.title}' is already in your library!`);
        }
        return;
      }
      goToOptionsStep(res);
    });

    lookupResultsList.appendChild(itemRow);
  });
}

export async function linkDiscoveryToLibrary(
  metadataItem: Record<string, unknown> | LookupResultItem,
  discoveryItem: MediaItem
): Promise<void> {
  const type = state.selectedItemForAdd ? state.selectedItemForAdd.type : "";
  try {
    const data = await apiLinkLibrary({
      type: type,
      title: discoveryItem.title,
      year: discoveryItem.year != null ? discoveryItem.year : 0,
      imdbId: discoveryItem.imdbId || (discoveryItem.imdb_id as string | undefined),
      link_metadata: metadataItem as Record<string, unknown>
    });
    if ((data.ok ?? true) && data.status === "success") {
      discoveryItem.is_in_library = true;
      if (metadataItem.tvdbId) discoveryItem.tvdbId = metadataItem.tvdbId as number;
      if (metadataItem.tmdbId) discoveryItem.tmdbId = metadataItem.tmdbId as number;
      if (metadataItem.imdbId) discoveryItem.imdbId = String(metadataItem.imdbId);

      const modalOverlay = document.getElementById("modal-overlay");
      if (modalOverlay) modalOverlay.classList.add("hidden");

      if (typeof alert !== "undefined") {
        alert(data.message || "Linked to library successfully");
      }
      emit("render");
    } else {
      if (typeof alert !== "undefined") {
        alert(`Link failed: ${data.message || "Unknown error"}`);
      }
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    if (typeof alert !== "undefined") {
      alert(`Link error: ${msg}`);
    }
  }
}

export function goToOptionsStep(metadataItem: Record<string, unknown> | LookupResultItem): void {
  if (!state.selectedItemForAdd) return;

  state.selectedItemForAdd.raw_metadata = metadataItem;
  const type = state.selectedItemForAdd.type;

  let targetConfig: ServiceConfig | { folders: Array<{ path: string }>; profiles: Array<{ id: number; name: string }> };
  if (state.selectedItemForAdd.isDemo) {
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
    targetConfig = (type === "tv" ? state.appConfig?.sonarr : state.appConfig?.radarr) as ServiceConfig;
  }

  const modalTitle = document.getElementById("modal-title");
  if (modalTitle) {
    modalTitle.textContent = `${state.selectedItemForAdd.isDemo ? "[Demo Sandbox] " : ""}Configure Download: ${metadataItem.title}`;
  }

  const selectFolder = document.getElementById("select-folder") as HTMLSelectElement | null;
  const selectProfile = document.getElementById("select-profile") as HTMLSelectElement | null;

  if (selectFolder) {
    selectFolder.innerHTML = moduleBuildSelectOptionsHtml(targetConfig ? targetConfig.folders : [], "path", "path");
  }
  if (selectProfile) {
    selectProfile.innerHTML = moduleBuildSelectOptionsHtml(targetConfig ? targetConfig.profiles : [], "id", "name");
  }

  const prefix = type === "tv" ? "sonarr" : "radarr";
  const explicitFolder = state.appSettings
    ? (state.appSettings[`${prefix}_default_root_folder`] as string | null)
    : null;
  const explicitProfile = state.appSettings
    ? (state.appSettings[`${prefix}_default_quality_profile`] as string | null)
    : null;

  const selectedFolder = resolveHybridPreset(
    targetConfig ? targetConfig.folders : [],
    "path",
    explicitFolder,
    `xarrtools_mru_${prefix}_folder`,
    null,
    state.appSettings
  );
  if (selectedFolder && selectFolder) {
    selectFolder.value = selectedFolder;
  }

  const selectedProfile = resolveHybridPreset(
    targetConfig ? targetConfig.profiles : [],
    "id",
    explicitProfile,
    `xarrtools_mru_${prefix}_profile`,
    null,
    state.appSettings
  );
  if (selectedProfile && selectProfile) {
    selectProfile.value = selectedProfile;
  }

  const groupTrackCollection = document.getElementById("group-track-collection");
  const checkTrackCollection = document.getElementById("check-track-collection") as HTMLInputElement | null;
  const lblCollectionName = document.getElementById("lbl-collection-name");

  const collectionName = moduleGetCollectionName(metadataItem as LookupResultItem);
  if (type === "movie" && collectionName) {
    if (groupTrackCollection && checkTrackCollection && lblCollectionName) {
      lblCollectionName.textContent = collectionName;
      checkTrackCollection.checked = false;
      groupTrackCollection.classList.remove("hidden");
    }
  } else {
    if (groupTrackCollection && checkTrackCollection) {
      groupTrackCollection.classList.add("hidden");
      checkTrackCollection.checked = false;
    }
  }

  const modalStepSearch = document.getElementById("modal-step-search");
  const modalStepOptions = document.getElementById("modal-step-options");
  const btnModalBack = document.getElementById("btn-modal-back");
  const btnModalMarkLibrary = document.getElementById("btn-modal-mark-library");
  const btnModalAddOnly = document.getElementById("btn-modal-add-only");
  const btnModalConfirm = document.getElementById("btn-modal-confirm");

  if (modalStepSearch) modalStepSearch.classList.add("hidden");
  if (modalStepOptions) modalStepOptions.classList.remove("hidden");
  if (btnModalBack) btnModalBack.classList.remove("hidden");
  if (btnModalMarkLibrary) btnModalMarkLibrary.classList.add("hidden");
  if (btnModalAddOnly) btnModalAddOnly.classList.remove("hidden");
  if (btnModalConfirm) btnModalConfirm.classList.remove("hidden");
}

export function goBackToSearchStep(): void {
  if (!state.selectedItemForAdd) return;

  const modalTitle = document.getElementById("modal-title");
  const modalStepSearch = document.getElementById("modal-step-search");
  const modalStepOptions = document.getElementById("modal-step-options");
  const btnModalBack = document.getElementById("btn-modal-back");
  const btnModalMarkLibrary = document.getElementById("btn-modal-mark-library");
  const btnModalAddOnly = document.getElementById("btn-modal-add-only");
  const btnModalConfirm = document.getElementById("btn-modal-confirm");

  if (modalTitle) modalTitle.textContent = `Search Indexer for '${state.selectedItemForAdd.item.title}'`;
  if (modalStepSearch) modalStepSearch.classList.remove("hidden");
  if (modalStepOptions) modalStepOptions.classList.add("hidden");
  if (btnModalBack) btnModalBack.classList.add("hidden");
  if (btnModalMarkLibrary) btnModalMarkLibrary.classList.remove("hidden");
  if (btnModalAddOnly) btnModalAddOnly.classList.add("hidden");
  if (btnModalConfirm) btnModalConfirm.classList.add("hidden");
}

export function closeModal(): void {
  const modalOverlay = document.getElementById("modal-overlay");
  if (modalOverlay) modalOverlay.classList.add("hidden");
  state.selectedItemForAdd = null;
}

export async function addMediaItem(searchNow: boolean | null = null): Promise<void> {
  if (!state.selectedItemForAdd || !state.selectedItemForAdd.raw_metadata) return;

  const type = state.selectedItemForAdd.type;
  const rawMeta = state.selectedItemForAdd.raw_metadata as Record<string, unknown>;
  const discoveryItem = state.selectedItemForAdd.item;
  const searchCard = state.selectedItemForAdd.card || null;

  const selectFolder = document.getElementById("select-folder") as HTMLSelectElement | null;
  const selectProfile = document.getElementById("select-profile") as HTMLSelectElement | null;
  const checkMonitored = document.getElementById("check-monitored") as HTMLInputElement | null;
  const checkSearch = document.getElementById("check-search") as HTMLInputElement | null;
  const loadingOverlay = document.getElementById("loading-overlay");
  const loadingText = document.getElementById("loading-text");

  const chosenFolder = selectFolder ? selectFolder.value : "";
  const chosenProfile = selectProfile ? selectProfile.value : "";
  updateMRUCache(type, chosenFolder, chosenProfile);

  // Demo mode
  if (state.selectedItemForAdd.isDemo) {
    closeModal();
    if (loadingOverlay) loadingOverlay.classList.remove("hidden");
    if (loadingText) loadingText.textContent = `[Demo Mode] Adding '${rawMeta.title}'...`;

    try {
      const resData = await apiAddMedia({
        type: type,
        raw_metadata: rawMeta,
        folder: chosenFolder || "demo",
        profile_id: chosenProfile || 1,
        demo: true
      });
      if (loadingOverlay) loadingOverlay.classList.add("hidden");

      if ((resData.ok ?? true) && resData.status === "success") {
        addNotification(
          resData.message ||
            `[Demo Sandbox] Successfully added ${type === "tv" ? "TV Show" : "Movie"} '${rawMeta.title}' to sandbox library!`,
          "success"
        );
        if (discoveryItem) {
          discoveryItem.is_in_library = true;
          emit("render");
        }
        if (searchCard) {
          const addBtn = searchCard.querySelector(".btn-search-add") as HTMLButtonElement | null;
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
      if (loadingOverlay) loadingOverlay.classList.add("hidden");
      const msg = error instanceof Error ? error.message : String(error);
      addNotification(`Connection error: ${msg}`, "error");
    }
    return;
  }

  const checkTrackCollection = document.getElementById("check-track-collection") as HTMLInputElement | null;
  const payload = moduleBuildAddMediaPayload({
    type,
    rawMetadata: rawMeta,
    folder: selectFolder ? selectFolder.value : "",
    profileId: selectProfile ? selectProfile.value : "",
    monitored: checkMonitored ? checkMonitored.checked : true,
    searchNow: searchNow !== null ? searchNow : checkSearch ? checkSearch.checked : true,
    addCollection: Boolean(type === "movie" && checkTrackCollection && checkTrackCollection.checked)
  });

  closeModal();
  if (loadingOverlay) loadingOverlay.classList.remove("hidden");
  if (loadingText) loadingText.textContent = `Adding '${rawMeta.title}'...`;

  try {
    const resData = await apiAddMedia(payload as unknown as AddMediaPayload);
    if (loadingOverlay) loadingOverlay.classList.add("hidden");

    if ((resData.ok ?? true) && resData.status === "success") {
      addNotification(resData.message || `Successfully queued '${rawMeta.title}' for download!`, "success");
      discoveryItem.is_in_library = true;
      emit("render");

      if (searchCard) {
        const addBtn = searchCard.querySelector(".btn-search-add") as HTMLButtonElement | null;
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
    if (loadingOverlay) loadingOverlay.classList.add("hidden");
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Connection error: ${msg}`, "error");
  }
}

export function openDemoAddModal(
  type: string,
  item: MediaItem,
  _index: number | null,
  searchCard: HTMLElement | null = null,
  rawMetadata: unknown = null
): void {
  state.selectedItemForAdd = {
    type,
    item,
    isDemo: true,
    card: searchCard,
    raw_metadata: rawMetadata
  };

  state.isMarkInLibraryMode = false;
  const linkHelperBanner = document.getElementById("link-helper-banner");
  const btnModalMarkLibrary = document.getElementById("btn-modal-mark-library");
  const modalTitle = document.getElementById("modal-title");
  const modalStepSearch = document.getElementById("modal-step-search");
  const modalStepOptions = document.getElementById("modal-step-options");
  const btnModalBack = document.getElementById("btn-modal-back");
  const btnModalConfirm = document.getElementById("btn-modal-confirm");
  const lookupLoading = document.getElementById("lookup-loading");
  const lookupResultsList = document.getElementById("lookup-results-list");
  const modalOverlay = document.getElementById("modal-overlay");

  if (linkHelperBanner) linkHelperBanner.classList.add("hidden");
  if (btnModalMarkLibrary) {
    btnModalMarkLibrary.classList.remove("hidden");
    btnModalMarkLibrary.classList.remove("btn-modal-mark-library-active");
    btnModalMarkLibrary.textContent = "Mark In Library";
  }
  if (modalTitle) modalTitle.textContent = `[Demo Sandbox] Search Indexer for '${item.title}'`;
  if (modalStepSearch) modalStepSearch.classList.remove("hidden");
  if (modalStepOptions) modalStepOptions.classList.add("hidden");
  if (btnModalBack) btnModalBack.classList.add("hidden");
  if (btnModalConfirm) btnModalConfirm.classList.add("hidden");

  if (lookupLoading) lookupLoading.classList.remove("hidden");
  if (lookupResultsList) {
    lookupResultsList.classList.add("hidden");
    lookupResultsList.innerHTML = "";
  }

  if (modalOverlay) modalOverlay.classList.remove("hidden");

  setTimeout(() => {
    if (lookupLoading) lookupLoading.classList.add("hidden");
    if (lookupResultsList) {
      lookupResultsList.classList.remove("hidden");
      const fakeResults: LookupResultItem[] = [
        {
          title: item.title,
          year: typeof item.year === "number" ? item.year : 2026,
          tvdbId: type === "tv" ? 99901 : undefined,
          tmdbId: type === "movie" ? 88801 : undefined,
          imdbId: item.imdbId || "tt1234567",
          overview: `[Demo Mode] Simulated match for '${item.title}'. In sandbox mode, you can select this to preview the settings configurations.`,
          collection:
            type === "movie" ? { title: `${item.title} Collection`, name: `${item.title} Collection` } : undefined,
          id: undefined
        },
        {
          title: `${item.title} (Sandbox Spinoff)`,
          year: typeof item.year === "number" ? item.year - 1 : 2025,
          tvdbId: type === "tv" ? 99902 : undefined,
          tmdbId: type === "movie" ? 88802 : undefined,
          imdbId: "tt2345678",
          overview: "[Demo Mode] Alternative simulated release for testing multiselection flows.",
          id: undefined
        }
      ];

      renderLookupResults(fakeResults, type, item);
    }
  }, 600);
}

export function openAddModalFromLookup(
  res: LookupResultItem,
  type: string,
  card: HTMLElement | null = null
): void {
  if (!state.appConfig) {
    if (typeof alert !== "undefined") {
      alert("Server configuration is not loaded yet.");
    }
    return;
  }

  const targetConfig = type === "tv" ? state.appConfig.sonarr : state.appConfig.radarr;
  if (!targetConfig || !targetConfig.configured) {
    openDemoAddModal(type, { title: res.title, year: res.year }, null, card, res);
    return;
  }

  state.selectedItemForAdd = {
    type: type,
    item: { title: res.title, year: res.year },
    raw_metadata: res,
    card: card
  };

  goToOptionsStep(res);

  const modalOverlay = document.getElementById("modal-overlay");
  if (modalOverlay) modalOverlay.classList.remove("hidden");
}

// Event listeners
on("openAddModal", (type: string, index: number) => {
  openAddModal(type, index);
});

on("openAddModalFromLookup", (res: LookupResultItem, type: string, card?: HTMLElement | null) => {
  openAddModalFromLookup(res, type, card || null);
});
