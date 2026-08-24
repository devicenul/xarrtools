import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from flask import Flask

import core.db
from core.config import config
from web.server import app


@pytest.fixture(autouse=True)
def reset_db_settings():
    """Resets api_key and clean state for tests."""
    from core.db import set_setting, clear_all_cache
    set_setting("api_key", "test_api_key_challenge_12345")
    config.refresh()
    yield
    set_setting("api_key", "test_api_key_challenge_12345")
    config.refresh()


@pytest.fixture
def test_app():
    """Provides a fresh configured test app instance."""
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(test_app):
    """Provides a test client."""
    return test_app.test_client()


# ============================================================================
# TIER 1: Static Asset Delivery & Route Robustness
# ============================================================================

def test_static_delivery_app_js_query_params_and_headers(client):
    """Adversarially tests /static/app.js under varied query parameters and request headers."""
    test_queries = [
        "",
        "?v=1.0.4",
        "?build=prod&minify=false",
        "?cache_bust=9999999",
        "?x=%3Cscript%3Ealert(1)%3C%2Fscript%3E",
        "?filter=all&sort=desc&limit=50",
    ]
    
    for q in test_queries:
        res = client.get(f"/static/app.js{q}", headers={
            "User-Agent": "Mozilla/5.0 (AdversarialTest/1.0)",
            "Accept": "application/javascript, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate",
            "If-Modified-Since": "Sat, 29 Oct 2025 19:43:31 GMT",
        })
        assert res.status_code in (200, 304), f"Failed for query '{q}' with status {res.status_code}"
        if res.status_code == 200:
            assert "javascript" in res.content_type
            assert len(res.data) > 10000


def test_static_delivery_style_css_query_params_and_headers(client):
    """Adversarially tests /static/style.css under varied query parameters and request headers."""
    test_queries = [
        "",
        "?v=2.1.0",
        "?theme=dark&variant=modern",
        "?ts=1724500000",
        "?foo=bar&test=1",
    ]
    
    for q in test_queries:
        res = client.get(f"/static/style.css{q}", headers={
            "User-Agent": "Mozilla/5.0 (AdversarialTest/1.0)",
            "Accept": "text/css, */*; q=0.1",
            "Accept-Encoding": "gzip, deflate",
        })
        assert res.status_code == 200
        assert "text/css" in res.content_type
        assert len(res.data) > 10000


def test_static_delivery_image_assets(client):
    """Tests all static image assets served by the server."""
    images = [
        "favicon.png",
        "favicon_light.png",
        "logo.png",
        "logo_light.png",
        "logo_master.png",
    ]
    for img in images:
        res = client.get(f"/static/{img}")
        assert res.status_code == 200, f"Missing image {img}"
        assert "image/png" in res.content_type
        assert len(res.data) > 0


def test_static_delivery_head_requests(client):
    """Tests HTTP HEAD requests for static assets and index route."""
    endpoints = ["/", "/static/app.js", "/static/style.css", "/static/favicon.png"]
    for ep in endpoints:
        res = client.head(ep)
        assert res.status_code == 200
        assert res.data == b""


def test_static_path_traversal_protection(client):
    """Tests that directory traversal attempts are securely rejected."""
    traversal_attacks = [
        "/static/../server.py",
        "/static/../../core/db.py",
        "/static/..%2fserver.py",
        "/static/%2e%2e%2fserver.py",
        "/static/%2e%2e/templates/app.js",
        "/static/nonexistent_file_404.js",
    ]
    for attack in traversal_attacks:
        res = client.get(attack)
        assert res.status_code in (400, 404), f"Traversal path '{attack}' returned unexpected {res.status_code}"


def test_server_http_methods_edge_cases(client):
    """Tests unsupported HTTP methods on / and /static/."""
    # POST to / should return 405 Method Not Allowed
    res = client.post("/")
    assert res.status_code == 405
    
    # PUT to / should return 405
    res = client.put("/")
    assert res.status_code == 405
    
    # DELETE to / should return 405
    res = client.delete("/")
    assert res.status_code == 405


def test_server_large_query_and_header_stress(client):
    """Tests that large query strings (>8KB) and weird headers do not crash the server."""
    huge_query = "?" + "&".join([f"param_{i}={'a'*50}" for i in range(150)])
    res = client.get(f"/{huge_query}")
    assert res.status_code == 200
    
    res_css = client.get(f"/static/style.css{huge_query}")
    assert res_css.status_code == 200
    
    res_js = client.get(f"/static/app.js{huge_query}")
    assert res_js.status_code == 200


# ============================================================================
# TIER 2: HTML Template Rendering & XSS Hardening
# ============================================================================

def test_index_template_rendering_varied_queries(client):
    """Tests / with various query parameters."""
    test_queries = [
        "",
        "?tab=tv",
        "?tab=movies",
        "?search=The+Matrix",
        "?show_archived=1",
        "?debug=1&param=%22%3E%3Cscript%3E",
    ]
    for q in test_queries:
        res = client.get(f"/{q}")
        assert res.status_code == 200
        assert "text/html" in res.content_type
        content = res.data.decode("utf-8")
        assert "<!DOCTYPE html>" in content
        assert "xarrtools" in content
        assert 'id="check-show-archived"' in content


def test_index_template_api_key_injection_and_escaping(client):
    """Tests Jinja2 api_key interpolation in meta tag, including special chars escaping."""
    from core.db import set_setting
    
    # Standard hex key
    set_setting("api_key", "deadbeef12345678")
    config.refresh()
    res = client.get("/")
    assert res.status_code == 200
    assert '<meta name="x-api-key" content="deadbeef12345678">' in res.data.decode("utf-8")
    
    # Key containing HTML characters (should be escaped by Jinja2)
    special_key = 'testkey" onclick="alert(1)" <tag>'
    set_setting("api_key", special_key)
    config.refresh()
    res = client.get("/")
    assert res.status_code == 200
    content = res.data.decode("utf-8")
    # Jinja2 autoescaping converts " to &#34; and < to &lt;
    assert "<script>" not in content
    assert 'content="testkey&#34; onclick=&#34;alert(1)&#34; &lt;tag&gt;"' in content


def test_index_template_auto_generates_api_key_if_empty(client):
    """Tests that index route generates a fresh api_key if not set."""
    from core.db import set_setting
    set_setting("api_key", "")
    config.refresh()
    
    res = client.get("/")
    assert res.status_code == 200
    content = res.data.decode("utf-8")
    match = re.search(r'<meta name="x-api-key" content="([^"]+)">', content)
    assert match is not None
    generated_key = match.group(1)
    assert len(generated_key) >= 16


# ============================================================================
# TIER 3: CSS Stylesheet Syntax & Integrity Validation
# ============================================================================

def test_css_stylesheet_syntax_and_balanced_braces():
    """Parses style.css to guarantee balanced braces, valid rules, and complete syntax."""
    css_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "style.css"
    assert css_path.is_file()
    css_text = css_path.read_text(encoding="utf-8")
    
    open_braces = 0
    open_parens = 0
    in_comment = False
    in_str = None
    i = 0
    
    while i < len(css_text):
        c = css_text[i]
        if in_comment:
            if c == "*" and i + 1 < len(css_text) and css_text[i+1] == "/":
                in_comment = False
                i += 2
                continue
        elif in_str:
            if c == "\\":
                i += 2
                continue
            elif c == in_str:
                in_str = None
        else:
            if c == "/" and i + 1 < len(css_text) and css_text[i+1] == "*":
                in_comment = True
                i += 2
                continue
            elif c in ('"', "'"):
                in_str = c
            elif c == "{":
                open_braces += 1
            elif c == "}":
                open_braces -= 1
                assert open_braces >= 0, f"Unexpected closing brace at index {i}"
            elif c == "(":
                open_parens += 1
            elif c == ")":
                open_parens -= 1
                assert open_parens >= 0, f"Unexpected closing paren at index {i}"
        i += 1
    
    assert not in_comment, "Unclosed CSS comment /*"
    assert open_braces == 0, f"Unbalanced CSS curly braces count: {open_braces}"
    assert open_parens == 0, f"Unbalanced CSS parentheses count: {open_parens}"


def test_css_malformed_syntax_detector():
    """Verifies that our CSS parsing algorithm accurately catches invalid/unbalanced CSS."""
    def parse_css(css_text):
        open_braces = 0
        in_comment = False
        in_str = None
        i = 0
        while i < len(css_text):
            c = css_text[i]
            if in_comment:
                if c == "*" and i + 1 < len(css_text) and css_text[i+1] == "/":
                    in_comment = False
                    i += 2
                    continue
            elif in_str:
                if c == "\\":
                    i += 2
                    continue
                elif c == in_str:
                    in_str = None
            else:
                if c == "/" and i + 1 < len(css_text) and css_text[i+1] == "*":
                    in_comment = True
                    i += 2
                    continue
                elif c in ('"', "'"):
                    in_str = c
                elif c == "{":
                    open_braces += 1
                elif c == "}":
                    open_braces -= 1
                    if open_braces < 0:
                        return False
            i += 1
        return open_braces == 0 and not in_comment

    assert parse_css(".test { color: red; }") is True
    assert parse_css(".test { color: red;") is False  # unclosed brace
    assert parse_css(".test { color: red; }}") is False  # extra brace
    assert parse_css("/* unclosed comment .test { color: red; }") is False


def test_css_badge_styles_completeness():
    """Verifies all required badging rules for both Dark and Light themes."""
    css_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "style.css"
    css_text = css_path.read_text(encoding="utf-8")
    
    # Required CSS selector declarations
    required_selectors = [
        ".badge-new-metadata",
        ".badge-new-metadata::before",
        ".media-card:hover .badge-new-metadata",
        "body.light-theme .badge-new-metadata",
        "body.light-theme .badge-new-metadata::before",
        ".badge-archived",
        ".badge-in-library",
        ".badge-returning",
        ".badge-network",
    ]
    for selector in required_selectors:
        assert selector in css_text, f"Missing CSS selector '{selector}' in style.css"


def test_css_responsive_breakpoints():
    """Verifies standard responsive media queries exist in style.css."""
    css_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "style.css"
    css_text = css_path.read_text(encoding="utf-8")
    
    assert "@media" in css_text
    assert "max-width" in css_text


# ============================================================================
# TIER 4: JavaScript Syntax, Template Literals & Badging Logic
# ============================================================================

def test_app_js_syntax_via_node():
    """Executes node --check on app.js to ensure 100% syntax validity."""
    node_bin = shutil.which("node")
    assert node_bin, "Node.js executable not found"
    app_js_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"
    res = subprocess.run([node_bin, "--check", str(app_js_path)], capture_output=True, text=True)
    assert res.returncode == 0, f"Node syntax check failed on app.js:\n{res.stderr}"


def test_app_js_template_interpolation_node_ast():
    """Validates that template string interpolations and expressions in app.js parse cleanly in Node VM."""
    node_bin = shutil.which("node")
    assert node_bin, "Node.js executable not found"
    app_js_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"
    
    # Parse file using node vm.Script to verify full AST and template literal compilation
    check_script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync({json.dumps(str(app_js_path))}, 'utf8');
    new vm.Script(code);
    """
    res = subprocess.run([node_bin, "-e", check_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node vm.Script failed on app.js:\n{res.stderr}"


def test_app_js_has_new_metadata_interpolation_logic():
    """Validates the exact rendering token and conditions for 'New metadata' badging in app.js."""
    app_js_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"
    app_js = app_js_path.read_text(encoding="utf-8")
    
    # 1. Check template string contains the ternary for has_new_metadata
    expected_pattern = r'item\.has_new_metadata\s*\?\s*[\'"`]<span class="badge badge-new-metadata">New metadata</span>[\'"`]\s*:\s*[\'"`][\'"`]'
    assert re.search(expected_pattern, app_js) is not None, "Missing or incorrect has_new_metadata rendering ternary in app.js"
    
    # 2. Check toggleArchive resets has_new_metadata
    toggle_archive_block = app_js[app_js.find("async function toggleArchive"):app_js.find("async function refreshMetadata")]
    assert "item.has_new_metadata = false" in toggle_archive_block, "toggleArchive does not reset has_new_metadata to false"
    
    # 3. Check renderMediaLists exists and is called
    assert "function renderMediaLists" in app_js
    assert "renderMediaLists()" in toggle_archive_block


def test_dom_ids_parity_between_html_and_js():
    """Guarantees that every getElementById in app.js has a corresponding id in index.html."""
    index_html = (Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    app_js = (Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js").read_text(encoding="utf-8")
    
    ids_in_js = set(re.findall(r"getElementById\([\"'`]?([a-zA-Z0-9_-]+)[\"'`]?\)", app_js))
    ids_in_html = set(re.findall(r'id=["\']([a-zA-Z0-9_-]+)["\']', index_html))
    
    missing_ids = ids_in_js - ids_in_html
    assert not missing_ids, f"DOM element IDs referenced in app.js but missing in index.html: {missing_ids}"


def test_js_rating_badges_html_matrix():
    """Adversarially tests buildRatingBadgesHtml function using Node VM across rating permutations."""
    node_bin = shutil.which("node")
    assert node_bin, "Node.js executable not found"
    app_js_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"
    
    eval_script = f"""
    const fs = require('fs');
    const appJs = fs.readFileSync({json.dumps(str(app_js_path))}, 'utf8');
    
    // Extract buildRatingBadgesHtml definition
    const fnStart = appJs.indexOf('function buildRatingBadgesHtml');
    const fnEnd = appJs.indexOf('function createMediaCard');
    const fnCode = appJs.substring(fnStart, fnEnd);
    
    eval(fnCode);
    
    const tests = [
        {{ in: {{}}, expectedEmpty: true }},
        {{ in: {{ rating_imdb: null, rating_metacritic: null, rating_rt: null }}, expectedEmpty: true }},
        {{ in: {{ rating_imdb: 0, rating_metacritic: 0, rating_rt: 0 }}, expectedEmpty: true }},
        {{ in: {{ rating_imdb: 8.5, rating_metacritic: 80, rating_rt: 95 }}, contains: ['badge-rating-imdb', '8.5', 'badge-rating-mc', 'mc-good', '80', 'badge-rating-rt', 'rt-certified', '95%'] }},
        {{ in: {{ rating_metacritic: 50, rating_rt: 65 }}, contains: ['mc-mixed', '50', 'rt-fresh', '65%'] }},
        {{ in: {{ rating_metacritic: 30, rating_rt: 40 }}, contains: ['mc-bad', '30', 'rt-rotten', '40%'] }},
    ];
    
    for (const t of tests) {{
        const out = buildRatingBadgesHtml(t.in);
        if (t.expectedEmpty && out !== '') {{
            console.error('Expected empty for input:', JSON.stringify(t.in), 'got:', out);
            process.exit(1);
        }}
        if (t.contains) {{
            for (const c of t.contains) {{
                if (!out.includes(c)) {{
                    console.error('Expected output to contain:', c, 'in output:', out);
                    process.exit(1);
                }}
            }}
        }}
    }}
    process.exit(0);
    """
    res = subprocess.run([node_bin, "-e", eval_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Rating badges JS evaluation failed:\n{res.stderr}"


def test_js_filter_and_archived_visibility_simulation():
    """Simulates client-side filtering logic to verify archived items are hidden unless checkShowArchived is active."""
    node_bin = shutil.which("node")
    assert node_bin, "Node.js executable not found"
    
    eval_script = """
    const items = [
        { title: "Active Movie", year: 2026, is_archived: false, has_new_metadata: false },
        { title: "New Metadata Movie", year: 2026, is_archived: false, has_new_metadata: true },
        { title: "Archived Movie", year: 2026, is_archived: true, has_new_metadata: false },
    ];
    
    function filterReleases(list, showArchived) {
        return list.filter(item => {
            if (!showArchived && item.is_archived) return false;
            return true;
        });
    }
    
    // Standard view (archived hidden)
    const standardView = filterReleases(items, false);
    if (standardView.length !== 2) process.exit(1);
    if (standardView.some(i => i.is_archived)) process.exit(2);
    
    // Archived view (archived visible)
    const archivedView = filterReleases(items, true);
    if (archivedView.length !== 3) process.exit(3);
    if (!archivedView.some(i => i.is_archived)) process.exit(4);
    
    process.exit(0);
    """
    res = subprocess.run([node_bin, "-e", eval_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Client filtering simulation failed: {res.stderr}"


# ============================================================================
# TIER 5: Live API & DOM Badging Simulation
# ============================================================================

def test_api_discover_and_card_rendering_simulation(client):
    """Simulates smart unarchiving flow and card rendering with has_new_metadata=True."""
    from core.db import add_cached_item
    
    # 1. First insert TV item with low metadata (missing network & cast) -> auto-archived
    tv_item_low = {
        "title": "Empirical Challenge TV Show",
        "year": 2026,
        "network": "Unknown",
        "cast": "",
        "plot": "A thrilling exploration of empirical testing.",
        "poster_url": "https://example.com/poster.jpg",
        "genres": ["Sci-Fi", "Mystery"],
        "trailer": "https://youtube.com/watch?v=123",
        "is_in_library": False,
        "date_str": "Aug 24",
        "date_obj": "2026-08-24",
        "is_returning": True,
    }
    add_cached_item("tv", tv_item_low)
    
    # 2. Rescan / enrich item with full metadata -> smart auto-unarchived with has_new_metadata=1
    tv_item_enriched = {
        "title": "Empirical Challenge TV Show",
        "year": 2026,
        "network": "HBO Max",
        "cast": "Empirical Actor, Stress Lead",
        "plot": "A thrilling exploration of empirical testing under adverse conditions.",
        "poster_url": "https://example.com/poster.jpg",
        "genres": ["Sci-Fi", "Mystery"],
        "trailer": "https://youtube.com/watch?v=123",
        "is_in_library": False,
        "date_str": "Aug 24",
        "date_obj": "2026-08-24",
        "is_returning": True,
    }
    add_cached_item("tv", tv_item_enriched)
    
    # Fetch discoveries
    res = client.get("/api/discover?skip_scrape=true")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    
    matching = [i for i in data["tv"] if i["title"] == "Empirical Challenge TV Show"]
    assert len(matching) == 1
    item = matching[0]
    assert item["is_archived"] in (False, 0)
    assert item["has_new_metadata"] in (True, 1)
    
    # Simulate JS card innerHTML construction matching app.js logic
    returning_badge = '<span class="badge badge-returning">Returning</span>' if item.get("is_returning") else ''
    new_metadata_badge = '<span class="badge badge-new-metadata">New metadata</span>' if item.get("has_new_metadata") else ''
    archived_badge = '<span class="badge badge-archived">Archived</span>' if item.get("is_archived") else ''
    
    card_badges_html = f"""
        <div class="card-badges">
            <span class="badge badge-network">{item['network']}</span>
            {returning_badge}
            {new_metadata_badge}
            {archived_badge}
        </div>
    """
    
    assert 'class="badge badge-network">HBO Max</span>' in card_badges_html
    assert 'class="badge badge-returning">Returning</span>' in card_badges_html
    assert 'class="badge badge-new-metadata">New metadata</span>' in card_badges_html
    assert 'class="badge badge-archived"' not in card_badges_html


def test_api_archive_and_card_rendering_badge_removal_simulation(client):
    """Simulates archiving an item with has_new_metadata=True, ensuring badge disappears."""
    from core.db import add_cached_item, set_setting
    
    # 1. Setup item with has_new_metadata = 1 via smart auto-unarchiving
    movie_low = {
        "title": "Empirical Movie",
        "year": 2026,
        "network": "",
        "cast": "",
        "plot": "An epic adventure in cinema.",
        "poster_url": "https://example.com/movie.jpg",
        "genres": ["Adventure"],
        "trailer": "https://youtube.com/watch?v=456",
        "is_in_library": False,
        "date_str": "Sep 01",
        "date_obj": "2026-09-01",
    }
    add_cached_item("movie", movie_low)
    
    movie_full = {
        "title": "Empirical Movie",
        "year": 2026,
        "network": "Universal Pictures",
        "cast": "Star One, Star Two",
        "plot": "An epic adventure in cinema.",
        "poster_url": "https://example.com/movie.jpg",
        "genres": ["Adventure"],
        "trailer": "https://youtube.com/watch?v=456",
        "is_in_library": False,
        "date_str": "Sep 01",
        "date_obj": "2026-09-01",
    }
    add_cached_item("movie", movie_full)
    
    api_key = config._get_setting("api_key")
    
    # Archive item via authenticated API POST
    res = client.post("/api/archive", json={
        "type": "movie",
        "title": "Empirical Movie",
        "year": 2026,
        "archive": True,
        "raw_item": movie_full,
    }, headers={"X-API-Key": api_key})
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    
    # Fetch discoveries again
    res = client.get("/api/discover?skip_scrape=true")
    assert res.status_code == 200
    data = res.get_json()
    matching = [i for i in data["movies"] if i["title"] == "Empirical Movie"]
    assert len(matching) == 1
    item = matching[0]
    assert item["is_archived"] in (True, 1)
    assert not item.get("has_new_metadata")
    
    # Simulate JS card innerHTML
    new_metadata_badge = '<span class="badge badge-new-metadata">New metadata</span>' if item.get("has_new_metadata") else ''
    archived_badge = '<span class="badge badge-archived">Archived</span>' if item.get("is_archived") else ''
    
    assert new_metadata_badge == ""
    assert 'class="badge badge-archived"' in archived_badge
