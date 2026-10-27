/**
 * Typed helpers for settings configuration, preset/MRU resolution, and custom feeds.
 *
 * All functions take explicit arguments without direct document/DOM access.
 */

import { escapeHtml } from "./cards.js";
import {
  SettingsResponse,
  FeedItem,
  SaveFeedPayload,
  TestFeedPayload,
  TestFeedPreviewItem
} from "./types.js";

/**
 * Built-in default parser configuration templates for custom feeds.
 */
export const DEFAULT_PARSER_CONFIGS: Record<string, Record<string, unknown>> = {
  rss: {
    item_selector: "item",
    mappings: {
      title: { selector: "title" },
      year: { selector: "filmYear", transforms: [{ type: "regex_search", pattern: "\\d{4}" }] },
      date_str: { selector: "pubDate" },
      href: { selector: "link" }
    }
  },
  json: {
    item_selector: "$",
    mappings: {
      title: { selector: "title" },
      year: { selector: "year" },
      href: { selector: "url" }
    }
  },
  html: {
    item_selector: "table.wikitable tbody tr",
    mappings: {
      title: { selector: "td i a", extract: "text" },
      year: { selector: "td", extract: "text", transforms: [{ type: "regex_search", pattern: "\\d{4}" }] },
      href: { selector: "td i a", extract: "attribute", attribute_name: "href" }
    }
  }
};

export interface SettingsFormValues {
  radarrUrl?: string | null;
  radarrKey?: string | null;
  radarrDefaultFolder?: string | null;
  radarrDefaultProfile?: string | null;
  sonarrUrl?: string | null;
  sonarrKey?: string | null;
  tmdbKey?: string | null;
  sonarrDefaultFolder?: string | null;
  sonarrDefaultProfile?: string | null;
  pastMonths?: string | number | null;
  futureMonths?: string | number | null;
  showReturning?: boolean | string | number | null;
  showLibrary?: boolean | string | number | null;
  showArchived?: boolean | string | number | null;
  matchIgnoreYear?: boolean | string | number | null;
  schedulerEnabled?: boolean | string | number | null;
  schedulerInterval?: string | number | null;
  schedulerTimeOfDay?: string | null;
  logLevel?: string | null;
}

/**
 * Collects form values into the payload expected by saveSettings (POST /api/settings).
 */
export function collectSettingsPayload(values: SettingsFormValues): Record<string, string> {
  const isChecked = (val: boolean | string | number | null | undefined, defaultTrue = false): string => {
    if (val === undefined || val === null) return defaultTrue ? "1" : "0";
    if (typeof val === "boolean") return val ? "1" : "0";
    const str = String(val).trim();
    if (str === "1" || str === "true") return "1";
    if (str === "0" || str === "false") return "0";
    return defaultTrue ? "1" : "0";
  };

  return {
    radarr_url: (values.radarrUrl || "").trim(),
    radarr_api_key: (values.radarrKey || "").trim(),
    radarr_default_root_folder: values.radarrDefaultFolder || "",
    radarr_default_quality_profile: values.radarrDefaultProfile || "",
    sonarr_url: (values.sonarrUrl || "").trim(),
    sonarr_api_key: (values.sonarrKey || "").trim(),
    tmdb_api_key: values.tmdbKey ? values.tmdbKey.trim() : "",
    sonarr_default_root_folder: values.sonarrDefaultFolder || "",
    sonarr_default_quality_profile: values.sonarrDefaultProfile || "",
    default_past_months: values.pastMonths !== undefined && values.pastMonths !== null ? String(values.pastMonths) : "1",
    default_future_months: values.futureMonths !== undefined && values.futureMonths !== null ? String(values.futureMonths) : "2",
    default_show_returning: isChecked(values.showReturning, false),
    default_show_library: isChecked(values.showLibrary, false),
    default_show_archived: isChecked(values.showArchived, false),
    default_match_ignore_year: isChecked(values.matchIgnoreYear, true),
    scheduler_enabled: isChecked(values.schedulerEnabled, false),
    scheduler_interval_hours: values.schedulerInterval !== undefined && values.schedulerInterval !== null && String(values.schedulerInterval).trim() !== "" ? String(values.schedulerInterval) : "24",
    scheduler_time_of_day: (values.schedulerTimeOfDay || "").trim(),
    log_level: (values.logLevel || "INFO").trim().toUpperCase()
  };
}

export interface SettingsDefaults {
  radarr_url: string;
  radarr_api_key: string;
  sonarr_url: string;
  sonarr_api_key: string;
  tmdb_api_key: string;
  default_past_months: string;
  default_future_months: string;
  default_show_returning: boolean;
  default_show_library: boolean;
  default_show_archived: boolean;
  default_match_ignore_year: boolean;
  radarr_default_root_folder: string;
  radarr_default_quality_profile: string;
  sonarr_default_root_folder: string;
  sonarr_default_quality_profile: string;
  scheduler_enabled: boolean;
  scheduler_interval_hours: string;
  scheduler_time_of_day: string;
  log_level: string;
}

/**
 * Resolves default values from an appSettings object with safe fallbacks.
 */
export function resolveSettingsDefaults(settings?: SettingsResponse | Record<string, unknown> | null): SettingsDefaults {
  const s = settings || {};
  const schedEnabled = s.scheduler_enabled;
  const isSchedEnabled = typeof schedEnabled === "boolean" ? schedEnabled : (String(schedEnabled || "0").trim() === "1" || String(schedEnabled || "false").toLowerCase() === "true");
  const schedInterval = s.scheduler_interval_hours !== undefined && s.scheduler_interval_hours !== null && String(s.scheduler_interval_hours).trim() !== "" ? String(s.scheduler_interval_hours) : "24";
  const schedTime = typeof s.scheduler_time_of_day === "string" ? s.scheduler_time_of_day : "";

  return {
    radarr_url: typeof s.radarr_url === "string" ? s.radarr_url : "",
    radarr_api_key: typeof s.radarr_api_key === "string" ? s.radarr_api_key : "",
    sonarr_url: typeof s.sonarr_url === "string" ? s.sonarr_url : "",
    sonarr_api_key: typeof s.sonarr_api_key === "string" ? s.sonarr_api_key : "",
    tmdb_api_key: typeof s.tmdb_api_key === "string" ? s.tmdb_api_key : "",
    default_past_months: typeof s.default_past_months === "string" && s.default_past_months ? s.default_past_months : "1",
    default_future_months: typeof s.default_future_months === "string" && s.default_future_months ? s.default_future_months : "2",
    default_show_returning: s.default_show_returning === "1",
    default_show_library: s.default_show_library === "1",
    default_show_archived: s.default_show_archived === "1",
    default_match_ignore_year: s.default_match_ignore_year !== "0",
    radarr_default_root_folder: typeof s.radarr_default_root_folder === "string" ? s.radarr_default_root_folder : "",
    radarr_default_quality_profile: typeof s.radarr_default_quality_profile === "string"
      ? s.radarr_default_quality_profile
      : (typeof s.radarr_default_profile_id === "string" ? s.radarr_default_profile_id : ""),
    sonarr_default_root_folder: typeof s.sonarr_default_root_folder === "string" ? s.sonarr_default_root_folder : "",
    sonarr_default_quality_profile: typeof s.sonarr_default_quality_profile === "string"
      ? s.sonarr_default_quality_profile
      : (typeof s.sonarr_default_profile_id === "string" ? s.sonarr_default_profile_id : ""),
    scheduler_enabled: isSchedEnabled,
    scheduler_interval_hours: schedInterval,
    scheduler_time_of_day: schedTime,
    log_level: typeof s.log_level === "string" && s.log_level ? s.log_level : "INFO"
  };
}

/**
 * Resolves the quality profile or root folder selection using a 3-tier hybrid strategy:
 * Tier 1: Explicit Settings Default (appSettings[explicitSettingKey])
 * Tier 2: Most-Recently-Used Fallback (localStorage[mruKey] or appSettings[mruKey])
 * Tier 3: Safety Fallback (First available option)
 */
export function resolveHybridPreset(
  optionsList: Array<Record<string, unknown>> | null | undefined,
  valueKey: string,
  explicitSettingValue?: unknown,
  mruKey?: string | null,
  storage?: { getItem(k: string): string | null } | null,
  settings?: Record<string, unknown> | null
): string {
  if (!optionsList || !Array.isArray(optionsList) || optionsList.length === 0) {
    return "";
  }

  const findOption = (val: unknown) => {
    if (val === undefined || val === null) return null;
    const valStr = String(val).trim();
    if (valStr === "") return null;
    return optionsList.find(opt => opt && String(opt[valueKey]).trim() === valStr) || null;
  };

  // Tier 1: Explicit Server Setting
  const explicitMatch = findOption(explicitSettingValue);
  if (explicitMatch) {
    return String(explicitMatch[valueKey]);
  }

  // Tier 2: Most-Recently-Used (MRU) Fallback
  let mruVal: string | null = null;
  if (mruKey) {
    try {
      const s = storage || (typeof localStorage !== "undefined" ? localStorage : null);
      if (s) {
        mruVal = s.getItem(mruKey);
      }
    } catch {
      // ignore storage access error
    }
  }
  let mruMatch = findOption(mruVal);
  if (mruMatch) {
    return String(mruMatch[valueKey]);
  }

  const fallbackSettings =
    settings ||
    (typeof (globalThis as any).appSettings !== "undefined"
      ? (globalThis as any).appSettings
      : null);

  if (mruKey && fallbackSettings) {
    mruMatch = findOption(fallbackSettings[mruKey]);
    if (mruMatch) {
      return String(mruMatch[valueKey]);
    }
    const backendKeyMap: Record<string, string> = {
      xarrtools_mru_radarr_folder: "radarr_mru_root_folder",
      xarrtools_mru_radarr_profile: "radarr_mru_quality_profile",
      xarrtools_mru_sonarr_folder: "sonarr_mru_root_folder",
      xarrtools_mru_sonarr_profile: "sonarr_mru_quality_profile"
    };
    const altKey = backendKeyMap[mruKey];
    if (altKey) {
      mruMatch = findOption(fallbackSettings[altKey]);
      if (mruMatch) {
        return String(mruMatch[valueKey]);
      }
    }
  }

  // Tier 3: Safety Fallback (First Available Option)
  if (optionsList[0] && optionsList[0][valueKey] !== undefined) {
    return String(optionsList[0][valueKey]);
  }

  return "";
}

/**
 * Updates the localStorage MRU cache upon media addition.
 */
export function updateMRUCache(
  type: string,
  folder?: unknown,
  profileId?: unknown,
  storage?: { setItem(k: string, v: string): void } | null
): void {
  const prefix = type === "tv" ? "xarrtools_mru_sonarr" : "xarrtools_mru_radarr";
  try {
    const s = storage || (typeof localStorage !== "undefined" ? localStorage : null);
    if (!s) return;
    if (folder !== undefined && folder !== null && String(folder).trim() !== "") {
      s.setItem(`${prefix}_folder`, String(folder).trim());
    }
    if (profileId !== undefined && profileId !== null && String(profileId).trim() !== "") {
      s.setItem(`${prefix}_profile`, String(profileId).trim());
    }
  } catch (e) {
    console.warn("Failed to update localStorage MRU cache:", e);
  }
}

export interface FeedFormInput {
  id?: number | string | null;
  name?: string | null;
  url?: string | null;
  feed_type?: string | null;
  default_media_type?: string | null;
  enabled?: boolean | number | null;
  headers_raw?: string | null;
  parser_config_raw?: string | null;
}

export interface FeedValidationResult {
  valid: boolean;
  error?: string;
  payload?: SaveFeedPayload;
}

/**
 * Validates a feed form input and constructs a SaveFeedPayload if valid.
 */
export function validateFeedForm(input: FeedFormInput): FeedValidationResult {
  const name = (input.name || "").trim();
  const url = (input.url || "").trim();
  const feedType = input.feed_type || "rss";
  const defaultMediaType = input.default_media_type || "movie";
  const enabled = (input.enabled === 1 || input.enabled === true) ? 1 : 0;
  const headersRaw = (input.headers_raw || "").trim();
  const configRaw = (input.parser_config_raw || "").trim();

  if (!name || !url) {
    return { valid: false, error: "Please enter a feed name and URL." };
  }

  let httpHeaders: Record<string, unknown> = {};
  if (headersRaw) {
    try {
      httpHeaders = JSON.parse(headersRaw);
    } catch (e: any) {
      return { valid: false, error: "HTTP Headers must be valid JSON object. Error: " + (e?.message || String(e)) };
    }
  }

  let parserConfig: Record<string, any> = {};
  try {
    parserConfig = configRaw ? JSON.parse(configRaw) : {};
  } catch (e: any) {
    return { valid: false, error: "Parser Config must be valid JSON object. Error: " + (e?.message || String(e)) };
  }

  const builtinTypes = ["metacritic_tv", "metacritic_movie", "dvds_releases", "tvmaze_schedule", "tmdb_movies"];
  if (!builtinTypes.includes(feedType)) {
    if (!parserConfig.mappings || !parserConfig.mappings.title) {
      return { valid: false, error: "Parser config mappings must contain at least a 'title' selector rule." };
    }
  }

  let parsedId: number | null = null;
  if (input.id !== undefined && input.id !== null && String(input.id).trim() !== "") {
    const num = parseInt(String(input.id), 10);
    parsedId = isNaN(num) ? null : num;
  }

  return {
    valid: true,
    payload: {
      id: parsedId,
      name,
      url,
      feed_type: feedType,
      default_media_type: defaultMediaType,
      enabled,
      http_headers: httpHeaders,
      parser_config: parserConfig
    }
  };
}

export interface TestFeedInput {
  url?: string | null;
  feed_type?: string | null;
  default_media_type?: string | null;
  headers_raw?: string | null;
  parser_config_raw?: string | null;
}

export interface TestFeedValidationResult {
  valid: boolean;
  error?: string;
  payload?: TestFeedPayload;
}

/**
 * Validates test feed inputs and constructs a TestFeedPayload.
 */
export function validateTestFeedInput(input: TestFeedInput): TestFeedValidationResult {
  const url = (input.url || "").trim();
  const feedType = input.feed_type || "rss";
  const defaultMediaType = input.default_media_type || "movie";
  const headersRaw = (input.headers_raw || "").trim();
  const configRaw = (input.parser_config_raw || "").trim();

  if (!url) {
    return { valid: false, error: "Please enter a feed URL to test." };
  }

  let httpHeaders: Record<string, unknown> = {};
  if (headersRaw) {
    try {
      httpHeaders = JSON.parse(headersRaw);
    } catch (e: any) {
      return { valid: false, error: "HTTP Headers must be valid JSON object. Error: " + (e?.message || String(e)) };
    }
  }

  let parserConfig: Record<string, unknown> = {};
  try {
    parserConfig = configRaw ? JSON.parse(configRaw) : {};
  } catch (e: any) {
    return { valid: false, error: "Parser Config must be valid JSON object. Error: " + (e?.message || String(e)) };
  }

  return {
    valid: true,
    payload: {
      url,
      feed_type: feedType,
      default_media_type: defaultMediaType,
      http_headers: httpHeaders,
      parser_config: parserConfig
    }
  };
}

/**
 * Formats dry-run test results into readable diagnostic summary text.
 */
export function formatTestFeedResults(
  results?: TestFeedPreviewItem[] | null,
  itemsCount = 0,
  _timeMs?: number
): string {
  if (results && results.length > 0) {
    let text = `Total parsed: ${itemsCount} items. Showing first ${results.length}:\n\n`;
    results.forEach((item, idx) => {
      const yearStr = item.year ? ` (${item.year})` : "";
      const imdbStr = item.imdb_id ? ` [IMDb: ${item.imdb_id}]` : "";
      text += `${idx + 1}. Title: "${item.title}"${yearStr}${imdbStr}\n`;
      text += `   Link:  ${item.href || "N/A"}\n`;
      if (item.description) {
        text += `   Plot:  ${item.description}\n`;
      }
      text += `\n`;
    });
    return text;
  }
  return "Fetched successfully, but 0 items matched your mapping selectors.";
}

/**
 * Builds HTML status badge for a feed row.
 */
export function buildFeedStatusBadgeHtml(status?: string | null, errorMessage?: string | null): string {
  if (status === "success") {
    return `<span class="badge" style="background: rgba(0, 255, 135, 0.1); color: var(--accent-green); border: 1px solid rgba(0, 255, 135, 0.25); font-size:10px; padding:2px 6px;">Success</span>`;
  }
  if (status === "error") {
    const errorTooltip = errorMessage ? `title="${escapeHtml(errorMessage)}"` : "";
    return `<span class="badge" style="background: rgba(255, 0, 80, 0.1); color: #ff0050; border: 1px solid rgba(255, 0, 80, 0.25); font-size:10px; padding:2px 6px; cursor:help;" ${errorTooltip}>Error ⚠️</span>`;
  }
  return `<span class="badge" style="background: rgba(255, 255, 255, 0.05); color: var(--text-secondary); border: 1px solid var(--border-color); font-size:10px; padding:2px 6px;">Never</span>`;
}

/**
 * Builds the inner HTML for a custom feed table row (tr), with all dynamic fields escaped.
 */
export function buildFeedTableRowHtml(feed: FeedItem): string {
  const statusBadge = buildFeedStatusBadgeHtml(feed.last_status, feed.last_error_message);
  const enabledStyle = (feed.enabled === 1 || feed.enabled === true) ? "" : "opacity: 0.5; text-decoration: line-through;";

  return `
                    <td style="padding: 8px; font-weight: 500; color: var(--text-primary); max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; ${enabledStyle}">${escapeHtml(feed.name)}</td>
                    <td style="padding: 8px; text-transform: uppercase; font-size: 11px; color: var(--text-secondary);">${escapeHtml(feed.feed_type)}</td>
                    <td style="padding: 8px;">${statusBadge}</td>
                    <td style="padding: 8px; text-align: right; white-space: nowrap;">
                        <button type="button" class="btn btn-secondary btn-feed-row-edit" data-feed-id="${escapeHtml(feed.id)}" style="font-size:11px; padding:2px 6px; margin:0 4px 0 0; width:auto; display:inline-block;">Edit</button>
                        <button type="button" class="btn btn-feed-row-delete" data-feed-id="${escapeHtml(feed.id)}" data-feed-name="${escapeHtml(feed.name)}" style="background: rgba(255, 42, 133, 0.1); border: 1px solid rgba(255, 42, 133, 0.3); color: var(--accent-magenta); font-size:11px; padding:2px 6px; margin:0; width:auto; display:inline-block;">&times;</button>
                    </td>
                `;
}

/**
 * Resolves default parser config string when feed type changes in the UI editor.
 */
export function resolveDefaultParserConfig(feedType: string, currentConfigValue: string): string | null {
  const builtinTypes = ["metacritic_tv", "metacritic_movie", "dvds_releases", "tvmaze_schedule", "tmdb_movies"];
  if (builtinTypes.includes(feedType)) {
    return "{}";
  }

  const trimmed = (currentConfigValue || "").trim();
  let matchesDefault = false;

  try {
    const parsedCurrent = JSON.parse(trimmed);
    if (
      Object.keys(parsedCurrent).length === 0 ||
      (trimmed.includes("filmYear") && feedType !== "rss") ||
      (trimmed.includes("tbody tr") && feedType !== "html") ||
      (trimmed.includes('item_selector": "$"') && feedType !== "json")
    ) {
      matchesDefault = true;
    }
  } catch {
    matchesDefault = true;
  }

  if (matchesDefault && DEFAULT_PARSER_CONFIGS[feedType]) {
    return JSON.stringify(DEFAULT_PARSER_CONFIGS[feedType], null, 2);
  }

  return null;
}

export interface FeedEditorFormDefaults {
  title: string;
  id: string;
  name: string;
  url: string;
  feed_type: string;
  default_media_type: string;
  enabled: boolean;
  headers_json: string;
  parser_config_json: string;
}

/**
 * Extracts form field defaults when opening the feed editor modal (add or edit).
 */
export function getFeedEditorFormDefaults(feed?: FeedItem | Record<string, unknown> | null): FeedEditorFormDefaults {
  if (feed) {
    let headersObj = {};
    try {
      headersObj = typeof feed.http_headers === "string" ? JSON.parse(feed.http_headers) : (feed.http_headers || {});
    } catch {
      headersObj = {};
    }
    let configObj = {};
    try {
      configObj = typeof feed.parser_config === "string" ? JSON.parse(feed.parser_config) : (feed.parser_config || {});
    } catch {
      configObj = {};
    }
    return {
      title: "Edit Custom Feed",
      id: feed.id !== undefined && feed.id !== null ? String(feed.id) : "",
      name: typeof feed.name === "string" ? feed.name : "",
      url: typeof feed.url === "string" ? feed.url : "",
      feed_type: typeof feed.feed_type === "string" ? feed.feed_type : "rss",
      default_media_type: typeof feed.default_media_type === "string" ? feed.default_media_type : "movie",
      enabled: feed.enabled === 1 || feed.enabled === true,
      headers_json: JSON.stringify(headersObj, null, 2),
      parser_config_json: JSON.stringify(configObj, null, 2)
    };
  }
  return {
    title: "Add Custom Feed",
    id: "",
    name: "",
    url: "",
    feed_type: "rss",
    default_media_type: "movie",
    enabled: true,
    headers_json: "{}",
    parser_config_json: JSON.stringify(DEFAULT_PARSER_CONFIGS.rss, null, 2)
  };
}

