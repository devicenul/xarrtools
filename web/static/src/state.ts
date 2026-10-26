/**
 * Shared application state and state mutation helpers for xarrtools frontend.
 */
import type {
  ConfigResponse,
  SettingsResponse,
  MediaItem,
  SelectedItemForAdd,
  FeedItem
} from "./types.js";

export interface AppState {
  appConfig: ConfigResponse | null;
  appSettings: SettingsResponse | null;
  currentDiscoveries: { tv: MediaItem[]; movies: MediaItem[] };
  selectedItemForAdd: SelectedItemForAdd | null;
  selectedGenres: Set<string>;
  selectedNetworks: Set<string>;
  selectedCountries: Set<string>;
  selectedLanguages: Set<string>;
  isMarkInLibraryMode: boolean;
  activeTab: string;
  progressInterval: ReturnType<typeof setInterval> | number | null;
  customFeedsList: FeedItem[];
}

export function createInitialState(): AppState {
  return {
    appConfig: null,
    appSettings: null,
    currentDiscoveries: { tv: [], movies: [] },
    selectedItemForAdd: null,
    selectedGenres: new Set<string>(),
    selectedNetworks: new Set<string>(),
    selectedCountries: new Set<string>(),
    selectedLanguages: new Set<string>(),
    isMarkInLibraryMode: false,
    activeTab: "all",
    progressInterval: null,
    customFeedsList: []
  };
}

export const state: AppState = createInitialState();

export function resetFilters(): void {
  state.selectedGenres.clear();
  state.selectedNetworks.clear();
  state.selectedCountries.clear();
  state.selectedLanguages.clear();
}

export function setDiscoveries(discoveries: { tv?: MediaItem[]; movies?: MediaItem[] }): void {
  state.currentDiscoveries.tv = Array.isArray(discoveries.tv) ? [...discoveries.tv] : [];
  state.currentDiscoveries.movies = Array.isArray(discoveries.movies) ? [...discoveries.movies] : [];
}

export function setConfig(config: ConfigResponse | null): void {
  state.appConfig = config;
}

export function setSettings(settings: SettingsResponse | null): void {
  state.appSettings = settings;
}

export function setSelectedForAdd(item: SelectedItemForAdd | null): void {
  state.selectedItemForAdd = item;
}

export function setMarkInLibraryMode(mode: boolean): void {
  state.isMarkInLibraryMode = mode;
}

export function setActiveTab(tab: string): void {
  state.activeTab = tab;
}

export function setCustomFeeds(feeds: FeedItem[]): void {
  state.customFeedsList = Array.isArray(feeds) ? [...feeds] : [];
}

export function resetState(): void {
  const initial = createInitialState();
  state.appConfig = initial.appConfig;
  state.appSettings = initial.appSettings;
  state.currentDiscoveries = initial.currentDiscoveries;
  state.selectedItemForAdd = initial.selectedItemForAdd;
  state.selectedGenres = initial.selectedGenres;
  state.selectedNetworks = initial.selectedNetworks;
  state.selectedCountries = initial.selectedCountries;
  state.selectedLanguages = initial.selectedLanguages;
  state.isMarkInLibraryMode = initial.isMarkInLibraryMode;
  state.activeTab = initial.activeTab;
  if (state.progressInterval) {
    clearInterval(state.progressInterval as number);
  }
  state.progressInterval = initial.progressInterval;
  state.customFeedsList = initial.customFeedsList;
}
