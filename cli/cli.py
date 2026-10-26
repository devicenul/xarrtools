import sys
import logging
import urllib.parse
from rich.console import Console

logger = logging.getLogger("xarrtools.cli")
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.panel import Panel
from rich.status import Status
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from core.config import config
from core.db import get_setting, set_setting
from core.client import RadarrClient, SonarrClient, ArrAPIError
from core.scraper import get_discoveries
from core.enricher import enrich_tv_show, enrich_movie

console = Console()

# Try to use unicode check/cross marks if supported by stdout encoding, fallback to ASCII indicators otherwise.
CHECK_MARK = "[green]✓[/green]"
CROSS_MARK = "[red]✗[/red]"
try:
    "✓".encode(sys.stdout.encoding or 'ascii')
except Exception:
    CHECK_MARK = "[green]V[/green]"
    CROSS_MARK = "[red]X[/red]"


def parse_indices(selection_str: str, max_val: int) -> list:
    """Parses selection string like '1, 3' or '1-3' or 'all' into 0-indexed integers."""
    selection_str = selection_str.strip().lower()
    if not selection_str:
        return []
    
    if selection_str == "all":
        return list(range(max_val))
        
    indices = set()
    parts = [p.strip() for p in selection_str.split(",")]
    for part in parts:
        if "-" in part:
            try:
                start, end = part.split("-")
                start_val = int(start.strip())
                end_val = int(end.strip())
                # Boundary clamping
                start_val = max(1, start_val)
                end_val = min(max_val, end_val)
                for i in range(start_val, end_val + 1):
                    indices.add(i - 1)
            except ValueError:
                pass
        else:
            try:
                val = int(part)
                if 1 <= val <= max_val:
                    indices.add(val - 1)
            except ValueError:
                pass
    return sorted(list(indices))

def show_config_status():
    """Renders a panel showing connection status to Sonarr/Radarr."""
    radarr_ok = config.validate_radarr()
    sonarr_ok = config.validate_sonarr()

    status_lines = []
    
    if radarr_ok:
        status_lines.append(f"{CHECK_MARK} [bold]Radarr[/bold]: Configured ([cyan]" + config.radarr_url + "[/cyan])")
    else:
        status_lines.append(f"{CROSS_MARK} [bold]Radarr[/bold]: Not Configured (Missing: " + ", ".join(config.get_missing_radarr_vars()) + ")")
        
    if sonarr_ok:
        status_lines.append(f"{CHECK_MARK} [bold]Sonarr[/bold]: Configured ([cyan]" + config.sonarr_url + "[/cyan])")
    else:
        status_lines.append(f"{CROSS_MARK} [bold]Sonarr[/bold]: Not Configured (Missing: " + ", ".join(config.get_missing_sonarr_vars()) + ")")

    console.print(Panel("\n".join(status_lines), title="[bold white]Service Status[/bold white]", expand=False))

def resolve_preset_index(
    items: list,
    key_field: str,
    explicit_keys: list,
    mru_keys: list
) -> int:
    """
    Resolves the 1-based index for default selection from items using a 3-tier hybrid strategy:
    1. Explicit Default: Look up explicit settings keys. If set and matches an item, return its 1-based index.
    2. MRU Fallback: Look up MRU settings keys. If set and matches an item, return its 1-based index.
    3. Safety Fallback: Default to index 1.
    Gracefully handles invalid/missing settings or deleted item IDs/paths.
    """
    if not items:
        return 1

    def _get_val(keys: list) -> str:
        for k in keys:
            try:
                val = get_setting(k, "")
                if val:
                    return str(val).strip()
            except Exception:
                pass
            val = getattr(config, k, "")
            if val:
                return str(val).strip()
        return ""

    def _find_index(val: str) -> int:
        if not val:
            return -1
        for idx, item in enumerate(items, 1):
            if key_field == "id":
                if str(item.get("id")) == val or str(item.get("name", "")).strip().lower() == val.lower():
                    return idx
            elif key_field == "path":
                item_path = str(item.get("path", "")).rstrip("/\\").lower()
                val_path = val.rstrip("/\\").lower()
                if item_path == val_path or str(item.get("path")) == val or str(item.get("id")) == val:
                    return idx
            else:
                if str(item.get(key_field)) == val:
                    return idx
        return -1

    # 1. Primary: Explicit Default
    explicit_val = _get_val(explicit_keys)
    idx = _find_index(explicit_val)
    if idx != -1:
        return idx

    # 2. Fallback: MRU Setting
    mru_val = _get_val(mru_keys)
    idx = _find_index(mru_val)
    if idx != -1:
        return idx

    # 3. Safety Fallback: Index 1
    return 1

def select_from_list(prompt_text: str, items: list, display_key: str = "name", default_index: int = 1) -> dict:
    """Uses a rich Table to let the user select a configuration parameter from a list."""
    if not items:
        return {}
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("No.", style="cyan", justify="right")
    table.add_column(display_key.capitalize(), style="white")

    for idx, item in enumerate(items, 1):
        table.add_row(str(idx), str(item.get(display_key, "N/A")))
        
    console.print(table)
    
    clamped_default = default_index if (isinstance(default_index, int) and 1 <= default_index <= len(items)) else 1

    while True:
        choice = IntPrompt.ask(prompt_text, default=clamped_default)
        if 1 <= choice <= len(items):
            return items[choice - 1]
        console.print("[red]Invalid selection. Please choose a valid index.[/red]")

def handle_radarr_workflow():
    if not config.validate_radarr():
        console.print("[red]Radarr is not configured! Please update your .env file.[/red]")
        return

    client = RadarrClient(config.radarr_url, config.radarr_api_key)
    query = Prompt.ask("\n[bold yellow]Search Movie (Radarr)[/bold yellow]")
    if not query.strip():
        return

    try:
        with console.status("[bold blue]Querying Radarr and fetching configuration...[/bold blue]"):
            results = client.lookup_movie(query)
            profiles = client.get_quality_profiles()
            folders = client.get_root_folders()
    except ArrAPIError as e:
        logger.error(f"Error communicating with Radarr: {e}")
        console.print(f"[red]Error communicating with Radarr: {e}[/red]")
        return

    if not results:
        console.print("[yellow]No movies found matching that term.[/yellow]")
        return

    if not profiles or not folders:
        console.print("[red]Could not retrieve required quality profiles or root folders from Radarr.[/red]")
        return

    table = Table(title=f"Radarr Search Results for '{query}'", show_header=True, header_style="bold cyan")
    table.add_column("No.", justify="right", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Year", style="yellow", justify="center")
    table.add_column("TMDB ID", style="blue")
    table.add_column("Library Status", style="green")

    for idx, movie in enumerate(results[:15], 1):
        in_lib_id = movie.get("id")
        status = f"[green]In Library (ID: {in_lib_id})[/green]" if in_lib_id else "[grey50]Not Added[/grey50]"
        table.add_row(
            str(idx),
            movie.get("title", "Unknown"),
            str(movie.get("year", "N/A")),
            str(movie.get("tmdbId", "N/A")),
            status
        )
    console.print(table)

    selection = Prompt.ask("\nSelect movie numbers to add (e.g. [cyan]1[/cyan], [cyan]1,3[/cyan], [cyan]2-4[/cyan], [cyan]all[/cyan], or [cyan]c[/cyan] to cancel)", default="c")
    if selection.lower() == 'c':
        return

    selected_indices = parse_indices(selection, len(results[:15]))
    if not selected_indices:
        console.print("[red]No valid selections made.[/red]")
        return

    movies_to_add = [results[i] for i in selected_indices]
    already_added = [m for m in movies_to_add if m.get("id")]
    to_add = [m for m in movies_to_add if not m.get("id")]

    if already_added:
        names = ", ".join(f"'{m['title']}'" for m in already_added)
        console.print(f"[yellow]Skipping already added movies: {names}[/yellow]")

    if not to_add:
        console.print("[yellow]No new movies selected to add.[/yellow]")
        return

    console.print(Panel(f"Adding [bold]{len(to_add)}[/bold] movies. Please select download options:", title="Options", expand=False))
    folder_default_idx = resolve_preset_index(
        folders,
        key_field="path",
        explicit_keys=["radarr_default_root_folder"],
        mru_keys=["radarr_mru_root_folder"]
    )
    profile_default_idx = resolve_preset_index(
        profiles,
        key_field="id",
        explicit_keys=["radarr_default_quality_profile", "radarr_default_profile_id"],
        mru_keys=["radarr_mru_quality_profile", "radarr_mru_profile_id"]
    )
    selected_folder = select_from_list("Select Root Path", folders, "path", default_index=folder_default_idx)
    selected_profile = select_from_list("Select Quality Profile", profiles, "name", default_index=profile_default_idx)
    
    monitored = Confirm.ask("Monitor these movies?", default=True)
    search_now = Confirm.ask("Search immediately on add?", default=True)

    for movie in to_add:
        try:
            with console.status(f"[bold blue]Adding '{movie['title']}' to Radarr...[/bold blue]"):
                res = client.add_movie(
                    movie_data=movie,
                    quality_profile_id=selected_profile["id"],
                    root_folder_path=selected_folder["path"],
                    monitored=monitored,
                    search_now=search_now
                )
            console.print(f"{CHECK_MARK} Successfully added [bold]'{res.get('title')}'[/bold]!")
            try:
                set_setting("radarr_mru_quality_profile", str(selected_profile["id"]))
                set_setting("radarr_mru_root_folder", str(selected_folder["path"]))
            except Exception:
                pass
        except ArrAPIError as e:
            console.print(f"{CROSS_MARK} Failed to add '{movie.get('title')}': {e}")

def handle_sonarr_workflow():
    if not config.validate_sonarr():
        console.print("[red]Sonarr is not configured! Please update your .env file.[/red]")
        return

    client = SonarrClient(config.sonarr_url, config.sonarr_api_key)
    query = Prompt.ask("\n[bold yellow]Search TV Show (Sonarr)[/bold yellow]")
    if not query.strip():
        return

    try:
        with console.status("[bold blue]Querying Sonarr and fetching configuration...[/bold blue]"):
            results = client.lookup_series(query)
            profiles = client.get_quality_profiles()
            folders = client.get_root_folders()
    except ArrAPIError as e:
        logger.error(f"Error communicating with Sonarr: {e}")
        console.print(f"[red]Error communicating with Sonarr: {e}[/red]")
        return

    if not results:
        console.print("[yellow]No TV shows found matching that term.[/yellow]")
        return

    if not profiles or not folders:
        console.print("[red]Could not retrieve required quality profiles or root folders from Sonarr.[/red]")
        return

    table = Table(title=f"Sonarr Search Results for '{query}'", show_header=True, header_style="bold cyan")
    table.add_column("No.", justify="right", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Year", style="yellow", justify="center")
    table.add_column("TVDB ID", style="blue")
    table.add_column("Library Status", style="green")

    for idx, series in enumerate(results[:15], 1):
        in_lib_id = series.get("id")
        status = f"[green]In Library (ID: {in_lib_id})[/green]" if in_lib_id else "[grey50]Not Added[/grey50]"
        table.add_row(
            str(idx),
            series.get("title", "Unknown"),
            str(series.get("year", "N/A")),
            str(series.get("tvdbId", "N/A")),
            status
        )
    console.print(table)

    selection = Prompt.ask("\nSelect show numbers to add (e.g. [cyan]1[/cyan], [cyan]1,3[/cyan], [cyan]2-4[/cyan], [cyan]all[/cyan], or [cyan]c[/cyan] to cancel)", default="c")
    if selection.lower() == 'c':
        return

    selected_indices = parse_indices(selection, len(results[:15]))
    if not selected_indices:
        console.print("[red]No valid selections made.[/red]")
        return

    shows_to_add = [results[i] for i in selected_indices]
    already_added = [s for s in shows_to_add if s.get("id")]
    to_add = [s for s in shows_to_add if not s.get("id")]

    if already_added:
        names = ", ".join(f"'{m['title']}'" for m in already_added)
        console.print(f"[yellow]Skipping already added shows: {names}[/yellow]")

    if not to_add:
        console.print("[yellow]No new series selected to add.[/yellow]")
        return

    console.print(Panel(f"Adding [bold]{len(to_add)}[/bold] series. Please select download options:", title="Options", expand=False))
    folder_default_idx = resolve_preset_index(
        folders,
        key_field="path",
        explicit_keys=["sonarr_default_root_folder"],
        mru_keys=["sonarr_mru_root_folder"]
    )
    profile_default_idx = resolve_preset_index(
        profiles,
        key_field="id",
        explicit_keys=["sonarr_default_quality_profile", "sonarr_default_profile_id"],
        mru_keys=["sonarr_mru_quality_profile", "sonarr_mru_profile_id"]
    )
    selected_folder = select_from_list("Select Root Path", folders, "path", default_index=folder_default_idx)
    selected_profile = select_from_list("Select Quality Profile", profiles, "name", default_index=profile_default_idx)

    monitored = Confirm.ask("Monitor this series?", default=True)
    search_now = Confirm.ask("Search immediately on add?", default=True)

    for series in to_add:
        try:
            with console.status(f"[bold blue]Adding '{series['title']}' to Sonarr...[/bold blue]"):
                res = client.add_series(
                    series_data=series,
                    quality_profile_id=selected_profile["id"],
                    root_folder_path=selected_folder["path"],
                    monitored=monitored,
                    search_now=search_now
                )
            console.print(f"{CHECK_MARK} Successfully added [bold]'{res.get('title')}'[/bold]!")
            try:
                set_setting("sonarr_mru_quality_profile", str(selected_profile["id"]))
                set_setting("sonarr_mru_root_folder", str(selected_folder["path"]))
            except Exception:
                pass
        except ArrAPIError as e:
            console.print(f"{CROSS_MARK} Failed to add '{series.get('title')}': {e}")

def handle_discovery_workflow():
    """Runs the Metacritic scraper and TVMaze/Radarr enrichment to find and add new releases."""
    console.print("\n[bold yellow]=== Discover New Releases ===[/bold yellow]")
    
    # 1. Ask for Timeframe
    timeframe_months = Prompt.ask("Enter timeframe in months (e.g. 1, 2, 3)", default="2")
    try:
        months = int(timeframe_months)
        days_window = months * 30
    except ValueError:
        console.print("[red]Invalid value. Defaulting to 2 months (60 days).[/red]")
        days_window = 60

    # Initialize clients if configured
    radarr_client = None
    if config.validate_radarr():
        radarr_client = RadarrClient(config.radarr_url, config.radarr_api_key)
        
    sonarr_client = None
    if config.validate_sonarr():
        sonarr_client = SonarrClient(config.sonarr_url, config.sonarr_api_key)

    # 2. Scrape Metacritic
    with console.status("[bold blue]Scraping Metacritic new releases...[/bold blue]"):
        tv_releases, movie_releases = get_discoveries(past_days=days_window, future_days=7)
        
    total_found = len(tv_releases) + len(movie_releases)
    if total_found == 0:
        console.print("[yellow]No new releases found in the specified timeframe.[/yellow]")
        return
        
    console.print(f"[green]Scraped Metacritic successfully! Found {len(tv_releases)} TV shows and {len(movie_releases)} movies.[/green]")

    # 3. Enrich with progress bar
    enriched_tv = []
    enriched_movies = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        # TV Shows Task
        if tv_releases:
            tv_task = progress.add_task("[blue]Enriching TV shows...[/blue]", total=len(tv_releases))
            for item in tv_releases:
                if item.get("is_returning", False):
                    progress.advance(tv_task)
                    continue
                try:
                    data = enrich_tv_show(item["title"], item["date_obj"].year, sonarr_client)
                    # Preserve Metacritic date and plot if TVMaze plot is empty
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    data["date_str"] = item["date_str"]
                    enriched_tv.append(data)
                except Exception as e:
                    item["year"] = item["date_obj"].year
                    item["plot"] = item["description"]
                    item["cast"] = "Error getting details."
                    item["genres"] = []
                    item["trailer"] = f"https://www.youtube.com/results?search_query={urllib.parse.quote(item['title'] + ' trailer')}"
                    item["tvdbId"] = None
                    item["is_in_library"] = False
                    item["raw_metadata"] = None
                    enriched_tv.append(item)
                progress.advance(tv_task)

        # Movies Task
        if movie_releases:
            movie_task = progress.add_task("[green]Enriching movies...[/green]", total=len(movie_releases))
            for item in movie_releases:
                try:
                    extra = {"tmdb_id": item["tmdbId"]} if item.get("tmdbId") else {}
                    data = enrich_movie(item["title"], item["date_obj"].year, radarr_client, item.get("imdbId"), **extra)
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    data["date_str"] = item["date_str"]
                    if "imdbId" not in data or not data["imdbId"]:
                        data["imdbId"] = item.get("imdbId")
                    enriched_movies.append(data)
                except Exception as e:
                    item["year"] = item["date_obj"].year
                    item["plot"] = item["description"]
                    item["cast"] = "Error getting details."
                    item["genres"] = []
                    item["trailer"] = f"https://www.youtube.com/results?search_query={urllib.parse.quote(item['title'] + ' trailer')}"
                    item["tmdbId"] = None
                    item["is_in_library"] = False
                    item["raw_metadata"] = None
                    enriched_movies.append(item)
                progress.advance(movie_task)

    # 4. Display Results in Consecutive Order
    combined_items = []
    
    # TV Shows First
    console.print("\n[bold cyan]============ NEW TV SHOWS ============[/bold cyan]")
    for item in enriched_tv:
        combined_items.append({"type": "tv", "data": item})
        idx = len(combined_items)
        status_tags = []
        if item.get("is_in_library"):
            status_tags.append("[green](In Library)[/green]")
        if item.get("has_new_metadata"):
            status_tags.append("[bold cyan][New metadata][/bold cyan]")
        if item.get("is_archived"):
            status_tags.append("[dim yellow](Archived)[/dim yellow]")
        status_str = (" " + " ".join(status_tags)) if status_tags else ""
        genres = ", ".join(item["genres"]) if item["genres"] else "Unknown"
        
        console.print(f"[bold]{idx}. TV SHOW: {item['title']} ({item['year']})[/bold]{status_str}")
        console.print(f"   [yellow]Released:[/yellow] {item['date_str']}")
        console.print(f"   [yellow]Genres:[/yellow] {genres} | [yellow]TVDB ID:[/yellow] {item['tvdbId'] or 'N/A'}")
        console.print(f"   [yellow]Cast:[/yellow] {item['cast']}")
        console.print(f"   [yellow]Plot:[/yellow] {item['plot']}")
        console.print(f"   [yellow]Trailer:[/yellow] [link={item['trailer']}]{item['trailer']}[/link]")
        console.print("-" * 50)
        
    # Movies Second
    console.print("\n[bold cyan]============ NEW MOVIES ============[/bold cyan]")
    for item in enriched_movies:
        combined_items.append({"type": "movie", "data": item})
        idx = len(combined_items)
        status_tags = []
        if item.get("is_in_library"):
            status_tags.append("[green](In Library)[/green]")
        if item.get("has_new_metadata"):
            status_tags.append("[bold cyan][New metadata][/bold cyan]")
        if item.get("is_archived"):
            status_tags.append("[dim yellow](Archived)[/dim yellow]")
        status_str = (" " + " ".join(status_tags)) if status_tags else ""
        genres = ", ".join(item["genres"]) if item["genres"] else "Unknown"
        
        console.print(f"[bold]{idx}. MOVIE: {item['title']} ({item['year']})[/bold]{status_str}")
        console.print(f"   [yellow]Released:[/yellow] {item['date_str']}")
        console.print(f"   [yellow]Genres:[/yellow] {genres} | [yellow]TMDB ID:[/yellow] {item['tmdbId'] or 'N/A'}")
        console.print(f"   [yellow]Cast:[/yellow] {item['cast']}")
        console.print(f"   [yellow]Plot:[/yellow] {item['plot']}")
        console.print(f"   [yellow]Trailer:[/yellow] [link={item['trailer']}]{item['trailer']}[/link]")
        console.print("-" * 50)

    # 5. Handle Selection and Bulk Adding
    selection = Prompt.ask(
        "\nSelect numbers to add (e.g. [cyan]1, 3[/cyan] for TV, [cyan]6[/cyan] for movie, [cyan]all[/cyan], or [cyan]c[/cyan] to cancel)", 
        default="c"
    )
    if selection.lower() == 'c':
        return

    selected_indices = parse_indices(selection, len(combined_items))
    if not selected_indices:
        console.print("[red]No valid selections made.[/red]")
        return

    selected_tv_shows = []
    selected_movies = []

    for i in selected_indices:
        entry = combined_items[i]
        item_data = entry["data"]
        
        if item_data.get("is_in_library"):
            console.print(f"[yellow]Skipping '{item_data['title']}' (already in library).[/yellow]")
            continue
            
        if not item_data.get("raw_metadata"):
            # If no raw metadata exists, we can't add it directly because Radarr/Sonarr require the search result payload structure.
            # To fix this, we trigger a live API search for the title and take the first match!
            with console.status(f"[bold blue]Searching API metadata for '{item_data['title']}'...[/bold blue]"):
                try:
                    if entry["type"] == "tv" and sonarr_client:
                        results = sonarr_client.lookup_series(item_data["title"])
                        if results:
                            item_data["raw_metadata"] = results[0]
                    elif entry["type"] == "movie" and radarr_client:
                        results = radarr_client.lookup_movie(item_data["title"])
                        if results:
                            item_data["raw_metadata"] = results[0]
                except Exception as e:
                    logger.error(f"Error fetching API metadata for '{item_data['title']}': {e}")
                    console.print(f"[red]Error fetching API metadata for '{item_data['title']}': {e}[/red]")
                    
        if not item_data.get("raw_metadata"):
            console.print(f"[red]Could not find '{item_data['title']}' in Sonarr/Radarr indexers. Skipping.[/red]")
            continue

        if entry["type"] == "tv":
            selected_tv_shows.append(item_data["raw_metadata"])
        else:
            selected_movies.append(item_data["raw_metadata"])

    # Bulk TV Shows Adding
    if selected_tv_shows:
        if not sonarr_client:
            console.print("[red]Sonarr is not configured. Cannot add TV shows.[/red]")
        else:
            try:
                with console.status("[bold blue]Loading Sonarr configuration...[/bold blue]"):
                    profiles = sonarr_client.get_quality_profiles()
                    folders = sonarr_client.get_root_folders()
                
                console.print(Panel(f"Adding [bold]{len(selected_tv_shows)}[/bold] series to Sonarr. Select options:", title="Sonarr Options", expand=False))
                folder_default_idx = resolve_preset_index(
                    folders,
                    key_field="path",
                    explicit_keys=["sonarr_default_root_folder"],
                    mru_keys=["sonarr_mru_root_folder"]
                )
                profile_default_idx = resolve_preset_index(
                    profiles,
                    key_field="id",
                    explicit_keys=["sonarr_default_quality_profile", "sonarr_default_profile_id"],
                    mru_keys=["sonarr_mru_quality_profile", "sonarr_mru_profile_id"]
                )
                selected_folder = select_from_list("Select Root Path", folders, "path", default_index=folder_default_idx)
                selected_profile = select_from_list("Select Quality Profile", profiles, "name", default_index=profile_default_idx)
                
                monitored = Confirm.ask("Monitor these series?", default=True)
                search_now = Confirm.ask("Search immediately on add?", default=True)

                for show in selected_tv_shows:
                    try:
                        with console.status(f"[bold blue]Adding '{show['title']}' to Sonarr...[/bold blue]"):
                            res = sonarr_client.add_series(
                                series_data=show,
                                quality_profile_id=selected_profile["id"],
                                root_folder_path=selected_folder["path"],
                                monitored=monitored,
                                search_now=search_now
                            )
                        console.print(f"{CHECK_MARK} Successfully added [bold]'{res.get('title')}'[/bold]!")
                        try:
                            set_setting("sonarr_mru_quality_profile", str(selected_profile["id"]))
                            set_setting("sonarr_mru_root_folder", str(selected_folder["path"]))
                        except Exception:
                            pass
                    except ArrAPIError as e:
                        console.print(f"{CROSS_MARK} Failed to add '{show.get('title')}': {e}")
            except ArrAPIError as e:
                console.print(f"[red]Error fetching Sonarr config options: {e}[/red]")

    # Bulk Movies Adding
    if selected_movies:
        if not radarr_client:
            console.print("[red]Radarr is not configured. Cannot add movies.[/red]")
        else:
            try:
                with console.status("[bold blue]Loading Radarr configuration...[/bold blue]"):
                    profiles = radarr_client.get_quality_profiles()
                    folders = radarr_client.get_root_folders()
                
                console.print(Panel(f"Adding [bold]{len(selected_movies)}[/bold] movies to Radarr. Select options:", title="Radarr Options", expand=False))
                folder_default_idx = resolve_preset_index(
                    folders,
                    key_field="path",
                    explicit_keys=["radarr_default_root_folder"],
                    mru_keys=["radarr_mru_root_folder"]
                )
                profile_default_idx = resolve_preset_index(
                    profiles,
                    key_field="id",
                    explicit_keys=["radarr_default_quality_profile", "radarr_default_profile_id"],
                    mru_keys=["radarr_mru_quality_profile", "radarr_mru_profile_id"]
                )
                selected_folder = select_from_list("Select Root Path", folders, "path", default_index=folder_default_idx)
                selected_profile = select_from_list("Select Quality Profile", profiles, "name", default_index=profile_default_idx)
                
                monitored = Confirm.ask("Monitor these movies?", default=True)
                search_now = Confirm.ask("Search immediately on add?", default=True)

                for movie in selected_movies:
                    try:
                        with console.status(f"[bold blue]Adding '{movie['title']}' to Radarr...[/bold blue]"):
                            res = radarr_client.add_movie(
                                movie_data=movie,
                                quality_profile_id=selected_profile["id"],
                                root_folder_path=selected_folder["path"],
                                monitored=monitored,
                                search_now=search_now
                            )
                        console.print(f"{CHECK_MARK} Successfully added [bold]'{res.get('title')}'[/bold]!")
                        try:
                            set_setting("radarr_mru_quality_profile", str(selected_profile["id"]))
                            set_setting("radarr_mru_root_folder", str(selected_folder["path"]))
                        except Exception:
                            pass
                    except ArrAPIError as e:
                        console.print(f"{CROSS_MARK} Failed to add '{movie.get('title')}': {e}")
            except ArrAPIError as e:
                console.print(f"[red]Error fetching Radarr config options: {e}[/red]")


def handle_export_workflow():
    console.print("\n[bold yellow]Backup Settings & Cache[/bold yellow]")
    console.print("[yellow]Warning: Backups contain API keys in plain text. Keep exported files private and secure.[/yellow]")
    include_media = Confirm.ask("Include basic details of cached media objects?", default=True)
    
    default_filename = "xarrtools_backup.json"
    filename = Prompt.ask("Enter destination file path (.json for settings/cache, .zip for full backup with posters)", default=default_filename)
    
    try:
        if filename.lower().endswith(".zip"):
            from core.backup import export_full_backup
            res = export_full_backup(filename, include_media=include_media)
            console.print(f"[green]✓ Successfully exported full backup to '{filename}'[/green]")
            console.print(f"  - Settings: [bold]{res.get('settings_count', 0)}[/bold]")
            console.print(f"  - Custom feeds: [bold]{res.get('custom_feeds_count', 0)}[/bold]")
            console.print(f"  - Media items: [bold]{res.get('media_count', 0)}[/bold]")
            console.print(f"  - Posters cached: [bold]{res.get('posters_count', 0)}[/bold]")
        else:
            from core.db import export_to_dict
            data = export_to_dict(include_media=include_media)
            import json
            content = json.dumps(data, indent=2)
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
                
            console.print(f"[green]✓ Successfully exported backup to '{filename}'[/green]")
    except Exception as e:
        logger.error(f"Error exporting backup: {e}")
        console.print(f"[red]Error exporting backup: {e}[/red]")


def handle_import_workflow():
    console.print("\n[bold yellow]Restore Settings & Cache[/bold yellow]")
    console.print("[yellow]Warning: Backups contain API keys in plain text. Keep them private and secure.[/yellow]")
    filename = Prompt.ask("Enter path to backup file (.json or .zip)")
    
    import os
    if not os.path.exists(filename):
        console.print(f"[red]File '{filename}' does not exist.[/red]")
        return
        
    try:
        with open(filename, "rb") as f:
            content = f.read()
            
        if content.startswith(b"PK") or filename.lower().endswith(".zip"):
            from core.backup import import_full_backup
            import io
            res = import_full_backup(io.BytesIO(content))
            console.print(f"[green]✓ Successfully imported backup from '{filename}'![/green]")
            console.print(f"  - Settings imported/updated: [bold]{res.get('settings_count', 0)}[/bold]")
            console.print(f"  - Custom feeds imported/updated: [bold]{res.get('custom_feeds_count', 0)}[/bold]")
            console.print(f"  - Media items imported/updated: [bold]{res.get('media_count', 0)}[/bold]")
            console.print(f"  - Posters restored: [bold]{res.get('posters_count', 0)}[/bold]")
            return
            
        import json
        data = json.loads(content.decode("utf-8"))
        
        if not isinstance(data, dict):
            console.print("[red]Invalid backup file structure.[/red]")
            return
        
        from core.db import verify_backup_checksum, import_from_dict
        check = verify_backup_checksum(data)
        if check is False:
            logger.warning("Backup checksum verification failed.")
            console.print("[red]Error: Backup checksum verification failed (file corrupted or tampered).[/red]")
            return
            
        s_count, m_count = import_from_dict(data)
        console.print(f"[green]✓ Successfully imported backup from '{filename}'![/green]")
        console.print(f"  - Settings imported/updated: [bold]{s_count}[/bold]")
        console.print(f"  - Media items imported/updated: [bold]{m_count}[/bold]")
    except Exception as e:
        logger.error(f"Error importing backup: {e}")
        console.print(f"[red]Error importing backup: {e}[/red]")


def run_cli():
    from core.logging_setup import setup_logging
    setup_logging()
    while True:
        console.clear()
        console.print(Panel(
            "[bold white]xarrtools - Radarr & Sonarr CLI Manager[/bold white]",
            subtitle="Premium media adder via REST APIs",
            style="bold blue",
            expand=False
        ))
        show_config_status()

        console.print("\n[bold]Main Menu:[/bold]")
        console.print(" [1] Search & Add Movie (Radarr)")
        console.print(" [2] Search & Add TV Show (Sonarr)")
        console.print(" [3] Discover New Releases (Metacritic)")
        console.print(" [4] Export Settings & Cache (Backup)")
        console.print(" [5] Import Settings & Cache (Restore)")
        console.print(" [6] Exit")

        choice = Prompt.ask("\nChoose an option", choices=["1", "2", "3", "4", "5", "6"], default="6")
        
        if choice == "1":
            handle_radarr_workflow()
            Prompt.ask("\nPress Enter to return to menu...")
        elif choice == "2":
            handle_sonarr_workflow()
            Prompt.ask("\nPress Enter to return to menu...")
        elif choice == "3":
            handle_discovery_workflow()
            Prompt.ask("\nPress Enter to return to menu...")
        elif choice == "4":
            handle_export_workflow()
            Prompt.ask("\nPress Enter to return to menu...")
        elif choice == "5":
            handle_import_workflow()
            Prompt.ask("\nPress Enter to return to menu...")
        elif choice == "6":
            console.print("[yellow]Goodbye![/yellow]")
            break

