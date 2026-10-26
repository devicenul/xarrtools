/**
 * Pure HTML and data builders for Add/Indexer modal, Select Option dropdowns, and Global Search cards.
 *
 * All dynamic values are strictly sanitized/escaped using escapeHtml and safeUrl from cards.ts.
 */

import {
  escapeHtml,
  safeUrl,
  buildRatingBadgesHtml,
  getPosterNavigationUrl
} from "./cards.js";
import { MediaItem, LookupResultItem } from "./types.js";

/**
 * Builds <option> markup list for <select> elements, with optional default placeholder.
 */
export function buildSelectOptionsHtml(
  items: Array<Record<string, unknown>> | null | undefined,
  valueProp: string,
  textProp: string,
  currentValue?: unknown,
  defaultOptionLabel?: string | null
): string {
  let html = "";
  if (defaultOptionLabel !== undefined && defaultOptionLabel !== null) {
    html += `<option value="">${escapeHtml(defaultOptionLabel)}</option>`;
  }

  if (items && Array.isArray(items)) {
    const currentStr =
      currentValue !== undefined && currentValue !== null
        ? String(currentValue).trim()
        : null;
    items.forEach(item => {
      if (!item) return;
      const val = item[valueProp];
      const text = item[textProp];
      const isSelected =
        currentStr !== null && currentStr !== "" && String(val).trim() === currentStr;
      html += `<option value="${escapeHtml(val)}"${isSelected ? " selected" : ""}>${escapeHtml(text)}</option>`;
    });
  }

  return html;
}

/**
 * Determines whether a lookup indexer candidate is an auto "best match" for a discovery item.
 */
export function isIndexerBestMatch(
  discoveryItem: Partial<MediaItem>,
  res: LookupResultItem | Record<string, unknown>,
  type: string
): boolean {
  let isBestMatch = false;
  const resId = type === "tv" ? res.tvdbId : res.tmdbId;
  const discoveryId =
    type === "tv"
      ? (discoveryItem.tvdbId ?? discoveryItem.tvdb_id)
      : (discoveryItem.tmdbId ?? discoveryItem.tmdb_id);

  const resImdbId = res.imdbId;
  const discoveryImdbId = discoveryItem.imdbId ?? discoveryItem.imdb_id;

  const stripYearSuffix = (t?: unknown) =>
    (t ? String(t) : "").replace(/\s*[\(\[]\d{4}[\)\]]?$/, "").trim().toLowerCase();

  if (discoveryId && resId && String(discoveryId) === String(resId)) {
    isBestMatch = true;
  } else if (
    discoveryImdbId &&
    resImdbId &&
    String(discoveryImdbId).toLowerCase() === String(resImdbId).toLowerCase()
  ) {
    isBestMatch = true;
  } else if (
    (String(res.title || "").toLowerCase() === String(discoveryItem.title || "").toLowerCase() ||
      stripYearSuffix(res.title) === stripYearSuffix(discoveryItem.title)) &&
    Math.abs(Number(res.year || 0) - Number(discoveryItem.year || 0)) <= 1
  ) {
    isBestMatch = true;
  }

  return isBestMatch;
}

/**
 * Extracts collection title/name from a metadata object if present.
 */
export function getCollectionName(item: Record<string, unknown> | null | undefined): string | null {
  if (!item) return null;
  const collection = item.collection as Record<string, unknown> | undefined;
  if (!collection) return null;
  const name = collection.title || collection.name;
  return name ? String(name) : null;
}

/**
 * Builds collection badge HTML pill with safe escaping.
 */
export function buildCollectionBadgeHtml(collectionName?: string | null): string {
  if (!collectionName) return "";
  return `<span class="badge" style="background: rgba(0, 210, 255, 0.08); color: var(--accent-blue); border: 1px solid rgba(0, 210, 255, 0.2); font-size: 10px; padding: 2px 6px; border-radius: 4px; display: inline-flex; align-items: center; text-transform: none; margin: 0;">📦 ${escapeHtml(collectionName)}</span>`;
}

/**
 * Builds the inner HTML for an indexer search candidate item row.
 */
export function buildLookupItemHtml(
  res: LookupResultItem | Record<string, unknown>,
  type: string,
  isBestMatch = false,
  inLibrary = false
): string {
  const statusBadge = inLibrary
    ? `<span class="lookup-item-status status-exists">In Library</span>`
    : `<span class="lookup-item-status status-not-exists">Not Added</span>`;

  const idLabel =
    type === "tv"
      ? `TVDB ID: ${res.tvdbId || "N/A"}`
      : `TMDB ID: ${res.tmdbId || "N/A"}`;

  const collectionName =
    type === "movie" ? getCollectionName(res as Record<string, unknown>) : null;
  const collectionBadge =
    type === "movie" && collectionName
      ? `<span class="badge" style="background: rgba(0, 210, 255, 0.08); color: var(--accent-blue); border: 1px solid rgba(0, 210, 255, 0.2); font-size: 10px; padding: 2px 6px; border-radius: 4px; display: inline-flex; align-items: center; text-transform: none; margin: 0;">📦 ${escapeHtml(collectionName)}</span>`
      : "";

  return `
            <div class="lookup-item-details">
                <div class="lookup-item-title">
                    ${escapeHtml(res.title)}
                    ${isBestMatch ? '<span class="auto-match-tag">Auto Match</span>' : ""}
                </div>
                <div class="lookup-item-meta" style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 4px;">
                    <span class="year-badge">${escapeHtml(res.year || "N/A")}</span>
                    <span class="id-badge">${escapeHtml(idLabel)}</span>
                    ${collectionBadge}
                </div>
            </div>
            ${statusBadge}
        `;
}

/**
 * Builds external source links (chips) for IMDb, TMDB, TVDB, and Google Search.
 */
export function buildExternalChipsHtml(
  res: LookupResultItem | Record<string, unknown>,
  type: string
): string {
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
  const title = String(res.title || "Unknown Title");
  const year = res.year || "N/A";
  const searchString = encodeURIComponent(`${title} ${year} ${type === "tv" ? "tv show" : "movie"}`);
  chipsHtml += `<a href="https://www.google.com/search?q=${searchString}" target="_blank" class="chip chip-google">Google Search 🔍</a>`;
  return chipsHtml;
}

/**
 * Extracts remote poster URL from a lookup result.
 */
export function getLookupPosterUrl(res: Record<string, unknown>): string | null {
  if (res.remotePoster && typeof res.remotePoster === "string") {
    return res.remotePoster;
  }

  const images = res.images as Array<Record<string, unknown>> | undefined;
  if (images && Array.isArray(images) && images.length > 0) {
    const poster = images.find(img => img && img.coverType === "poster");
    if (poster && typeof poster.remoteUrl === "string") {
      return poster.remoteUrl;
    }
  }

  return null;
}

/**
 * Normalizes ratings object from lookup item into rating badge helper input format.
 */
export function buildRatingItemFromLookup(
  res: Record<string, unknown>,
  type: string
): Record<string, string> {
  const ratingItem: Record<string, string> = {
    rating_imdb: "",
    rating_metacritic: "",
    rating_rt: ""
  };
  const ratings = res.ratings as Record<string, any> | undefined;
  if (type === "movie" && ratings) {
    if (ratings.imdb && ratings.imdb.value) {
      ratingItem.rating_imdb = String(ratings.imdb.value);
    }
    if (ratings.metacritic && ratings.metacritic.value) {
      ratingItem.rating_metacritic = String(Math.round(ratings.metacritic.value));
    }
    if (ratings.rottenTomatoes && ratings.rottenTomatoes.value) {
      ratingItem.rating_rt = String(Math.round(ratings.rottenTomatoes.value));
    }
  } else if (type === "tv" && ratings) {
    if (ratings.value) {
      ratingItem.rating_imdb = String(ratings.value);
    }
  }
  return ratingItem;
}

/**
 * Builds expandable plot markup for search card.
 */
export function buildSearchCardPlotHtml(overview?: string | null): string {
  const plot = overview || "No overview available.";
  const maxChars = 140;
  if (plot.length > maxChars) {
    const visibleText = plot.slice(0, maxChars);
    const hiddenText = plot.slice(maxChars);
    return `
            <span class="plot-visible">${escapeHtml(visibleText)}</span><span class="plot-ellipsis">...</span><span class="plot-hidden hidden">${escapeHtml(hiddenText)}</span><button class="plot-more-btn">more</button>
        `;
  }
  return escapeHtml(plot);
}

/**
 * Builds poster or fallback placeholder markup for search card.
 */
export function buildSearchCardPosterHtml(
  _res: Record<string, unknown>,
  type: string,
  posterUrl: string | null,
  navUrl: string,
  title: string
): string {
  if (posterUrl) {
    return `
            <a href="${escapeHtml(navUrl)}" target="_blank" class="card-poster-link" title="Click to view external page">
                <div class="card-poster">
                    <img src="${escapeHtml(safeUrl(posterUrl))}" alt="${escapeHtml(title)} poster" class="poster-img" data-fallback-title="${escapeHtml(title)}" data-fallback-icon="${type === "tv" ? "tv" : "movie"}" onerror="xarrtoolsPosterFallback(this)">
                </div>
            </a>
        `;
  }
  return `
            <a href="${escapeHtml(navUrl)}" target="_blank" class="card-poster-link" title="Click to view external page">
                <div class="card-poster">
                    <div class="poster-fallback">
                        <span>${type === "tv" ? "📺" : "🎬"}</span>
                        <p style="font-size: 11px; padding: 0 8px; font-weight: 500; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;">${escapeHtml(title)}</p>
                    </div>
                </div>
            </a>
        `;
}

/**
 * Builds complete innerHTML for a global search media card.
 */
export function buildSearchCardHtml(
  res: Record<string, unknown>,
  type: string
): string {
  const inLibrary = res.id != null && res.id !== 0;
  const posterUrl = getLookupPosterUrl(res);
  const overview =
    (typeof res.overview === "string" ? res.overview : null) ||
    "No overview available.";
  const year = res.year || "N/A";
  const title = String(res.title || "Unknown Title");
  const network =
    type === "tv"
      ? String(res.network || "Unknown Network")
      : String(res.studio || "Unknown Studio");
  const runtime = res.runtime ? `${res.runtime} min` : "";
  const genres = Array.isArray(res.genres)
    ? res.genres.map((g: unknown) => `<span class="genre-pill">${escapeHtml(g)}</span>`).join("")
    : "";
  const certification = res.certification
    ? `<span class="badge badge-network">${escapeHtml(res.certification)}</span>`
    : "";

  const ratingItem = buildRatingItemFromLookup(res, type);
  const plotHtml = buildSearchCardPlotHtml(overview);
  const navUrl = safeUrl(getPosterNavigationUrl(res as Partial<MediaItem>, type));
  const posterHtml = buildSearchCardPosterHtml(res, type, posterUrl, navUrl, title);
  const chipsHtml = buildExternalChipsHtml(res, type);

  const buttonText = inLibrary
    ? "In Library"
    : type === "tv"
    ? "Add to Sonarr"
    : "Add to Radarr";
  const buttonClass = inLibrary
    ? "btn btn-secondary btn-added"
    : "btn btn-primary";

  return `
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
                ${runtime ? `<span class="badge badge-network">${escapeHtml(runtime)}</span>` : ""}
                ${inLibrary ? '<span class="badge badge-in-library">In Library</span>' : ""}
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
                <button class="${buttonClass} btn-search-add" ${inLibrary ? "disabled" : ""}>
                    ${buttonText}
                </button>
            </div>
        </div>
    `;
}

/**
 * Builds HTML for global search loading spinner state.
 */
export function buildSearchLoadingHtml(query: string, type: string): string {
  return `
        <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
            <div class="spinner-small" style="margin: 0 auto 12px;"></div>
            <p>Searching ${type === "tv" ? "Sonarr" : "Radarr"} for "${escapeHtml(query)}"...</p>
        </div>
    `;
}

/**
 * Builds HTML for global search empty result state.
 */
export function buildSearchEmptyStateHtml(query: string): string {
  return `
        <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
            <div class="empty-icon" style="font-size: 40px; margin-bottom: 12px;">🤷</div>
            <p>No results found for "${escapeHtml(query)}". Try a different title or media type.</p>
        </div>
    `;
}

/**
 * Builds HTML for global search error state.
 */
export function buildSearchErrorHtml(errorMessage: string): string {
  return `
        <div class="empty-state" style="height: 30vh; margin: 0 auto; grid-column: 1 / -1;">
            <div class="empty-icon" style="font-size: 40px; margin-bottom: 12px;">⚠️</div>
            <p>Search error: ${escapeHtml(errorMessage)}</p>
        </div>
    `;
}

/**
 * Builds HTML status message for indexer lookup container.
 */
export function buildLookupStatusHtml(message: string): string {
  return `<div class="lookup-status">${escapeHtml(message)}</div>`;
}

/**
 * Formats notification string for search results summary.
 */
export function formatSearchResultNotification(
  count: number,
  query: string,
  isDemo = false
): string {
  if (isDemo) {
    return `[Demo Mode] Found ${count} simulated result(s) for "${query}".`;
  }
  if (count > 0) {
    return `Found ${count} result(s) for "${query}".`;
  }
  return `No results found for "${query}".`;
}

/**
 * Returns mock demo search results for sandbox exploration.
 */
export function getDemoSearchResults(query: string, type: string): Array<Record<string, unknown>> {
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
  }
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

export interface AddMediaPayloadOptions {
  type: string;
  rawMetadata: Record<string, unknown>;
  folder: string;
  profileId: string | number;
  monitored: boolean;
  searchNow: boolean;
  addCollection: boolean;
  demo?: boolean;
}

/**
 * Constructs the payload object for adding media to Radarr/Sonarr (POST /api/add).
 */
export function buildAddMediaPayload(options: AddMediaPayloadOptions): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    type: options.type,
    raw_metadata: options.rawMetadata,
    folder: options.folder,
    profile_id: options.profileId,
    monitored: options.monitored,
    search_now: options.searchNow,
    add_collection: options.addCollection
  };
  if (options.demo) {
    payload.demo = true;
  }
  return payload;
}

