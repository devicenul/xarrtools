"""Tests for compiled state.js module under Node.js.

Verifies the state container and mutation helpers:
- initial state properties
- resetFilters
- setDiscoveries
- setConfig, setSettings
- setSelectedForAdd
- setMarkInLibraryMode
- setActiveTab
- setCustomFeeds
- resetState
"""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

DIST_STATE = Path(__file__).resolve().parent.parent / "web" / "static" / "dist" / "state.js"


def run_node_state(body: str):
    if not DIST_STATE.is_file():
        pytest.skip("web/static/dist/state.js not found; run 'npm run build' first")
    code = f"""
import {{
  state,
  createInitialState,
  resetFilters,
  setDiscoveries,
  setConfig,
  setSettings,
  setSelectedForAdd,
  setMarkInLibraryMode,
  setActiveTab,
  setCustomFeeds,
  resetState
}} from {json.dumps(DIST_STATE.as_uri())};

(async () => {{
{body}
}})().catch(err => {{
    console.error(err);
    process.exit(1);
}});
"""
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"Node error: {out.stderr}\nStdout: {out.stdout}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_state_initial_defaults():
    res = run_node_state("""
      resetState();
      console.log(JSON.stringify({
        hasConfig: state.appConfig !== null,
        hasSettings: state.appSettings !== null,
        tvLength: state.currentDiscoveries.tv.length,
        moviesLength: state.currentDiscoveries.movies.length,
        selectedItem: state.selectedItemForAdd,
        genresSize: state.selectedGenres.size,
        networksSize: state.selectedNetworks.size,
        countriesSize: state.selectedCountries.size,
        languagesSize: state.selectedLanguages.size,
        isMarkInLibrary: state.isMarkInLibraryMode,
        activeTab: state.activeTab,
        feedsLength: state.customFeedsList.length
      }));
    """)
    assert res["hasConfig"] is False
    assert res["hasSettings"] is False
    assert res["tvLength"] == 0
    assert res["moviesLength"] == 0
    assert res["selectedItem"] is None
    assert res["genresSize"] == 0
    assert res["networksSize"] == 0
    assert res["countriesSize"] == 0
    assert res["languagesSize"] == 0
    assert res["isMarkInLibrary"] is False
    assert res["activeTab"] == "all"
    assert res["feedsLength"] == 0


def test_set_discoveries_helper():
    res = run_node_state("""
      resetState();
      setDiscoveries({
        tv: [{ title: "TV Show 1", year: 2026 }],
        movies: [{ title: "Movie 1", year: 2025 }, { title: "Movie 2", year: 2024 }]
      });
      const counts1 = { tv: state.currentDiscoveries.tv.length, movies: state.currentDiscoveries.movies.length };
      setDiscoveries({});
      const counts2 = { tv: state.currentDiscoveries.tv.length, movies: state.currentDiscoveries.movies.length };
      console.log(JSON.stringify({ counts1, counts2 }));
    """)
    assert res["counts1"] == {"tv": 1, "movies": 2}
    assert res["counts2"] == {"tv": 0, "movies": 0}


def test_reset_filters_helper():
    res = run_node_state("""
      resetState();
      state.selectedGenres.add("Action");
      state.selectedGenres.add("Comedy");
      state.selectedNetworks.add("HBO");
      state.selectedCountries.add("US");
      state.selectedLanguages.add("English");
      const before = {
        genres: state.selectedGenres.size,
        networks: state.selectedNetworks.size,
        countries: state.selectedCountries.size,
        languages: state.selectedLanguages.size
      };
      resetFilters();
      const after = {
        genres: state.selectedGenres.size,
        networks: state.selectedNetworks.size,
        countries: state.selectedCountries.size,
        languages: state.selectedLanguages.size
      };
      console.log(JSON.stringify({ before, after }));
    """)
    assert res["before"] == {"genres": 2, "networks": 1, "countries": 1, "languages": 1}
    assert res["after"] == {"genres": 0, "networks": 0, "countries": 0, "languages": 0}


def test_set_config_and_settings_helpers():
    res = run_node_state("""
      resetState();
      setConfig({ radarr: { configured: true, folders: [], profiles: [] }, sonarr: { configured: false, folders: [], profiles: [] } });
      setSettings({ radarr_url: "http://localhost:7878" });
      console.log(JSON.stringify({
        radarrConfigured: state.appConfig?.radarr?.configured,
        radarrUrl: state.appSettings?.radarr_url
      }));
    """)
    assert res["radarrConfigured"] is True
    assert res["radarrUrl"] == "http://localhost:7878"


def test_set_selected_for_add_helper():
    res = run_node_state("""
      resetState();
      setSelectedForAdd({ type: "movie", item: { title: "Inception", year: 2010 } });
      const addedTitle = state.selectedItemForAdd?.item?.title;
      setSelectedForAdd(null);
      const cleared = state.selectedItemForAdd === null;
      console.log(JSON.stringify({ addedTitle, cleared }));
    """)
    assert res["addedTitle"] == "Inception"
    assert res["cleared"] is True


def test_set_mark_in_library_mode_and_active_tab():
    res = run_node_state("""
      resetState();
      setMarkInLibraryMode(true);
      setActiveTab("movies");
      console.log(JSON.stringify({
        isMark: state.isMarkInLibraryMode,
        tab: state.activeTab
      }));
    """)
    assert res["isMark"] is True
    assert res["tab"] == "movies"


def test_set_custom_feeds_and_reset_state():
    res = run_node_state("""
      resetState();
      setCustomFeeds([{ id: 1, name: "Feed 1", url: "http://example.com/rss", feed_type: "rss", enabled: 1 }]);
      const feedsCount = state.customFeedsList.length;
      resetState();
      console.log(JSON.stringify({
        feedsCount,
        afterResetFeedsCount: state.customFeedsList.length
      }));
    """)
    assert res["feedsCount"] == 1
    assert res["afterResetFeedsCount"] == 0
