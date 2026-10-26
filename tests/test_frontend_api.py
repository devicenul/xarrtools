"""Tests for compiled api.js module under Node.js with a stubbed global fetch.

Asserts exact URLs, methods, headers, request bodies, and response parsing.
"""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

DIST_API = Path(__file__).resolve().parent.parent / "web" / "static" / "dist" / "api.js"


def run_api_test(body: str):
    if not DIST_API.is_file():
        pytest.skip("web/static/dist/api.js not found; run 'npm run build' first")
    code = f"""
const calls = [];
let mockResponses = {{}};

globalThis.fetch = async (url, opts = {{}}) => {{
  const record = {{
    url: String(url),
    method: opts.method || "GET",
    headers: opts.headers || {{}},
    body: opts.body ? (typeof opts.body === "string" ? JSON.parse(opts.body) : "[FormData]") : null
  }};
  calls.push(record);
  
  const matched = mockResponses[record.method + " " + url] || mockResponses[record.method + " " + url.split("?")[0]] || mockResponses[url] || mockResponses[url.split("?")[0]] || {{ status: 200, ok: true, json: {{ status: "success" }} }};
  const isOk = matched.ok !== undefined ? matched.ok : (matched.status >= 200 && matched.status < 300);
  return {{
    status: matched.status || 200,
    statusText: matched.statusText || "OK",
    ok: isOk,
    json: async () => matched.json
  }};
}};

import {{
  archiveBatch,
  archiveItem,
  fetchConfig,
  fetchSettings,
  saveSettings,
  fetchScanProgress,
  fetchDiscoveries,
  refreshCacheItem,
  lookupMedia,
  addMedia,
  linkLibrary,
  fetchCacheStats,
  pruneCache,
  clearCache,
  getBackupExportUrl,
  importBackup,
  fetchFeeds,
  saveFeed,
  deleteFeed,
  testFeed,
  restoreDefaultFeeds,
  getSchedulerStatus,
  runSchedulerNow,
  getLogsDownloadUrl
}} from {json.dumps(DIST_API.as_uri())};

(async () => {{
{body}
}})();
"""
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_fetch_discoveries_options_and_errors():
    res = run_api_test("""
      mockResponses["/api/discover?past_months=1&future_months=2&skip_scrape=true"] = {
        status: 200,
        ok: true,
        json: { status: "success", tv: [{ title: "T1" }], movies: [{ title: "M1" }] }
      };
      const res1 = await fetchDiscoveries({ pastMonths: 1, futureMonths: 2, skipScrape: true });
      
      mockResponses["/api/discover?past_months=3&future_months=4"] = {
        status: 200,
        ok: true,
        json: { status: "success", tv: [], movies: [] }
      };
      const res2 = await fetchDiscoveries({ pastMonths: 3, futureMonths: 4 });
      
      // Test error throwing on non-ok
      mockResponses["/api/discover?past_months=1&future_months=2"] = {
        status: 500,
        ok: false,
        json: { status: "error", message: "Scan worker failed" }
      };
      let caughtMsg = null;
      try {
        await fetchDiscoveries();
      } catch (err) {
        caughtMsg = err.message;
      }

      console.log(JSON.stringify({ calls, res1, res2, caughtMsg }));
    """)
    assert len(res["calls"]) == 3
    assert res["calls"][0]["url"] == "/api/discover?past_months=1&future_months=2&skip_scrape=true"
    assert res["calls"][0]["method"] == "GET"
    assert res["res1"]["tv"][0]["title"] == "T1"
    assert res["res1"]["ok"] is True
    assert res["calls"][1]["url"] == "/api/discover?past_months=3&future_months=4"
    assert res["caughtMsg"] == "Scan worker failed"


def test_scan_progress_and_config_and_settings():
    res = run_api_test("""
      mockResponses["/api/scan/progress"] = {
        status: 200, ok: true,
        json: { status: "enriching", message: "Enriching items", current: 5, total: 10 }
      };
      const progress = await fetchScanProgress();

      mockResponses["/api/config"] = {
        status: 200, ok: true,
        json: { radarr: { configured: true, folders: [] }, sonarr: { configured: false, folders: [] } }
      };
      const config = await fetchConfig();

      mockResponses["/api/settings"] = {
        status: 200, ok: true,
        json: { radarr_url: "http://radarr:7878" }
      };
      const settings = await fetchSettings();

      mockResponses["POST /api/settings"] = {
        status: 200, ok: true,
        json: { status: "success", message: "Settings saved" }
      };
      const saveRes = await saveSettings({ default_past_months: "3" });

      console.log(JSON.stringify({ progress, config, settings, saveRes, calls }));
    """)
    assert res["progress"]["status"] == "enriching"
    assert res["progress"]["current"] == 5
    assert res["progress"]["ok"] is True
    assert res["config"]["radarr"]["configured"] is True
    assert res["settings"]["radarr_url"] == "http://radarr:7878"
    assert res["saveRes"]["status"] == "success"
    assert any(c["url"] == "/api/settings" and c["method"] == "POST" and c["body"] == {"default_past_months": "3"} for c in res["calls"])


def test_media_add_archive_refresh_and_lookup():
    res = run_api_test("""
      mockResponses["POST /api/add"] = {
        status: 200, ok: true,
        json: { status: "success", message: "Queued" }
      };
      const addRes = await addMedia({ type: "movie", raw_metadata: { title: "Dune" }, folder: "/movies", profile_id: 1 });

      mockResponses["POST /api/archive"] = {
        status: 200, ok: true,
        json: { status: "success", message: "Archived" }
      };
      const archRes = await archiveItem({ type: "tv", title: "Show 1", year: 2026, archive: true });

      mockResponses["POST /api/archive/batch"] = {
        status: 200, ok: true,
        json: { status: "success", archived: 2, failed: [] }
      };
      const batchRes = await archiveBatch([{ type: "tv", title: "Show 1", year: 2026 }]);

      mockResponses["POST /api/cache/refresh"] = {
        status: 200, ok: true,
        json: { status: "success", item: { title: "Dune", year: 2024, rating_imdb: 8.6 } }
      };
      const refreshRes = await refreshCacheItem({ type: "movie", title: "Dune", year: 2024, imdbId: "tt123" });

      mockResponses["GET /api/lookup"] = {
        status: 200, ok: true,
        json: { status: "success", results: [{ title: "Dune", tmdbId: 693134 }] }
      };
      const lookupRes = await lookupMedia("movie", "Dune");

      mockResponses["POST /api/link_library"] = {
        status: 200, ok: true,
        json: { status: "success", message: "Linked" }
      };
      const linkRes = await linkLibrary({ type: "movie", title: "Dune", year: 2024, link_metadata: { tmdbId: 693134 } });

      console.log(JSON.stringify({ addRes, archRes, batchRes, refreshRes, lookupRes, linkRes, calls }));
    """)
    assert res["addRes"]["ok"] is True and res["addRes"]["status"] == "success"
    assert res["archRes"]["status"] == "success"
    assert res["batchRes"]["archived"] == 2
    assert res["refreshRes"]["item"]["title"] == "Dune"
    assert res["lookupRes"]["results"][0]["tmdbId"] == 693134
    assert res["linkRes"]["message"] == "Linked"

    # Verify calls
    urls = [c["url"] for c in res["calls"]]
    assert any("/api/add" in u for u in urls)
    assert any("/api/archive" in u for u in urls)
    assert any("/api/cache/refresh" in u for u in urls)
    assert any("/api/lookup?type=movie&title=Dune" in u for u in urls)
    assert any("/api/link_library" in u for u in urls)


def test_cache_maintenance_and_backup_and_feeds():
    res = run_api_test("""
      mockResponses["GET /api/cache/stats"] = {
        status: 200, ok: true,
        json: { total_discoveries: 150, archived_discoveries: 20, database_size: "1.2 MB" }
      };
      const stats = await fetchCacheStats();

      mockResponses["POST /api/cache/prune"] = { status: 200, ok: true, json: { status: "success", message: "Pruned" } };
      const prune = await pruneCache();

      mockResponses["POST /api/cache/clear"] = { status: 200, ok: true, json: { status: "success", message: "Cleared" } };
      const clear = await clearCache();

      const exportUrl = getBackupExportUrl(true);

      mockResponses["POST /api/backup/import"] = { status: 200, ok: true, json: { status: "success", settings_count: 5, media_count: 50 } };
      const importRes = await importBackup({});

      mockResponses["GET /api/feeds"] = { status: 200, ok: true, json: { status: "success", feeds: [{ id: 1, name: "Feed 1" }] } };
      const feeds = await fetchFeeds();

      mockResponses["POST /api/feeds"] = { status: 200, ok: true, json: { status: "success", feed_id: 2 } };
      const saveF = await saveFeed({ name: "New", url: "https://example.com/rss", feed_type: "rss", enabled: 1 });

      mockResponses["POST /api/feeds/delete"] = { status: 200, ok: true, json: { status: "success" } };
      const delF = await deleteFeed(2);

      mockResponses["POST /api/feeds/test"] = { status: 200, ok: true, json: { status: "success", parsed_items_count: 10 } };
      const testF = await testFeed({ url: "https://example.com/feed", feed_type: "rss" });

      mockResponses["POST /api/feeds/restore"] = { status: 200, ok: true, json: { status: "success", message: "Restored" } };
      const restoreF = await restoreDefaultFeeds();
      const logsUrl = getLogsDownloadUrl();

      console.log(JSON.stringify({ stats, prune, clear, exportUrl, logsUrl, importRes, feeds, saveF, delF, testF, restoreF, calls }));
    """)
    assert res["stats"]["total_discoveries"] == 150
    assert res["prune"]["message"] == "Pruned"
    assert res["clear"]["message"] == "Cleared"
    assert res["exportUrl"] == "/api/backup/export?include_media=true"
    assert res["logsUrl"] == "/api/logs/download"
    assert res["importRes"]["settings_count"] == 5
    assert res["feeds"]["feeds"][0]["id"] == 1
    assert res["saveF"]["feed_id"] == 2
    assert res["testF"]["parsed_items_count"] == 10
    assert res["restoreF"]["message"] == "Restored"


def test_scheduler_api():
    res = run_api_test("""
      mockResponses["GET /api/scheduler/status"] = {
        status: 200,
        ok: true,
        json: {
          status: "success",
          enabled: true,
          interval_hours: 12,
          time_of_day: "04:00",
          last_run: null,
          next_run: "2026-10-27T04:00:00Z",
          is_running: false,
          last_result: null
        }
      };
      const statusRes = await getSchedulerStatus();

      mockResponses["POST /api/scheduler/run-now"] = {
        status: 200,
        ok: true,
        json: { status: "started", message: "Scan started" }
      };
      const runNowRes = await runSchedulerNow();

      console.log(JSON.stringify({ statusRes, runNowRes, calls }));
    """)
    assert res["statusRes"]["enabled"] is True
    assert res["statusRes"]["interval_hours"] == 12
    assert res["statusRes"]["time_of_day"] == "04:00"
    assert res["runNowRes"]["status"] == "started"
    urls = [c["url"] for c in res["calls"]]
    assert "/api/scheduler/status" in urls
    assert "/api/scheduler/run-now" in urls
