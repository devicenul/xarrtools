/**
 * Shared TypeScript type definitions for xarrtools frontend media items and filters.
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
  tmdb_id?: number | string | null;
  tvdb_id?: number | string | null;
  source_feed_id?: number | string | null;
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

export interface ArchiveBatchResponse {
  status?: string;
  archived: number;
  failed?: Array<{ title: string; message?: string }>;
  message?: string;
}
