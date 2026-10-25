/**
 * Pure HTML-building card helpers for xarrtools frontend media items.
 */

import { MediaItem, CardRenderOptions } from "./types.js";

/**
 * Escapes characters with special meaning in HTML entities.
 */
export function escapeHtml(v: unknown): string {
  return String(v).replace(
    /[&<>"']/g,
    c =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[c] as string)
  );
}

/**
 * Resolves a 2-letter country code to an English display name via Intl.DisplayNames.
 */
export function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

/**
 * Builds the HTML badge for country and original language.
 */
export function localeBadge(item: Partial<MediaItem>): string {
  const parts: string[] = [];
  if (item.country) parts.push(escapeHtml(item.country));
  if (item.language) parts.push(escapeHtml(item.language));
  if (!parts.length) return "";
  return `<span class="badge badge-network" title="Country / original language">${parts.join(" &middot; ")}</span>`;
}

/**
 * Builds the HTML snippet for IMDb, Metacritic, and Rotten Tomatoes score badges.
 */
export function buildRatingBadgesHtml(item: Partial<MediaItem>): string {
  let html = "";

  // IMDb Rating (out of 10)
  const imdbRating = item.rating_imdb || item.rating_imdb === 0 ? item.rating_imdb : "";
  if (imdbRating && parseFloat(String(imdbRating)) > 0) {
    const val = parseFloat(String(imdbRating)).toFixed(1);
    html += `<span class="badge-rating badge-rating-imdb" title="IMDb Rating"><span class="rating-label">⭐ IMDb</span> <span class="rating-value">${val}</span></span>`;
  }

  // Metacritic Score (out of 100)
  const mcScore = item.rating_metacritic || "";
  if (mcScore && parseInt(String(mcScore), 10) > 0) {
    const val = parseInt(String(mcScore), 10);
    let mcClass = "mc-mixed";
    if (val >= 61) mcClass = "mc-good";
    else if (val <= 39) mcClass = "mc-bad";
    html += `<span class="badge-rating badge-rating-mc ${mcClass}" title="Metacritic Score"><span class="rating-label">MC</span> <span class="rating-value">${val}</span></span>`;
  }

  // Rotten Tomatoes (percentage)
  const rtScore = item.rating_rt || "";
  if (rtScore && parseInt(String(rtScore), 10) > 0) {
    const val = parseInt(String(rtScore), 10);
    let rtClass = "rt-rotten";
    let rtIcon = "🍅";
    if (val >= 75) {
      rtClass = "rt-certified";
      rtIcon = "🍅";
    } else if (val >= 60) {
      rtClass = "rt-fresh";
      rtIcon = "🍅";
    } else {
      rtIcon = "🟢";
    }
    html += `<span class="badge-rating badge-rating-rt ${rtClass}" title="Rotten Tomatoes"><span class="rating-label">${rtIcon} RT</span> <span class="rating-value">${val}%</span></span>`;
  }

  if (!html) return "";
  return `<div class="rating-badges">${html}</div>`;
}

/**
 * Resolves external poster navigation link for an item.
 */
export function getPosterNavigationUrl(item: Partial<MediaItem>, type: string): string {
  const imdbId = item.imdbId || item.imdb_id;
  const tmdbId = item.tmdbId || item.tmdb_id;
  const tvdbId = item.tvdbId || item.tvdb_id;

  if (type === "movie") {
    if (imdbId) return `https://www.imdb.com/title/${imdbId}/`;
    if (tmdbId) return `https://www.themoviedb.org/movie/${tmdbId}`;
  } else if (type === "tv") {
    if (tvdbId) return `https://thetvdb.com/dereferrer/series/${tvdbId}`;
    if (imdbId) return `https://www.imdb.com/title/${imdbId}/`;
  }

  // Fallback to Metacritic/source URL
  if (item.href) return item.href;

  // Double fallback to Google search
  const searchString = encodeURIComponent(
    `${item.title || ""} ${item.year || ""} ${type === "tv" ? "tv show" : "movie"}`
  );
  return `https://www.google.com/search?q=${searchString}`;
}

/**
 * Pure string-building function returning the exact card innerHTML for a media item.
 */
export function buildMediaCardHtml(
  item: MediaItem,
  type: string = "movie",
  optionsOrIsAdded?: boolean | CardRenderOptions,
  legacyIndex?: number | string
): string {
  const isAdded =
    typeof optionsOrIsAdded === "boolean"
      ? optionsOrIsAdded
      : optionsOrIsAdded && typeof optionsOrIsAdded === "object" && optionsOrIsAdded.isAdded !== undefined
      ? Boolean(optionsOrIsAdded.isAdded)
      : Boolean(item.is_in_library);

  const index =
    optionsOrIsAdded && typeof optionsOrIsAdded === "object" && optionsOrIsAdded.index !== undefined
      ? optionsOrIsAdded.index
      : legacyIndex !== undefined
      ? legacyIndex
      : 0;

  const genres = (item.genres || []).map(g => `<span class="genre-pill">${g}</span>`).join("");
  const buttonText = isAdded ? "Added to Library" : type === "tv" ? "Add to Sonarr" : "Add to Radarr";
  const buttonClass = isAdded ? "btn btn-secondary btn-added" : "btn btn-primary";

  // Setup expandable plot
  const maxChars = 140;
  const needsTruncation = item.plot && item.plot.length > maxChars;
  let plotHtml = "";
  if (needsTruncation && item.plot) {
    const visibleText = item.plot.slice(0, maxChars);
    const hiddenText = item.plot.slice(maxChars);
    plotHtml = `
            <span class="plot-visible">${visibleText}</span><span class="plot-ellipsis">...</span><span class="plot-hidden hidden">${hiddenText}</span><button class="plot-more-btn">more</button>
        `;
  } else {
    plotHtml = item.plot || "";
  }

  const returningBadge =
    type === "tv" && item.is_returning
      ? '<span class="badge badge-network" style="background:rgba(138,43,226,0.1); color:#bc8cf2; border-color:rgba(138,43,226,0.2);">Returning</span>'
      : "";

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
  const searchString = encodeURIComponent(`${item.title} ${item.year} ${type === "tv" ? "tv show" : "movie"}`);
  chipsHtml += `<a href="https://www.google.com/search?q=${searchString}" target="_blank" class="chip chip-google">Google Search 🔍</a>`;

  // Setup poster image
  const navUrl = getPosterNavigationUrl(item, type);
  const titleEscapedForFallback = (item.title || "").replace(/'/g, "&#39;").replace(/"/g, "&quot;");
  let posterHtml = "";
  if (item.poster_url) {
    posterHtml = `
            <a href="${navUrl}" target="_blank" class="card-poster-link" title="Click to view external page">
                <div class="card-poster">
                    <img src="${item.poster_url}" alt="${item.title} poster" class="poster-img" onerror="this.onerror=null; this.parentElement.innerHTML='<div class=&quot;poster-fallback&quot;><span>${type === "tv" ? "📺" : "🎬"}</span><p style=&quot;font-size: 11px; padding: 0 8px; font-weight: 500; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;&quot;>${titleEscapedForFallback}</p></div>';">
                </div>
            </a>
        `;
  } else {
    posterHtml = `
            <a href="${navUrl}" target="_blank" class="card-poster-link" title="Click to view external page">
                <div class="card-poster">
                    <div class="poster-fallback">
                        <span>${type === "tv" ? "📺" : "🎬"}</span>
                        <p style="font-size: 11px; padding: 0 8px; font-weight: 500; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;">${titleEscapedForFallback}</p>
                    </div>
                </div>
            </a>
        `;
  }

  return `
        ${posterHtml}
        <div class="card-info-content">
            <div class="card-title-row">
                <h3>${item.title}</h3>
                <div class="card-year-refresh">
                    <span class="year">${item.year}</span>
                    <button class="btn-refresh-icon" title="Refresh Metadata">
                        <svg class="refresh-svg" viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round" style="display: block; pointer-events: none;">
                            <polyline points="23 4 23 10 17 10"></polyline>
                            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="card-badges">
                <span class="badge badge-network">${item.network}</span>
                ${returningBadge}
                ${localeBadge(item)}
                ${item.has_new_metadata ? '<span class="badge badge-new-metadata">New metadata</span>' : ""}
                ${isAdded ? '<span class="badge badge-in-library">In Library</span>' : ""}
                ${item.is_archived ? '<span class="badge badge-archived" style="background:rgba(255, 42, 133, 0.1); color:var(--accent-magenta); border:1px solid rgba(255, 42, 133, 0.2);">Archived</span>' : ""}
            </div>
            ${buildRatingBadgesHtml(item)}
            <div class="genres-list">${genres}</div>
            <div class="card-cast"><strong>Cast:</strong> <span>${item.cast}</span></div>
            ${type === "movie" && item.director ? `<div class="card-crew"><strong>Director:</strong> <span>${item.director}</span></div>` : ""}
            ${type === "movie" && item.producer ? `<div class="card-crew"><strong>Producer:</strong> <span>${item.producer}</span></div>` : ""}
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
                <button class="${buttonClass}" ${isAdded ? "disabled" : ""} onclick="openAddModal('${type}', ${index})">
                    ${buttonText}
                </button>
            </div>
        </div>
    `;
}
