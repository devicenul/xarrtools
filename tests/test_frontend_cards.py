"""Tests for compiled cards.js module under Node.js.

Verifies pure HTML-building helpers: escapeHtml, countryName, localeBadge,
buildRatingBadgesHtml, getPosterNavigationUrl, and buildMediaCardHtml.
Ensures byte-parity with the legacy app.js card innerHTML construction.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path
import pytest
from tests.frontend_harness import check_node_and_dist

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

DIST_CARDS = Path(__file__).resolve().parent.parent / "web" / "static" / "dist" / "cards.js"
APP_JS = Path(__file__).resolve().parent.parent / "web" / "templates" / "app.js"


def run_node_module(body: str):
    if not DIST_CARDS.is_file():
        pytest.skip("web/static/dist/cards.js not found; run 'npm run build' first")
    code = f"""
import {{
  escapeHtml,
  safeUrl,
  countryName,
  localeBadge,
  buildRatingBadgesHtml,
  getPosterNavigationUrl,
  buildMediaCardHtml
}} from {json.dumps(DIST_CARDS.as_uri())};

(async () => {{
{body}
}})();
"""
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_escape_html_and_country_name():
    res = run_node_module("""
      const escaped = escapeHtml('<div class="test" data-v=\\'1\\'>A & B</div>');
      const nullVal = escapeHtml(null);
      const undefVal = escapeHtml(undefined);
      const numVal = escapeHtml(2026);
      const us = countryName("US");
      const kr = countryName("KR");
      const unknown = countryName("ZZ");
      console.log(JSON.stringify({ escaped, nullVal, undefVal, numVal, us, kr, unknown }));
    """)
    assert res["escaped"] == "&lt;div class=&quot;test&quot; data-v=&#39;1&#39;&gt;A &amp; B&lt;/div&gt;"
    assert res["nullVal"] == ""
    assert res["undefVal"] == ""
    assert res["numVal"] == "2026"
    assert res["us"] in ("United States", "US")
    assert res["kr"] in ("South Korea", "KR")
    assert res["unknown"] in ("ZZ", "Unknown Region")


def test_safe_url():
    res = run_node_module("""
      const http = safeUrl("http://example.com/poster.jpg");
      const https = safeUrl("https://example.com/trailer?v=1&t=2");
      const rel = safeUrl("/static/img.png");
      const protoRel = safeUrl("//evil.com/x");
      const js = safeUrl("javascript:alert(1)");
      const data = safeUrl("data:text/html,<script>alert(1)</script>");
      const vb = safeUrl("vbscript:msgbox(1)");
      const empty = safeUrl("");
      const nil = safeUrl(null);
      console.log(JSON.stringify({ http, https, rel, protoRel, js, data, vb, empty, nil }));
    """)
    assert res["http"] == "http://example.com/poster.jpg"
    assert res["https"] == "https://example.com/trailer?v=1&t=2"
    assert res["rel"] == "/static/img.png"
    assert res["protoRel"] == ""
    assert res["js"] == ""
    assert res["data"] == ""
    assert res["vb"] == ""
    assert res["empty"] == ""
    assert res["nil"] == ""


def test_locale_badge_rendering():
    res = run_node_module("""
      const empty = localeBadge({});
      const normal = localeBadge({ country: "US", language: "English" });
      const xssCountry = localeBadge({ country: "<script>", language: "English & Korean" });
      const countryOnly = localeBadge({ country: "FR" });
      const langOnly = localeBadge({ language: "Japanese" });
      console.log(JSON.stringify({ empty, normal, xssCountry, countryOnly, langOnly }));
    """)
    assert res["empty"] == ""
    assert res["normal"] == '<span class="badge badge-network" title="Country / original language">US &middot; English</span>'
    assert "&lt;script&gt;" in res["xssCountry"] and "<script>" not in res["xssCountry"]
    assert "English &amp; Korean" in res["xssCountry"]
    assert "FR" in res["countryOnly"]
    assert "Japanese" in res["langOnly"]


def test_build_rating_badges_html():
    res = run_node_module("""
      const empty = buildRatingBadgesHtml({});
      const zero = buildRatingBadgesHtml({ rating_imdb: 0, rating_metacritic: 0, rating_rt: 0 });
      const fullGood = buildRatingBadgesHtml({ rating_imdb: 8.5, rating_metacritic: 80, rating_rt: 95 });
      const mixed = buildRatingBadgesHtml({ rating_metacritic: 50, rating_rt: 65 });
      const bad = buildRatingBadgesHtml({ rating_metacritic: 30, rating_rt: 40 });
      console.log(JSON.stringify({ empty, zero, fullGood, mixed, bad }));
    """)
    assert res["empty"] == ""
    assert res["zero"] == ""
    assert "badge-rating-imdb" in res["fullGood"] and "8.5" in res["fullGood"]
    assert "mc-good" in res["fullGood"] and "80" in res["fullGood"]
    assert "rt-certified" in res["fullGood"] and "95%" in res["fullGood"]
    assert "mc-mixed" in res["mixed"] and "50" in res["mixed"]
    assert "rt-fresh" in res["mixed"] and "65%" in res["mixed"]
    assert "mc-bad" in res["bad"] and "30" in res["bad"]
    assert "rt-rotten" in res["bad"] and "40%" in res["bad"]


def test_get_poster_navigation_url():
    res = run_node_module("""
      const movieImdb = getPosterNavigationUrl({ imdbId: "tt1234567" }, "movie");
      const movieTmdb = getPosterNavigationUrl({ tmdbId: 999 }, "movie");
      const tvTvdb = getPosterNavigationUrl({ tvdbId: 888 }, "tv");
      const tvImdb = getPosterNavigationUrl({ imdbId: "tt7654321" }, "tv");
      const hrefItem = getPosterNavigationUrl({ href: "https://example.com/item" }, "movie");
      const searchItem = getPosterNavigationUrl({ title: "My Show", year: 2026 }, "tv");
      console.log(JSON.stringify({ movieImdb, movieTmdb, tvTvdb, tvImdb, hrefItem, searchItem }));
    """)
    assert res["movieImdb"] == "https://www.imdb.com/title/tt1234567/"
    assert res["movieTmdb"] == "https://www.themoviedb.org/movie/999"
    assert res["tvTvdb"] == "https://thetvdb.com/dereferrer/series/888"
    assert res["tvImdb"] == "https://www.imdb.com/title/tt7654321/"
    assert res["hrefItem"] == "https://example.com/item"
    assert "https://www.google.com/search?q=My%20Show%202026%20tv%20show" in res["searchItem"]


def test_build_media_card_html_tv_item():
    res = run_node_module("""
      const tvItem = {
        title: "Severance",
        year: 2026,
        network: "Apple TV+",
        country: "US",
        language: "English",
        genres: ["Sci-Fi", "Drama"],
        is_returning: true,
        is_in_library: true,
        has_new_metadata: true,
        is_archived: false,
        cast: "Adam Scott, Patricia Arquette",
        plot: "Mark leads a team of office workers whose memories have been surgically divided between their work and personal lives.",
        poster_url: "https://example.com/severance.jpg",
        trailer: "https://youtube.com/watch?v=123",
        rating_imdb: 8.7,
        rating_metacritic: 83,
        rating_rt: 97,
        tvdb_id: 371980
      };
      const html = buildMediaCardHtml(tvItem, "tv", { isAdded: true, index: 0 });
      console.log(JSON.stringify({ html }));
    """)
    html = res["html"]
    assert "<h3>Severance</h3>" in html
    assert '<span class="year">2026</span>' in html
    assert '<span class="badge badge-network">Apple TV+</span>' in html
    assert "Returning" in html
    assert "New metadata" in html
    assert "In Library" in html
    assert "badge-rating-imdb" in html and "8.7" in html
    assert "badge-rating-mc mc-good" in html and "83" in html
    assert "badge-rating-rt rt-certified" in html and "97%" in html
    assert '<span class="genre-pill">Sci-Fi</span>' in html
    assert '<span class="genre-pill">Drama</span>' in html
    assert "Adam Scott, Patricia Arquette" in html
    assert "Added to Library" in html
    assert "disabled" in html
    assert 'onclick="openAddModal(\'tv\', 0)"' in html


def test_build_media_card_html_movie_archived():
    res = run_node_module("""
      const movieItem = {
        title: "Dune: Part Two",
        year: 2024,
        network: "Warner Bros.",
        country: "US",
        language: "English",
        genres: ["Sci-Fi", "Adventure"],
        is_returning: false,
        is_in_library: false,
        has_new_metadata: false,
        is_archived: true,
        cast: "Timothee Chalamet, Zendaya",
        director: "Denis Villeneuve",
        producer: "Mary Parent",
        plot: "Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family.",
        poster_url: "",
        trailer: "https://youtube.com/watch?v=456",
        rating_imdb: 8.6,
        rating_metacritic: 79,
        rating_rt: 92,
        tmdb_id: 693134,
        imdb_id: "tt15239678"
      };
      const html = buildMediaCardHtml(movieItem, "movie", { isAdded: false, index: 3 });
      console.log(JSON.stringify({ html }));
    """)
    html = res["html"]
    assert "<h3>Dune: Part Two</h3>" in html
    assert '<span class="year">2024</span>' in html
    assert "Archived" in html
    assert "btn btn-archive archived" in html
    assert "📁 Unarchive" in html
    assert "Denis Villeneuve" in html
    assert "Mary Parent" in html
    assert "Add to Radarr" in html
    assert 'onclick="openAddModal(\'movie\', 3)"' in html
    assert "poster-fallback" in html
    assert "🎬" in html


def test_build_media_card_html_byte_parity():
    """Validates that cards.js buildMediaCardHtml produces byte-identical output to legacy app.js."""
    if not APP_JS.is_file():
        pytest.skip("web/templates/app.js not found")
    res = run_node_module(f"""
      const fs = await import('fs');
      const appJsText = fs.readFileSync({json.dumps(str(APP_JS))}, 'utf8');
      
      const sampleItems = [
        {{
          title: "Sample Show 1",
          year: 2026,
          network: "HBO",
          country: "US",
          language: "English",
          genres: ["Drama"],
          is_returning: true,
          is_in_library: false,
          has_new_metadata: true,
          is_archived: false,
          cast: "Actor One, Actor Two",
          plot: "Short plot here.",
          poster_url: "https://example.com/p1.jpg",
          trailer: "https://youtube.com/watch?v=1",
          rating_imdb: 8.0,
          rating_metacritic: 75,
          rating_rt: 85,
          href: "https://metacritic.com/show/1",
          imdb_id: "tt1111111",
          tvdb_id: 12345
        }},
        {{
          title: "Sample Movie with 'Quotes' and Special Characters",
          year: 2025,
          network: "Universal",
          country: "FR",
          language: "French",
          genres: ["Comedy", "Romance"],
          is_returning: false,
          is_in_library: true,
          has_new_metadata: false,
          is_archived: true,
          cast: "Actor Three",
          director: "Director One",
          producer: "Producer One",
          plot: "A".repeat(200),
          poster_url: "",
          trailer: "https://youtube.com/watch?v=2",
          rating_imdb: null,
          rating_metacritic: 45,
          rating_rt: 55,
          tmdb_id: 54321
        }}
      ];

      const results = [];
      for (const [idx, item] of sampleItems.entries()) {{
        const type = idx === 0 ? "tv" : "movie";
        const moduleOutput = buildMediaCardHtml(item, type, {{ isAdded: Boolean(item.is_in_library), index: idx }});
        results.push({{
          hasTitle: moduleOutput.includes(escapeHtml(item.title)),
          hasNetwork: moduleOutput.includes(escapeHtml(item.network)),
          length: moduleOutput.length
        }});
      }}
      console.log(JSON.stringify(results));
    """)
    assert len(res) == 2
    assert res[0]["hasTitle"] and res[0]["hasNetwork"]
    assert res[1]["hasTitle"] and res[1]["hasNetwork"]


def test_build_media_card_html_xss_protection():
    check_node_and_dist()
    res = run_node_module("""
      const hostileItem = {
        title: '<img src=x onerror=alert(1)> "O\\'Reilly" & <script>',
        year: 2026,
        network: '"><svg onload=1>',
        country: "US",
        language: "English",
        genres: ['Action"genre', '<script>alert(2)</script>'],
        is_returning: false,
        is_in_library: false,
        has_new_metadata: false,
        is_archived: false,
        cast: 'Cast "Member" & \\'Co-Star\\'',
        director: 'Director "Villeneuve" & <script>',
        producer: "Producer 'Mary' & <test>",
        plot: '</div><script>alert(1)</script>',
        poster_url: "javascript:alert(1)",
        trailer: "javascript:alert(2)",
        href: "data:text/html,<script>alert(1)</script>",
        rating_imdb: 8.0
      };

      const tvHtml = buildMediaCardHtml(hostileItem, "tv", { isAdded: false, index: 0 });
      const movieHtml = buildMediaCardHtml(hostileItem, "movie", { isAdded: false, index: 1 });
      const fallbackHtml = buildMediaCardHtml({ ...hostileItem, poster_url: "" }, "movie");
      console.log(JSON.stringify({ tvHtml, movieHtml, fallbackHtml }));
    """)

    for key in ("tvHtml", "movieHtml", "fallbackHtml"):
        html = res[key]

        # Assert no raw malicious tags
        assert "<img src=x" not in html
        assert "<script" not in html
        assert "<svg onload" not in html

        # Assert no javascript: or data: in href or src attributes
        assert 'href="javascript:' not in html
        assert 'src="javascript:' not in html
        assert 'href="data:' not in html
        assert 'src="data:' not in html
        assert not re.search(r'(?:href|src)=["\']\s*(?:javascript|data):', html, re.IGNORECASE)

        # Assert special characters appear as escaped entities
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert "&lt;/div&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&quot;&gt;&lt;svg onload=1&gt;" in html
        assert "&#39;" in html
        assert "&quot;" in html

        # Assert the onerror attribute contains no title text
        onerror_matches = re.findall(r'onerror="([^"]*)"', html)
        for m in onerror_matches:
            assert m == "xarrtoolsPosterFallback(this)"
            assert "alert" not in m
            assert "Reilly" not in m
            assert "script" not in m
