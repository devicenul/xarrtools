/**
 * Shared TypeScript type definitions for xarrtools frontend media items, filters, APIs, and cards.
 */

export interface MediaItem {
  title: string;
  year?: number | string | null;
  country?: string | null;
  language?: string | null;
  genres?: string[] | null;
  network?: string | null;
  is_archived?: boolean | number | null;
  is_returning?: boolean | number | null;
  is_in_library?: boolean | number | null;
  has_new_metadata?: boolean | number | null;
  cast?: string | null;
  director?: string | null;
  producer?: string | null;
  date_obj?: string | null;
  date_str?: string | null;
  plot?: string | null;
  description?: string | null;
  poster_url?: string | null;
  trailer?: string | null;
  rating_imdb?: number | string | null;
  rating_metacritic?: number | string | null;
  rating_rt?: number | string | null;
  imdb_id?: string | null;
  imdbId?: string | null;
  tmdb_id?: number | string | null;
  tmdbId?: number | string | null;
  tvdb_id?: number | string | null;
  tvdbId?: number | string | null;
  source_feed_id?: number | string | null;
  href?: string | null;
  [key: string]: unknown;
}

export interface FilterState {
  showReturning?: boolean;
  showLibrary?: boolean;
  showArchived?: boolean;
  searchTerm?: string;
  genres?: Set<string>;
  networks?: Set<string>;
  countries?: Set<string>;
  languages?: Set<string>;
}

export interface Discoveries {
  tv?: MediaItem[];
  movies?: MediaItem[];
}

export interface FilteredTarget {
  type: "tv" | "movie" | string;
  item: MediaItem;
}

export interface ArchiveBatchItem {
  type: string;
  title: string;
  year?: number | string | null;
  raw_item?: MediaItem;
}

export interface ApiResponse {
  ok?: boolean;
  status?: string;
  message?: string;
  [key: string]: unknown;
}

export interface ArchiveBatchResponse extends ApiResponse {
  archived: number;
  failed?: Array<{ title: string | null; message?: string }>;
}

export interface FolderOption {
  id?: number;
  path: string;
  [key: string]: unknown;
}

export interface ProfileOption {
  id: number;
  name: string;
  [key: string]: unknown;
}

export interface ServiceConfig {
  configured: boolean;
  folders: FolderOption[];
  profiles: ProfileOption[];
  error?: string;
}

export interface ConfigResponse extends ApiResponse {
  radarr: ServiceConfig;
  sonarr: ServiceConfig;
}

export interface SettingsResponse extends ApiResponse {
  radarr_url?: string;
  radarr_api_key?: string;
  radarr_default_root_folder?: string;
  radarr_default_quality_profile?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  sonarr_default_root_folder?: string;
  sonarr_default_quality_profile?: string;
  tmdb_api_key?: string;
  default_past_months?: string;
  default_future_months?: string;
  default_show_returning?: string;
  default_show_library?: string;
  default_show_archived?: string;
  default_match_ignore_year?: string;
  scheduler_enabled?: string | boolean;
  scheduler_interval_hours?: string | number;
  scheduler_time_of_day?: string;
  scheduler_last_run?: string;
  scheduler_last_result?: string;
  log_level?: string;
  [key: string]: unknown;
}

export interface SchedulerLastResult {
  started_at: string;
  finished_at: string;
  status: "ok" | "error" | string;
  tv_count: number;
  movie_count: number;
  new_items: number;
  error?: string | null;
}

export interface SchedulerStatusResponse extends ApiResponse {
  enabled: boolean;
  interval_hours: number;
  time_of_day: string;
  last_run: string | null;
  next_run: string | null;
  running: boolean;
  last_result: SchedulerLastResult | null;
}

export interface ScanProgressResponse extends ApiResponse {
  status: "idle" | "scraping" | "enriching" | string;
  message: string;
  current: number;
  total: number;
}

export interface DiscoverOptions {
  pastMonths?: number | string;
  futureMonths?: number | string;
  skipScrape?: boolean;
}

export interface DiscoveriesResponse extends ApiResponse {
  tv: MediaItem[];
  movies: MediaItem[];
}

export interface AddMediaPayload {
  type: string;
  raw_metadata: Record<string, unknown>;
  folder?: string;
  profile_id?: number | string;
  monitored?: boolean;
  search_now?: boolean;
  add_collection?: boolean;
  demo?: boolean;
}

export interface ArchiveItemPayload {
  type: string;
  title: string;
  year?: number | string | null;
  archive: boolean;
  raw_item?: MediaItem;
}

export interface RefreshCacheItemPayload {
  type: string;
  title: string;
  year: number | string;
  imdbId?: string | null;
}

export interface RefreshCacheItemResponse extends ApiResponse {
  item?: MediaItem;
}

export interface LookupResultItem {
  id?: number;
  title: string;
  year?: number;
  tvdbId?: number;
  tmdbId?: number;
  imdbId?: string;
  remotePoster?: string;
  collection?: { title?: string; name?: string };
  [key: string]: unknown;
}

export interface LookupResponse extends ApiResponse {
  results?: LookupResultItem[];
}

export interface LinkLibraryPayload {
  type: string;
  title: string;
  year: number | string;
  imdbId?: string | null;
  link_metadata: Record<string, unknown>;
}

export interface CacheStatsResponse extends ApiResponse {
  total_discoveries?: number;
  archived_discoveries?: number;
  database_size?: string;
}

export interface BackupImportResponse extends ApiResponse {
  settings_count?: number;
  media_count?: number;
  posters_count?: number;
  custom_feeds_count?: number;
}

export interface FeedItem {
  id: number;
  name: string;
  url: string;
  feed_type: string;
  default_media_type?: string;
  enabled: number | boolean;
  http_headers?: string;
  parser_config?: string;
  last_status?: "success" | "error" | "never" | string;
  last_error_message?: string;
  last_run?: string;
  [key: string]: unknown;
}

export interface FeedsResponse extends ApiResponse {
  feeds: FeedItem[];
}

export interface SaveFeedPayload {
  id?: number | null;
  name: string;
  url: string;
  feed_type: string;
  default_media_type?: string;
  enabled: number | boolean;
  http_headers?: Record<string, unknown> | string;
  parser_config?: Record<string, unknown> | string;
}

export interface SaveFeedResponse extends ApiResponse {
  feed_id?: number;
}

export interface TestFeedPayload {
  url: string;
  feed_type: string;
  default_media_type?: string;
  http_headers?: Record<string, unknown>;
  parser_config?: Record<string, unknown>;
}

export interface TestFeedPreviewItem {
  title: string;
  year?: number | string;
  type: string;
  date_str?: string;
  href?: string;
  imdb_id?: string;
  tvdb_id?: number | string;
  tmdb_id?: number | string;
  description?: string;
}

export interface TestFeedResponse extends ApiResponse {
  fetch_time_ms?: number;
  parsed_items_count?: number;
  results?: TestFeedPreviewItem[];
  errors?: unknown[];
}

export interface CardRenderOptions {
  isAdded?: boolean;
  index?: number | string;
}

export interface SelectedItemForAdd {
  type: string;
  item: MediaItem;
  raw_metadata?: unknown;
  card?: HTMLElement | null;
  isDemo?: boolean;
}
