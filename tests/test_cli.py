import pytest
from unittest.mock import patch, MagicMock
from core.client import ArrAPIError
from cli.cli import (
    parse_indices,
    show_config_status,
    select_from_list,
    handle_radarr_workflow,
    handle_sonarr_workflow,
    handle_discovery_workflow,
    run_cli
)

def test_parse_indices():
    # Simple values
    assert parse_indices("1", 5) == [0]
    assert parse_indices("1, 3", 5) == [0, 2]
    # Ranges
    assert parse_indices("1-3", 5) == [0, 1, 2]
    assert parse_indices("2-4, 5", 5) == [1, 2, 3, 4]
    # Clamping
    assert parse_indices("0-10", 5) == [0, 1, 2, 3, 4]
    # All
    assert parse_indices("all", 5) == [0, 1, 2, 3, 4]
    # Empty/invalid
    assert parse_indices("", 5) == []
    assert parse_indices("c", 5) == []
    assert parse_indices("invalid-range", 5) == []
    assert parse_indices("abc", 5) == []
    # Out of bounds check to hit line 44->28 branch
    assert parse_indices("10", 5) == []

@patch("cli.cli.console.print")
def test_show_config_status(mock_print):
    with patch("cli.cli.config") as mock_config:
        # 1. Both configured
        mock_config.validate_radarr.return_value = True
        mock_config.validate_sonarr.return_value = True
        mock_config.radarr_url = "http://radarr"
        mock_config.sonarr_url = "http://sonarr"
        show_config_status()
        assert mock_print.call_count == 1

        # 2. Both unconfigured
        mock_config.validate_radarr.return_value = False
        mock_config.validate_sonarr.return_value = False
        mock_config.get_missing_radarr_vars.return_value = ["API_KEY"]
        mock_config.get_missing_sonarr_vars.return_value = ["URL"]
        show_config_status()
        assert mock_print.call_count == 2

@patch("cli.cli.IntPrompt.ask")
@patch("cli.cli.console.print")
def test_select_from_list(mock_print, mock_ask):
    items = [{"name": "Profile A"}, {"name": "Profile B"}]
    
    # 1. First choice valid
    mock_ask.return_value = 1
    selected = select_from_list("Prompt text", items, "name")
    assert selected == items[0]

    # 2. First choice invalid, second valid
    mock_ask.side_effect = [3, 2]
    selected = select_from_list("Prompt text", items, "name")
    assert selected == items[1]
    mock_print.assert_any_call("[red]Invalid selection. Please choose a valid index.[/red]")

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
def test_handle_radarr_workflow_unconfigured(mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = False
    handle_radarr_workflow()
    mock_print.assert_called_once()
    assert "Radarr is not configured" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
def test_handle_radarr_workflow_empty_query(mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "   " # Empty search query
    handle_radarr_workflow()
    mock_ask.assert_called_once()

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_api_error(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "Inception"
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.side_effect = ArrAPIError("Radarr offline error")
    
    handle_radarr_workflow()
    assert "Error communicating with Radarr" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_no_results(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "NonexistentMovie"
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = []
    
    handle_radarr_workflow()
    assert "No movies found matching that term." in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_missing_configs(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "Inception"
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception"}]
    client_inst.get_quality_profiles.return_value = [] # Missing profiles
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert "Could not retrieve required quality profiles" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_cancel_selection(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "c"]
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception", "year": 2010}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert client_inst.add_movie.call_count == 0

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_invalid_selection(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "invalid_indices"]
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception", "year": 2010}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert any("No valid selections made" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_all_already_added(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "1"]
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception", "year": 2010, "id": 123}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert any("No new movies selected to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_add_success_and_failure(
    mock_radarr, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    # 1. Search term, 2. Selection index string
    mock_ask.side_effect = ["Inception", "1-3"]
    mock_confirm.side_effect = [True, True] # Monitor, Search Now
    
    client_inst = mock_radarr.return_value
    # Two movies: one already added (has "id"), one to add, one to skip
    movies = [
        {"title": "Inception 1", "year": 2010, "tmdbId": 11, "id": 123}, # Already added
        {"title": "Inception 2", "year": 2012, "tmdbId": 12},           # To add (succeeds)
        {"title": "Inception 3", "year": 2015, "tmdbId": 13}            # To add (fails with error)
    ]
    client_inst.lookup_movie.return_value = movies
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    mock_select.side_effect = [{"path": "/movies"}, {"id": 1, "name": "HD"}]
    
    client_inst.add_movie.side_effect = [
        {"title": "Inception 2"},
        ArrAPIError("Disk full")
    ]
    
    handle_radarr_workflow()
    
    # Verify add_movie calls
    assert client_inst.add_movie.call_count == 2
    client_inst.add_movie.assert_any_call(
        movie_data=movies[1],
        quality_profile_id=1,
        root_folder_path="/movies",
        monitored=True,
        search_now=True
    )
    
    # Assert printing messages
    assert any("Skipping already added movies" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Successfully added" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Failed to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
def test_handle_sonarr_workflow_unconfigured(mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = False
    handle_sonarr_workflow()
    assert "Sonarr is not configured" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
def test_handle_sonarr_workflow_empty_query(mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = ""
    handle_sonarr_workflow()
    mock_ask.assert_called_once()

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_api_error(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = "Rivals"
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.side_effect = ArrAPIError("Sonarr offline error")
    
    handle_sonarr_workflow()
    assert "Error communicating with Sonarr" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_no_results(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = "NonexistentShow"
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = []
    
    handle_sonarr_workflow()
    assert "No TV shows found matching that term." in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_missing_configs(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = "Rivals"
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals"}]
    client_inst.get_quality_profiles.return_value = []
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert "Could not retrieve required quality profiles" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_cancel_selection(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "c"]
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals", "year": 2026}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert client_inst.add_series.call_count == 0

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_invalid_selection(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "invalid_indices"]
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals", "year": 2026}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert any("No valid selections made" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_all_already_added(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "1"]
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals", "year": 2026, "id": 123}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert any("No new series selected to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_add_success(
    mock_sonarr, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "1"]
    mock_confirm.side_effect = [True, True]
    
    client_inst = mock_sonarr.return_value
    shows = [{"title": "Rivals", "year": 2026, "tvdbId": 11}]
    client_inst.lookup_series.return_value = shows
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    # Test multiple language profiles branch
    client_inst.get_language_profiles.return_value = [{"id": 1, "name": "English"}, {"id": 2, "name": "Spanish"}]
    
    # 1. Folder, 2. Profile, 3. Language Profile
    mock_select.side_effect = [{"path": "/tv"}, {"id": 1, "name": "HD"}, {"id": 2, "name": "Spanish"}]
    
    client_inst.add_series.return_value = {"title": "Rivals"}
    
    handle_sonarr_workflow()
    
    client_inst.add_series.assert_called_once_with(
        series_data=shows[0],
        quality_profile_id=1,
        root_folder_path="/tv",
        monitored=True,
        search_now=True,
        language_profile_id=2
    )
    assert any("Successfully added" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.SonarrClient")
def test_handle_sonarr_workflow_single_language_profile_and_add_failure(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "1"]
    
    client_inst = mock_sonarr.return_value
    shows = [{"title": "Rivals", "year": 2026, "tvdbId": 11}]
    client_inst.lookup_series.return_value = shows
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    # Test single language profiles branch (skips language prompt)
    client_inst.get_language_profiles.return_value = [{"id": 1, "name": "English"}]
    
    # 1. Folder, 2. Profile (no lang selection)
    with patch("cli.cli.select_from_list") as mock_select, \
         patch("cli.cli.Confirm.ask", return_value=True):
        mock_select.side_effect = [{"path": "/tv"}, {"id": 1, "name": "HD"}]
        client_inst.add_series.side_effect = ArrAPIError("Sonarr add failed")
        handle_sonarr_workflow()
        
    assert client_inst.add_series.call_count == 1
    assert any("Failed to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.get_discoveries")
def test_handle_discovery_workflow_no_releases(mock_get_disc, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    mock_ask.return_value = "2" # Timeframe
    mock_get_disc.return_value = ([], []) # No TV shows or movies
    
    handle_discovery_workflow()
    assert "No new releases found" in mock_print.call_args[0][0]

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
@patch("cli.cli.RadarrClient")
@patch("cli.cli.SonarrClient")
def test_handle_discovery_workflow_add_all(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    # 1. Timeframe = "invalid" -> default to 60 days
    # 2. Selection index string = "all"
    mock_ask.side_effect = ["invalid", "all"]
    # Confirm series monitor, confirm series search, confirm movie monitor, confirm movie search
    mock_confirm.side_effect = [True, True, True, True]
    
    from datetime import datetime
    tv_raw = [{"title": "Show New", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie New", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_tv.return_value = {
        "title": "Show New", "year": 2026, "plot": "TV Plot", "cast": "Cast",
        "genres": ["Drama"], "trailer": "http://youtube", "tvdbId": 12,
        "imdbId": "tt12", "is_in_library": False, "raw_metadata": {"title": "Show New", "id": None}
    }
    mock_enrich_movie.return_value = {
        "title": "Movie New", "year": 2026, "plot": "Movie Plot", "cast": "Cast",
        "genres": ["Action"], "trailer": "http://youtube", "tmdbId": 34,
        "imdbId": "tt34", "is_in_library": False, "raw_metadata": {"title": "Movie New", "id": None}
    }
    
    sonarr_inst = mock_sonarr.return_value
    sonarr_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    sonarr_inst.get_root_folders.return_value = [{"path": "/tv"}]
    sonarr_inst.get_language_profiles.return_value = []
    
    radarr_inst = mock_radarr.return_value
    radarr_inst.get_quality_profiles.return_value = [{"id": 2, "name": "HD"}]
    radarr_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    # 1. TV Root, 2. TV Profile, 3. Movie Root, 4. Movie Profile
    mock_select.side_effect = [
        {"path": "/tv"}, {"id": 1, "name": "HD"},
        {"path": "/movies"}, {"id": 2, "name": "HD"}
    ]
    
    sonarr_inst.add_series.return_value = {"title": "Show New"}
    radarr_inst.add_movie.return_value = {"title": "Movie New"}
    
    handle_discovery_workflow()
    
    # Verify adds
    sonarr_inst.add_series.assert_called_once()
    radarr_inst.add_movie.assert_called_once()

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
def test_handle_discovery_workflow_empty_selections_and_edge_branches(
    mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    # 1. Timeframe = 2
    # 2. Add selection index = "c" (Cancel selection)
    mock_ask.side_effect = ["2", "c"]
    
    from datetime import datetime
    # TV raw contains a returning show (should skip enrichment)
    tv_raw = [{"title": "Show Returning", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": True}]
    # Movie raw contains a movie
    movie_raw = [{"title": "Movie Normal", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_movie.return_value = {
        "title": "Movie Normal", "year": 2026, "plot": "", "cast": "Cast", # Test empty plot fallback
        "genres": ["Action"], "trailer": "http://youtube", "tmdbId": 34,
        "imdbId": "", "is_in_library": False, "raw_metadata": {"title": "Movie Normal"}
    }
    
    handle_discovery_workflow()
    
    # Returning TV show should be skipped for enrichment
    mock_enrich_tv.assert_not_called()
    # Movie enrichment should have run
    mock_enrich_movie.assert_called_once()

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
def test_handle_discovery_workflow_invalid_selections(
    mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    # Timeframe = 2, Selection = "invalid"
    mock_ask.side_effect = ["2", "invalid"]
    
    from datetime import datetime
    tv_raw = [{"title": "Show New", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, [])
    
    mock_enrich_tv.return_value = {
        "title": "Show New", "year": 2026, "plot": "TV Plot", "cast": "Cast",
        "genres": ["Drama"], "trailer": "http://youtube", "tvdbId": 12,
        "imdbId": "tt12", "is_in_library": False, "raw_metadata": {"title": "Show New"}
    }
    
    handle_discovery_workflow()
    assert any("No valid selections made" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
def test_handle_discovery_workflow_skip_already_in_library_and_empty_metadata(
    mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    # Timeframe = 2, Selection = "1, 2"
    mock_ask.side_effect = ["2", "1, 2"]
    
    from datetime import datetime
    tv_raw = [{"title": "Show Library", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie Empty", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    # 1. TV show already in library (skipped)
    mock_enrich_tv.return_value = {
        "title": "Show Library", "year": 2026, "plot": "TV Plot", "cast": "Cast",
        "genres": ["Drama"], "trailer": "http://youtube", "tvdbId": 12,
        "imdbId": "tt12", "is_in_library": True, "raw_metadata": {"title": "Show Library"}
    }
    # 2. Movie lacks raw metadata and lookup returns nothing (skipped)
    mock_enrich_movie.return_value = {
        "title": "Movie Empty", "year": 2026, "plot": "Movie Plot", "cast": "Cast",
        "genres": ["Action"], "trailer": "http://youtube", "tmdbId": 34,
        "imdbId": "tt34", "is_in_library": False, "raw_metadata": None
    }
    
    with patch("cli.cli.RadarrClient") as mock_radarr:
        radarr_inst = mock_radarr.return_value
        radarr_inst.lookup_movie.return_value = [] # Missing raw_metadata lookup yields empty
        handle_discovery_workflow()
        
    assert any("Skipping 'Show Library' (already in library)" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Could not find 'Movie Empty'" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
@patch("cli.cli.RadarrClient")
@patch("cli.cli.SonarrClient")
def test_handle_discovery_workflow_enrichment_fails_and_missing_raw_metadata_lookup(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    # Timeframe = 2, Add selection index = "1, 2"
    mock_ask.side_effect = ["2", "1, 2"]
    mock_confirm.side_effect = [True, True, True, True]
    
    from datetime import datetime
    tv_raw = [{"title": "Show Fail", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie Fail", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    # Enrichment raises exception, falling back to basic details with no raw_metadata!
    mock_enrich_tv.side_effect = Exception("Enrich fail")
    mock_enrich_movie.side_effect = Exception("Enrich fail")
    
    sonarr_inst = mock_sonarr.return_value
    # Triggered lookup fallback returns a series payload
    sonarr_inst.lookup_series.return_value = [{"title": "Show Fail", "id": None}]
    sonarr_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    sonarr_inst.get_root_folders.return_value = [{"path": "/tv"}]
    sonarr_inst.get_language_profiles.return_value = []
    
    radarr_inst = mock_radarr.return_value
    # Triggered lookup fallback returns a movie payload
    radarr_inst.lookup_movie.return_value = [{"title": "Movie Fail", "id": None}]
    radarr_inst.get_quality_profiles.return_value = [{"id": 2, "name": "HD"}]
    radarr_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    mock_select.side_effect = [
        {"path": "/tv"}, {"id": 1, "name": "HD"},
        {"path": "/movies"}, {"id": 2, "name": "HD"}
    ]
    
    handle_discovery_workflow()
    
    # Lookups should be called to fetch metadata payload
    sonarr_inst.lookup_series.assert_called_once_with("Show Fail")
    radarr_inst.lookup_movie.assert_called_once_with("Movie Fail")
    
    # Adds should have been triggered
    sonarr_inst.add_series.assert_called_once()
    radarr_inst.add_movie.assert_called_once()

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
@patch("cli.cli.RadarrClient")
@patch("cli.cli.SonarrClient")
def test_handle_discovery_workflow_lookup_exception_during_fallback(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_print, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    mock_ask.side_effect = ["2", "1, 2"]
    
    from datetime import datetime
    tv_raw = [{"title": "Show Fail", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie Fail", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_tv.return_value = {"title": "Show Fail", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tvdbId": 12, "is_in_library": False, "raw_metadata": None}
    mock_enrich_movie.return_value = {"title": "Movie Fail", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tmdbId": 34, "is_in_library": False, "raw_metadata": None}
    
    sonarr_inst = mock_sonarr.return_value
    sonarr_inst.lookup_series.side_effect = Exception("Lookup TV error")
    
    radarr_inst = mock_radarr.return_value
    radarr_inst.lookup_movie.side_effect = Exception("Lookup Movie error")
    
    handle_discovery_workflow()
    
    # TV lookup fail should print error
    assert any("Error fetching API metadata for 'Show Fail'" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    # Movie lookup fail should print error
    assert any("Error fetching API metadata for 'Movie Fail'" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
def test_handle_discovery_workflow_bulk_adding_no_clients_configured(
    mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
):
    # Both clients unconfigured
    mock_config.validate_radarr.return_value = False
    mock_config.validate_sonarr.return_value = False
    
    mock_ask.side_effect = ["2", "1, 2"]
    
    from datetime import datetime
    tv_raw = [{"title": "Show", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_tv.return_value = {"title": "Show", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tvdbId": 12, "is_in_library": False, "raw_metadata": {"title": "Show"}}
    mock_enrich_movie.return_value = {"title": "Movie", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tmdbId": 34, "is_in_library": False, "raw_metadata": {"title": "Movie"}}
    
    handle_discovery_workflow()
    
    # Prints errors saying not configured
    assert any("Sonarr is not configured. Cannot add TV shows." in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Radarr is not configured. Cannot add movies." in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
@patch("cli.cli.RadarrClient")
@patch("cli.cli.SonarrClient")
def test_handle_discovery_workflow_bulk_adding_api_config_failures(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    mock_ask.side_effect = ["2", "1, 2"]
    
    from datetime import datetime
    tv_raw = [{"title": "Show", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_tv.return_value = {"title": "Show", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tvdbId": 12, "is_in_library": False, "raw_metadata": {"title": "Show"}}
    mock_enrich_movie.return_value = {"title": "Movie", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tmdbId": 34, "is_in_library": False, "raw_metadata": {"title": "Movie"}}
    
    sonarr_inst = mock_sonarr.return_value
    sonarr_inst.get_quality_profiles.side_effect = ArrAPIError("API error loading Sonarr config")
    
    radarr_inst = mock_radarr.return_value
    radarr_inst.get_quality_profiles.side_effect = ArrAPIError("API error loading Radarr config")
    
    handle_discovery_workflow()
    
    # Assert configuration loading errors printed
    assert any("Error fetching Sonarr config options: API error loading Sonarr config" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Error fetching Radarr config options: API error loading Radarr config" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.clear")
@patch("cli.cli.show_config_status")
@patch("cli.cli.handle_radarr_workflow")
@patch("cli.cli.handle_sonarr_workflow")
@patch("cli.cli.handle_discovery_workflow")
@patch("cli.cli.console.print")
def test_run_cli_menu_loop_with_invalid_options(
    mock_print, mock_discovery, mock_sonarr, mock_radarr, mock_status, mock_clear, mock_ask
):
    # Choice side effects:
    # 1. "invalid" choice -> prompts choice again
    # 2. "4" -> exit menu loop
    mock_ask.side_effect = ["invalid", "4"]
    run_cli()
    
    # Verify exit message printed
    assert any("Goodbye!" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert mock_clear.call_count == 2

@patch("cli.cli.Prompt.ask")
@patch("cli.cli.console.clear")
@patch("cli.cli.show_config_status")
@patch("cli.cli.handle_radarr_workflow")
@patch("cli.cli.handle_sonarr_workflow")
@patch("cli.cli.handle_discovery_workflow")
@patch("cli.cli.console.print")
def test_run_cli_menu_options_1_2_3(
    mock_print, mock_discovery, mock_sonarr, mock_radarr, mock_status, mock_clear, mock_ask
):
    # Side effects:
    # - choice "1", then return to menu
    # - choice "2", then return to menu
    # - choice "3", then return to menu
    # - choice "4" (exit)
    mock_ask.side_effect = ["1", "", "2", "", "3", "", "4"]
    run_cli()
    mock_radarr.assert_called_once()
    mock_sonarr.assert_called_once()
    mock_discovery.assert_called_once()

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.RadarrClient")
def test_handle_radarr_workflow_already_added_false_branch(
    mock_radarr, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "1"]
    mock_confirm.side_effect = [True, True]
    
    client_inst = mock_radarr.return_value
    # No "id" key in results (not already added)
    movies = [{"title": "Inception", "year": 2010, "tmdbId": 11}]
    client_inst.lookup_movie.return_value = movies
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    mock_select.side_effect = [{"path": "/movies"}, {"id": 1, "name": "HD"}]
    client_inst.add_movie.return_value = {"title": "Inception"}
    
    handle_radarr_workflow()
    # verify that the already_added warning printed list is empty (was not skipped)
    assert not any("Skipping already added movies:" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
@patch("cli.cli.RadarrClient")
@patch("cli.cli.SonarrClient")
def test_handle_discovery_workflow_additional_branches(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    mock_ask.side_effect = ["2", "1, 2"]
    mock_confirm.side_effect = [True, True, True, True]
    
    from datetime import datetime
    tv_raw = [{"title": "Show Extra", "date_obj": datetime(2026, 5, 30), "description": "TV Plot Description", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie Extra", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot Description", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    # 1. TV show plot is empty, covers line 326 fallback
    mock_enrich_tv.return_value = {
        "title": "Show Extra",
        "year": 2026,
        "plot": "",
        "cast": "Cast",
        "genres": [],
        "trailer": "",
        "tvdbId": None, # Force lookup fallback
        "is_in_library": False,
        "raw_metadata": None
    }
    mock_enrich_movie.return_value = {
        "title": "Movie Extra",
        "year": 2026,
        "plot": "",
        "cast": "Cast",
        "genres": [],
        "trailer": "",
        "tmdbId": None, # Force lookup fallback
        "is_in_library": False,
        "raw_metadata": None
    }
    
    sonarr_inst = mock_sonarr.return_value
    # lookup returns empty results to cover the 'if results:' falsy branch
    sonarr_inst.lookup_series.return_value = []
    
    radarr_inst = mock_radarr.return_value
    # lookup returns empty results to cover the 'if results:' falsy branch
    radarr_inst.lookup_movie.return_value = []
    
    handle_discovery_workflow()
    
    # Since lookups returned empty lists, it should say could not find in indexers
    assert any("Could not find 'Show Extra' in Sonarr/Radarr indexers" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Could not find 'Movie Extra' in Sonarr/Radarr indexers" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_tv_show")
@patch("cli.cli.enrich_movie")
@patch("cli.cli.RadarrClient")
@patch("cli.cli.SonarrClient")
def test_handle_discovery_workflow_bulk_failures_and_language_profiles(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    mock_ask.side_effect = ["2", "1, 2"]
    mock_confirm.side_effect = [True, True, True, True]
    
    from datetime import datetime
    tv_raw = [{"title": "Show Fail", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Movie Fail", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_tv.return_value = {"title": "Show Fail", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tvdbId": 12, "is_in_library": False, "raw_metadata": {"title": "Show Fail"}}
    mock_enrich_movie.return_value = {"title": "Movie Fail", "year": 2026, "plot": "Plot", "cast": "Cast", "genres": [], "trailer": "", "tmdbId": 34, "is_in_library": False, "raw_metadata": {"title": "Movie Fail"}}
    
    sonarr_inst = mock_sonarr.return_value
    sonarr_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    sonarr_inst.get_root_folders.return_value = [{"path": "/tv"}]
    # multiple language profiles to cover the len > 1 selection branch
    sonarr_inst.get_language_profiles.return_value = [{"id": 1, "name": "English"}, {"id": 2, "name": "French"}]
    sonarr_inst.add_series.side_effect = ArrAPIError("Sonarr Disk error")
    
    radarr_inst = mock_radarr.return_value
    radarr_inst.get_quality_profiles.return_value = [{"id": 2, "name": "HD"}]
    radarr_inst.get_root_folders.return_value = [{"path": "/movies"}]
    radarr_inst.add_movie.side_effect = ArrAPIError("Radarr Disk error")
    
    mock_select.side_effect = [
        {"path": "/tv"}, {"id": 1, "name": "HD"}, {"id": 2, "name": "French"}, # TV selection
        {"path": "/movies"}, {"id": 2, "name": "HD"} # Movie selection
    ]
    
    handle_discovery_workflow()
    
    # Assert bulk adding failures logged
    assert any("Failed to add 'Show Fail': Sonarr Disk error" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Failed to add 'Movie Fail': Radarr Disk error" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("cli.cli.config")
@patch("cli.cli.Prompt.ask")
@patch("cli.cli.Confirm.ask")
@patch("cli.cli.console.print")
@patch("cli.cli.select_from_list")
@patch("cli.cli.get_discoveries")
@patch("cli.cli.enrich_movie")
def test_handle_discovery_workflow_falsy_branches(
    mock_enrich_movie, mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    # Radarr and Sonarr unconfigured (clients will be None)
    mock_config.validate_radarr.return_value = False
    mock_config.validate_sonarr.return_value = False
    
    mock_ask.side_effect = ["2", "1"]
    
    from datetime import datetime
    # tv_releases is empty -> covers line 316 'if tv_releases' False
    tv_raw = []
    movie_raw = [{"title": "Movie Extra", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot Description", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)
    
    mock_enrich_movie.return_value = {
        "title": "Movie Extra",
        "year": 2026,
        "plot": "Plot",
        "cast": "Cast",
        "genres": [],
        "trailer": "",
        "tmdbId": None,
        "is_in_library": False,
        "raw_metadata": None
    }
    
    handle_discovery_workflow()
    
    # Since radarr_client is None, it should skip adding/searching and print 'Could not find Movie Extra'
    assert any("Could not find 'Movie Extra' in Sonarr/Radarr indexers" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
