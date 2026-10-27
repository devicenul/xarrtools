import pytest
from typing import Any, Dict, List, Optional

from xarrtools.core.metadata import (
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


class TestSentinelConstants:
    def test_sentinel_sets_exist_and_populated(self):
        assert isinstance(MISSING_TITLE_STRINGS, set)
        assert isinstance(MISSING_NETWORK_STRINGS, set)
        assert isinstance(MISSING_CAST_STRINGS, set)
        assert isinstance(MISSING_PLOT_STRINGS, set)

        # Title sentinels
        assert "" in MISSING_TITLE_STRINGS
        assert "unknown" in MISSING_TITLE_STRINGS
        assert "tbd" in MISSING_TITLE_STRINGS
        assert "none" in MISSING_TITLE_STRINGS
        assert "null" in MISSING_TITLE_STRINGS
        assert "n/a" in MISSING_TITLE_STRINGS
        assert "na" in MISSING_TITLE_STRINGS

        # Network sentinels
        assert "unknown network" in MISSING_NETWORK_STRINGS
        assert "unknown studio" in MISSING_NETWORK_STRINGS

        # Cast sentinels
        assert "cast details not available." in MISSING_CAST_STRINGS
        assert "cast details not available" in MISSING_CAST_STRINGS
        assert "error getting details." in MISSING_CAST_STRINGS

        # Plot sentinels
        assert "no plot summary available." in MISSING_PLOT_STRINGS
        assert "no plot summary available" in MISSING_PLOT_STRINGS


class TestFieldCheckers:
    @pytest.mark.parametrize(
        "val",
        [
            None,
            True,
            False,
            "",
            "   ",
            "\t\n",
            "unknown",
            "UNKNOWN",
            "Unknown",
            "  unknown  ",
            "tbd",
            "TBD",
            "none",
            "NONE",
            "null",
            "NULL",
            "n/a",
            "N/A",
            "na",
            "NA",
            [],
            {},
            set(),
            (),
        ],
    )
    def test_is_title_missing_true_cases(self, val: Any):
        assert is_title_missing(val) is True

    @pytest.mark.parametrize(
        "val",
        [
            "Dune: Part Two",
            "Severance",
            "1917",
            1917,
            "A",
            "Unknown Soldier",
            "None of the Above",
            "TBD Documentary",
            "Null Island",
        ],
    )
    def test_is_title_missing_false_cases(self, val: Any):
        assert is_title_missing(val) is False

    @pytest.mark.parametrize(
        "val",
        [
            None,
            True,
            False,
            "",
            "   ",
            "\n\t",
            "unknown",
            "UNKNOWN",
            "Unknown Network",
            "unknown studio",
            "UNKNOWN STUDIO",
            "n/a",
            "N/A",
            "na",
            "none",
            "null",
            "tbd",
            "  unknown network  ",
            [],
            {},
            [""],
            ["unknown"],
            ["Unknown Network"],
            {"name": "unknown"},
            {"studio": "n/a"},
            {"network": "Unknown Studio"},
            {"name": None},
        ],
    )
    def test_is_network_missing_true_cases(self, val: Any):
        assert is_network_missing(val) is True

    @pytest.mark.parametrize(
        "val",
        [
            "HBO",
            "Netflix",
            "Apple TV+",
            "BBC One",
            "Warner Bros.",
            "AMC",
            "Showtime",
            ["HBO", "Max"],
            {"name": "HBO"},
            {"network": "Netflix"},
            {"studio": "Universal Pictures"},
            "Unknown World Channel",
            "None Other TV",
        ],
    )
    def test_is_network_missing_false_cases(self, val: Any):
        assert is_network_missing(val) is False

    @pytest.mark.parametrize(
        "val",
        [
            None,
            True,
            False,
            "",
            "   ",
            [],
            [""],
            ["  "],
            ["unknown"],
            ["Cast details not available."],
            "cast details not available.",
            "Cast details not available",
            "CAST DETAILS NOT AVAILABLE.",
            "unknown",
            "UNKNOWN",
            "n/a",
            "N/A",
            "na",
            "none",
            "null",
            "tbd",
            "error getting details.",
            "ERROR GETTING DETAILS.",
            "  error getting details.  ",
            {},
            [{"name": "unknown"}],
            [{"person": {"name": "n/a"}}],
            [{"name": ""}],
        ],
    )
    def test_is_cast_missing_true_cases(self, val: Any):
        assert is_cast_missing(val) is True

    @pytest.mark.parametrize(
        "val",
        [
            "Bryan Cranston, Aaron Paul",
            ["Bryan Cranston", "Aaron Paul"],
            "Pedro Pascal",
            ["Bella Ramsey"],
            [{"name": "Gary Oldman"}],
            [{"person": {"name": "Gary Oldman"}}],
            "Unknown Actor In Role",
            "None Smith",
        ],
    )
    def test_is_cast_missing_false_cases(self, val: Any):
        assert is_cast_missing(val) is False

    @pytest.mark.parametrize(
        "val",
        [
            None,
            True,
            False,
            "",
            "   ",
            "no plot summary available.",
            "No plot summary available",
            "NO PLOT SUMMARY AVAILABLE.",
            "unknown",
            "UNKNOWN",
            "n/a",
            "N/A",
            "na",
            "none",
            "null",
            "tbd",
            "  No plot summary available.  ",
            [],
            {},
        ],
    )
    def test_is_plot_missing_true_cases(self, val: Any):
        assert is_plot_missing(val) is True

    @pytest.mark.parametrize(
        "val",
        [
            "A high school chemistry teacher diagnosed with lung cancer...",
            "Brief synopsis.",
            "A story with unknown origins.",
            "Plot with none to spare.",
        ],
    )
    def test_is_plot_missing_false_cases(self, val: Any):
        assert is_plot_missing(val) is False


class TestEvaluateMetadataCombinatorics:
    @pytest.mark.parametrize(
        "title,network,cast,plot,expected_missing,expected_low",
        [
            # 0 missing fields (1 permutation)
            ("Valid Title", "HBO", ["Actor A"], "Plot text", [], False),
            # 1 missing field (4 permutations) -> low = False
            ("unknown", "HBO", ["Actor A"], "Plot text", ["title"], False),
            ("Valid Title", "unknown network", ["Actor A"], "Plot text", ["network"], False),
            ("Valid Title", "HBO", "Cast details not available.", "Plot text", ["cast"], False),
            ("Valid Title", "HBO", ["Actor A"], "No plot summary available.", ["plot"], False),
            # 2 missing fields (6 permutations) -> low = True
            ("", "n/a", ["Actor A"], "Plot text", ["title", "network"], True),
            ("", "HBO", [], "Plot text", ["title", "cast"], True),
            ("", "HBO", ["Actor A"], None, ["title", "plot"], True),
            ("Valid Title", "unknown", "unknown", "Plot text", ["network", "cast"], True),
            ("Valid Title", "unknown", ["Actor A"], "tbd", ["network", "plot"], True),
            ("Valid Title", "HBO", "error getting details.", "no plot summary available.", ["cast", "plot"], True),
            # 3 missing fields (4 permutations) -> low = True
            ("tbd", "unknown", [], "Plot text", ["title", "network", "cast"], True),
            ("tbd", "unknown", ["Actor A"], "", ["title", "network", "plot"], True),
            ("tbd", "HBO", [], "", ["title", "cast", "plot"], True),
            ("Valid Title", "unknown studio", "n/a", "unknown", ["network", "cast", "plot"], True),
            # 4 missing fields (1 permutation) -> low = True
            ("unknown", "unknown", "unknown", "unknown", ["title", "network", "cast", "plot"], True),
        ],
    )
    def test_all_16_combinations_evaluate_metadata(
        self,
        title: Any,
        network: Any,
        cast: Any,
        plot: Any,
        expected_missing: List[str],
        expected_low: bool,
    ):
        item = {"title": title, "network": network, "cast": cast, "plot": plot}
        res = evaluate_metadata(item)

        assert res["missing_fields"] == expected_missing
        assert res["missing_count"] == len(expected_missing)
        assert res["is_low_metadata"] == expected_low
        assert should_auto_archive(item) == expected_low

        assert res["fields"]["title"]["is_missing"] == ("title" in expected_missing)
        assert res["fields"]["network"]["is_missing"] == ("network" in expected_missing)
        assert res["fields"]["cast"]["is_missing"] == ("cast" in expected_missing)
        assert res["fields"]["plot"]["is_missing"] == ("plot" in expected_missing)


class TestEvaluateMetadataAliasesAndEdgeCases:
    def test_key_aliases_network_studio(self):
        item = {"title": "Movie Title", "studio": "Warner Bros.", "cast": "Actor One", "plot": "Movie plot"}
        res = evaluate_metadata(item)
        assert res["missing_count"] == 0
        assert res["is_low_metadata"] is False
        assert res["fields"]["network"]["value"] == "Warner Bros."
        assert res["fields"]["network"]["is_missing"] is False

    def test_key_aliases_plot_description_overview_summary(self):
        item_desc = {"title": "Show", "network": "HBO", "cast": "Actor", "description": "Good description"}
        assert evaluate_metadata(item_desc)["missing_count"] == 0

        item_over = {"title": "Show", "network": "HBO", "cast": "Actor", "overview": "Good overview"}
        assert evaluate_metadata(item_over)["missing_count"] == 0

        item_summ = {"title": "Show", "network": "HBO", "cast": "Actor", "summary": "Good summary"}
        assert evaluate_metadata(item_summ)["missing_count"] == 0

    def test_key_aliases_cast_actors_starring_cast_list(self):
        item_act = {"title": "Show", "network": "HBO", "actors": ["Actor A"], "plot": "Plot"}
        assert evaluate_metadata(item_act)["missing_count"] == 0

        item_star = {"title": "Show", "network": "HBO", "starring": "Actor B", "plot": "Plot"}
        assert evaluate_metadata(item_star)["missing_count"] == 0

        item_list = {"title": "Show", "network": "HBO", "cast_list": ["Actor C"], "plot": "Plot"}
        assert evaluate_metadata(item_list)["missing_count"] == 0

    def test_key_aliases_title_name_clean_title(self):
        item_name = {"name": "Show Name", "network": "HBO", "cast": "Actor", "plot": "Plot"}
        assert evaluate_metadata(item_name)["missing_count"] == 0

        item_clean = {"clean_title": "Clean Title", "network": "HBO", "cast": "Actor", "plot": "Plot"}
        assert evaluate_metadata(item_clean)["missing_count"] == 0

    def test_empty_dict_and_none_item(self):
        res_empty = evaluate_metadata({})
        assert res_empty["missing_count"] == 4
        assert res_empty["is_low_metadata"] is True
        assert should_auto_archive({}) is True

        res_none = evaluate_metadata(None)
        assert res_none["missing_count"] == 4
        assert res_none["is_low_metadata"] is True
        assert should_auto_archive(None) is True

    def test_non_dict_object(self):
        class ItemObj:
            def __init__(self):
                self.title = "Object Title"
                self.network = "Object Network"
                self.cast = "Object Cast"
                self.plot = "Object Plot"

            def get(self, k, default=None):
                return getattr(self, k, default)

        obj = ItemObj()
        res = evaluate_metadata(obj)
        assert res["missing_count"] == 0
        assert res["is_low_metadata"] is False

    def test_custom_subscriptable_mapping_without_get(self):
        class SubscriptableDict:
            def __init__(self, d):
                self._d = d

            def __getitem__(self, k):
                return self._d[k]

        item = SubscriptableDict({"title": "Sub Movie", "network": "HBO", "cast": "Actor", "plot": "Plot"})
        res = evaluate_metadata(item)
        assert res["missing_count"] == 0
        assert res["is_low_metadata"] is False

    def test_scalar_and_type_fallbacks(self):
        assert is_network_missing(2024) is False
        assert is_cast_missing(12345) is False
        assert is_cast_missing({}) is True
        assert is_cast_missing({"name": "Gary Oldman"}) is False
        assert is_cast_missing({"name": "unknown"}) is True
        assert is_cast_missing({"person": {"name": "Gary Oldman"}}) is False
        assert is_cast_missing({"person": {"name": "unknown"}}) is True
        assert is_plot_missing(99999) is False
        assert is_network_missing("unknown") is True
        assert should_auto_archive(12345) is True

    def test_key_error_handling_in_extract_field(self):
        class StrictDict:
            def __getitem__(self, k):
                raise KeyError(k)

        res = evaluate_metadata(StrictDict())
        assert res["missing_count"] == 4
        assert res["is_low_metadata"] is True


class TestStateTransitions:
    @pytest.mark.parametrize(
        "existing_item,new_item,expected_archived,expected_badge",
        [
            # --- Brand new items (existing_item is None) ---
            # 1. New rich item
            (None, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B"}, 0, 0),
            # 2. New low metadata item
            (None, {"title": "Bad", "network": "unknown", "cast": "unknown", "plot": "B"}, 1, 0),
            # 3. New rich item with explicit is_archived=1
            (None, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B", "is_archived": 1}, 1, 0),
            # 4. New low metadata item with explicit is_archived=0 (low metadata auto-archives)
            (None, {"title": "Bad", "network": "unknown", "cast": "unknown", "plot": "B", "is_archived": 0}, 1, 0),

            # --- Existing unarchived items (is_archived = 0) ---
            # 5. Unarchived (badge=0) updated with rich metadata -> stays (0, 0)
            ({"is_archived": 0, "has_new_metadata": 0}, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B"}, 0, 0),
            # 6. Unarchived (badge=1) updated with rich metadata -> retains badge (0, 1)
            ({"is_archived": 0, "has_new_metadata": 1}, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B"}, 0, 1),
            # 7. Unarchived (badge=0) degraded to low metadata -> auto-archives (1, 0)
            ({"is_archived": 0, "has_new_metadata": 0}, {"title": "Bad", "network": "unknown", "cast": "unknown", "plot": "B"}, 1, 0),
            # 8. Unarchived (badge=1) degraded to low metadata -> auto-archives & clears badge (1, 0)
            ({"is_archived": 0, "has_new_metadata": 1}, {"title": "Bad", "network": "unknown", "cast": "unknown", "plot": "B"}, 1, 0),
            # 9. Unarchived (badge=1) explicitly archived -> badge reset (1, 0)
            ({"is_archived": 0, "has_new_metadata": 1}, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B", "is_archived": 1}, 1, 0),

            # --- Existing archived items (is_archived = 1) ---
            # 10. Archived (badge=0) discovered with rich metadata -> SMART AUTO-UNARCHIVE (0, 1)
            ({"is_archived": 1, "has_new_metadata": 0}, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B"}, 0, 1),
            # 11. Archived (badge=1) discovered with rich metadata -> unarchived (0, 1)
            ({"is_archived": 1, "has_new_metadata": 1}, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B"}, 0, 1),
            # 12. Archived (badge=0) rescanned with low metadata -> stays archived (1, 0)
            ({"is_archived": 1, "has_new_metadata": 0}, {"title": "Bad", "network": "unknown", "cast": "unknown", "plot": "B"}, 1, 0),
            # 13. Archived (badge=1) rescanned with low metadata -> stays archived, badge reset (1, 0)
            ({"is_archived": 1, "has_new_metadata": 1}, {"title": "Bad", "network": "unknown", "cast": "unknown", "plot": "B"}, 1, 0),
            # 14. Archived (badge=0) updated with rich metadata but explicit is_archived=1 -> stays archived (1, 0)
            ({"is_archived": 1, "has_new_metadata": 0}, {"title": "Good", "network": "HBO", "cast": "A", "plot": "B", "is_archived": 1}, 1, 0),
        ],
    )
    def test_state_transitions(
        self,
        existing_item: Optional[Dict[str, Any]],
        new_item: Dict[str, Any],
        expected_archived: int,
        expected_badge: int,
    ):
        archived, badge = evaluate_item_state_transition(existing_item, new_item)
        assert archived == expected_archived
        assert badge == expected_badge

    def test_state_transition_invalid_new_item(self):
        assert evaluate_item_state_transition(None, None) == (1, 0)
        assert evaluate_item_state_transition({"is_archived": 0}, None) == (1, 0)

    def test_state_transition_subscriptable_without_get(self):
        class SubscriptableItem:
            def __init__(self, d):
                self._d = d

            def __getitem__(self, k):
                return self._d[k]

        existing = SubscriptableItem({"is_archived": 1, "has_new_metadata": 0})
        new_item = SubscriptableItem({"title": "Show", "network": "HBO", "cast": "A", "plot": "B", "is_archived": 0})
        archived, badge = evaluate_item_state_transition(existing, new_item)
        assert archived == 0
        assert badge == 1

    def test_state_transition_key_error_in_get_val(self):
        class StrictItem:
            def __getitem__(self, k):
                raise KeyError(k)

        archived, badge = evaluate_item_state_transition(StrictItem(), StrictItem())
        assert archived == 1
        assert badge == 0
