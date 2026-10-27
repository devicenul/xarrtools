/**
 * Global media search controller and search result card construction.
 */
import { state } from "./state.js";
import type { LookupResultItem } from "./types.js";
import { lookupMedia as apiLookupMedia } from "./api.js";
import {
  buildSearchLoadingHtml as moduleBuildSearchLoadingHtml,
  buildSearchEmptyStateHtml as moduleBuildSearchEmptyStateHtml,
  buildSearchErrorHtml as moduleBuildSearchErrorHtml,
  buildSearchCardHtml as moduleBuildSearchCardHtml,
  formatSearchResultNotification as moduleFormatSearchResultNotification,
  getDemoSearchResults as moduleGetDemoSearchResults
} from "./modals.js";
import { addNotification } from "./notifications.js";
import { emit } from "./events.js";

export async function runGlobalSearch(): Promise<void> {
  if (typeof document === "undefined") return;

  const input = document.getElementById("global-search-input") as HTMLInputElement | null;
  const typeSelect = document.getElementById("global-search-type") as HTMLSelectElement | null;
  const resultsGrid = document.getElementById("grid-search-results");

  if (!input || !resultsGrid) return;
  const query = input.value.trim();
  if (!query) return;

  const type = typeSelect ? typeSelect.value : "movie";

  // Show loading state
  resultsGrid.innerHTML = moduleBuildSearchLoadingHtml(query, type);

  // Intercept if unconfigured to return demo search results
  const isConfigured =
    type === "tv"
      ? Boolean(state.appConfig && state.appConfig.sonarr && state.appConfig.sonarr.configured)
      : Boolean(state.appConfig && state.appConfig.radarr && state.appConfig.radarr.configured);

  if (!isConfigured) {
    setTimeout(() => {
      const demoResults = moduleGetDemoSearchResults(query, type);
      resultsGrid.innerHTML = "";
      demoResults.forEach(res => {
        const card = createSearchCard(res as unknown as LookupResultItem, type);
        resultsGrid.appendChild(card);
      });
      addNotification(moduleFormatSearchResultNotification(demoResults.length, query, true), "info");
    }, 600);
    return;
  }

  try {
    const data = await apiLookupMedia(type, query);
    if ((data.ok ?? true) && data.status === "success" && data.results && data.results.length > 0) {
      resultsGrid.innerHTML = "";
      data.results.forEach(res => {
        const card = createSearchCard(res, type);
        resultsGrid.appendChild(card);
      });
      addNotification(moduleFormatSearchResultNotification(data.results.length, query, false), "info");
    } else {
      resultsGrid.innerHTML = moduleBuildSearchEmptyStateHtml(query);
      addNotification(moduleFormatSearchResultNotification(0, query, false), "info");
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    resultsGrid.innerHTML = moduleBuildSearchErrorHtml(msg);
    addNotification(`Global search error: ${msg}`, "error");
  }
}

export function createSearchCard(res: LookupResultItem, type: string): HTMLElement {
  const card = document.createElement("div");
  card.className = "media-card";
  card.innerHTML = moduleBuildSearchCardHtml(res, type);

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

  // Details toggle handler
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

  // Add button handler
  const inLibrary = res.id != null && res.id !== 0;
  const addBtn = card.querySelector(".btn-search-add");
  if (addBtn && !inLibrary) {
    addBtn.addEventListener("click", () => {
      emit("openAddModalFromLookup", res, type, card);
    });
  }

  return card;
}
