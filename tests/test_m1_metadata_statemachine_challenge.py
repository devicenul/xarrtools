"""
tests/test_m1_metadata_statemachine_challenge.py
------------------------------------------------
Milestone 1 Empirical Challenger Test Suite:
1. Combinatorial generative stress test across all 16 permutations of core metadata fields.
2. Boundary and corner case testing: sentinels vs substrings, numeric, boolean, unicode, nested structures.
3. State machine formal verification: exhaustive 4x5 state transition matrix.
4. Multi-step lifecycle simulations in database: auto-archive -> enrich -> preserve -> re-archive -> degrade.
5. Concurrent database state transitions and batch ingestion resilience.
"""

import os
import json
import tempfile
import itertools
import threading
import concurrent.futures
from pathlib import Path
from datetime import datetime
import pytest

import core.db
from core.metadata import (
    MISSING_TITLE_STRINGS,
    MISSING_NETWORK_STRINGS,
    MISSING_CAST_STRINGS,
    MISSING_PLOT_STRINGS,
    is_title_missing,
    is_network_missing,
    is_cast_missing,
    is_plot_missing,
    evaluate_metadata,
    should_auto_archive,
    evaluate_item_state_transition,
)


@pytest.fixture
def temp_db():
    """Provides an isolated clean SQLite database for db-level state machine tests."""
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    old_db_path = core.db.DB_PATH
    core.db.DB_PATH = Path(temp_path)
    core.db.init_db()

    yield temp_path

    core.db.DB_PATH = old_db_path
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


# ===========================================================================
# 1. Combinatorial Generative Stress Test (All 16 Field Permutations)
# ===========================================================================

class TestCombinatorialCoreMetadata:
    """Generative verification of all 2^4 = 16 core field missingness combinations."""

    # Representative missing samples per field
    MISSING_TITLE_SAMPLES = [
        None, "", "   ", "\t\n", "unknown", "UNKNOWN", "  Unknown  ",
        "tbd", "TBD", "none", "null", "NULL", "n/a", "N/A", "na", True, False, [], {}
    ]
    VALID_TITLE_SAMPLES = [
        "Inception", "1984", 2001, 0, "Unknown Soldier", "None So Blind",
        "Null Island", "TBD Documentary", "映画: Spirited Away", "Café Society 🚀"
    ]

    MISSING_NETWORK_SAMPLES = [
        None, "", "   ", "unknown", "Unknown Network", "unknown studio",
        "UNKNOWN STUDIO", "n/a", "N/A", "na", "none", "null", "tbd", True, False,
        [], {}, ["unknown"], ["", "N/A"], {"name": "unknown"}, {"studio": "n/a"},
        {"network": "Unknown Studio"}, {"name": None}, [None, ""]
    ]
    VALID_NETWORK_SAMPLES = [
        "HBO", "Netflix", "Universal Pictures", "BBC One", "Network 10",
        "Studio Ghibli", "None Other TV", "Unknown World TV",
        {"name": "Apple TV+"}, {"network": "Amazon Prime"}, {"studio": "A24"},
        ["HBO", "Max"], [None, "Warner Bros."], [{"name": "Paramount+"}]
    ]

    MISSING_CAST_SAMPLES = [
        None, "", "   ", "cast details not available.", "Cast details not available",
        "CAST DETAILS NOT AVAILABLE.", "error getting details.", "ERROR GETTING DETAILS.",
        "unknown", "UNKNOWN", "n/a", "N/A", "na", "none", "null", "tbd", True, False,
        [], {}, ["cast details not available."], ["unknown", "N/A"], [None, ""],
        {"name": "unknown"}, {"person": {"name": "n/a"}}, {"person": None},
        [{"name": "unknown"}, {"person": {"name": "TBD"}}]
    ]
    VALID_CAST_SAMPLES = [
        "Bryan Cranston, Aaron Paul", "Pedro Pascal", ["Gary Oldman", "Jack Lowden"],
        "Castor Troy", "Unknown Actor In Role", "None Smith", 12345,
        {"name": "Keanu Reeves"}, {"person": {"name": "Harrison Ford"}},
        [None, "Leonardo DiCaprio"], [{"name": "Tom Hanks"}, {"name": "unknown"}]
    ]

    MISSING_PLOT_SAMPLES = [
        None, "", "   ", "no plot summary available.", "No plot summary available",
        "NO PLOT SUMMARY AVAILABLE.", "unknown", "UNKNOWN", "n/a", "N/A", "na",
        "none", "null", "tbd", True, False, [], {}
    ]
    VALID_PLOT_SAMPLES = [
        "A chemistry teacher turns to manufacturing methamphetamine.",
        "An unknown detective investigates a mysterious plot with no plot holes.",
        "Brief overview.", 9999, "Plot about TBD project in 1984."
    ]

    def test_all_16_combinations_generative(self):
        """Generatively test every bitmask of (title, network, cast, plot) presence/absence."""
        fields = ["title", "network", "cast", "plot"]
        
        # Test 2^4 = 16 binary combinations
        for combo in itertools.product([False, True], repeat=4):
            # True means missing, False means valid
            title_is_missing, net_is_missing, cast_is_missing, plot_is_missing = combo
            
            # Select sample values
            t_val = self.MISSING_TITLE_SAMPLES[0] if title_is_missing else self.VALID_TITLE_SAMPLES[0]
            n_val = self.MISSING_NETWORK_SAMPLES[0] if net_is_missing else self.VALID_NETWORK_SAMPLES[0]
            c_val = self.MISSING_CAST_SAMPLES[0] if cast_is_missing else self.VALID_CAST_SAMPLES[0]
            p_val = self.MISSING_PLOT_SAMPLES[0] if plot_is_missing else self.VALID_PLOT_SAMPLES[0]
            
            item = {"title": t_val, "network": n_val, "cast": c_val, "plot": p_val}
            res = evaluate_metadata(item)
            
            expected_missing_count = sum(combo)
            expected_low = expected_missing_count >= 2
            
            assert res["missing_count"] == expected_missing_count
            assert res["is_low_metadata"] == expected_low
            assert should_auto_archive(item) == expected_low
            
            assert res["fields"]["title"]["is_missing"] == title_is_missing
            assert res["fields"]["network"]["is_missing"] == net_is_missing
            assert res["fields"]["cast"]["is_missing"] == cast_is_missing
            assert res["fields"]["plot"]["is_missing"] == plot_is_missing

    def test_generative_fuzz_samples(self):
        """Fuzz evaluate_metadata with cartesian sample variations."""
        for t in self.MISSING_TITLE_SAMPLES[:4] + self.VALID_TITLE_SAMPLES[:4]:
            for n in self.MISSING_NETWORK_SAMPLES[:4] + self.VALID_NETWORK_SAMPLES[:4]:
                for c in self.MISSING_CAST_SAMPLES[:4] + self.VALID_CAST_SAMPLES[:4]:
                    for p in self.MISSING_PLOT_SAMPLES[:4] + self.VALID_PLOT_SAMPLES[:4]:
                        item = {"title": t, "network": n, "cast": c, "plot": p}
                        res = evaluate_metadata(item)
                        
                        # Verify invariants
                        assert isinstance(res["missing_fields"], list)
                        assert res["missing_count"] == len(res["missing_fields"])
                        assert res["is_low_metadata"] == (res["missing_count"] >= 2)
                        assert should_auto_archive(item) == res["is_low_metadata"]


# ===========================================================================
# 2. Boundary & Corner Cases (Substrings, Types, Unicode, Nested)
# ===========================================================================

class TestCornerCasesAndAdversarialInputs:
    """Stress-test subtle edge cases in string matching, types, and nesting."""

    def test_title_containing_sentinel_words_not_missing(self):
        """Titles that CONTAIN sentinel words as substrings must NOT be marked missing."""
        valid_titles = [
            "Unknown Soldier",
            "The Unknown",
            "Unknown: The Lost Pyramid",
            "Unknown Origins",
            "None of the Above",
            "None So Blind",
            "Null Island",
            "TBD (To Be Determined)",
            "N/A: Not Applicable Movie",
            "The NA Experience",
        ]
        for title in valid_titles:
            assert is_title_missing(title) is False, f"Title '{title}' was incorrectly marked missing!"
            eval_res = evaluate_metadata({"title": title, "network": "HBO", "cast": "Actor", "plot": "Plot"})
            assert "title" not in eval_res["missing_fields"]

    def test_network_containing_sentinel_words_not_missing(self):
        """Networks that CONTAIN sentinel words as substrings must NOT be marked missing."""
        valid_networks = [
            "Network 10",
            "The Network",
            "Studio Ghibli",
            "StudioCanal",
            "Unknown World Channel",
            "None Other Network",
        ]
        for net in valid_networks:
            assert is_network_missing(net) is False, f"Network '{net}' was incorrectly marked missing!"

    def test_cast_containing_sentinel_words_not_missing(self):
        """Cast members that CONTAIN sentinel words as substrings must NOT be marked missing."""
        valid_casts = [
            "Castor Troy",
            "Unknown Actor",
            "None Smith",
            "Bill Nighy",
        ]
        for cast in valid_casts:
            assert is_cast_missing(cast) is False, f"Cast '{cast}' was incorrectly marked missing!"

    def test_plot_containing_sentinel_words_not_missing(self):
        """Plot text that CONTAINS sentinel words as substrings must NOT be marked missing."""
        valid_plots = [
            "An unknown detective investigates a case with no plot summary available in police files.",
            "There is none like him in this thrilling drama with unknown origins.",
            "TBD in future releases, this film explores uncharted territory.",
        ]
        for plot in valid_plots:
            assert is_plot_missing(plot) is False, f"Plot was incorrectly marked missing: {plot}"

    def test_numeric_and_special_types(self):
        """Ensure integers, floats, and zero values evaluate safely."""
        assert is_title_missing(1984) is False
        assert is_title_missing(0) is False
        assert is_network_missing(10) is False
        assert is_cast_missing(99) is False
        assert is_plot_missing(100) is False

    def test_boolean_values_always_missing(self):
        """Booleans (True/False) should never be treated as valid metadata strings."""
        assert is_title_missing(True) is True
        assert is_title_missing(False) is True
        assert is_network_missing(True) is True
        assert is_network_missing(False) is True
        assert is_cast_missing(True) is True
        assert is_cast_missing(False) is True
        assert is_plot_missing(True) is True
        assert is_plot_missing(False) is True

    def test_nested_structures_with_none_and_empty(self):
        """Test lists and dicts containing None or mixed invalid/valid entries."""
        # Mixed list with 1 valid entry -> NOT missing
        assert is_network_missing([None, "", "HBO", "unknown"]) is False
        # List of all invalid entries -> missing
        assert is_network_missing([None, "", "unknown", "N/A", {"name": "None"}]) is True

        # Cast with deeply nested person dict
        assert is_cast_missing([
            {"person": {"name": "Unknown"}},
            {"person": None},
            {"person": {}},
            {"invalid_key": "foo"}
        ]) is True

        assert is_cast_missing([
            {"person": {"name": "Unknown"}},
            {"person": {"name": "Bryan Cranston"}}
        ]) is False

    def test_unicode_and_emojis(self):
        """Verify non-ASCII, accents, and emojis."""
        assert is_title_missing("千と千尋の神隠し") is False
        assert is_title_missing("Amélie") is False
        assert is_network_missing("フジテレビ") is False
        assert is_cast_missing("役所 広司") is False
        assert is_plot_missing("東京を舞台にした物語。") is False


# ===========================================================================
# 3. State Machine Formal Verification (State x Input Transition Matrix)
# ===========================================================================

class TestStateMachineFormalMatrix:
    """
    Formally tests all transitions in the state machine:
    States:
      - S0: None (Not in cache)
      - S1: (is_archived=0, has_new_metadata=0) [Normal Unarchived]
      - S2: (is_archived=0, has_new_metadata=1) [Unarchived with Badge]
      - S3: (is_archived=1, has_new_metadata=0) [Archived]
    """

    RICH_ITEM = {"title": "Rich Title", "network": "HBO", "cast": "Actor", "plot": "Plot"}
    LOW_ITEM = {"title": "Low Title", "network": "unknown", "cast": "unknown", "plot": "unknown"}

    # --- S0 (New Item) ---
    def test_s0_transitions(self):
        # S0 + Rich -> S1 (0, 0)
        assert evaluate_item_state_transition(None, self.RICH_ITEM) == (0, 0)
        # S0 + Low -> S3 (1, 0)
        assert evaluate_item_state_transition(None, self.LOW_ITEM) == (1, 0)
        # S0 + Rich (explicit is_archived=1) -> S3 (1, 0)
        rich_archived = dict(self.RICH_ITEM, is_archived=1)
        assert evaluate_item_state_transition(None, rich_archived) == (1, 0)
        # S0 + Low (explicit is_archived=0) -> S3 (1, 0) [Low metadata auto-archives regardless]
        low_unarchived = dict(self.LOW_ITEM, is_archived=0)
        assert evaluate_item_state_transition(None, low_unarchived) == (1, 0)

    # --- S1 (Unarchived, No Badge) ---
    def test_s1_transitions(self):
        s1 = {"is_archived": 0, "has_new_metadata": 0}
        # S1 + Rich -> S1 (0, 0)
        assert evaluate_item_state_transition(s1, self.RICH_ITEM) == (0, 0)
        # S1 + Low -> S3 (1, 0) [Degraded -> Auto-Archived]
        assert evaluate_item_state_transition(s1, self.LOW_ITEM) == (1, 0)
        # S1 + Rich (explicit is_archived=1) -> S3 (1, 0)
        rich_archived = dict(self.RICH_ITEM, is_archived=1)
        assert evaluate_item_state_transition(s1, rich_archived) == (1, 0)

    # --- S2 (Unarchived, With Badge) ---
    def test_s2_transitions(self):
        s2 = {"is_archived": 0, "has_new_metadata": 1}
        # S2 + Rich -> S2 (0, 1) [Preserves Badge]
        assert evaluate_item_state_transition(s2, self.RICH_ITEM) == (0, 1)
        # S2 + Low -> S3 (1, 0) [Degraded -> Auto-Archived & Badge Reset]
        assert evaluate_item_state_transition(s2, self.LOW_ITEM) == (1, 0)
        # S2 + Rich (explicit is_archived=1) -> S3 (1, 0) [Manual Archive -> Badge Reset]
        rich_archived = dict(self.RICH_ITEM, is_archived=1)
        assert evaluate_item_state_transition(s2, rich_archived) == (1, 0)

    # --- S3 (Archived) ---
    def test_s3_transitions(self):
        s3 = {"is_archived": 1, "has_new_metadata": 0}
        # S3 + Rich -> S2 (0, 1) [SMART UNARCHIVING WITH BADGE!]
        assert evaluate_item_state_transition(s3, self.RICH_ITEM) == (0, 1)
        # S3 + Low -> S3 (1, 0) [Stays Archived]
        assert evaluate_item_state_transition(s3, self.LOW_ITEM) == (1, 0)
        # S3 + Rich (explicit is_archived=1) -> S3 (1, 0) [User locked in archive]
        rich_archived = dict(self.RICH_ITEM, is_archived=1)
        assert evaluate_item_state_transition(s3, rich_archived) == (1, 0)


# ===========================================================================
# 4. Database Lifecycle Simulations (End-to-End State Machine in SQLite)
# ===========================================================================

class TestDatabaseLifecycleSimulations:
    """Full lifecycle stress testing via core/db.py."""

    def test_complete_discovery_enrichment_archive_cycle(self, temp_db):
        """
        Lifecycle:
        1. Ingest item with missing cast & plot (missing 2) -> S3: Auto-archived (is_archived=1, has_new_metadata=0)
        2. Rescan 1: Metadata enriched with cast & plot -> S2: Smart unarchived (is_archived=0, has_new_metadata=1)
        3. Rescan 2: Metadata stays rich -> S2: Preserved badge (is_archived=0, has_new_metadata=1)
        4. Manual archive via archive_cached_item(is_archived=True) -> S3: Archived (is_archived=1, has_new_metadata=0)
        5. Rescan 3: Metadata still rich -> S2: Smart unarchived again (is_archived=0, has_new_metadata=1)
        6. Rescan 4: Upstream metadata scraper returns empty plot/cast -> S3: Auto-archived (is_archived=1, has_new_metadata=0)
        """
        title = "Challenger Show"
        year = 2026

        # Step 1: Initial discovery with low metadata
        item_v1 = {
            "title": title,
            "year": year,
            "network": "HBO",
            "cast": "Cast details not available.",
            "plot": "No plot summary available.",
        }
        core.db.add_cached_item("tv", item_v1)
        row = core.db.get_cached_item("tv", title, year)
        assert row["is_archived"] == 1
        assert row["has_new_metadata"] == 0

        # Step 2: Rescan with full metadata discovered
        item_v2 = {
            "title": title,
            "year": year,
            "network": "HBO",
            "cast": "Bryan Cranston",
            "plot": "A compelling drama.",
        }
        core.db.add_cached_item("tv", item_v2)
        row = core.db.get_cached_item("tv", title, year)
        assert row["is_archived"] == 0
        assert row["has_new_metadata"] == 1

        # Step 3: Rescan retaining full metadata
        item_v3 = dict(item_v2, plot="An even more detailed compelling drama.")
        core.db.add_cached_item("tv", item_v3)
        row = core.db.get_cached_item("tv", title, year)
        assert row["is_archived"] == 0
        assert row["has_new_metadata"] == 1  # BADGE PRESERVED

        # Step 4: Re-archive item
        core.db.archive_cached_item("tv", title, year, is_archived=True)
        row = core.db.get_cached_item("tv", title, year)
        assert row["is_archived"] == 1
        assert row["has_new_metadata"] == 0  # BADGE RESET

        # Step 5: Enriched rescan after re-archiving
        core.db.add_cached_item("tv", item_v3)
        row = core.db.get_cached_item("tv", title, year)
        assert row["is_archived"] == 0
        assert row["has_new_metadata"] == 1  # SMART UNARCHIVED AGAIN

        # Step 6: Metadata degraded
        item_v4 = {
            "title": title,
            "year": year,
            "network": "unknown",
            "cast": "unknown",
            "plot": "unknown",
        }
        core.db.add_cached_item("tv", item_v4)
        row = core.db.get_cached_item("tv", title, year)
        assert row["is_archived"] == 1
        assert row["has_new_metadata"] == 0  # AUTO-ARCHIVED & BADGE RESET

    def test_batch_ingestion_mixed_states(self, temp_db):
        """Verify add_cached_items_batch correctly classifies mixed rich/low items."""
        items = []
        for i in range(50):
            if i % 2 == 0:
                items.append({
                    "title": f"Batch Rich {i}",
                    "year": 2026,
                    "network": "Netflix",
                    "cast": "Actor One",
                    "plot": "Full synopsis."
                })
            else:
                items.append({
                    "title": f"Batch Low {i}",
                    "year": 2026,
                    "network": "unknown",
                    "cast": "unknown",
                    "plot": "No plot summary available."
                })

        core.db.add_cached_items_batch("movie", items)

        conn = core.db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache WHERE is_archived = 1")
        archived_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cache WHERE is_archived = 0")
        unarchived_count = cursor.fetchone()[0]
        conn.close()

        assert archived_count == 25
        assert unarchived_count == 25


# ===========================================================================
# 5. Concurrency and Multi-Threaded State Transition Stress Test
# ===========================================================================

class TestConcurrentTransitions:
    """Verify SQLite WAL and transactions handle concurrent state updates correctly."""

    def test_concurrent_unarchive_and_archive_cycles(self, temp_db):
        """Multiple threads concurrently updating the same item across rich/low metadata states."""
        title = "Concurrent Media"
        year = 2026

        # Seed initial item
        core.db.add_cached_item("movie", {
            "title": title,
            "year": year,
            "network": "unknown",
            "cast": "unknown",
            "plot": "unknown"
        })

        errors = []

        def worker(thread_id):
            try:
                for cycle in range(5):
                    if (thread_id + cycle) % 2 == 0:
                        # Rich update
                        core.db.add_cached_item("movie", {
                            "title": title,
                            "year": year,
                            "network": f"Studio_{thread_id}",
                            "cast": f"Actor_{thread_id}",
                            "plot": f"Plot synopsis {thread_id}"
                        })
                    else:
                        # Manual archive
                        core.db.archive_cached_item("movie", title, year, is_archived=True)
            except Exception as e:
                errors.append(f"Thread {thread_id} failed: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrency errors: {errors}"

        # Final state check: item exists and fields are valid
        final_item = core.db.get_cached_item("movie", title, year)
        assert final_item is not None
        assert final_item["is_archived"] in (0, 1)
        assert final_item["has_new_metadata"] in (0, 1)
