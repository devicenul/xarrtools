"""
Empirical and Adversarial Test Suite for Milestone 3: Client State & DOM Badging
================================================================================
Stress-tests `web/templates/app.js`, `web/templates/style.css`, and `web/templates/index.html`:
1. Card badging under all permutations of `has_new_metadata` (true, false, undefined, 1, 0, null, "", "true", NaN).
2. Card badging coexistence alongside returning seasons, in-library items, ratings, and archived items (TV & Movies).
3. Immediate reset of `item.has_new_metadata` to false upon manual or automatic archive toggle.
4. Refresh metadata updating client state in-place, preserving unreturned scraper fields, and triggering DOM re-render with new badge.
5. Filter interactions (`check-show-archived`, `check-show-returning`, `check-show-library`, search) with badged cards.
6. CSS selector conformance for both dark mode and light theme.
7. Adversarial edge cases: concurrent refresh clicks, HTML injection/escaping, successive toggles, search filtering.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
import pytest

APP_JS_PATH = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"
STYLE_CSS_PATH = Path(__file__).resolve().parent.parent / "web" / "templates" / "style.css"
INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html"


def run_node_harness(script_code: str) -> dict:
    """Executes a JavaScript test snippet in Node.js within the app.js closure scope."""
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js is not installed in the environment.")

    wrapped_script = f"""
    const fs = require('fs');
    const appJsCode = fs.readFileSync({json.dumps(str(APP_JS_PATH))}, 'utf8');

    class MockClassList {{
        constructor() {{ this.classes = new Set(); }}
        add(...cls) {{ cls.forEach(c => this.classes.add(c)); }}
        remove(...cls) {{ cls.forEach(c => this.classes.delete(c)); }}
        contains(cls) {{ return this.classes.has(cls); }}
        toggle(cls) {{ 
            if (this.contains(cls)) {{ this.remove(cls); return false; }} 
            else {{ this.add(cls); return true; }} 
        }}
    }}

    class MockElement {{
        constructor(tagName = 'div') {{
            this.tagName = tagName.toUpperCase();
            this.classList = new MockClassList();
            this.children = [];
            this.childNodes = [];
            this._innerHTML = '';
            this.value = '';
            this.checked = false;
            this.textContent = '';
            this.disabled = false;
            this.style = {{}};
            this.attributes = {{}};
            this.listeners = {{}};
            this.parentElement = null;
        }}
        get innerHTML() {{ return this._innerHTML; }}
        set innerHTML(val) {{
            this._innerHTML = String(val);
            this.children = [];
            this.childNodes = [];
        }}
        appendChild(el) {{
            el.parentElement = this;
            this.children.push(el);
            this.childNodes.push(el);
            return el;
        }}
        insertBefore(el, before) {{
            el.parentElement = this;
            const idx = this.childNodes.indexOf(before);
            if (idx === -1) {{
                this.childNodes.unshift(el);
                this.children.unshift(el);
            }} else {{
                this.childNodes.splice(idx, 0, el);
                this.children.splice(idx, 0, el);
            }}
            return el;
        }}
        removeChild(el) {{
            const idx = this.childNodes.indexOf(el);
            if (idx !== -1) this.childNodes.splice(idx, 1);
            const cidx = this.children.indexOf(el);
            if (cidx !== -1) this.children.splice(cidx, 1);
            el.parentElement = null;
            return el;
        }}
        remove() {{
            if (this.parentElement) {{
                this.parentElement.removeChild(this);
            }}
        }}
        getAttribute(attr) {{
            if (attr === 'data-tab') return this.attributes[attr] || 'tab-all';
            return this.attributes[attr] !== undefined ? this.attributes[attr] : null;
        }}
        setAttribute(attr, val) {{
            this.attributes[attr] = String(val);
        }}
        removeAttribute(attr) {{
            delete this.attributes[attr];
        }}
        addEventListener(event, fn) {{
            if (!this.listeners[event]) this.listeners[event] = [];
            this.listeners[event].push(fn);
        }}
        click() {{
            if (this.listeners['click']) {{
                this.listeners['click'].forEach(fn => fn({{ target: this }}));
            }}
        }}
        querySelector(selector) {{
            const mock = new MockElement('div');
            mock.parentElement = this;
            if (selector && selector.startsWith('.')) {{
                mock.classList.add(selector.slice(1));
            }}
            return mock;
        }}
        querySelectorAll(selector) {{
            return [];
        }}
    }}

    const elementsStore = {{}};
    function getOrCreateElement(id) {{
        if (!elementsStore[id]) {{
            const el = new MockElement('div');
            el.id = id;
            elementsStore[id] = el;
        }}
        return elementsStore[id];
    }}

    // Global mock environment
    global.fetchHistory = [];
    global.mockFetchHandler = null;

    const baseFetch = async function(resource, config) {{
        global.fetchHistory.push({{ resource, config }});
        if (global.mockFetchHandler) {{
            return global.mockFetchHandler(resource, config);
        }}
        return {{
            ok: true,
            status: 200,
            json: async () => ({{ status: 'success' }})
        }};
    }};

    global.window = {{}};
    global.window.fetch = baseFetch;
    global.fetch = baseFetch;

    global.document = {{
        addEventListener: () => {{}},
        createElement: (tag) => new MockElement(tag),
        getElementById: (id) => getOrCreateElement(id),
        querySelector: (sel) => {{
            if (sel && sel.startsWith('#')) return getOrCreateElement(sel.slice(1));
            const mock = new MockElement('div');
            if (sel && sel.includes('active')) {{
                mock.classList.add('active');
                mock.setAttribute('data-tab', 'tab-all');
            }}
            return mock;
        }},
        querySelectorAll: (sel) => []
    }};

    global.localStorage = {{
        store: {{}},
        getItem(k) {{ return this.store[k] || null; }},
        setItem(k, v) {{ this.store[k] = String(v); }},
        clear() {{ this.store = {{}}; }}
    }};

    // Combine appJsCode with runner inside same eval scope so let/const declarations are shared
    const combinedScript = appJsCode + "\\n;\\n(async () => {{\\n" + {json.dumps(script_code)} + "\\n}})();";

    eval(combinedScript);
    """

    res = subprocess.run(
        [node_bin, "-e", wrapped_script],
        capture_output=True,
        text=True,
        timeout=15
    )

    if res.returncode != 0:
        raise RuntimeError(f"Node execution failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")

    try:
        return json.loads(res.stdout.strip())
    except Exception as e:
        raise ValueError(f"Failed to parse JSON output from Node:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}\nError: {e}")


class TestCardBadgingPermutations:
    """Stress-tests createMediaCard across all permutations of has_new_metadata values."""

    def test_has_new_metadata_truthy_permutations(self):
        """Verifies that true, 1, and 'true' render the .badge-new-metadata element."""
        script = """
        const truthyValues = [true, 1, "true", 100];
        const results = [];

        for (const val of truthyValues) {
            const item = {
                title: "Test Show",
                year: 2026,
                network: "HBO",
                plot: "Some plot description.",
                cast: "Actor A, Actor B",
                genres: ["Drama"],
                is_in_library: false,
                is_archived: false,
                is_returning: false,
                has_new_metadata: val
            };

            const card = createMediaCard(item, "tv", 0);
            const html = card.innerHTML;
            const hasBadge = html.includes('class="badge badge-new-metadata"') && html.includes('New metadata');
            results.push({ val, hasBadge, htmlSnippet: html.substring(0, 300) });
        }

        console.log(JSON.stringify({ results }));
        """
        output = run_node_harness(script)
        for res in output["results"]:
            assert res["hasBadge"] is True, f"Failed for truthy value: {res['val']}"

    def test_has_new_metadata_falsy_permutations(self):
        """Verifies that false, 0, null, undefined, '', NaN, and omitted key do NOT render badge."""
        script = """
        const falsyCases = [
            { name: "false", val: false },
            { name: "0", val: 0 },
            { name: "null", val: null },
            { name: "undefined", val: undefined },
            { name: "empty_string", val: "" },
            { name: "NaN", val: NaN },
            { name: "omitted", val: "__OMIT__" }
        ];

        const results = [];

        for (const c of falsyCases) {
            const item = {
                title: "Test Show",
                year: 2026,
                network: "Netflix",
                plot: "Plot summary.",
                cast: "Actor C",
                genres: ["Comedy"],
                is_in_library: false,
                is_archived: false,
                is_returning: false
            };

            if (c.val !== "__OMIT__") {
                item.has_new_metadata = c.val;
            }

            const card = createMediaCard(item, "tv", 0);
            const html = card.innerHTML;
            const hasBadge = html.includes('badge-new-metadata') || html.includes('New metadata');
            results.push({ name: c.name, val: c.val, hasBadge });
        }

        console.log(JSON.stringify({ results }));
        """
        output = run_node_harness(script)
        for res in output["results"]:
            assert res["hasBadge"] is False, f"Falsy case '{res['name']}' incorrectly rendered badge!"


class TestCardBadgingCoexistence:
    """Stress-tests all 16 combinatorial states of (returning, in_library, is_archived, has_new_metadata)."""

    def test_all_16_tv_badge_combinations(self):
        """Tests all 16 permutations of TV badge states to ensure no collision or broken markup."""
        script = """
        const permutations = [];
        const flags = [false, true];

        for (const returning of flags) {
            for (const inLibrary of flags) {
                for (const archived of flags) {
                    for (const newMeta of flags) {
                        const item = {
                            title: `Show R${returning ? 1:0}L${inLibrary ? 1:0}A${archived ? 1:0}N${newMeta ? 1:0}`,
                            year: 2026,
                            network: "AMC",
                            plot: "Comprehensive plot for test item.",
                            cast: "Actor X, Actor Y",
                            genres: ["Sci-Fi", "Drama"],
                            is_returning: returning,
                            is_in_library: inLibrary,
                            is_archived: archived,
                            has_new_metadata: newMeta,
                            rating_imdb: "8.5",
                            rating_metacritic: "78",
                            rating_rt: "92"
                        };

                        const card = createMediaCard(item, "tv", 0);
                        const html = card.innerHTML;

                        const hasReturningBadge = html.includes('badge-network') && html.includes('Returning');
                        const hasInLibraryBadge = html.includes('badge-in-library') && html.includes('In Library');
                        const hasArchivedBadge = html.includes('badge-archived') && html.includes('Archived');
                        const hasNewMetadataBadge = html.includes('badge-new-metadata') && html.includes('New metadata');
                        const hasNetworkBadge = html.includes('badge-network') && html.includes('AMC');
                        const hasImdbBadge = html.includes('badge-rating-imdb') && html.includes('8.5');
                        const hasMcBadge = html.includes('badge-rating-mc') && html.includes('78');
                        const hasRtBadge = html.includes('badge-rating-rt') && html.includes('92%');

                        permutations.push({
                            returning,
                            inLibrary,
                            archived,
                            newMeta,
                            hasReturningBadge,
                            hasInLibraryBadge,
                            hasArchivedBadge,
                            hasNewMetadataBadge,
                            hasNetworkBadge,
                            hasImdbBadge,
                            hasMcBadge,
                            hasRtBadge
                        });
                    }
                }
            }
        }

        console.log(JSON.stringify({ permutations }));
        """
        output = run_node_harness(script)
        for p in output["permutations"]:
            ret = p["returning"]
            lib = p["inLibrary"]
            arc = p["archived"]
            meta = p["newMeta"]

            assert p["hasReturningBadge"] == ret, f"Returning mismatch for state R{ret}L{lib}A{arc}N{meta}"
            assert p["hasInLibraryBadge"] == lib, f"In-Library mismatch for state R{ret}L{lib}A{arc}N{meta}"
            assert p["hasArchivedBadge"] == arc, f"Archived mismatch for state R{ret}L{lib}A{arc}N{meta}"
            assert p["hasNewMetadataBadge"] == meta, f"New Metadata mismatch for state R{ret}L{lib}A{arc}N{meta}"
            assert p["hasNetworkBadge"] is True, "Network badge should always be present"
            assert p["hasImdbBadge"] is True, "IMDb rating badge missing"
            assert p["hasMcBadge"] is True, "Metacritic rating badge missing"
            assert p["hasRtBadge"] is True, "Rotten Tomatoes rating badge missing"

    def test_all_8_movie_badge_combinations(self):
        """Tests all 8 permutations of Movie badge states (movies do not render returning badge)."""
        script = """
        const permutations = [];
        const flags = [false, true];

        for (const inLibrary of flags) {
            for (const archived of flags) {
                for (const newMeta of flags) {
                    const item = {
                        title: `Movie L${inLibrary ? 1:0}A${archived ? 1:0}N${newMeta ? 1:0}`,
                        year: 2026,
                        network: "Universal Pictures",
                        plot: "A feature film synopsis.",
                        cast: "Movie Star",
                        genres: ["Action"],
                        is_in_library: inLibrary,
                        is_archived: archived,
                        has_new_metadata: newMeta
                    };

                    const card = createMediaCard(item, "movie", 0);
                    const html = card.innerHTML;

                    const hasReturningBadge = html.includes('Returning');
                    const hasInLibraryBadge = html.includes('badge-in-library');
                    const hasArchivedBadge = html.includes('badge-archived');
                    const hasNewMetadataBadge = html.includes('badge-new-metadata');

                    permutations.push({
                        inLibrary,
                        archived,
                        newMeta,
                        hasReturningBadge,
                        hasInLibraryBadge,
                        hasArchivedBadge,
                        hasNewMetadataBadge
                    });
                }
            }
        }

        console.log(JSON.stringify({ permutations }));
        """
        output = run_node_harness(script)
        for p in output["permutations"]:
            lib = p["inLibrary"]
            arc = p["archived"]
            meta = p["newMeta"]

            assert p["hasReturningBadge"] is False, "Movies should never render Returning badge"
            assert p["hasInLibraryBadge"] == lib, f"Movie In-Library mismatch for state L{lib}A{arc}N{meta}"
            assert p["hasArchivedBadge"] == arc, f"Movie Archived mismatch for state L{lib}A{arc}N{meta}"
            assert p["hasNewMetadataBadge"] == meta, f"Movie New Metadata mismatch for state L{lib}A{arc}N{meta}"


class TestArchiveToggleBehavior:
    """Stress-tests toggleArchive resetting has_new_metadata immediately on archive."""

    def test_toggle_archive_immediately_resets_has_new_metadata(self):
        """Archiving an item with has_new_metadata=true must set is_archived=true and has_new_metadata=false."""
        script = """
        const item = {
            title: "Archived Candidate",
            year: 2026,
            network: "FX",
            plot: "Sample plot.",
            cast: "Sample Cast",
            genres: ["Drama"],
            is_archived: false,
            has_new_metadata: true
        };

        currentDiscoveries.tv = [item];

        global.mockFetchHandler = async (url, config) => {
            if (url === '/api/archive') {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({ status: 'success', message: 'Item archived' })
                };
            }
            return { ok: false, status: 404 };
        };

        // Execute toggleArchive
        await toggleArchive("tv", item);

        // Verify state mutations
        console.log(JSON.stringify({
            is_archived: item.is_archived,
            has_new_metadata: item.has_new_metadata,
            fetchCalls: global.fetchHistory
        }));
        """
        output = run_node_harness(script)
        assert output["is_archived"] is True
        assert output["has_new_metadata"] is False
        assert len(output["fetchCalls"]) >= 1
        last_fetch = output["fetchCalls"][-1]
        assert last_fetch["resource"] == "/api/archive"
        payload = json.loads(last_fetch["config"]["body"])
        assert payload["archive"] is True
        assert payload["title"] == "Archived Candidate"

    def test_toggle_unarchive_preserves_badge_state(self):
        """Unarchiving an item toggles is_archived to false."""
        script = """
        const item = {
            title: "Unarchive Candidate",
            year: 2026,
            network: "BBC",
            plot: "Sample plot.",
            cast: "Sample Cast",
            genres: ["Mystery"],
            is_archived: true,
            has_new_metadata: false
        };

        currentDiscoveries.tv = [item];

        global.mockFetchHandler = async (url, config) => {
            if (url === '/api/archive') {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({ status: 'success', message: 'Item unarchived' })
                };
            }
            return { ok: false, status: 404 };
        };

        await toggleArchive("tv", item);

        console.log(JSON.stringify({
            is_archived: item.is_archived,
            has_new_metadata: item.has_new_metadata,
            fetchCalls: global.fetchHistory
        }));
        """
        output = run_node_harness(script)
        assert output["is_archived"] is False
        assert output["has_new_metadata"] is False
        last_fetch = output["fetchCalls"][-1]
        payload = json.loads(last_fetch["config"]["body"])
        assert payload["archive"] is False

    def test_toggle_archive_api_failure_does_not_mutate_state(self):
        """If server returns an error, item.is_archived and has_new_metadata must NOT mutate."""
        script = """
        const item = {
            title: "Failure Candidate",
            year: 2026,
            network: "Showtime",
            plot: "Sample plot.",
            cast: "Sample Cast",
            genres: ["Drama"],
            is_archived: false,
            has_new_metadata: true
        };

        currentDiscoveries.tv = [item];

        global.mockFetchHandler = async (url, config) => {
            return {
                ok: false,
                status: 500,
                json: async () => ({ status: 'error', message: 'Internal Server Error' })
            };
        };

        await toggleArchive("tv", item);

        console.log(JSON.stringify({
            is_archived: item.is_archived,
            has_new_metadata: item.has_new_metadata
        }));
        """
        output = run_node_harness(script)
        assert output["is_archived"] is False, "State should not mutate on API failure"
        assert output["has_new_metadata"] is True, "Badge flag should not mutate on API failure"

    def test_successive_archive_unarchive_cycles(self):
        """Item cycling through Archive -> Unarchive -> Archive maintains badge reset."""
        script = """
        const item = {
            title: "Multi Toggle Show",
            year: 2026,
            network: "HBO",
            plot: "Plot.",
            cast: "Cast",
            genres: ["Drama"],
            is_archived: false,
            has_new_metadata: true
        };

        currentDiscoveries.tv = [item];

        global.mockFetchHandler = async () => ({
            ok: true,
            status: 200,
            json: async () => ({ status: 'success' })
        });

        // 1. Archive
        await toggleArchive("tv", item);
        const s1 = { is_archived: item.is_archived, has_new_metadata: item.has_new_metadata };

        // 2. Unarchive
        await toggleArchive("tv", item);
        const s2 = { is_archived: item.is_archived, has_new_metadata: item.has_new_metadata };

        // 3. Re-archive
        await toggleArchive("tv", item);
        const s3 = { is_archived: item.is_archived, has_new_metadata: item.has_new_metadata };

        console.log(JSON.stringify({ s1, s2, s3 }));
        """
        output = run_node_harness(script)
        assert output["s1"] == {"is_archived": True, "has_new_metadata": False}
        assert output["s2"] == {"is_archived": False, "has_new_metadata": False}
        assert output["s3"] == {"is_archived": True, "has_new_metadata": False}


class TestRefreshMetadataClientState:
    """Stress-tests refreshMetadata updating discoveries and re-rendering with new badge."""

    def test_refresh_metadata_updates_state_and_adds_badge(self):
        """Refreshing a previously low-metadata item updates currentDiscoveries and sets has_new_metadata."""
        script = """
        const initialItem = {
            title: "Evolving Series",
            year: 2026,
            network: "Unknown",
            plot: "No plot summary available.",
            cast: "Cast details not available.",
            genres: ["Drama"],
            is_archived: true,
            has_new_metadata: false,
            date_str: "2026-10-01",
            is_returning: true
        };

        currentDiscoveries.tv = [initialItem];

        const refreshBtn = document.createElement("button");
        const card = document.createElement("div");

        global.mockFetchHandler = async (url, config) => {
            if (url === '/api/cache/refresh') {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({
                        status: 'success',
                        message: 'Refreshed metadata',
                        item: {
                            title: "Evolving Series",
                            year: 2026,
                            network: "Apple TV+",
                            plot: "A detailed compelling synopsis of the evolving series.",
                            cast: "Lead Star, Supporting Star",
                            genres: ["Drama", "Sci-Fi"],
                            is_archived: 0,
                            has_new_metadata: 1
                        }
                    })
                };
            }
            return { ok: false, status: 404 };
        };

        await refreshMetadata("tv", initialItem, refreshBtn, card);

        const updatedDiscovery = currentDiscoveries.tv[0];

        console.log(JSON.stringify({
            updatedDiscovery,
            btnLoading: refreshBtn.classList.contains("loading"),
            btnDisabled: refreshBtn.disabled
        }));
        """
        output = run_node_harness(script)
        item = output["updatedDiscovery"]
        assert item["network"] == "Apple TV+"
        assert item["is_archived"] == 0
        assert item["has_new_metadata"] == 1
        assert item["date_str"] == "2026-10-01", "Should preserve scraper date_str"
        assert item["is_returning"] is True, "Should preserve scraper is_returning"
        assert output["btnLoading"] is False
        assert output["btnDisabled"] is False

    def test_refresh_metadata_movie_flow(self):
        """Refreshing a movie updates currentDiscoveries.movies."""
        script = """
        const initialMovie = {
            title: "Future Sci-Fi Blockbuster",
            year: 2026,
            network: "Unknown Studio",
            plot: "No plot summary available.",
            cast: "Unknown",
            genres: [],
            is_archived: true,
            has_new_metadata: false,
            imdbId: "tt9988776"
        };

        currentDiscoveries.movies = [initialMovie];

        const refreshBtn = document.createElement("button");
        const card = document.createElement("div");

        global.mockFetchHandler = async (url, config) => {
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    status: 'success',
                    item: {
                        title: "Future Sci-Fi Blockbuster",
                        year: 2026,
                        network: "Paramount",
                        plot: "Epic galactic journey.",
                        cast: "Sci-Fi Star",
                        genres: ["Sci-Fi"],
                        is_archived: 0,
                        has_new_metadata: 1,
                        imdbId: "tt9988776"
                    }
                })
            };
        };

        await refreshMetadata("movie", initialMovie, refreshBtn, card);

        console.log(JSON.stringify({
            updatedMovie: currentDiscoveries.movies[0]
        }));
        """
        output = run_node_harness(script)
        movie = output["updatedMovie"]
        assert movie["network"] == "Paramount"
        assert movie["is_archived"] == 0
        assert movie["has_new_metadata"] == 1

    def test_refresh_metadata_concurrent_guard(self):
        """Clicking refresh button when it is already in loading state does not trigger extra fetches."""
        script = """
        const item = {
            title: "Concurrent Guard Show",
            year: 2026,
            network: "Netflix",
            plot: "Plot.",
            cast: "Cast",
            genres: ["Drama"],
            is_archived: false,
            has_new_metadata: false
        };

        currentDiscoveries.tv = [item];

        const refreshBtn = document.createElement("button");
        refreshBtn.classList.add("loading"); // Already loading
        const card = document.createElement("div");

        global.fetchHistory = [];

        await refreshMetadata("tv", item, refreshBtn, card);

        console.log(JSON.stringify({
            fetchCount: global.fetchHistory.length
        }));
        """
        output = run_node_harness(script)
        assert output["fetchCount"] == 0, "Should abort early when button is already loading"


class TestRenderMediaListsFiltering:
    """Tests renderMediaLists DOM rendering and filter checkbox interactions."""

    def test_filter_interactions_with_new_metadata_badges(self):
        """Verifies that archived items hide when check-show-archived is false, but badged items show."""
        script = """
        const itemA = {
            title: "Auto Unarchived Show",
            year: 2026,
            network: "HBO",
            plot: "Rich plot.",
            cast: "Star A",
            genres: ["Drama"],
            is_archived: false,
            has_new_metadata: true,
            is_returning: false,
            is_in_library: false
        };

        const itemB = {
            title: "Low Metadata Archived Show",
            year: 2026,
            network: "Unknown",
            plot: "No plot",
            cast: "Unknown",
            genres: [],
            is_archived: true,
            has_new_metadata: false,
            is_returning: false,
            is_in_library: false
        };

        currentDiscoveries.tv = [itemA, itemB];
        currentDiscoveries.movies = [];

        // 1. When check-show-archived is unchecked (false)
        document.getElementById("check-show-archived").checked = false;
        document.getElementById("check-show-returning").checked = true;
        document.getElementById("check-show-library").checked = true;
        document.getElementById("search-bar").value = "";

        renderMediaLists();

        const gridTv = document.getElementById("grid-tv");
        const renderedCardsCount1 = gridTv.children.length;
        const renderedHtml1 = gridTv.children.map(c => c.innerHTML).join(" ");
        const itemAShown1 = renderedHtml1.includes("Auto Unarchived Show") && renderedHtml1.includes("badge-new-metadata");
        const itemBShown1 = renderedHtml1.includes("Low Metadata Archived Show");

        // 2. When check-show-archived is checked (true)
        document.getElementById("check-show-archived").checked = true;
        renderMediaLists();

        const renderedCardsCount2 = gridTv.children.length;
        const renderedHtml2 = gridTv.children.map(c => c.innerHTML).join(" ");
        const itemAShown2 = renderedHtml2.includes("Auto Unarchived Show") && renderedHtml2.includes("badge-new-metadata");
        const itemBShown2 = renderedHtml2.includes("Low Metadata Archived Show") && renderedHtml2.includes("badge-archived");

        console.log(JSON.stringify({
            pass1: { count: renderedCardsCount1, itemAShown: itemAShown1, itemBShown: itemBShown1 },
            pass2: { count: renderedCardsCount2, itemAShown: itemAShown2, itemBShown: itemBShown2 }
        }));
        """
        output = run_node_harness(script)
        p1 = output["pass1"]
        p2 = output["pass2"]

        assert p1["itemAShown"] is True, "Unarchived item with new metadata badge must be visible"
        assert p1["itemBShown"] is False, "Archived item must be hidden when show-archived is unchecked"

        assert p2["itemAShown"] is True, "Unarchived item with new metadata badge must remain visible"
        assert p2["itemBShown"] is True, "Archived item must now be visible with badge-archived"

    def test_search_filter_with_new_metadata_items(self):
        """Verifies searching across title, network, cast, and genres preserves badged items."""
        script = """
        const badgedItem = {
            title: "Cyberpunk Odyssey",
            year: 2026,
            network: "Neon Studios",
            plot: "Dystopian future with advanced cyberware.",
            cast: "Keanu Reaves",
            genres: ["Cyberpunk", "Action"],
            is_archived: false,
            has_new_metadata: true
        };

        const otherItem = {
            title: "Medieval Tale",
            year: 2026,
            network: "Kingdom TV",
            plot: "Ancient swords and knights.",
            cast: "Knight Actor",
            genres: ["Historical"],
            is_archived: false,
            has_new_metadata: false
        };

        currentDiscoveries.tv = [badgedItem, otherItem];
        currentDiscoveries.movies = [];

        document.getElementById("check-show-archived").checked = false;
        document.getElementById("check-show-returning").checked = true;
        document.getElementById("check-show-library").checked = true;

        const gridTv = document.getElementById("grid-tv");

        // 1. Search matching title
        document.getElementById("search-bar").value = "cyberpunk";
        renderMediaLists();
        const search1 = gridTv.children.map(c => c.innerHTML).join(" ");

        // 2. Search matching cast
        document.getElementById("search-bar").value = "keanu";
        renderMediaLists();
        const search2 = gridTv.children.map(c => c.innerHTML).join(" ");

        // 3. Search matching network
        document.getElementById("search-bar").value = "neon";
        renderMediaLists();
        const search3 = gridTv.children.map(c => c.innerHTML).join(" ");

        // 4. Search not matching
        document.getElementById("search-bar").value = "nonexistent";
        renderMediaLists();
        const search4 = gridTv.children.map(c => c.innerHTML).join(" ");
        const search4Empty = gridTv.innerHTML.includes("No matching");

        console.log(JSON.stringify({
            search1MatchesBadge: search1.includes("Cyberpunk Odyssey") && search1.includes("badge-new-metadata"),
            search2MatchesBadge: search2.includes("Cyberpunk Odyssey") && search2.includes("badge-new-metadata"),
            search3MatchesBadge: search3.includes("Cyberpunk Odyssey") && search3.includes("badge-new-metadata"),
            search4MatchesBadge: search4.includes("Cyberpunk Odyssey"),
            search4Empty
        }));
        """
        output = run_node_harness(script)
        assert output["search1MatchesBadge"] is True
        assert output["search2MatchesBadge"] is True
        assert output["search3MatchesBadge"] is True
        assert output["search4MatchesBadge"] is False
        assert output["search4Empty"] is True


class TestAdversarialCardRenderingSafety:
    """Tests createMediaCard resilience against special characters, quotes, and HTML strings."""

    def test_special_characters_and_quotes_in_metadata(self):
        """Verifies that titles with quotes, apostrophes, ampersands, and HTML tags do not crash card creation."""
        script = """
        const adversarialItem = {
            title: "The 'Special' & \\\"Exciting\\\" <Show> 2026",
            year: 2026,
            network: "FX & Hulu",
            plot: "A story about <b>bold</b> moves & 'quotes' galore.",
            cast: "Actor O'Connor, Star & Co.",
            genres: ["Sci-Fi & Fantasy", "Action / Thriller"],
            is_in_library: false,
            is_archived: false,
            has_new_metadata: true,
            poster_url: "https://example.com/poster'with'quote.jpg"
        };

        const card = createMediaCard(adversarialItem, "tv", 0);
        const html = card.innerHTML;

        console.log(JSON.stringify({
            hasBadge: html.includes('badge-new-metadata'),
            containsTitle: html.includes("The &#39;Special&#39; &amp; &quot;Exciting&quot;") || html.includes("The 'Special'") || html.includes("Special"),
            cardCreated: !!card
        }));
        """
        output = run_node_harness(script)
        assert output["cardCreated"] is True
        assert output["hasBadge"] is True


class TestCSSAndStaticAssetConformance:
    """Validates CSS rules, HTML markup tags, and theme adaptability."""

    def test_css_badge_styles_conformance(self):
        """Verifies that .badge-new-metadata and other badges are styled for dark & light themes."""
        css = STYLE_CSS_PATH.read_text(encoding="utf-8")

        # Dark theme badge definitions
        assert ".badge-new-metadata" in css
        assert "background:" in css
        assert "border:" in css
        assert ".badge-new-metadata::before" in css
        assert ".badge-archived" in css
        assert ".badge-returning" in css
        assert ".badge-in-library" in css

        # Light theme badge overrides
        assert "body.light-theme .badge-new-metadata" in css
        assert "body.light-theme .badge-new-metadata::before" in css

    def test_index_html_filter_controls(self):
        """Verifies that index.html contains all necessary filter switches."""
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        assert 'id="check-show-archived"' in html
        assert 'id="check-show-returning"' in html
        assert 'id="check-show-library"' in html
        assert 'id="grid-tv"' in html
        assert 'id="grid-movies"' in html
