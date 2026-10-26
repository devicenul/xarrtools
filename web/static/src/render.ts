/**
 * Media list rendering, filtering, sorting, card creation, and card interactions.
 */
import { state } from "./state.js";
import type { MediaItem, FilterState, FilteredTarget } from "./types.js";
import {
  itemPassesFilters as moduleItemPassesFilters,
  getFilteredUnarchived as moduleGetFilteredUnarchived,
  matchLocale as moduleMatchLocale,
  matchFilter as moduleMatchFilter
} from "./filters.js";
import {
  archiveBatch as moduleArchiveBatch,
  archiveItem as moduleArchiveItem,
  refreshCacheItem as moduleRefreshCacheItem
} from "./api.js";
import {
  buildMediaCardHtml as moduleBuildMediaCardHtml,
  escapeHtml,
  countryName
} from "./cards.js";
import { addNotification } from "./notifications.js";
import { on, emit } from "./events.js";

export function getFilterState(): FilterState {
  if (typeof document === "undefined") {
    return {
      showReturning: false,
      showLibrary: false,
      showArchived: false,
      searchTerm: "",
      genres: state.selectedGenres,
      networks: state.selectedNetworks,
      countries: state.selectedCountries,
      languages: state.selectedLanguages
    };
  }
  const searchInput = document.getElementById("search-bar") as HTMLInputElement | null;
  const term = searchInput ? searchInput.value : "";
  const returningEl = document.getElementById("check-show-returning") as HTMLInputElement | null;
  const libraryEl = document.getElementById("check-show-library") as HTMLInputElement | null;
  const archivedEl = document.getElementById("check-show-archived") as HTMLInputElement | null;
  return {
    showReturning: returningEl ? returningEl.checked : false,
    showLibrary: libraryEl ? libraryEl.checked : false,
    showArchived: archivedEl ? archivedEl.checked : false,
    searchTerm: term ? term.toLowerCase().trim() : "",
    genres: state.selectedGenres,
    networks: state.selectedNetworks,
    countries: state.selectedCountries,
    languages: state.selectedLanguages
  };
}

export function itemPassesFilters(item: MediaItem, type: string): boolean {
  return moduleItemPassesFilters(item, type, getFilterState());
}

export function getFilteredUnarchived(): FilteredTarget[] {
  if (typeof document === "undefined") {
    return moduleGetFilteredUnarchived(state.currentDiscoveries, state.activeTab || "all", getFilterState());
  }
  const activeTabEl = document.querySelector(".tab-btn.active");
  const activeTab = activeTabEl ? activeTabEl.getAttribute("data-tab") || "all" : state.activeTab || "all";
  return moduleGetFilteredUnarchived(state.currentDiscoveries, activeTab, getFilterState());
}

export async function archiveAllFiltered(): Promise<void> {
  const targets = getFilteredUnarchived();
  if (targets.length === 0) {
    addNotification("No un-archived items match the current filters.", "info");
    return;
  }
  if (typeof window !== "undefined" && window.confirm) {
    if (!window.confirm(`Archive ${targets.length} filtered item${targets.length === 1 ? "" : "s"}?`)) {
      return;
    }
  }
  try {
    const batchItems = targets.map(t => ({
      type: t.type,
      title: t.item.title,
      year: t.item.year,
      raw_item: t.item
    }));
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
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Archive error: ${msg}`, "error");
  }
}

export async function toggleArchive(type: string, item: MediaItem): Promise<void> {
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
      addNotification(`Successfully ${isArchiving ? "archived" : "unarchived"} '${item.title}'.`, "success");
      renderMediaLists();
    } else {
      addNotification(`Failed to archive '${item.title}': ${resData.message || "Unknown error."}`, "error");
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Archive error: ${msg}`, "error");
  }
}

export async function refreshMetadata(
  type: string,
  item: MediaItem,
  refreshBtn: HTMLButtonElement,
  _card?: HTMLElement | null
): Promise<void> {
  if (refreshBtn.classList.contains("loading")) return;

  refreshBtn.classList.add("loading");
  refreshBtn.disabled = true;

  try {
    const data = await moduleRefreshCacheItem({
      type: type,
      title: item.title,
      year: item.year != null ? item.year : 0,
      imdbId: item.imdbId || item.imdb_id
    });

    if ((data.ok ?? true) && data.status === "success" && data.item) {
      const list = type === "tv" ? state.currentDiscoveries.tv : state.currentDiscoveries.movies;
      const index = list.findIndex(i => i.title === item.title && i.year === item.year);
      if (index !== -1) {
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
    const msg = error instanceof Error ? error.message : String(error);
    addNotification(`Refresh error: ${msg}`, "error");
  } finally {
    refreshBtn.classList.remove("loading");
    refreshBtn.disabled = false;
  }
}

export function createMediaCard(item: MediaItem, type: string, index: number): HTMLElement {
  const card = document.createElement("div");
  card.className = "media-card";

  const isAdded = Boolean(item.is_in_library);
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
        if (hiddenSpan) hiddenSpan.classList.add("hidden");
        if (ellipsis) ellipsis.classList.remove("hidden");
        moreBtn.textContent = "more";
      } else {
        plotDiv.classList.add("expanded");
        if (hiddenSpan) hiddenSpan.classList.remove("hidden");
        if (ellipsis) ellipsis.classList.add("hidden");
        moreBtn.textContent = "less";
      }
    });
  }

  // Bind click event on Details Toggle
  const toggleBtn = card.querySelector(".btn-details-toggle") as HTMLElement | null;
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
  const refreshBtn = card.querySelector(".btn-refresh-icon") as HTMLButtonElement | null;
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

  // Bind click event on Add button if present
  const addBtn = card.querySelector(".btn-add");
  if (addBtn) {
    addBtn.addEventListener("click", (e) => {
      e.preventDefault();
      emit("openAddModal", type, index);
    });
  }

  return card;
}

export function renderMediaLists(): void {
  if (typeof document === "undefined") return;

  const gridTv = document.getElementById("grid-tv");
  const gridMovies = document.getElementById("grid-movies");
  if (!gridTv || !gridMovies) return;

  gridTv.innerHTML = "";
  gridMovies.innerHTML = "";

  const selectSort = document.getElementById("select-sort") as HTMLSelectElement | null;
  const sortVal = selectSort ? selectSort.value : "date-asc";

  const sortItems = (a: MediaItem, b: MediaItem): number => {
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

  // 1. Render TV shows
  const tvMatches = state.currentDiscoveries.tv.filter(item => itemPassesFilters(item, "tv"));
  tvMatches.sort(sortItems);

  tvMatches.forEach(item => {
    const origIndex = state.currentDiscoveries.tv.indexOf(item);
    const card = createMediaCard(item, "tv", origIndex);
    gridTv.appendChild(card);
  });

  if (tvMatches.length === 0) {
    gridTv.innerHTML = `<div class="empty-state">No matching TV shows found.</div>`;
  }

  // 2. Render Movies
  const movieMatches = state.currentDiscoveries.movies.filter(item => itemPassesFilters(item, "movie"));
  movieMatches.sort(sortItems);

  movieMatches.forEach(item => {
    const origIndex = state.currentDiscoveries.movies.indexOf(item);
    const card = createMediaCard(item, "movie", origIndex);
    gridMovies.appendChild(card);
  });

  if (movieMatches.length === 0) {
    gridMovies.innerHTML = `<div class="empty-state">No matching movies found.</div>`;
  }

  applyTabFilter();
}

export function applyTabFilter(): void {
  if (typeof document === "undefined") return;

  const activeTabEl = document.querySelector(".tab-btn.active");
  const activeTab = activeTabEl ? activeTabEl.getAttribute("data-tab") || "all" : state.activeTab || "all";
  state.activeTab = activeTab;

  const noResultsContainer = document.getElementById("no-results-container");
  const sectionSearch = document.getElementById("section-search");
  const sectionTv = document.getElementById("section-tv");
  const sectionMovies = document.getElementById("section-movies");
  const contentArea = document.getElementById("content-area");
  const welcomeState = document.getElementById("welcome-state");

  // Handle Global Search tab
  if (activeTab === "search") {
    if (sectionTv) sectionTv.classList.add("hidden");
    if (sectionMovies) sectionMovies.classList.add("hidden");
    if (noResultsContainer) noResultsContainer.classList.add("hidden");
    if (sectionSearch) sectionSearch.classList.remove("hidden");
    if (contentArea) contentArea.classList.remove("hidden");
    if (welcomeState) welcomeState.classList.add("hidden");
    return;
  }

  // Hide search section for non-search tabs
  if (sectionSearch) sectionSearch.classList.add("hidden");

  const searchBar = document.getElementById("search-bar") as HTMLInputElement | null;
  const searchTerm = searchBar ? searchBar.value.toLowerCase().trim() : "";
  const returningEl = document.getElementById("check-show-returning") as HTMLInputElement | null;
  const libraryEl = document.getElementById("check-show-library") as HTMLInputElement | null;
  const archivedEl = document.getElementById("check-show-archived") as HTMLInputElement | null;

  const showReturning = returningEl ? returningEl.checked : false;
  const showLibrary = libraryEl ? libraryEl.checked : false;
  const showArchived = archivedEl ? archivedEl.checked : false;

  const tvMatchesCount = state.currentDiscoveries.tv.filter(item => {
    if (!showReturning && item.is_returning) return false;
    if (!showLibrary && item.is_in_library) return false;
    if (!showArchived && item.is_archived) return false;
    if (!moduleMatchLocale(item, state.selectedCountries, state.selectedLanguages)) return false;
    return moduleMatchFilter(item, searchTerm);
  }).length;

  const movieMatchesCount = state.currentDiscoveries.movies.filter(item => {
    if (!showLibrary && item.is_in_library) return false;
    if (!showArchived && item.is_archived) return false;
    if (!moduleMatchLocale(item, state.selectedCountries, state.selectedLanguages)) return false;
    return moduleMatchFilter(item, searchTerm);
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

  if (sectionTv) {
    if (showTv) sectionTv.classList.remove("hidden");
    else sectionTv.classList.add("hidden");
  }

  if (sectionMovies) {
    if (showMovies) sectionMovies.classList.remove("hidden");
    else sectionMovies.classList.add("hidden");
  }

  if (!showTv && !showMovies) {
    if (noResultsContainer) noResultsContainer.classList.remove("hidden");
  } else {
    if (noResultsContainer) noResultsContainer.classList.add("hidden");
  }
}

export function buildLocaleMultiselect(
  key: string,
  values: string[],
  selected: Set<string>,
  label: string,
  text: (val: string) => string
): void {
  if (typeof document === "undefined") return;
  const container = document.querySelector("#options-" + key + "-filter");
  const btn = document.querySelector("#btn-" + key + "-filter");
  if (!container || !btn) return;

  selected.forEach(v => {
    if (!values.includes(v)) selected.delete(v);
  });

  const updateBtn = (): void => {
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
    const input = option.querySelector("input");
    if (input) {
      input.addEventListener("change", (e: Event) => {
        const target = e.target as HTMLInputElement;
        if (target.checked) selected.add(value);
        else selected.delete(value);
        updateBtn();
        renderMediaLists();
      });
    }
    container.appendChild(option);
  });
  updateBtn();
}

export function populateLocaleFilters(): void {
  const countries = new Set<string>();
  const languages = new Set<string>();
  [...state.currentDiscoveries.tv, ...state.currentDiscoveries.movies].forEach(item => {
    if (item.country) countries.add(String(item.country));
    if (item.language) languages.add(String(item.language));
  });
  buildLocaleMultiselect(
    "country",
    Array.from(countries).sort((a, b) => countryName(a).localeCompare(countryName(b))),
    state.selectedCountries,
    "Country",
    countryName
  );
  buildLocaleMultiselect(
    "language",
    Array.from(languages).sort(),
    state.selectedLanguages,
    "Language",
    v => v
  );
}

export function updateGenreFilterBtnText(): void {
  if (typeof document === "undefined") return;
  const btn = document.getElementById("btn-genres-filter");
  if (!btn) return;
  if (state.selectedGenres.size === 0) {
    btn.textContent = "Genres (All)";
    btn.classList.remove("active");
  } else {
    btn.textContent = `Genres (${state.selectedGenres.size})`;
    btn.classList.add("active");
  }
}

export function updateNetworkFilterBtnText(): void {
  if (typeof document === "undefined") return;
  const btn = document.getElementById("btn-networks-filter");
  if (!btn) return;
  if (state.selectedNetworks.size === 0) {
    btn.textContent = "Studios/Nets (All)";
    btn.classList.remove("active");
  } else {
    btn.textContent = `Studios/Nets (${state.selectedNetworks.size})`;
    btn.classList.add("active");
  }
}

export function populateFilterOptions(): void {
  populateLocaleFilters();
  const allGenres = new Set<string>();
  const allNetworks = new Set<string>();

  state.currentDiscoveries.tv.forEach(item => {
    if (item.genres) item.genres.forEach(g => allGenres.add(g));
    if (item.network) allNetworks.add(item.network);
  });

  state.currentDiscoveries.movies.forEach(item => {
    if (item.genres) item.genres.forEach(g => allGenres.add(g));
    if (item.network) allNetworks.add(item.network);
  });

  const sortedGenres = Array.from(allGenres).sort();
  const sortedNetworks = Array.from(allNetworks).sort();

  // Cleanup stale filter selections
  state.selectedGenres.forEach(g => {
    if (!allGenres.has(g)) state.selectedGenres.delete(g);
  });
  state.selectedNetworks.forEach(n => {
    if (!allNetworks.has(n)) state.selectedNetworks.delete(n);
  });

  if (typeof document !== "undefined") {
    // Genres options
    const genresContainer = document.getElementById("options-genres-filter");
    if (genresContainer) {
      genresContainer.innerHTML = "";
      sortedGenres.forEach(genre => {
        const option = document.createElement("label");
        option.className = "multiselect-option";
        const isChecked = state.selectedGenres.has(genre);
        option.innerHTML = `
          <input type="checkbox" value="${escapeHtml(genre)}" ${isChecked ? "checked" : ""}>
          <span>${escapeHtml(genre)}</span>
        `;
        const cb = option.querySelector("input");
        if (cb) {
          cb.addEventListener("change", (e: Event) => {
            const target = e.target as HTMLInputElement;
            if (target.checked) {
              state.selectedGenres.add(genre);
            } else {
              state.selectedGenres.delete(genre);
            }
            updateGenreFilterBtnText();
            renderMediaLists();
          });
        }
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
        const isChecked = state.selectedNetworks.has(network);
        option.innerHTML = `
          <input type="checkbox" value="${escapeHtml(network)}" ${isChecked ? "checked" : ""}>
          <span>${escapeHtml(network)}</span>
        `;
        const cb = option.querySelector("input");
        if (cb) {
          cb.addEventListener("change", (e: Event) => {
            const target = e.target as HTMLInputElement;
            if (target.checked) {
              state.selectedNetworks.add(network);
            } else {
              state.selectedNetworks.delete(network);
            }
            updateNetworkFilterBtnText();
            renderMediaLists();
          });
        }
        networksContainer.appendChild(option);
      });
    }
  }

  updateGenreFilterBtnText();
  updateNetworkFilterBtnText();
}

export function invertMultiselect(key: string, set: Set<string>, update: (() => void) | null): void {
  if (typeof document === "undefined") return;
  document.querySelectorAll("#options-" + key + "-filter input").forEach(node => {
    const cb = node as HTMLInputElement;
    cb.checked = !cb.checked;
    if (cb.checked) set.add(cb.value);
    else set.delete(cb.value);
  });
  if (update) {
    update();
  } else {
    const btn = document.getElementById("btn-" + key + "-filter");
    if (btn) {
      const label = key === "country" ? "Country" : "Language";
      btn.textContent = set.size === 0 ? `${label} (All)` : `${label} (${set.size})`;
      btn.classList.toggle("active", set.size > 0);
    }
  }
  renderMediaLists();
}

// Subscribe to events
on("render", () => {
  renderMediaLists();
});

on("applyTabFilter", () => {
  applyTabFilter();
});
