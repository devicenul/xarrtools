"""Tests for compiled modals.ts module under Node.js.

Verifies pure modals, search, lookup, and builder helpers:
- buildSelectOptionsHtml
- isIndexerBestMatch
- getCollectionName
- buildCollectionBadgeHtml
- buildLookupItemHtml
- buildExternalChipsHtml
- getLookupPosterUrl
- buildRatingItemFromLookup
- buildSearchCardPlotHtml
- buildSearchCardPosterHtml
- buildSearchCardHtml
- buildSearchLoadingHtml
- buildSearchEmptyStateHtml
- buildSearchErrorHtml
- buildLookupStatusHtml
- formatSearchResultNotification
- getDemoSearchResults
- buildAddMediaPayload
"""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

DIST_MODALS = Path(__file__).resolve().parent.parent / "web" / "static" / "dist" / "modals.js"


def run_node_modals(body: str):
    if not DIST_MODALS.is_file():
        pytest.skip("web/static/dist/modals.js not found; run 'npm run build' first")
    code = f"""
import {{
  buildSelectOptionsHtml,
  isIndexerBestMatch,
  getCollectionName,
  buildCollectionBadgeHtml,
  buildLookupItemHtml,
  buildExternalChipsHtml,
  getLookupPosterUrl,
  buildRatingItemFromLookup,
  buildSearchCardPlotHtml,
  buildSearchCardPosterHtml,
  buildSearchCardHtml,
  buildSearchLoadingHtml,
  buildSearchEmptyStateHtml,
  buildSearchErrorHtml,
  buildLookupStatusHtml,
  formatSearchResultNotification,
  getDemoSearchResults,
  buildAddMediaPayload
}} from {json.dumps(DIST_MODALS.as_uri())};

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


def test_build_select_options_html():
    res = run_node_modals("""
      const profiles = [
        { id: 1, name: "SD" },
        { id: 2, name: "HD-1080p" },
        { id: "3", name: '<b style="color:red">UHD</b>' }
      ];

      const optDefault = buildSelectOptionsHtml(profiles, "id", "name", 2, "Select Quality Profile");
      const optNoDefault = buildSelectOptionsHtml(profiles, "id", "name", "3");
      const optEmpty = buildSelectOptionsHtml([], "id", "name", 1);
      const optNull = buildSelectOptionsHtml(null, "id", "name");

      console.log(JSON.stringify({ optDefault, optNoDefault, optEmpty, optNull }));
    """)
    # Default placeholder option
    assert '<option value="">Select Quality Profile</option>' in res["optDefault"]
    # Selection matching
    assert '<option value="2" selected>HD-1080p</option>' in res["optDefault"]
    assert '<option value="1">SD</option>' in res["optDefault"]

    # String value selection and HTML escaping
    assert '<option value="3" selected>&lt;b style=&quot;color:red&quot;&gt;UHD&lt;/b&gt;</option>' in res["optNoDefault"]
    assert '<b style="color:red">' not in res["optNoDefault"]

    # Resilience
    assert res["optEmpty"] == ""
    assert res["optNull"] == ""


def test_is_indexer_best_match():
    res = run_node_modals("""
      // TV match on tvdbId
      const tvMatch = isIndexerBestMatch(
        { title: "Shogun", year: 2024, tvdbId: 361701 },
        { title: "Shōgun (2024)", year: 2024, tvdbId: 361701 },
        "tv"
      );

      // Movie match on tmdbId
      const movieMatch = isIndexerBestMatch(
        { title: "Dune", year: 2021, tmdb_id: 438631 },
        { title: "Dune: Part One", year: 2021, tmdbId: 438631 },
        "movie"
      );

      // IMDb ID match
      const imdbMatch = isIndexerBestMatch(
        { title: "Different Title", year: 2020, imdbId: "tt1160419" },
        { title: "Dune", year: 2021, imdbId: "TT1160419" },
        "movie"
      );

      // Title + Year tolerance (±1 year) match
      const titleYearMatch = isIndexerBestMatch(
        { title: "Severance", year: 2022 },
        { title: "Severance (2022)", year: 2023 },
        "tv"
      );

      // Mismatch on title and year
      const mismatch = isIndexerBestMatch(
        { title: "Batman", year: 2022, tmdbId: 414906 },
        { title: "Superman", year: 2025, tmdbId: 999999 },
        "movie"
      );

      console.log(JSON.stringify({ tvMatch, movieMatch, imdbMatch, titleYearMatch, mismatch }));
    """)
    assert res["tvMatch"] is True
    assert res["movieMatch"] is True
    assert res["imdbMatch"] is True
    assert res["titleYearMatch"] is True
    assert res["mismatch"] is False


def test_collection_helpers():
    res = run_node_modals("""
      const name1 = getCollectionName({ collection: { title: "Dune Collection" } });
      const name2 = getCollectionName({ collection: { name: "Star Wars Saga" } });
      const nameNone = getCollectionName({ title: "Solo Movie" });
      const nameNull = getCollectionName(null);

      const badgeHtml = buildCollectionBadgeHtml("Dune Collection");
      const badgeEmpty = buildCollectionBadgeHtml(null);
      const badgeXss = buildCollectionBadgeHtml('<script>alert("xss")</script>');

      console.log(JSON.stringify({ name1, name2, nameNone, nameNull, badgeHtml, badgeEmpty, badgeXss }));
    """)
    assert res["name1"] == "Dune Collection"
    assert res["name2"] == "Star Wars Saga"
    assert res["nameNone"] is None
    assert res["nameNull"] is None

    assert "📦 Dune Collection" in res["badgeHtml"]
    assert res["badgeEmpty"] == ""
    assert '<script>alert("xss")</script>' not in res["badgeXss"]
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in res["badgeXss"]


def test_build_lookup_item_html():
    res = run_node_modals("""
      const tvItem = buildLookupItemHtml(
        { title: "Severance", year: 2022, tvdbId: 395982 },
        "tv",
        true,  // isBestMatch
        false  // inLibrary
      );

      const movieItem = buildLookupItemHtml(
        {
          title: '<img src=x onerror=1> Inception',
          year: 2010,
          tmdbId: 27205,
          collection: { title: "Nolan Collection" }
        },
        "movie",
        false, // isBestMatch
        true   // inLibrary
      );

      console.log(JSON.stringify({ tvItem, movieItem }));
    """)
    # TV item checks
    assert "Severance" in res["tvItem"]
    assert "TVDB ID: 395982" in res["tvItem"]
    assert '<span class="auto-match-tag">Auto Match</span>' in res["tvItem"]
    assert '<span class="lookup-item-status status-not-exists">Not Added</span>' in res["tvItem"]

    # Movie item checks with collection and XSS escaping
    assert '<img src=x onerror=1>' not in res["movieItem"]
    assert "&lt;img src=x onerror=1&gt; Inception" in res["movieItem"]
    assert "TMDB ID: 27205" in res["movieItem"]
    assert "📦 Nolan Collection" in res["movieItem"]
    assert '<span class="lookup-item-status status-exists">In Library</span>' in res["movieItem"]


def test_build_external_chips_html():
    res = run_node_modals("""
      const movieChips = buildExternalChipsHtml({
        title: "Dune 2",
        year: 2024,
        imdbId: "tt15239678",
        tmdbId: 693134
      }, "movie");

      const tvChips = buildExternalChipsHtml({
        title: "Slow Horses",
        year: 2022,
        imdbId: "tt5875444",
        tvdbId: 372138
      }, "tv");

      console.log(JSON.stringify({ movieChips, tvChips }));
    """)
    assert "https://www.imdb.com/title/tt15239678/" in res["movieChips"]
    assert "https://www.themoviedb.org/movie/693134" in res["movieChips"]
    assert "Google Search 🔍" in res["movieChips"]

    assert "https://www.imdb.com/title/tt5875444/" in res["tvChips"]
    assert "https://thetvdb.com/dereferrer/series/372138" in res["tvChips"]


def test_get_lookup_poster_url():
    res = run_node_modals("""
      const p1 = getLookupPosterUrl({ remotePoster: "https://artworks.thetvdb.com/banners/poster.jpg" });
      const p2 = getLookupPosterUrl({
        images: [
          { coverType: "banner", remoteUrl: "https://artworks.thetvdb.com/banner.jpg" },
          { coverType: "poster", remoteUrl: "https://artworks.thetvdb.com/real_poster.jpg" }
        ]
      });
      const pNone = getLookupPosterUrl({});

      console.log(JSON.stringify({ p1, p2, pNone }));
    """)
    assert res["p1"] == "https://artworks.thetvdb.com/banners/poster.jpg"
    assert res["p2"] == "https://artworks.thetvdb.com/real_poster.jpg"
    assert res["pNone"] is None


def test_build_rating_item_from_lookup():
    res = run_node_modals("""
      const movieRatings = buildRatingItemFromLookup({
        ratings: {
          imdb: { value: 8.8 },
          metacritic: { value: 74.2 },
          rottenTomatoes: { value: 92.6 }
        }
      }, "movie");

      const tvRatings = buildRatingItemFromLookup({
        ratings: { value: 8.5 }
      }, "tv");

      const emptyRatings = buildRatingItemFromLookup({}, "movie");

      console.log(JSON.stringify({ movieRatings, tvRatings, emptyRatings }));
    """)
    assert res["movieRatings"]["rating_imdb"] == "8.8"
    assert res["movieRatings"]["rating_metacritic"] == "74"
    assert res["movieRatings"]["rating_rt"] == "93"

    assert res["tvRatings"]["rating_imdb"] == "8.5"
    assert res["emptyRatings"]["rating_imdb"] == ""


def test_build_search_card_plot_and_poster_html():
    res = run_node_modals("""
      const shortPlot = buildSearchCardPlotHtml("A short synopsis.");
      const longPlot = buildSearchCardPlotHtml(
        "A very long narrative that goes on and on, explaining every single detail of the intricate sci-fi thriller plot with various twists, turns, and character betrayals spanning multiple galaxies."
      );
      const emptyPlot = buildSearchCardPlotHtml(null);

      const posterWithUrl = buildSearchCardPosterHtml(
        {},
        "movie",
        "https://image.tmdb.org/t/p/w500/poster.jpg",
        "https://www.imdb.com/title/tt123/",
        "Alien 2026"
      );

      const posterFallback = buildSearchCardPosterHtml(
        {},
        "tv",
        null,
        "https://thetvdb.com/series/123/",
        "Alien: The Series"
      );

      console.log(JSON.stringify({ shortPlot, longPlot, emptyPlot, posterWithUrl, posterFallback }));
    """)
    assert res["shortPlot"] == "A short synopsis."
    assert "plot-visible" in res["longPlot"]
    assert "plot-ellipsis" in res["longPlot"]
    assert "plot-hidden hidden" in res["longPlot"]
    assert "plot-more-btn" in res["longPlot"]
    assert res["emptyPlot"] == "No overview available."

    # Poster checks
    assert '<img src="https://image.tmdb.org/t/p/w500/poster.jpg"' in res["posterWithUrl"]
    assert 'class="poster-fallback"' in res["posterFallback"]
    assert "📺" in res["posterFallback"]
    assert "ALIEN: THE SERIES" in res["posterFallback"].upper()


def test_build_search_card_html_full():
    res = run_node_modals("""
      const movieCardNotInLibrary = buildSearchCardHtml({
        id: 0,
        title: "Gladiator II",
        year: 2024,
        studio: "Paramount Pictures",
        runtime: 148,
        certification: "R",
        genres: ["Action", "Adventure", "Drama"],
        overview: "Years after witnessing the death of the revered hero Maximus...",
        imdbId: "tt2104996",
        tmdbId: 558449,
        ratings: { imdb: { value: 6.8 } }
      }, "movie");

      const tvCardInLibrary = buildSearchCardHtml({
        id: 42,
        title: '<script>alert("xss")</script> Arcane',
        year: 2021,
        network: "Netflix",
        genres: ["Animation", "Sci-Fi"],
        overview: "Set in the utopian region of Piltover...",
        tvdbId: 366924
      }, "tv");

      console.log(JSON.stringify({ movieCardNotInLibrary, tvCardInLibrary }));
    """)
    # Movie card checks
    assert "Gladiator II" in res["movieCardNotInLibrary"]
    assert "Paramount Pictures" in res["movieCardNotInLibrary"]
    assert "148 min" in res["movieCardNotInLibrary"]
    assert "Action" in res["movieCardNotInLibrary"]
    assert "Add to Radarr" in res["movieCardNotInLibrary"]
    assert "btn btn-primary" in res["movieCardNotInLibrary"]

    # TV card in library with XSS check
    assert '<script>alert("xss")</script>' not in res["tvCardInLibrary"]
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt; Arcane" in res["tvCardInLibrary"]
    assert "badge-in-library" in res["tvCardInLibrary"]
    assert "In Library" in res["tvCardInLibrary"]
    assert "disabled" in res["tvCardInLibrary"]


def test_search_feedback_and_notification_helpers():
    res = run_node_modals("""
      const loading = buildSearchLoadingHtml("Dune", "movie");
      const loadingXss = buildSearchLoadingHtml("<script>test</script>", "tv");
      const empty = buildSearchEmptyStateHtml("Nonexistent Query");
      const err = buildSearchErrorHtml("Connection timed out");
      const status = buildLookupStatusHtml("Searching upstream indexer...");

      const notifDemo = formatSearchResultNotification(2, "Matrix", true);
      const notifLive = formatSearchResultNotification(5, "Matrix", false);
      const notifZero = formatSearchResultNotification(0, "Matrix", false);

      console.log(JSON.stringify({ loading, loadingXss, empty, err, status, notifDemo, notifLive, notifZero }));
    """)
    assert 'Searching Radarr for "Dune"...' in res["loading"]
    assert '<script>test</script>' not in res["loadingXss"]
    assert '&lt;script&gt;test&lt;/script&gt;' in res["loadingXss"]
    assert 'No results found for "Nonexistent Query"' in res["empty"]
    assert "Search error: Connection timed out" in res["err"]
    assert '<div class="lookup-status">Searching upstream indexer...</div>' in res["status"]

    assert '[Demo Mode] Found 2 simulated result(s) for "Matrix".' in res["notifDemo"]
    assert 'Found 5 result(s) for "Matrix".' in res["notifLive"]
    assert 'No results found for "Matrix".' in res["notifZero"]


def test_get_demo_search_results_and_build_add_payload():
    res = run_node_modals("""
      const movieDemo = getDemoSearchResults("Inception", "movie");
      const tvDemo = getDemoSearchResults("Breaking Bad", "tv");

      const payloadLive = buildAddMediaPayload({
        type: "movie",
        rawMetadata: { title: "Dune", year: 2021, tmdbId: 438631 },
        folder: "/data/movies",
        profileId: 3,
        monitored: true,
        searchNow: false,
        addCollection: true
      });

      const payloadDemo = buildAddMediaPayload({
        type: "tv",
        rawMetadata: { title: "Demo Show", year: 2026 },
        folder: "/sandbox/tv",
        profileId: 1,
        monitored: true,
        searchNow: true,
        addCollection: false,
        demo: true
      });

      console.log(JSON.stringify({ movieDemo, tvDemo, payloadLive, payloadDemo }));
    """)
    # Demo results
    assert len(res["movieDemo"]) == 2
    assert res["movieDemo"][0]["title"] == "Inception"
    assert res["movieDemo"][0]["tmdbId"] == 88801
    assert len(res["tvDemo"]) == 2
    assert res["tvDemo"][0]["title"] == "Breaking Bad"
    assert res["tvDemo"][0]["tvdbId"] == 99901

    # Payload checks
    assert res["payloadLive"]["type"] == "movie"
    assert res["payloadLive"]["folder"] == "/data/movies"
    assert res["payloadLive"]["profile_id"] == 3
    assert res["payloadLive"]["monitored"] is True
    assert res["payloadLive"]["search_now"] is False
    assert res["payloadLive"]["add_collection"] is True
    assert "demo" not in res["payloadLive"]

    assert res["payloadDemo"]["type"] == "tv"
    assert res["payloadDemo"]["demo"] is True
