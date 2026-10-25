/**
 * Typed client API functions for all xarrtools backend endpoints.
 */

import {
  ApiResponse,
  ArchiveBatchItem,
  ArchiveBatchResponse,
  ConfigResponse,
  SettingsResponse,
  ScanProgressResponse,
  DiscoverOptions,
  DiscoveriesResponse,
  AddMediaPayload,
  ArchiveItemPayload,
  RefreshCacheItemPayload,
  RefreshCacheItemResponse,
  LookupResponse,
  LinkLibraryPayload,
  CacheStatsResponse,
  BackupImportResponse,
  FeedsResponse,
  SaveFeedPayload,
  SaveFeedResponse,
  TestFeedPayload,
  TestFeedResponse
} from "./types.js";

async function parseResponse<T extends ApiResponse>(response: Response): Promise<T> {
  const data = (await response.json()) as T;
  if (data && typeof data === "object") {
    data.ok = response.ok;
  }
  return data;
}

/**
 * Batched archive API call to POST /api/archive/batch.
 */
export async function archiveBatch(
  items: ArchiveBatchItem[],
  archive: boolean = true
): Promise<ArchiveBatchResponse> {
  const response = await fetch("/api/archive/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      archive,
      items
    })
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return (await response.json()) as ArchiveBatchResponse;
}

/**
 * Single item archive API call to POST /api/archive.
 */
export async function archiveItem(payload: ArchiveItemPayload): Promise<ApiResponse> {
  const response = await fetch("/api/archive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<ApiResponse>(response);
}

/**
 * Load server configuration status (Sonarr / Radarr root folders and quality profiles).
 * GET /api/config
 */
export async function fetchConfig(): Promise<ConfigResponse> {
  const response = await fetch("/api/config");
  return parseResponse<ConfigResponse>(response);
}

/**
 * Load saved settings from SQLite.
 * GET /api/settings
 */
export async function fetchSettings(): Promise<SettingsResponse> {
  const response = await fetch("/api/settings");
  return parseResponse<SettingsResponse>(response);
}

/**
 * Save configuration settings.
 * POST /api/settings
 */
export async function saveSettings(payload: Record<string, unknown>): Promise<ApiResponse> {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<ApiResponse>(response);
}

/**
 * Poll current scrape/enrich scan progress.
 * GET /api/scan/progress
 */
export async function fetchScanProgress(): Promise<ScanProgressResponse> {
  const response = await fetch("/api/scan/progress");
  return parseResponse<ScanProgressResponse>(response);
}

/**
 * Scan releases or read cached discoveries.
 * GET /api/discover?past_months=X&future_months=Y[&skip_scrape=true]
 */
export async function fetchDiscoveries(
  options: DiscoverOptions = {}
): Promise<DiscoveriesResponse> {
  const pastMonths = options.pastMonths ?? 1;
  const futureMonths = options.futureMonths ?? 2;
  const skipScrape = options.skipScrape === true;
  const url = `/api/discover?past_months=${pastMonths}&future_months=${futureMonths}${
    skipScrape ? "&skip_scrape=true" : ""
  }`;
  const response = await fetch(url);
  if (!response.ok) {
    let errMsg = "Failed to scan releases.";
    try {
      const err = (await response.json()) as { message?: string };
      if (err && err.message) errMsg = err.message;
    } catch {
      // fallback
    }
    throw new Error(errMsg);
  }
  return parseResponse<DiscoveriesResponse>(response);
}

/**
 * Force metadata enrichment from live APIs for a single movie or show and update cache.
 * POST /api/cache/refresh
 */
export async function refreshCacheItem(
  payload: RefreshCacheItemPayload
): Promise<RefreshCacheItemResponse> {
  const response = await fetch("/api/cache/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<RefreshCacheItemResponse>(response);
}

/**
 * Perform a live indexer lookup on Sonarr/Radarr indexers.
 * GET /api/lookup?type=X&title=Y
 */
export async function lookupMedia(type: string, title: string): Promise<LookupResponse> {
  const response = await fetch(
    `/api/lookup?type=${encodeURIComponent(type)}&title=${encodeURIComponent(title)}`
  );
  return parseResponse<LookupResponse>(response);
}

/**
 * Add a movie or TV show to Sonarr/Radarr library.
 * POST /api/add
 */
export async function addMedia(payload: AddMediaPayload): Promise<ApiResponse> {
  const response = await fetch("/api/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<ApiResponse>(response);
}

/**
 * Manually link a discovery item to an existing library match.
 * POST /api/link_library
 */
export async function linkLibrary(payload: LinkLibraryPayload): Promise<ApiResponse> {
  const response = await fetch("/api/link_library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<ApiResponse>(response);
}

/**
 * Retrieve cache row counts and database size diagnostics.
 * GET /api/cache/stats
 */
export async function fetchCacheStats(): Promise<CacheStatsResponse> {
  const response = await fetch("/api/cache/stats");
  return parseResponse<CacheStatsResponse>(response);
}

/**
 * Trigger manual pruning of cache entries older than 12 months.
 * POST /api/cache/prune
 */
export async function pruneCache(): Promise<ApiResponse> {
  const response = await fetch("/api/cache/prune", { method: "POST" });
  return parseResponse<ApiResponse>(response);
}

/**
 * Wipe all discoveries from the cache table.
 * POST /api/cache/clear
 */
export async function clearCache(): Promise<ApiResponse> {
  const response = await fetch("/api/cache/clear", { method: "POST" });
  return parseResponse<ApiResponse>(response);
}

/**
 * Build backup export URL.
 */
export function getBackupExportUrl(includeMedia: boolean = true): string {
  return `/api/backup/export?include_media=${includeMedia}`;
}

/**
 * Import settings and cached media data from an uploaded JSON file.
 * POST /api/backup/import
 */
export async function importBackup(formData: FormData): Promise<BackupImportResponse> {
  const response = await fetch("/api/backup/import", {
    method: "POST",
    body: formData
  });
  return parseResponse<BackupImportResponse>(response);
}

/**
 * Retrieve all configured custom feeds.
 * GET /api/feeds
 */
export async function fetchFeeds(): Promise<FeedsResponse> {
  const response = await fetch("/api/feeds");
  if (!response.ok) {
    throw new Error(`HTTP error ${response.status}`);
  }
  return parseResponse<FeedsResponse>(response);
}

/**
 * Create or update a custom feed configuration.
 * POST /api/feeds
 */
export async function saveFeed(payload: SaveFeedPayload): Promise<SaveFeedResponse> {
  const response = await fetch("/api/feeds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<SaveFeedResponse>(response);
}

/**
 * Delete a configured custom feed from the database.
 * POST /api/feeds/delete
 */
export async function deleteFeed(feedId: number | string): Promise<ApiResponse> {
  const response = await fetch("/api/feeds/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: feedId })
  });
  return parseResponse<ApiResponse>(response);
}

/**
 * Dry-run test feed configurations against target feeds.
 * POST /api/feeds/test
 */
export async function testFeed(payload: TestFeedPayload): Promise<TestFeedResponse> {
  const response = await fetch("/api/feeds/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse<TestFeedResponse>(response);
}

/**
 * Restore standard default feed configurations.
 * POST /api/feeds/restore
 */
export async function restoreDefaultFeeds(): Promise<ApiResponse> {
  const response = await fetch("/api/feeds/restore", { method: "POST" });
  return parseResponse<ApiResponse>(response);
}
