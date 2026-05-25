import sys
import urllib.parse
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.panel import Panel
from rich.status import Status
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from xarrtools.config import config
from xarrtools.client import RadarrClient, SonarrClient, ArrAPIError
from xarrtools.scraper import get_discoveries
from xarrtools.enricher import enrich_tv_show, enrich_movie

console = Console()

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
        status_lines.append("[green]✓[/green] [bold]Radarr[/bold]: Configured ([cyan]" + config.radarr_url + "[/cyan])")
    else:
        status_lines.append("[red]✗[/red] [bold]Radarr[/bold]: Not Configured (Missing: " + ", ".join(config.get_missing_radarr_vars()) + ")")
        
    if sonarr_ok:
        status_lines.append("[green]✓[/green] [bold]Sonarr[/bold]: Configured ([cyan]" + config.sonarr_url + "[/cyan])")
    else:
        status_lines.append("[red]✗[/red] [bold]Sonarr[/bold]: Not Configured (Missing: " + ", ".join(config.get_missing_sonarr_vars()) + ")")

    console.print(Panel("\n".join(status_lines), title="[bold white]Service Status[/bold white]", expand=False))

def select_from_list(prompt_text: str, items: list, display_key: str) -> dict:
    """Uses a rich Table to let the user select a configuration parameter from a list."""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("No.", style="cyan", justify="right")
    table.add_column(display_key.capitalize(), style="white")

    for idx, item in enumerate(items, 1):
        table.add_row(str(idx), str(item.get(display_key, "N/A")))
        
    console.print(table)
    
    while True:
        choice = IntPrompt.ask(prompt_text, default=1)
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
    selected_folder = select_from_list("Select Root Path", folders, "path")
    selected_profile = select_from_list("Select Quality Profile", profiles, "name")
    
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
            console.print(f"[green]✓[/green] Successfully added [bold]'{res.get('title')}'[/bold]!")
        except ArrAPIError as e:
            console.print(f"[red]✗ Failed to add '{movie.get('title')}': {e}[/red]")

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
            lang_profiles = client.get_language_profiles()
    except ArrAPIError as e:
        console.print(f"[red]Error communicating with Sonarr: {e}[/red]")
        return

    if not results:
        console.print("[yellow]No TV shows found matching that term.[/yellow]")
        return

    if not profiles or not folders:
        console.print("[red]Could not retrieve required quality profiles or root folders from Sonarr.[/red]")
        return

    lang_profile_id = lang_profiles[0]["id"] if lang_profiles else 1

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
        names = ", ".join(f"'{s['title']}'" for m in already_added)
        console.print(f"[yellow]Skipping already added shows: {names}[/yellow]")

    if not to_add:
        console.print("[yellow]No new series selected to add.[/yellow]")
        return

    console.print(Panel(f"Adding [bold]{len(to_add)}[/bold] series. Please select download options:", title="Options", expand=False))
    selected_folder = select_from_list("Select Root Path", folders, "path")
    selected_profile = select_from_list("Select Quality Profile", profiles, "name")
    
    selected_lang_profile_id = lang_profile_id
    if len(lang_profiles) > 1:
        selected_lang_profile = select_from_list("Select Language Profile", lang_profiles, "name")
        selected_lang_profile_id = selected_lang_profile["id"]

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
                    search_now=search_now,
                    language_profile_id=selected_lang_profile_id
                )
            console.print(f"[green]✓[/green] Successfully added [bold]'{res.get('title')}'[/bold]!")
        except ArrAPIError as e:
            console.print(f"[red]✗ Failed to add '{series.get('title')}': {e}[/red]")

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
                    data = enrich_movie(item["title"], item["date_obj"].year, radarr_client, item.get("imdbId"))
                    if not data["plot"] or data["plot"] == "No plot summary available.":
                        data["plot"] = item["description"]
                    data["date_str"] = item["date_str"]
                    if "imdbId" not in data or not data["imdbId"]:
                        data["imdbId"] = item.get("imdbId")
                    enriched_movies.append(data)
                except Exception as e:
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
        lib_status = "[green](In Library)[/green]" if item["is_in_library"] else ""
        genres = ", ".join(item["genres"]) if item["genres"] else "Unknown"
        
        console.print(f"[bold]{idx}. TV SHOW: {item['title']} ({item['year']})[/bold] {lib_status}")
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
        lib_status = "[green](In Library)[/green]" if item["is_in_library"] else ""
        genres = ", ".join(item["genres"]) if item["genres"] else "Unknown"
        
        console.print(f"[bold]{idx}. MOVIE: {item['title']} ({item['year']})[/bold] {lib_status}")
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
                    lang_profiles = sonarr_client.get_language_profiles()
                
                lang_profile_id = lang_profiles[0]["id"] if lang_profiles else 1
                
                console.print(Panel(f"Adding [bold]{len(selected_tv_shows)}[/bold] series to Sonarr. Select options:", title="Sonarr Options", expand=False))
                selected_folder = select_from_list("Select Root Path", folders, "path")
                selected_profile = select_from_list("Select Quality Profile", profiles, "name")
                
                selected_lang_profile_id = lang_profile_id
                if len(lang_profiles) > 1:
                    selected_lang_profile = select_from_list("Select Language Profile", lang_profiles, "name")
                    selected_lang_profile_id = selected_lang_profile["id"]

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
                                search_now=search_now,
                                language_profile_id=selected_lang_profile_id
                            )
                        console.print(f"[green]✓[/green] Successfully added [bold]'{res.get('title')}'[/bold]!")
                    except ArrAPIError as e:
                        console.print(f"[red]✗ Failed to add '{show.get('title')}': {e}[/red]")
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
                selected_folder = select_from_list("Select Root Path", folders, "path")
                selected_profile = select_from_list("Select Quality Profile", profiles, "name")
                
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
                        console.print(f"[green]✓[/green] Successfully added [bold]'{res.get('title')}'[/bold]!")
                    except ArrAPIError as e:
                        console.print(f"[red]✗ Failed to add '{movie.get('title')}': {e}[/red]")
            except ArrAPIError as e:
                console.print(f"[red]Error fetching Radarr config options: {e}[/red]")


def run_cli():
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
        console.print(" [4] Exit")

        choice = Prompt.ask("\nChoose an option", choices=["1", "2", "3", "4"], default="4")
        
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
            console.print("[yellow]Goodbye![/yellow]")
            break
