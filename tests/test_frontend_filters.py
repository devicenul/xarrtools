"""Behavioural tests for the sidebar filter JS (invert, archive-all-filtered, country/language).

Runs against compiled frontend dist modules in Node against a tiny DOM stub.
Skipped when Node or dist assets are not available.
"""
from pathlib import Path
import json
import shutil
import subprocess
import pytest

from tests.frontend_harness import (
    check_node_and_dist,
    DIST_FILTERS,
    DIST_CARDS,
    DIST_RENDER,
    DIST_STATE,
    INDEX_HTML
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def run_js(body):
    check_node_and_dist()
    code = f"""
let renders = 0;
const notes = [];
const boxes = {{}};
const buttons = {{}};
let confirmAnswer = true;
const fetchCalls = [];
let fetchResponse = {{ archived: 0, failed: [] }};

function createMockEl(tag = "div") {{
  return {{
    tagName: tag.toUpperCase(),
    className: "",
    _innerHTML: "",
    value: "",
    checked: false,
    textContent: "",
    disabled: false,
    style: {{}},
    classList: {{
      add() {{}},
      remove() {{}},
      toggle(cls, on) {{
        if (on !== undefined) {{
          if (on) this.add(cls);
          else this.remove(cls);
        }}
      }},
      contains() {{ return false; }}
    }},
    childNodes: [],
    children: [],
    get innerHTML() {{ return this._innerHTML; }},
    set innerHTML(v) {{ this._innerHTML = String(v); }},
    appendChild(c) {{ this.children.push(c); return c; }},
    insertBefore(c) {{ this.childNodes.unshift(c); return c; }},
    removeChild(c) {{ return c; }},
    addEventListener() {{}},
    querySelector() {{ return createMockEl(); }},
    querySelectorAll() {{ return []; }},
    getAttribute() {{ return null; }},
    setAttribute() {{}},
    removeAttribute() {{}}
  }};
}}

const elements = {{
  "grid-tv": {{
    appendChild: () => {{}},
    set innerHTML(v) {{ if (v === "") renders++; }},
    children: []
  }},
  "grid-movies": {{ appendChild: () => {{}}, set innerHTML(v) {{}}, children: [] }},
  "notifications-list": {{
    insertBefore(item) {{
      const type = item.className.replace("notification-item ", "").trim();
      const m = item.innerHTML.match(/<div>(.*?)<\\/div>/);
      notes.push([type, m ? m[1] : item.innerHTML]);
    }},
    querySelector: () => null,
    childNodes: []
  }}
}};

globalThis.window = {{
  confirm: () => confirmAnswer
}};
globalThis.confirm = () => confirmAnswer;

globalThis.document = {{
  getElementById(id) {{
    if (elements[id]) return elements[id];
    if (id.startsWith("btn-")) {{
      return buttons[id] = buttons[id] || {{
        textContent: "",
        classList: {{
          toggle(c, on) {{ buttons[id].active = on; }},
          remove() {{ buttons[id].active = false; }},
          add() {{}}
        }}
      }};
    }}
    return createMockEl();
  }},
  querySelector(sel) {{
    const el = createMockEl();
    el.getAttribute = () => "all";
    return el;
  }},
  querySelectorAll(sel) {{
    const m = sel.match(/#options-(\\w+)-filter/);
    if (m) return boxes[m[1]] || [];
    return [];
  }},
  createElement(tag) {{
    return createMockEl(tag);
  }}
}};

globalThis.fetch = async (url, opts) => {{
  fetchCalls.push([url, JSON.parse(opts.body)]);
  return {{ ok: true, json: async () => fetchResponse }};
}};

(async () => {{
  const [_distRender, _distCards, _distFilters, _distState] = await Promise.all([
    import({json.dumps(DIST_RENDER.as_uri())}),
    import({json.dumps(DIST_CARDS.as_uri())}),
    import({json.dumps(DIST_FILTERS.as_uri())}),
    import({json.dumps(DIST_STATE.as_uri())})
  ]);

  const invertMultiselect = _distRender.invertMultiselect;
  const archiveAllFiltered = _distRender.archiveAllFiltered;
  const getFilterState = _distRender.getFilterState;
  const escapeHtml = _distCards.escapeHtml;
  const countryName = _distCards.countryName;
  const localeBadge = _distCards.localeBadge;
  const matchLocale = _distFilters.matchLocale;
  const matchFilter = _distFilters.matchFilter;
  const itemPassesFilters = _distFilters.itemPassesFilters;
  const getFilteredUnarchived = _distFilters.getFilteredUnarchived;
  const currentDiscoveries = _distState.state.currentDiscoveries;
  let selectedGenres = _distState.state.selectedGenres;
  let selectedNetworks = _distState.state.selectedNetworks;
  let selectedCountries = _distState.state.selectedCountries;
  let selectedLanguages = _distState.state.selectedLanguages;

  function updateGenreFilterBtnText() {{
    buttons["btn-genres-filter"] = {{ textContent: `Genres (${{selectedGenres.size}})` }};
  }}
  function updateNetworkFilterBtnText() {{}}

  await (async () => {{
{body}
  }})();
}})().catch(err => {{
  console.error(err);
  process.exit(1);
}});
"""
    out = subprocess.run(["node", "--no-warnings", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def run_module_js(body):
    check_node_and_dist()
    code = f"""
import {{ matchLocale, matchFilter, itemPassesFilters, getFilteredUnarchived }} from {json.dumps(DIST_FILTERS.as_uri())};
(async () => {{
{body}
}})();
"""
    out = subprocess.run(["node", "--no-warnings", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
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
    res = run_module_js("""
      const items = [{title: "A", country: "US", language: "English"}, {title: "B", country: "KR", language: "Korean"},
                     {title: "C", country: "", language: "Korean"}, {title: "D", country: "JP", language: "Japanese"}];
      let selectedCountries = new Set(), selectedLanguages = new Set();
      const names = () => items.filter(i => matchLocale(i, selectedCountries, selectedLanguages)).map(i => i.title).join("");
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
    res = run_module_js("""
      const currentDiscoveries = {
        tv: [
          {title: "TV1", year: 1, country: "US", is_archived: false, is_returning: false},
          {title: "TV2", year: 1, country: "KR", is_archived: false},
          {title: "TVarch", year: 1, country: "US", is_archived: true},
          {title: "TVret", year: 1, country: "US", is_archived: false, is_returning: true},
          {title: "TVlib", year: 1, country: "US", is_archived: false, is_in_library: true}
        ],
        movies: [
          {title: "M1", year: 1, country: "US", is_archived: false},
          {title: "M2", year: 1, country: "KR", is_archived: false}
        ]
      };
      let selectedCountries = new Set();
      let activeTabName = "all";
      let searchTerm = "";
      const getState = () => ({
        showReturning: false, showLibrary: false, showArchived: false,
        searchTerm, countries: selectedCountries,
        genres: new Set(), networks: new Set(), languages: new Set()
      });
      const names = () => getFilteredUnarchived(currentDiscoveries, activeTabName, getState()).map(t => t.type + ":" + t.item.title);
      const out = {all: names()};
      selectedCountries = new Set(["US"]); out.us = names();
      activeTabName = "movies"; out.moviesTab = names();
      activeTabName = "tv"; searchTerm = "tv1"; out.search = names();
      console.log(JSON.stringify(out));
    """)
    assert res["all"] == ["tv:TV1", "tv:TV2", "movie:M1", "movie:M2"]   # archived/returning/library hidden
    assert res["us"] == ["tv:TV1", "movie:M1"]
    assert res["moviesTab"] == ["movie:M1"]
    assert res["search"] == ["tv:TV1"]   # search narrows the TV tab (US filter still applies)


def test_item_passes_filters_compiled_module():
    res = run_module_js("""
      const itemTv = {title: "Show", year: 2026, country: "US", language: "English", is_archived: false, is_returning: true, is_in_library: false};
      const itemLib = {title: "InLib", year: 2026, is_archived: false, is_returning: false, is_in_library: true};
      const itemArch = {title: "Arch", year: 2026, is_archived: true, is_returning: false, is_in_library: false};
      const out = {
        retHidden: itemPassesFilters(itemTv, "tv", {showReturning: false}),
        retShown: itemPassesFilters(itemTv, "tv", {showReturning: true}),
        libHidden: itemPassesFilters(itemLib, "tv", {showLibrary: false}),
        libShown: itemPassesFilters(itemLib, "tv", {showLibrary: true}),
        archHidden: itemPassesFilters(itemArch, "tv", {showArchived: false}),
        archShown: itemPassesFilters(itemArch, "tv", {showArchived: true}),
      };
      console.log(JSON.stringify(out));
    """)
    assert res == {
        "retHidden": False, "retShown": True,
        "libHidden": False, "libShown": True,
        "archHidden": False, "archShown": True
    }


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
