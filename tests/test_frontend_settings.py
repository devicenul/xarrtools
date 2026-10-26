"""Tests for compiled settings.js module under Node.js.

Verifies pure settings & feeds helpers:
- collectSettingsPayload
- resolveSettingsDefaults
- resolveHybridPreset (Tier 1 -> Tier 2 MRU -> Tier 3 Safety Fallback)
- updateMRUCache
- validateFeedForm
- validateTestFeedInput
- formatTestFeedResults
- buildFeedStatusBadgeHtml
- buildFeedTableRowHtml
- resolveDefaultParserConfig
- DEFAULT_PARSER_CONFIGS
- getFeedEditorFormDefaults
"""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

DIST_SETTINGS = Path(__file__).resolve().parent.parent / "web" / "static" / "dist" / "settings.js"


def run_node_settings(body: str):
    if not DIST_SETTINGS.is_file():
        pytest.skip("web/static/dist/settings.js not found; run 'npm run build' first")
    code = f"""
import {{
  DEFAULT_PARSER_CONFIGS,
  collectSettingsPayload,
  resolveSettingsDefaults,
  resolveHybridPreset,
  updateMRUCache,
  validateFeedForm,
  validateTestFeedInput,
  formatTestFeedResults,
  buildFeedStatusBadgeHtml,
  buildFeedTableRowHtml,
  resolveDefaultParserConfig,
  getFeedEditorFormDefaults
}} from {json.dumps(DIST_SETTINGS.as_uri())};

(async () => {{
{body}
}})().catch(err => {{
  console.error(err);
  process.exit(1);
}});
"""
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"Node script error: {out.stderr}\nSTDOUT: {out.stdout}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_resolve_settings_defaults():
    res = run_node_settings("""
      const d1 = resolveSettingsDefaults(null);
      const d2 = resolveSettingsDefaults({});
      const d3 = resolveSettingsDefaults({
        radarr_url: "http://radarr:7878",
        radarr_api_key: "abc123key",
        default_past_months: "3",
        default_future_months: "6",
        default_show_returning: "1",
        default_show_library: "0",
        default_show_archived: "1",
        default_match_ignore_year: "0",
        radarr_default_quality_profile: "7",
        sonarr_default_root_folder: "/data/tv"
      });
      console.log(JSON.stringify({ d1, d2, d3 }));
    """)
    # null or empty defaults
    assert res["d1"]["default_past_months"] == "1"
    assert res["d1"]["default_future_months"] == "2"
    assert res["d1"]["default_match_ignore_year"] is True
    assert res["d1"]["default_show_returning"] is False
    assert res["d1"]["radarr_url"] == ""

    # custom values
    assert res["d3"]["radarr_url"] == "http://radarr:7878"
    assert res["d3"]["radarr_api_key"] == "abc123key"
    assert res["d3"]["default_past_months"] == "3"
    assert res["d3"]["default_future_months"] == "6"
    assert res["d3"]["default_show_returning"] is True
    assert res["d3"]["default_show_library"] is False
    assert res["d3"]["default_show_archived"] is True
    assert res["d3"]["default_match_ignore_year"] is False
    assert res["d3"]["radarr_default_quality_profile"] == "7"
    assert res["d3"]["sonarr_default_root_folder"] == "/data/tv"


def test_resolve_hybrid_preset_all_tiers():
    res = run_node_settings("""
      const profiles = [
        { id: 1, name: "SD" },
        { id: 2, name: "HD-1080p" },
        { id: 3, name: "UHD-4K" }
      ];

      const mockStorage = {
        store: {},
        getItem(k) { return this.store[k] || null; },
        setItem(k, v) { this.store[k] = String(v); }
      };

      // Tier 1: Explicit match
      const t1 = resolveHybridPreset(profiles, "id", 2, "mru_key", mockStorage);
      const t1Str = resolveHybridPreset(profiles, "id", "3", "mru_key", mockStorage);

      // Tier 2: Storage MRU wins when explicit is null/missing
      mockStorage.setItem("mru_key", "3");
      const t2Storage = resolveHybridPreset(profiles, "id", null, "mru_key", mockStorage);

      // Tier 2: Storage MRU wins when explicit is stale
      const t2Stale = resolveHybridPreset(profiles, "id", 999, "mru_key", mockStorage);

      // Tier 2: Backend settings MRU fallback (via altKey mapping)
      mockStorage.store = {};
      const backendSettings = { radarr_mru_quality_profile: "2" };
      const t2Backend = resolveHybridPreset(
        profiles,
        "id",
        null,
        "xarrtools_mru_radarr_profile",
        mockStorage,
        backendSettings
      );

      // Tier 3: Safety Fallback to first available option
      const t3 = resolveHybridPreset(profiles, "id", 999, "nonexistent_key", mockStorage, {});

      // Resilience tests: empty array, null, undefined, malformed list
      const emptyRes = resolveHybridPreset([], "id", 1, "k", mockStorage);
      const nullRes = resolveHybridPreset(null, "id", 1, "k", mockStorage);
      const undefRes = resolveHybridPreset(undefined, "id", 1, "k", mockStorage);
      const malformedRes = resolveHybridPreset([{}], "id", 1, "k", mockStorage);

      console.log(JSON.stringify({
        t1, t1Str, t2Storage, t2Stale, t2Backend, t3,
        emptyRes, nullRes, undefRes, malformedRes
      }));
    """)
    assert res["t1"] == "2"
    assert res["t1Str"] == "3"
    assert res["t2Storage"] == "3"
    assert res["t2Stale"] == "3"
    assert res["t2Backend"] == "2"
    assert res["t3"] == "1"
    assert res["emptyRes"] == ""
    assert res["nullRes"] == ""
    assert res["undefRes"] == ""
    assert res["malformedRes"] == ""


def test_update_mru_cache():
    res = run_node_settings("""
      const mockStorage = {
        store: {},
        getItem(k) { return this.store[k] || null; },
        setItem(k, v) { this.store[k] = String(v); }
      };

      updateMRUCache("movie", "/data/movies", 5, mockStorage);
      const movieFolder = mockStorage.getItem("xarrtools_mru_radarr_folder");
      const movieProfile = mockStorage.getItem("xarrtools_mru_radarr_profile");

      updateMRUCache("tv", "/data/shows", "9", mockStorage);
      const tvFolder = mockStorage.getItem("xarrtools_mru_sonarr_folder");
      const tvProfile = mockStorage.getItem("xarrtools_mru_sonarr_profile");

      console.log(JSON.stringify({ movieFolder, movieProfile, tvFolder, tvProfile }));
    """)
    assert res["movieFolder"] == "/data/movies"
    assert res["movieProfile"] == "5"
    assert res["tvFolder"] == "/data/shows"
    assert res["tvProfile"] == "9"


def test_validate_feed_form():
    res = run_node_settings("""
      const vValid = validateFeedForm({
        name: "My Feed",
        url: "https://example.com/rss",
        feed_type: "rss",
        parser_config_raw: '{"mappings": {"title": {"selector": "title"}}}'
      });

      const vBuiltin = validateFeedForm({
        name: "Metacritic TV",
        url: "https://www.metacritic.com/feed",
        feed_type: "metacritic_tv"
      });

      const vMissingName = validateFeedForm({
        name: "   ",
        url: "https://example.com/rss",
        feed_type: "rss"
      });

      const vMissingUrl = validateFeedForm({
        name: "Feed",
        url: "",
        feed_type: "rss"
      });

      const vInvalidJson = validateFeedForm({
        name: "Feed",
        url: "http://example.com",
        feed_type: "rss",
        parser_config_raw: '{malformed json}'
      });

      console.log(JSON.stringify({ vValid, vBuiltin, vMissingName, vMissingUrl, vInvalidJson }));
    """)
    assert res["vValid"]["valid"] is True
    assert res["vValid"]["payload"]["name"] == "My Feed"
    assert res["vValid"]["payload"]["url"] == "https://example.com/rss"
    assert res["vBuiltin"]["valid"] is True
    assert res["vBuiltin"]["payload"]["feed_type"] == "metacritic_tv"
    assert res["vMissingName"]["valid"] is False
    assert "Please enter a feed name and URL" in res["vMissingName"]["error"]
    assert res["vMissingUrl"]["valid"] is False
    assert res["vInvalidJson"]["valid"] is False
    assert "Parser Config must be valid JSON" in res["vInvalidJson"]["error"]


def test_validate_test_feed_input():
    res = run_node_settings("""
      const tValid = validateTestFeedInput({
        url: "https://feeds.example.com/feed.xml",
        feed_type: "rss",
        parser_config_raw: '{"timeout": 5}'
      });

      const tMissingUrl = validateTestFeedInput({
        url: "   ",
        feed_type: "rss"
      });

      const tBadJson = validateTestFeedInput({
        url: "https://example.com",
        feed_type: "rss",
        parser_config_raw: "invalid json string"
      });

      console.log(JSON.stringify({ tValid, tMissingUrl, tBadJson }));
    """)
    assert res["tValid"]["valid"] is True
    assert res["tValid"]["payload"]["url"] == "https://feeds.example.com/feed.xml"
    assert res["tMissingUrl"]["valid"] is False
    assert "Please enter a feed URL to test" in res["tMissingUrl"]["error"]
    assert res["tBadJson"]["valid"] is False
    assert "Parser Config must be valid JSON" in res["tBadJson"]["error"]


def test_format_test_feed_results():
    res = run_node_settings("""
      const items = [
        { title: "Movie 1", year: 2026, href: "https://example.com/1", description: "First plot" },
        { title: "Movie 2", year: 2025, imdb_id: "tt999999" }
      ];
      const formatted = formatTestFeedResults(items, 2, 120);

      const empty = formatTestFeedResults(null);
      const emptyResults = formatTestFeedResults([], 0);
      console.log(JSON.stringify({ formatted, empty, emptyResults }));
    """)
    assert "Total parsed: 2 items" in res["formatted"]
    assert '1. Title: "Movie 1" (2026)' in res["formatted"]
    assert "Link:  https://example.com/1" in res["formatted"]
    assert "Plot:  First plot" in res["formatted"]
    assert '2. Title: "Movie 2" (2025) [IMDb: tt999999]' in res["formatted"]
    assert res["empty"] == "Fetched successfully, but 0 items matched your mapping selectors."
    assert "0 items matched" in res["emptyResults"]


def test_feed_status_badge_html_and_table_row_escaping():
    res = run_node_settings("""
      const bSuccess = buildFeedStatusBadgeHtml("success");
      const bError = buildFeedStatusBadgeHtml("error", "Failed to fetch XML");
      const bNever = buildFeedStatusBadgeHtml(null);

      const safeRow = buildFeedTableRowHtml({
        id: 1,
        name: "Standard Feed",
        feed_type: "tv",
        enabled: 1,
        last_status: "success",
        last_error_message: null
      });

      const xssRow = buildFeedTableRowHtml({
        id: 99,
        name: '<script>alert("xss")</script>',
        feed_type: "movie",
        enabled: 0,
        last_status: "error",
        last_error_message: '<b style="color:red">Error</b>'
      });

      console.log(JSON.stringify({ bSuccess, bError, bNever, safeRow, xssRow }));
    """)
    assert "Success" in res["bSuccess"]
    assert "Error ⚠️" in res["bError"]
    assert 'title="Failed to fetch XML"' in res["bError"]
    assert "Never" in res["bNever"]

    # Table row safe escaping
    assert "Standard Feed" in res["safeRow"]
    assert 'data-feed-id="1"' in res["safeRow"]

    # XSS prevention in table row
    assert '<script>alert("xss")</script>' not in res["xssRow"]
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in res["xssRow"]
    assert 'title="&lt;b style=&quot;color:red&quot;&gt;Error&lt;/b&gt;"' in res["xssRow"]
    assert "opacity: 0.5; text-decoration: line-through;" in res["xssRow"]


def test_parser_config_defaults_and_editor_defaults():
    res = run_node_settings("""
      const rssCfg = resolveDefaultParserConfig("rss", "{}");
      const builtinCfg = resolveDefaultParserConfig("metacritic_tv", "{}");
      const customCfg = resolveDefaultParserConfig("rss", '{"user_custom": true, "mappings": {}}');
      const formDefaults = getFeedEditorFormDefaults();

      console.log(JSON.stringify({
        rssParsed: JSON.parse(rssCfg),
        builtinCfg,
        customCfg,
        formDefaults
      }));
    """)
    assert res["rssParsed"]["item_selector"] == "item"
    assert "title" in res["rssParsed"]["mappings"]
    assert res["builtinCfg"] == "{}"
    assert res["customCfg"] is None
    assert res["formDefaults"]["feed_type"] == "rss"
    assert res["formDefaults"]["default_media_type"] == "movie"
    assert res["formDefaults"]["enabled"] is True


def test_collect_settings_payload():
    res = run_node_settings("""
      const values = {
        radarrUrl: " http://localhost:7878/ ",
        radarrKey: " secret-api-key ",
        sonarrUrl: "http://localhost:8989",
        sonarrKey: "sonarr-key",
        tmdbKey: "tmdb-key",
        pastMonths: "2",
        futureMonths: "4",
        showReturning: true,
        showLibrary: false,
        showArchived: true,
        matchIgnoreYear: false,
        radarrDefaultFolder: "/data/movies",
        radarrDefaultProfile: "5",
        sonarrDefaultFolder: "/data/tv",
        sonarrDefaultProfile: "3"
      };

      const payload = collectSettingsPayload(values);
      console.log(JSON.stringify({ payload }));
    """)
    p = res["payload"]
    assert p["radarr_url"] == "http://localhost:7878/"
    assert p["radarr_api_key"] == "secret-api-key"
    assert p["default_past_months"] == "2"
    assert p["default_future_months"] == "4"
    assert p["default_show_returning"] == "1"
    assert p["default_show_library"] == "0"
    assert p["default_show_archived"] == "1"
    assert p["default_match_ignore_year"] == "0"
    assert p["radarr_default_root_folder"] == "/data/movies"
    assert p["radarr_default_quality_profile"] == "5"
    assert p["sonarr_default_root_folder"] == "/data/tv"
    assert p["sonarr_default_quality_profile"] == "3"
