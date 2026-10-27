import json
import pytest
from unittest.mock import patch, MagicMock
from xarrtools.core.client import ArrAPIError
from xarrtools.cli.cli import (
    parse_indices,
    show_config_status,
    select_from_list,
    resolve_preset_index,
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

@patch("xarrtools.cli.cli.console.print")
def test_show_config_status(mock_print):
    with patch("xarrtools.cli.cli.config") as mock_config:
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

@patch("xarrtools.cli.cli.IntPrompt.ask")
@patch("xarrtools.cli.cli.console.print")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
def test_handle_radarr_workflow_unconfigured(mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = False
    handle_radarr_workflow()
    mock_print.assert_called_once()
    assert "Radarr is not configured" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
def test_handle_radarr_workflow_empty_query(mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "   " # Empty search query
    handle_radarr_workflow()
    mock_ask.assert_called_once()

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_api_error(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "Inception"
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.side_effect = ArrAPIError("Radarr offline error")
    
    handle_radarr_workflow()
    assert "Error communicating with Radarr" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_no_results(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "NonexistentMovie"
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = []
    
    handle_radarr_workflow()
    assert "No movies found matching that term." in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_missing_configs(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.return_value = "Inception"
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception"}]
    client_inst.get_quality_profiles.return_value = [] # Missing profiles
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert "Could not retrieve required quality profiles" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_cancel_selection(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "c"]
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception", "year": 2010}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert client_inst.add_movie.call_count == 0

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_invalid_selection(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "invalid_indices"]
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception", "year": 2010}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert any("No valid selections made" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_all_already_added(mock_radarr, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Inception", "1"]
    
    client_inst = mock_radarr.return_value
    client_inst.lookup_movie.return_value = [{"title": "Inception", "year": 2010, "id": 123}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/movies"}]
    
    handle_radarr_workflow()
    assert any("No new movies selected to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.RadarrClient")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
def test_handle_sonarr_workflow_unconfigured(mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = False
    handle_sonarr_workflow()
    assert "Sonarr is not configured" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
def test_handle_sonarr_workflow_empty_query(mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = ""
    handle_sonarr_workflow()
    mock_ask.assert_called_once()

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_api_error(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = "Rivals"
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.side_effect = ArrAPIError("Sonarr offline error")
    
    handle_sonarr_workflow()
    assert "Error communicating with Sonarr" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_no_results(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = "NonexistentShow"
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = []
    
    handle_sonarr_workflow()
    assert "No TV shows found matching that term." in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_missing_configs(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.return_value = "Rivals"
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals"}]
    client_inst.get_quality_profiles.return_value = []
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert "Could not retrieve required quality profiles" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_cancel_selection(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "c"]
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals", "year": 2026}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert client_inst.add_series.call_count == 0

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_invalid_selection(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "invalid_indices"]
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals", "year": 2026}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert any("No valid selections made" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_all_already_added(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "1"]
    
    client_inst = mock_sonarr.return_value
    client_inst.lookup_series.return_value = [{"title": "Rivals", "year": 2026, "id": 123}]
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    handle_sonarr_workflow()
    assert any("No new series selected to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.SonarrClient")
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
    
    # 1. Folder, 2. Profile
    mock_select.side_effect = [{"path": "/tv"}, {"id": 1, "name": "HD"}]
    
    client_inst.add_series.return_value = {"title": "Rivals"}
    
    handle_sonarr_workflow()
    
    client_inst.add_series.assert_called_once_with(
        series_data=shows[0],
        quality_profile_id=1,
        root_folder_path="/tv",
        monitored=True,
        search_now=True
    )
    assert any("Successfully added" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_add_failure(mock_sonarr, mock_print, mock_ask, mock_config):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Rivals", "1"]
    
    client_inst = mock_sonarr.return_value
    shows = [{"title": "Rivals", "year": 2026, "tvdbId": 11}]
    client_inst.lookup_series.return_value = shows
    client_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    client_inst.get_root_folders.return_value = [{"path": "/tv"}]
    
    # 1. Folder, 2. Profile
    with patch("xarrtools.cli.cli.select_from_list") as mock_select, \
         patch("xarrtools.cli.cli.Confirm.ask", return_value=True):
        mock_select.side_effect = [{"path": "/tv"}, {"id": 1, "name": "HD"}]
        client_inst.add_series.side_effect = ArrAPIError("Sonarr add failed")
        handle_sonarr_workflow()
        
    assert client_inst.add_series.call_count == 1
    assert any("Failed to add" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
def test_handle_discovery_workflow_no_releases(mock_get_disc, mock_print, mock_ask, mock_config):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True
    
    mock_ask.return_value = "2" # Timeframe
    mock_get_disc.return_value = ([], []) # No TV shows or movies
    
    handle_discovery_workflow()
    assert "No new releases found" in mock_print.call_args[0][0]

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
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
    
    with patch("xarrtools.cli.cli.RadarrClient") as mock_radarr:
        radarr_inst = mock_radarr.return_value
        radarr_inst.lookup_movie.return_value = [] # Missing raw_metadata lookup yields empty
        handle_discovery_workflow()
        
    assert any("Skipping 'Show Library' (already in library)" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Could not find 'Movie Empty'" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
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

@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.clear")
@patch("xarrtools.cli.cli.show_config_status")
@patch("xarrtools.cli.cli.handle_radarr_workflow")
@patch("xarrtools.cli.cli.handle_sonarr_workflow")
@patch("xarrtools.cli.cli.handle_discovery_workflow")
@patch("xarrtools.cli.cli.console.print")
def test_run_cli_menu_loop_with_invalid_options(
    mock_print, mock_discovery, mock_sonarr, mock_radarr, mock_status, mock_clear, mock_ask
):
    # Choice side effects:
    # 1. "invalid" choice -> prompts choice again
    # 2. "6" -> exit menu loop
    mock_ask.side_effect = ["invalid", "6"]
    run_cli()
    
    # Verify exit message printed
    assert any("Goodbye!" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert mock_clear.call_count == 2

@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.clear")
@patch("xarrtools.cli.cli.show_config_status")
@patch("xarrtools.cli.cli.handle_radarr_workflow")
@patch("xarrtools.cli.cli.handle_sonarr_workflow")
@patch("xarrtools.cli.cli.handle_discovery_workflow")
@patch("xarrtools.cli.cli.console.print")
def test_run_cli_menu_options_1_2_3(
    mock_print, mock_discovery, mock_sonarr, mock_radarr, mock_status, mock_clear, mock_ask
):
    # Side effects:
    # - choice "1", then return to menu
    # - choice "2", then return to menu
    # - choice "3", then return to menu
    # - choice "6" (exit)
    mock_ask.side_effect = ["1", "", "2", "", "3", "", "6"]
    run_cli()
    mock_radarr.assert_called_once()
    mock_sonarr.assert_called_once()
    mock_discovery.assert_called_once()

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.RadarrClient")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
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

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_discovery_workflow_bulk_failures(
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
    sonarr_inst.add_series.side_effect = ArrAPIError("Sonarr Disk error")
    
    radarr_inst = mock_radarr.return_value
    radarr_inst.get_quality_profiles.return_value = [{"id": 2, "name": "HD"}]
    radarr_inst.get_root_folders.return_value = [{"path": "/movies"}]
    radarr_inst.add_movie.side_effect = ArrAPIError("Radarr Disk error")
    
    mock_select.side_effect = [
        {"path": "/tv"}, {"id": 1, "name": "HD"}, # TV selection
        {"path": "/movies"}, {"id": 2, "name": "HD"} # Movie selection
    ]
    
    handle_discovery_workflow()
    
    # Assert bulk adding failures logged
    assert any("Failed to add 'Show Fail': Sonarr Disk error" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    assert any("Failed to add 'Movie Fail': Radarr Disk error" in str(call[0][0]) for call in mock_print.call_args_list if call[0])

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_movie")
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


@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
def test_handle_export_and_import_workflows(mock_print, mock_confirm, mock_ask):
    from xarrtools.cli.cli import handle_export_workflow, handle_import_workflow
    import tempfile
    import os
    
    # 1. Test Export Workflow
    mock_confirm.return_value = True # include_media = True
    
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_file = os.path.join(tmpdir, "backup.json")
        mock_ask.return_value = dest_file
        
        with patch("xarrtools.core.db.export_to_dict", return_value={"settings": {"test_key": "val"}, "media_items": []}) as mock_export:
            handle_export_workflow()
            mock_export.assert_called_once_with(include_media=True)
            
        assert os.path.exists(dest_file)
        with open(dest_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
            assert saved_data["settings"]["test_key"] == "val"
            
    # 2. Test Import Workflow
    mock_ask.side_effect = ["nonexistent_backup.json", dest_file]
    handle_import_workflow() # Should print file does not exist
    assert any("does not exist" in str(call[0][0]) for call in mock_print.call_args_list if call[0])
    
    # Prepare valid file and import
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_file = os.path.join(tmpdir, "backup.json")
        with open(dest_file, "w", encoding="utf-8") as f:
            json.dump({"settings": {"test_key": "val"}}, f)
            
        mock_ask.side_effect = [dest_file]
        with patch("xarrtools.core.db.import_from_dict", return_value=(1, 0)) as mock_import:
            handle_import_workflow()
            mock_import.assert_called_once()
            
        assert any("Successfully imported backup" in str(call[0][0]) for call in mock_print.call_args_list if call[0])


# ==============================================================================
# Milestone 2: Hybrid Preset Resolution & MRU Persistence Unit Tests
# ==============================================================================

@patch("xarrtools.cli.cli.IntPrompt.ask")
@patch("xarrtools.cli.cli.console.print")
def test_select_from_list_default_index_and_clamping(mock_print, mock_ask):
    items = [{"name": "Profile A"}, {"name": "Profile B"}, {"name": "Profile C"}]

    # 1. Valid custom default_index (1-based index 2)
    mock_ask.return_value = 2
    res = select_from_list("Select Option", items, "name", default_index=2)
    assert res == items[1]
    mock_ask.assert_called_with("Select Option", default=2)

    # 2. Out-of-bounds low (0 or negative) clamped to 1
    mock_ask.return_value = 1
    res = select_from_list("Select Option", items, "name", default_index=0)
    assert res == items[0]
    mock_ask.assert_called_with("Select Option", default=1)

    mock_ask.return_value = 1
    res = select_from_list("Select Option", items, "name", default_index=-3)
    assert res == items[0]
    mock_ask.assert_called_with("Select Option", default=1)

    # 3. Out-of-bounds high (> len(items)) clamped to 1
    mock_ask.return_value = 1
    res = select_from_list("Select Option", items, "name", default_index=10)
    assert res == items[0]
    mock_ask.assert_called_with("Select Option", default=1)

    # 4. Non-integer default_index clamped to 1
    mock_ask.return_value = 1
    res = select_from_list("Select Option", items, "name", default_index="invalid")
    assert res == items[0]
    mock_ask.assert_called_with("Select Option", default=1)

    # 5. Empty items list returns empty dict
    res_empty = select_from_list("Select Option", [], "name")
    assert res_empty == {}


def test_resolve_preset_index_unit():
    profiles = [
        {"id": 1, "name": "HD - 720p"},
        {"id": 2, "name": "Ultra-HD 4K"},
        {"id": 3, "name": "Any"}
    ]
    folders = [
        {"id": 10, "path": "/data/media/movies"},
        {"id": 20, "path": "/data/media/4k_movies"}
    ]

    # 1. Empty items returns 1
    assert resolve_preset_index([], "id", ["explicit"], ["mru"]) == 1

    # 2. Explicit match by ID (string or int)
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "2" if k == "exp_prof" else ""):
        idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
        assert idx == 2

    # 3. Explicit match by Name (case-insensitive)
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "ultra-hd 4k" if k == "exp_prof" else ""):
        idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
        assert idx == 2

    # 4. Explicit match by Path (with trailing slash difference)
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "/data/media/4k_movies/" if k == "exp_folder" else ""):
        idx = resolve_preset_index(folders, key_field="path", explicit_keys=["exp_folder"], mru_keys=["mru_folder"])
        assert idx == 2

    # 5. Explicit match by custom key
    custom_items = [{"tag": "standard"}, {"tag": "premium"}]
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "premium" if k == "exp_tag" else ""):
        idx = resolve_preset_index(custom_items, key_field="tag", explicit_keys=["exp_tag"], mru_keys=["mru_tag"])
        assert idx == 2

    # 6. MRU fallback when explicit is not set
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "3" if k == "mru_prof" else ""):
        idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
        assert idx == 3

    # 7. Fallback to MRU when explicit ID is invalid/deleted
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "999" if k == "exp_prof" else ("2" if k == "mru_prof" else "")):
        idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
        assert idx == 2

    # 8. Safety fallback when both explicit and MRU are invalid/missing
    with patch("xarrtools.cli.cli.get_setting", side_effect=lambda k, d="": "999" if k == "exp_prof" else ("888" if k == "mru_prof" else "")):
        idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
        assert idx == 1

    with patch("xarrtools.cli.cli.get_setting", return_value=""):
        idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
        assert idx == 1

    # 9. Exception in get_setting falls back to config or safety fallback 1
    with patch("xarrtools.cli.cli.get_setting", side_effect=Exception("DB locked")):
        with patch("xarrtools.cli.cli.config") as mock_conf:
            mock_conf.exp_prof = "2"
            idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
            assert idx == 2

    with patch("xarrtools.cli.cli.get_setting", side_effect=Exception("DB locked")):
        with patch("xarrtools.cli.cli.config") as mock_conf:
            mock_conf.exp_prof = ""
            mock_conf.mru_prof = ""
            idx = resolve_preset_index(profiles, key_field="id", explicit_keys=["exp_prof"], mru_keys=["mru_prof"])
            assert idx == 1


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_hybrid_presets_explicit(
    mock_radarr, mock_get_setting, mock_set_setting, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Matrix", "1"]
    mock_confirm.side_effect = [True, True]

    client_inst = mock_radarr.return_value
    movies = [{"title": "The Matrix", "year": 1999, "tmdbId": 603}]
    client_inst.lookup_movie.return_value = movies
    folders = [{"path": "/movies/standard"}, {"path": "/movies/4k"}]
    profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "Ultra-HD"}]
    client_inst.get_root_folders.return_value = folders
    client_inst.get_quality_profiles.return_value = profiles

    # Explicit settings configured for 2nd folder and 2nd profile
    def get_setting_side_effect(key, default=""):
        if key == "radarr_default_root_folder":
            return "/movies/4k"
        if key == "radarr_default_quality_profile":
            return "2"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect
    mock_select.side_effect = [folders[1], profiles[1]]
    client_inst.add_movie.return_value = {"title": "The Matrix"}

    handle_radarr_workflow()

    # Verify select_from_list was called with default_index=2 for both
    assert mock_select.call_args_list[0][1]["default_index"] == 2
    assert mock_select.call_args_list[1][1]["default_index"] == 2

    # Verify MRU settings updated upon successful addition
    mock_set_setting.assert_any_call("radarr_mru_quality_profile", "2")
    mock_set_setting.assert_any_call("radarr_mru_root_folder", "/movies/4k")


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_hybrid_presets_mru_fallback(
    mock_radarr, mock_get_setting, mock_set_setting, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Matrix", "1"]
    mock_confirm.side_effect = [True, True]

    client_inst = mock_radarr.return_value
    movies = [{"title": "The Matrix", "year": 1999, "tmdbId": 603}]
    client_inst.lookup_movie.return_value = movies
    folders = [{"path": "/movies/standard"}, {"path": "/movies/4k"}]
    profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "Ultra-HD"}]
    client_inst.get_root_folders.return_value = folders
    client_inst.get_quality_profiles.return_value = profiles

    # No explicit settings, but MRU set for 2nd folder and 2nd profile
    def get_setting_side_effect(key, default=""):
        if key == "radarr_mru_root_folder":
            return "/movies/4k"
        if key == "radarr_mru_quality_profile":
            return "2"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect
    mock_select.side_effect = [folders[1], profiles[1]]
    client_inst.add_movie.return_value = {"title": "The Matrix"}

    handle_radarr_workflow()

    assert mock_select.call_args_list[0][1]["default_index"] == 2
    assert mock_select.call_args_list[1][1]["default_index"] == 2


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.RadarrClient")
def test_handle_radarr_workflow_hybrid_presets_invalid_fallback(
    mock_radarr, mock_get_setting, mock_set_setting, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_ask.side_effect = ["Matrix", "1"]
    mock_confirm.side_effect = [True, True]

    client_inst = mock_radarr.return_value
    movies = [{"title": "The Matrix", "year": 1999, "tmdbId": 603}]
    client_inst.lookup_movie.return_value = movies
    folders = [{"path": "/movies/standard"}, {"path": "/movies/4k"}]
    profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "Ultra-HD"}]
    client_inst.get_root_folders.return_value = folders
    client_inst.get_quality_profiles.return_value = profiles

    # Invalid / deleted folder and profile IDs
    def get_setting_side_effect(key, default=""):
        if key in ("radarr_default_root_folder", "radarr_mru_root_folder"):
            return "/nonexistent/path"
        if key in ("radarr_default_quality_profile", "radarr_mru_quality_profile"):
            return "999"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect
    mock_select.side_effect = [folders[0], profiles[0]]
    client_inst.add_movie.return_value = {"title": "The Matrix"}

    handle_radarr_workflow()

    # Should safely fall back to default_index=1
    assert mock_select.call_args_list[0][1]["default_index"] == 1
    assert mock_select.call_args_list[1][1]["default_index"] == 1


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_hybrid_presets_explicit(
    mock_sonarr, mock_get_setting, mock_set_setting, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Severance", "1"]
    mock_confirm.side_effect = [True, True]

    client_inst = mock_sonarr.return_value
    shows = [{"title": "Severance", "year": 2022, "tvdbId": 371980}]
    client_inst.lookup_series.return_value = shows
    folders = [{"path": "/tv/standard"}, {"path": "/tv/4k"}]
    profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "Ultra-HD"}]
    client_inst.get_root_folders.return_value = folders
    client_inst.get_quality_profiles.return_value = profiles

    # Explicit settings configured for 2nd folder and 2nd profile
    def get_setting_side_effect(key, default=""):
        if key == "sonarr_default_root_folder":
            return "/tv/4k"
        if key == "sonarr_default_quality_profile":
            return "2"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect
    mock_select.side_effect = [folders[1], profiles[1]]
    client_inst.add_series.return_value = {"title": "Severance"}

    handle_sonarr_workflow()

    assert mock_select.call_args_list[0][1]["default_index"] == 2
    assert mock_select.call_args_list[1][1]["default_index"] == 2

    # Verify MRU updated
    mock_set_setting.assert_any_call("sonarr_mru_quality_profile", "2")
    mock_set_setting.assert_any_call("sonarr_mru_root_folder", "/tv/4k")


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_hybrid_presets_mru_fallback(
    mock_sonarr, mock_get_setting, mock_set_setting, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Severance", "1"]
    mock_confirm.side_effect = [True, True]

    client_inst = mock_sonarr.return_value
    shows = [{"title": "Severance", "year": 2022, "tvdbId": 371980}]
    client_inst.lookup_series.return_value = shows
    folders = [{"path": "/tv/standard"}, {"path": "/tv/4k"}]
    profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "Ultra-HD"}]
    client_inst.get_root_folders.return_value = folders
    client_inst.get_quality_profiles.return_value = profiles

    # No explicit, but MRU configured
    def get_setting_side_effect(key, default=""):
        if key == "sonarr_mru_root_folder":
            return "/tv/4k"
        if key == "sonarr_mru_quality_profile":
            return "2"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect
    mock_select.side_effect = [folders[1], profiles[1]]
    client_inst.add_series.return_value = {"title": "Severance"}

    handle_sonarr_workflow()

    assert mock_select.call_args_list[0][1]["default_index"] == 2
    assert mock_select.call_args_list[1][1]["default_index"] == 2


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_sonarr_workflow_hybrid_presets_invalid_fallback(
    mock_sonarr, mock_get_setting, mock_set_setting, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_sonarr.return_value = True
    mock_ask.side_effect = ["Severance", "1"]
    mock_confirm.side_effect = [True, True]

    client_inst = mock_sonarr.return_value
    shows = [{"title": "Severance", "year": 2022, "tvdbId": 371980}]
    client_inst.lookup_series.return_value = shows
    folders = [{"path": "/tv/standard"}, {"path": "/tv/4k"}]
    profiles = [{"id": 1, "name": "HD"}, {"id": 2, "name": "Ultra-HD"}]
    client_inst.get_root_folders.return_value = folders
    client_inst.get_quality_profiles.return_value = profiles

    # Invalid / deleted folder and profile IDs
    def get_setting_side_effect(key, default=""):
        if key in ("sonarr_default_root_folder", "sonarr_mru_root_folder"):
            return "/deleted/path"
        if key in ("sonarr_default_quality_profile", "sonarr_mru_quality_profile"):
            return "999"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect
    mock_select.side_effect = [folders[0], profiles[0]]
    client_inst.add_series.return_value = {"title": "Severance"}

    handle_sonarr_workflow()

    assert mock_select.call_args_list[0][1]["default_index"] == 1
    assert mock_select.call_args_list[1][1]["default_index"] == 1


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.set_setting")
@patch("xarrtools.cli.cli.get_setting")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_discovery_workflow_presets_and_mru_persistence(
    mock_sonarr, mock_radarr, mock_get_setting, mock_set_setting,
    mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_select,
    mock_print, mock_confirm, mock_ask, mock_config
):
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True

    mock_ask.side_effect = ["2", "all"]
    mock_confirm.side_effect = [True, True, True, True]

    from datetime import datetime
    tv_raw = [{"title": "Disc Show", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30"}]
    movie_raw = [{"title": "Disc Movie", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)

    mock_enrich_tv.return_value = {
        "title": "Disc Show", "year": 2026, "plot": "TV Plot", "cast": "Cast",
        "genres": ["Drama"], "trailer": "http://youtube", "tvdbId": 101,
        "imdbId": "tt101", "is_in_library": False, "raw_metadata": {"title": "Disc Show", "id": None}
    }
    mock_enrich_movie.return_value = {
        "title": "Disc Movie", "year": 2026, "plot": "Movie Plot", "cast": "Cast",
        "genres": ["Action"], "trailer": "http://youtube", "tmdbId": 202,
        "imdbId": "tt202", "is_in_library": False, "raw_metadata": {"title": "Disc Movie", "id": None}
    }

    sonarr_inst = mock_sonarr.return_value
    sonarr_folders = [{"path": "/tv/1"}, {"path": "/tv/2"}]
    sonarr_profiles = [{"id": 10, "name": "TV HD"}, {"id": 20, "name": "TV 4K"}]
    sonarr_inst.get_quality_profiles.return_value = sonarr_profiles
    sonarr_inst.get_root_folders.return_value = sonarr_folders
    sonarr_inst.add_series.return_value = {"title": "Disc Show"}

    radarr_inst = mock_radarr.return_value
    radarr_folders = [{"path": "/movies/1"}, {"path": "/movies/2"}]
    radarr_profiles = [{"id": 30, "name": "Movie HD"}, {"id": 40, "name": "Movie 4K"}]
    radarr_inst.get_quality_profiles.return_value = radarr_profiles
    radarr_inst.get_root_folders.return_value = radarr_folders
    radarr_inst.add_movie.return_value = {"title": "Disc Movie"}

    def get_setting_side_effect(key, default=""):
        if key == "sonarr_default_root_folder":
            return "/tv/2"
        if key == "sonarr_default_quality_profile":
            return "20"
        if key == "radarr_mru_root_folder":
            return "/movies/2"
        if key == "radarr_mru_quality_profile":
            return "40"
        return ""

    mock_get_setting.side_effect = get_setting_side_effect

    mock_select.side_effect = [
        sonarr_folders[1], sonarr_profiles[1], # TV
        radarr_folders[1], radarr_profiles[1]  # Movie
    ]

    handle_discovery_workflow()

    # TV: default_index should be 2 for both folder and profile (from explicit default)
    assert mock_select.call_args_list[0][1]["default_index"] == 2
    assert mock_select.call_args_list[1][1]["default_index"] == 2

    # Movie: default_index should be 2 for both folder and profile (from MRU fallback)
    assert mock_select.call_args_list[2][1]["default_index"] == 2
    assert mock_select.call_args_list[3][1]["default_index"] == 2

    # Verify MRU updates
    mock_set_setting.assert_any_call("sonarr_mru_quality_profile", "20")
    mock_set_setting.assert_any_call("sonarr_mru_root_folder", "/tv/2")
    mock_set_setting.assert_any_call("radarr_mru_quality_profile", "40")
    mock_set_setting.assert_any_call("radarr_mru_root_folder", "/movies/2")


# ==============================================================================
# Milestone 2: Discovery Workflow with has_new_metadata & Low-Metadata Releases
# ==============================================================================

@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
def test_handle_discovery_workflow_with_has_new_metadata_cleanly(
    mock_enrich_movie, mock_enrich_tv, mock_get_disc, mock_print, mock_ask, mock_config
):
    """Verifies that CLI discovery workflow handles items with has_new_metadata cleanly."""
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True

    # 1. Timeframe = "2"
    # 2. Selection = "c" (cancel after listing)
    mock_ask.side_effect = ["2", "c"]

    from datetime import datetime
    tv_raw = [{"title": "Badge Show", "date_obj": datetime(2026, 5, 30), "description": "TV Plot", "date_str": "May 30", "is_returning": False}]
    movie_raw = [{"title": "Badge Movie", "date_obj": datetime(2026, 5, 30), "description": "Movie Plot", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)

    mock_enrich_tv.return_value = {
        "title": "Badge Show", "year": 2026, "plot": "Enriched TV Plot", "cast": "Star A, Star B",
        "genres": ["Drama"], "trailer": "http://youtube/tv", "tvdbId": 12,
        "imdbId": "tt12", "network": "HBO", "is_in_library": True,
        "has_new_metadata": True, "is_archived": False, "raw_metadata": {"title": "Badge Show"}
    }
    mock_enrich_movie.return_value = {
        "title": "Badge Movie", "year": 2026, "plot": "Enriched Movie Plot", "cast": "Star C",
        "genres": ["Action"], "trailer": "http://youtube/movie", "tmdbId": 34,
        "imdbId": "tt34", "network": "Paramount", "is_in_library": True,
        "has_new_metadata": True, "is_archived": False, "raw_metadata": {"title": "Badge Movie"}
    }

    handle_discovery_workflow()

    # Assert that titles were rendered to console without error and with tags
    printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
    assert any("TV SHOW: Badge Show (2026)" in t and "[New metadata]" in t and "(In Library)" in t for t in printed_texts)
    assert any("MOVIE: Badge Movie (2026)" in t and "[New metadata]" in t and "(In Library)" in t for t in printed_texts)


@patch("xarrtools.cli.cli.config")
@patch("xarrtools.cli.cli.Prompt.ask")
@patch("xarrtools.cli.cli.Confirm.ask")
@patch("xarrtools.cli.cli.console.print")
@patch("xarrtools.cli.cli.select_from_list")
@patch("xarrtools.cli.cli.get_discoveries")
@patch("xarrtools.cli.cli.enrich_tv_show")
@patch("xarrtools.cli.cli.enrich_movie")
@patch("xarrtools.cli.cli.RadarrClient")
@patch("xarrtools.cli.cli.SonarrClient")
def test_handle_discovery_workflow_auto_archived_low_metadata_selection(
    mock_sonarr, mock_radarr, mock_enrich_movie, mock_enrich_tv,
    mock_get_disc, mock_select, mock_print, mock_confirm, mock_ask, mock_config
):
    """Verifies that CLI discovery workflow handles auto-archived/low-metadata items during bulk addition."""
    mock_config.validate_radarr.return_value = True
    mock_config.validate_sonarr.return_value = True

    # 1. Timeframe = "2", 2. Selection = "1, 2"
    mock_ask.side_effect = ["2", "1, 2"]
    mock_confirm.side_effect = [True, True, True, True]

    from datetime import datetime
    tv_raw = [{"title": "Low Meta TV Show", "date_obj": datetime(2026, 5, 30), "description": "Scraped Desc", "date_str": "May 30", "is_returning": False}]
    movie_raw = [{"title": "Low Meta Film", "date_obj": datetime(2026, 5, 30), "description": "Scraped Desc", "date_str": "May 30"}]
    mock_get_disc.return_value = (tv_raw, movie_raw)

    # Mock enrichment returning low metadata (auto-archived items)
    mock_enrich_tv.return_value = {
        "title": "Low Meta TV Show", "year": 2026, "plot": "", "cast": "Cast details not available.",
        "genres": [], "trailer": "", "tvdbId": None, "imdbId": None, "network": "Unknown",
        "is_in_library": False, "is_archived": True, "has_new_metadata": False, "raw_metadata": None
    }
    mock_enrich_movie.return_value = {
        "title": "Low Meta Film", "year": 2026, "plot": "", "cast": "Cast details not available.",
        "genres": [], "trailer": "", "tmdbId": None, "imdbId": None, "network": "Unknown",
        "is_in_library": False, "is_archived": True, "has_new_metadata": False, "raw_metadata": None
    }

    sonarr_inst = mock_sonarr.return_value
    sonarr_inst.lookup_series.return_value = [{"title": "Low Meta TV Show", "id": None}]
    sonarr_inst.get_quality_profiles.return_value = [{"id": 1, "name": "HD"}]
    sonarr_inst.get_root_folders.return_value = [{"path": "/tv"}]
    sonarr_inst.add_series.return_value = {"title": "Low Meta TV Show"}

    radarr_inst = mock_radarr.return_value
    radarr_inst.lookup_movie.return_value = [{"title": "Low Meta Film", "id": None}]
    radarr_inst.get_quality_profiles.return_value = [{"id": 2, "name": "HD"}]
    radarr_inst.get_root_folders.return_value = [{"path": "/movies"}]
    radarr_inst.add_movie.return_value = {"title": "Low Meta Film"}

    mock_select.side_effect = [
        {"path": "/tv"}, {"id": 1, "name": "HD"},
        {"path": "/movies"}, {"id": 2, "name": "HD"}
    ]

    handle_discovery_workflow()

    sonarr_inst.add_series.assert_called_once()
    radarr_inst.add_movie.assert_called_once()


