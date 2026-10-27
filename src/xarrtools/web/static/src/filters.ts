import { MediaItem, FilterState, Discoveries, FilteredTarget } from "./types.js";

/**
 * Checks whether an item matches the selected country and language filters.
 * Pure function: takes item and either (countries, languages) or FilterState.
 */
export function matchLocale(
  item: Partial<MediaItem>,
  countriesOrState?: Set<string> | FilterState,
  languages?: Set<string>
): boolean {
  let countries: Set<string> | undefined;
  let langs: Set<string> | undefined;

  if (
    countriesOrState &&
    !(countriesOrState instanceof Set) &&
    ("countries" in countriesOrState || "languages" in countriesOrState)
  ) {
    countries = countriesOrState.countries;
    langs = countriesOrState.languages;
  } else {
    countries = countriesOrState as Set<string> | undefined;
    langs = languages;
  }

  if (countries && countries.size > 0 && !countries.has(item.country || "")) return false;
  if (langs && langs.size > 0 && !langs.has(item.language || "")) return false;
  return true;
}

/**
 * Checks whether an item matches a search term across title, network, cast, and genres.
 */
export function matchFilter(item: Partial<MediaItem>, term?: string | null): boolean {
  if (!term) return true;
  const normalized = term.toLowerCase().trim();
  if (!normalized) return true;

  const titleMatch = Boolean(item.title && item.title.toLowerCase().includes(normalized));
  const networkMatch = Boolean(item.network && item.network.toLowerCase().includes(normalized));
  const castMatch = Boolean(item.cast && item.cast.toLowerCase().includes(normalized));
  const genreMatch = Boolean(item.genres && item.genres.some(g => g.toLowerCase().includes(normalized)));

  return Boolean(titleMatch || networkMatch || castMatch || genreMatch);
}

/**
 * Predicate to determine if an item satisfies all sidebar filter controls.
 * Pure function: takes item, type ("tv" | "movie"), and filter state.
 */
export function itemPassesFilters(
  item: MediaItem,
  type: string,
  state: FilterState = {}
): boolean {
  const showReturning = Boolean(state.showReturning);
  const showLibrary = Boolean(state.showLibrary);
  const showArchived = Boolean(state.showArchived);
  const searchTerm = (state.searchTerm || "").toLowerCase().trim();
  const selectedGenres = state.genres;
  const selectedNetworks = state.networks;
  const selectedCountries = state.countries;
  const selectedLanguages = state.languages;

  if (type === "tv" && !showReturning && Boolean(item.is_returning)) return false;
  if (!showLibrary && Boolean(item.is_in_library)) return false;
  if (!showArchived && Boolean(item.is_archived)) return false;
  if (!matchLocale(item, selectedCountries, selectedLanguages)) return false;
  if (!matchFilter(item, searchTerm)) return false;
  if (selectedGenres && selectedGenres.size > 0) {
    if (!(item.genres && item.genres.some(g => selectedGenres.has(g)))) return false;
  }
  if (selectedNetworks && selectedNetworks.size > 0) {
    if (!item.network || !selectedNetworks.has(item.network)) return false;
  }
  return true;
}

/**
 * Returns currently visible, unarchived items according to active tab and filter state.
 */
export function getFilteredUnarchived(
  discoveries: Discoveries,
  activeTab: string = "all",
  state: FilterState = {}
): FilteredTarget[] {
  const out: FilteredTarget[] = [];
  if ((activeTab === "all" || activeTab === "tv") && Array.isArray(discoveries.tv)) {
    discoveries.tv.forEach(item => {
      if (!item.is_archived && itemPassesFilters(item, "tv", state)) {
        out.push({ type: "tv", item });
      }
    });
  }
  if ((activeTab === "all" || activeTab === "movies") && Array.isArray(discoveries.movies)) {
    discoveries.movies.forEach(item => {
      if (!item.is_archived && itemPassesFilters(item, "movie", state)) {
        out.push({ type: "movie", item });
      }
    });
  }
  return out;
}
