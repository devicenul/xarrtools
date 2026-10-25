"""Behavioural tests for the sidebar filter JS (invert, archive-all-filtered, country/language).

app.js touches the DOM at load time, so the functions under test are sliced out of the source and run
in Node against a tiny DOM stub. Skipped when Node is not installed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = (Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

FUNCTIONS = ["matchLocale", "matchFilter", "itemPassesFilters", "getFilteredUnarchived",
             "archiveAllFiltered", "invertMultiselect", "escapeHtml", "countryName", "localeBadge"]


def _slice_function(name):
    start = APP_JS.index(f"function {name}(")
    if APP_JS[max(0, start - 6):start] == "async ":
        start -= 6
    async_prefix = "async " if APP_JS[start:start + 6] == "async " else ""
    i = APP_JS.index("{", APP_JS.index(")", start))
    depth = 0
    for j in range(i, len(APP_JS)):
        depth += {"{": 1, "}": -1}.get(APP_JS[j], 0)
        if depth == 0:
            return APP_JS[start:j + 1]
    raise AssertionError(name)


PRELUDE = r"""
const checks = {"check-show-returning": false, "check-show-library": false, "check-show-archived": false};
const searchBar = {value: ""};
let selectedGenres = new Set(), selectedNetworks = new Set(), selectedCountries = new Set(), selectedLanguages = new Set();
let currentDiscoveries = {tv: [], movies: []};
let activeTabName = "all";
const notes = []; let renders = 0; let confirmAnswer = true; let fetchCalls = []; let fetchResponse = {archived: 0, failed: []};
const boxes = {};   // option container key -> [{value, checked}]
const buttons = {}; // btn id -> {textContent, active}
const document = {
  getElementById(id) {
    if (id in checks) return {checked: checks[id]};
    if (id.startsWith("btn-")) { return buttons[id] = buttons[id] || {textContent: "", classList: {toggle(c, on){ buttons[id].active = on; }, remove(){ buttons[id].active = false; }, add(){}}}; }
    return null;
  },
  querySelector(sel) { return {getAttribute: () => activeTabName}; },
  querySelectorAll(sel) { const key = sel.match(/#options-(\w+)-filter/)[1]; return boxes[key] || []; },
};
function addNotification(m, t) { notes.push([t, m]); }
function renderMediaLists() { renders++; }
function confirm() { return confirmAnswer; }
function updateGenreFilterBtnText() { buttons["btn-genres-filter"] = {textContent: `Genres (${selectedGenres.size})`}; }
function updateNetworkFilterBtnText() {}
async function fetch(url, opts) { fetchCalls.push([url, JSON.parse(opts.body)]); return {ok: true, json: async () => fetchResponse}; }
"""


def run_js(body):
    code = PRELUDE + "\n" + "\n".join(_slice_function(n) for n in FUNCTIONS) + "\n(async () => {\n" + body + "\n})();"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_html_has_invert_buttons_and_archive_button_styled_like_scan():
    for key in ("genres", "networks", "country", "language"):
        assert f'id="invert-{key}-filter"' in INDEX_HTML
        assert f'id="clear-{key}-filter"' in INDEX_HTML
        assert f'id="options-{key}-filter"' in INDEX_HTML
    assert 'id="btn-scan" class="btn btn-primary"' in INDEX_HTML
    assert 'id="btn-archive-filtered" class="btn btn-primary"' in INDEX_HTML
    assert "select-country" not in INDEX_HTML  # replaced by multi-selects


def test_invert_flips_checkboxes_updates_set_button_and_rerenders():
    res = run_js("""
      boxes.country = [{value: "US", checked: true}, {value: "KR", checked: false}, {value: "JP", checked: false}];
      selectedCountries = new Set(["US"]);
      invertMultiselect("country", selectedCountries, null);
      const first = {sel: [...selectedCountries].sort(), checked: boxes.country.map(b => b.checked), text: buttons["btn-country-filter"].textContent, renders};
      invertMultiselect("country", selectedCountries, null);   // inverting twice restores
      const second = [...selectedCountries];
      boxes.country.forEach(b => b.checked = true);
      invertMultiselect("country", selectedCountries, null);   // all selected -> none selected
      console.log(JSON.stringify({first, second, none: selectedCountries.size, noneText: buttons["btn-country-filter"].textContent}));
    """)
    assert res["first"]["sel"] == ["JP", "KR"] and res["first"]["checked"] == [False, True, True]
    assert res["first"]["text"] == "Country (2)" and res["first"]["renders"] == 1
    assert res["second"] == ["US"]
    assert res["none"] == 0 and res["noneText"] == "Country (All)"


def test_invert_uses_custom_updater_for_genres():
    res = run_js("""
      boxes.genres = [{value: "Drama", checked: false}, {value: "Comedy", checked: true}];
      selectedGenres = new Set(["Comedy"]);
      invertMultiselect("genres", selectedGenres, updateGenreFilterBtnText);
      console.log(JSON.stringify({sel: [...selectedGenres], text: buttons["btn-genres-filter"].textContent}));
    """)
    assert res == {"sel": ["Drama"], "text": "Genres (1)"}


def test_locale_filters_are_multi_select_and_combine():
    res = run_js("""
      const items = [{title: "A", country: "US", language: "English"}, {title: "B", country: "KR", language: "Korean"},
                     {title: "C", country: "", language: "Korean"}, {title: "D", country: "JP", language: "Japanese"}];
      const names = () => items.filter(i => matchLocale(i)).map(i => i.title).join("");
      const out = {none: names()};
      selectedCountries = new Set(["US", "KR"]); out.countries = names();
      selectedLanguages = new Set(["Korean"]); out.both = names();
      selectedCountries.clear(); out.langOnly = names();
      console.log(JSON.stringify(out));
    """)
    assert res == {"none": "ABCD", "countries": "AB", "both": "B", "langOnly": "BC"}


def test_locale_badge_escapes_and_handles_empty():
    res = run_js("""
      console.log(JSON.stringify({e: localeBadge({}), b: localeBadge({country: "US", language: "<b>x</b>"})}));
    """)
    assert res["e"] == ""
    assert "US" in res["b"] and "&lt;b&gt;" in res["b"] and "<b>x" not in res["b"]


def test_filtered_unarchived_respects_filters_and_tab():
    res = run_js("""
      currentDiscoveries.tv = [
        {title: "TV1", year: 1, country: "US", is_archived: false, is_returning: false},
        {title: "TV2", year: 1, country: "KR", is_archived: false},
        {title: "TVarch", year: 1, country: "US", is_archived: true},
        {title: "TVret", year: 1, country: "US", is_archived: false, is_returning: true},
        {title: "TVlib", year: 1, country: "US", is_archived: false, is_in_library: true}];
      currentDiscoveries.movies = [
        {title: "M1", year: 1, country: "US", is_archived: false}, {title: "M2", year: 1, country: "KR", is_archived: false}];
      const names = () => getFilteredUnarchived().map(t => t.type + ":" + t.item.title);
      const out = {all: names()};
      selectedCountries = new Set(["US"]); out.us = names();
      activeTabName = "movies"; out.moviesTab = names();
      activeTabName = "tv"; searchBar.value = "tv1"; out.search = names();
      console.log(JSON.stringify(out));
    """)
    assert res["all"] == ["tv:TV1", "tv:TV2", "movie:M1", "movie:M2"]   # archived/returning/library hidden
    assert res["us"] == ["tv:TV1", "movie:M1"]
    assert res["moviesTab"] == ["movie:M1"]
    assert res["search"] == ["tv:TV1"]   # search narrows the TV tab (US filter still applies)


def test_archive_all_filtered_posts_batch_and_updates_items():
    res = run_js("""
      currentDiscoveries.tv = [{title: "T1", year: 2026, is_archived: false, has_new_metadata: true}];
      currentDiscoveries.movies = [{title: "M1", year: 2025, is_archived: false}, {title: "M2", year: 2025, is_archived: false}];
      fetchResponse = {archived: 2, failed: [{title: "M2", message: "boom"}]};
      await archiveAllFiltered();
      const [url, body] = fetchCalls[0];
      console.log(JSON.stringify({url, archive: body.archive, items: body.items.map(i => [i.type, i.title, i.year]),
        raw: body.items[0].raw_item.title,
        state: [currentDiscoveries.tv[0].is_archived, currentDiscoveries.tv[0].has_new_metadata,
                currentDiscoveries.movies[0].is_archived, currentDiscoveries.movies[1].is_archived],
        notes, renders}));
    """)
    assert res["url"] == "/api/archive/batch" and res["archive"] is True
    assert res["items"] == [["tv", "T1", 2026], ["movie", "M1", 2025], ["movie", "M2", 2025]]
    assert res["state"] == [True, False, True, False]     # failed item stays un-archived
    assert res["notes"][0][0] == "error" and res["renders"] == 1


def test_archive_all_filtered_noop_when_nothing_matches_or_not_confirmed():
    res = run_js("""
      await archiveAllFiltered();                         // nothing to archive
      const empty = {calls: fetchCalls.length, notes: notes.slice()};
      currentDiscoveries.movies = [{title: "M1", year: 1, is_archived: false}];
      confirmAnswer = false;
      await archiveAllFiltered();                         // user cancels
      console.log(JSON.stringify({empty, calls: fetchCalls.length, state: currentDiscoveries.movies[0].is_archived}));
    """)
    assert res["empty"]["calls"] == 0 and "No un-archived" in res["empty"]["notes"][0][1]
    assert res["calls"] == 0 and res["state"] is False
