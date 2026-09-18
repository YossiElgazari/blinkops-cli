import json
from contextlib import contextmanager
from dataclasses import replace
from itertools import islice
from typing import Generator, NoReturn, Optional

import typer
from rich.console import Console
from rich.markup import escape

from tforge import __version__
from tforge.client import TicketForgeClient
from tforge.config import DEFAULT_URL, Config, config_path, load_config, save_config, validate_username
from tforge.deps import build_dep_tree
from tforge.edits import apply_edits, parse_field_assignments
from tforge.errors import ConfigError, TicketForgeError
from tforge.models import Stage, normalize_ref
from tforge.render import changes_table, dep_tree, fields_table, format_time, stage_text, ticket_detail, tickets_table
from tforge.sorting import SortField, sort_tickets

app = typer.Typer(help="Manage TicketForge tickets from the terminal.", no_args_is_help=True)
ticket_app = typer.Typer(help="Create, list and update tickets.", no_args_is_help=True)
field_app = typer.Typer(help="Manage custom fields that tickets can carry.", no_args_is_help=True)
app.add_typer(ticket_app, name="ticket")
app.add_typer(field_app, name="field")

console = Console()
err_console = Console(stderr=True)


def fail(message: str) -> NoReturn:
    err_console.print(f"[red]Error:[/red] {escape(message)}")
    raise typer.Exit(1)


def notify_wait(seconds: float, error: TicketForgeError) -> None:
    err_console.print(f"[yellow]{escape(error.message)} Retrying in {seconds:.0f}s...[/yellow]")


# All API and config errors are handled here: print a red message and exit with code 1.
@contextmanager
def api_client(config: Config | None = None) -> Generator[TicketForgeClient, None, None]:
    try:
        config = config or load_config()
        with TicketForgeClient(config.url, config.username, config.password, on_wait=notify_wait) as client:
            yield client
    except ConfigError as exc:
        fail(str(exc))
    except TicketForgeError as exc:
        hint = " Check your credentials with `tforge setup`." if exc.code == "unauthorized" else ""
        fail(f"{exc}{hint}")


def ref_callback(value):
    # Typer calls this with None when an optional option is omitted.
    if value is None:
        return None
    try:
        if isinstance(value, list):
            return [normalize_ref(v) for v in value]
        return normalize_ref(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def fields_callback(values):
    # Only validate here. Typer turns the return value back into list[str], so the command does the parsing.
    try:
        parse_field_assignments(values or [])
        return values
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


# Makes Typer always treat tforge as a group of subcommands.
@app.callback()
def main() -> None:
    pass


@app.command(help="Print the tforge version.")
def version() -> None:
    typer.echo(__version__)


@app.command(help="Configure the connection to TicketForge and verify the credentials.")
def setup(
    username: str = typer.Option(..., "--username", "-u", prompt=True, help="TicketForge username."),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True, help="TicketForge password."),
    url: str = typer.Option(DEFAULT_URL, "--url", help="TicketForge base URL."),
    register: bool = typer.Option(False, "--register", help="Create the account before logging in."),
) -> None:
    try:
        validate_username(username)
    except ConfigError as exc:
        fail(str(exc))
    config = Config(url=url.rstrip("/"), username=username, password=password)
    with api_client(config) as client:
        if register:
            client.register(username, password)
            console.print(f"Registered account [bold]{escape(username)}[/bold].")
        client.check_auth()
    path = save_config(config)
    console.print(f"[green]Connected to {escape(config.url)} as {escape(username)}.[/green] Config saved to {escape(str(path))}")


@app.command(help="Show the configured account and current rate-limit status.")
def whoami() -> None:
    with api_client() as client:
        client.check_auth()
        config = load_config()
        limit = client.rate_limit
        console.print(f"User:       [bold]{escape(config.username)}[/bold]")
        console.print(f"Server:     {escape(config.url)}")
        console.print(f"Config:     {escape(str(config_path()))}")
        console.print(f"Rate limit: {limit.remaining}/{limit.limit} requests left, resets {format_time(limit.reset)}")


@ticket_app.command("create", help="Create a new ticket.")
def create_ticket(
    title: str = typer.Option(..., "--title", "-t", prompt=True, help="Ticket title."),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Ticket description."),
    depends_on: Optional[list[str]] = typer.Option(None, "--depends-on", callback=ref_callback, help="Ref this ticket depends on. Repeatable."),
    field: Optional[list[str]] = typer.Option(None, "--field", "-f", callback=fields_callback, help="Custom field value as name=value. Repeatable."),
) -> None:
    if not title.strip():
        fail("Title cannot be empty.")
    with api_client() as client:
        ticket = client.create_ticket(title.strip(), description, depends_on, parse_field_assignments(field or []))
    console.print(f"[green]Created[/green] [bold]{ticket.ref}[/bold]: {escape(ticket.title)} ", stage_text(ticket.stage))


@ticket_app.command("list", help="List your tickets, newest first unless --sort is given.")
def list_tickets(
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="Maximum number of tickets to show."),
    show_all: bool = typer.Option(False, "--all", "-a", help="Fetch every page."),
    stage: Optional[list[Stage]] = typer.Option(None, "--stage", "-s", case_sensitive=False, help="Only show these stages. Repeatable."),
    sort: Optional[SortField] = typer.Option(None, "--sort", case_sensitive=False, help="Sort by this field. Fetches all tickets first."),
    reverse: bool = typer.Option(False, "--reverse", "-r", help="Reverse the sort order."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table."),
) -> None:
    with api_client() as client:
        tickets = client.iter_tickets()
        if stage:
            tickets = (t for t in tickets if t.stage in stage)
        if sort:
            # Sorting needs every ticket, so all pages are fetched and --limit applies afterwards.
            tickets = iter(sort_tickets(tickets, sort, reverse))
        if show_all:
            shown, has_more = list(tickets), False
        else:
            # Fetch one extra ticket to know if more exist. Pages are fetched only as needed.
            fetched = list(islice(tickets, limit + 1))
            shown, has_more = fetched[:limit], len(fetched) > limit
    if as_json:
        typer.echo(json.dumps([t.to_json(details=False) for t in shown], indent=2))
        return
    if not shown:
        console.print("No tickets found.")
        return
    console.print(tickets_table(shown))
    footer = f"{len(shown)} ticket(s)."
    if has_more:
        footer += " More available: raise --limit or use --all."
    console.print(footer, style="dim")


@ticket_app.command("update", help="Update a ticket. Only the options you pass are changed.")
def update_ticket(
    ref: str = typer.Argument(..., callback=ref_callback, help="Ticket ref, e.g. TF-12 or 12."),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="New title."),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description. Pass \"\" to clear it."),
    stage: Optional[Stage] = typer.Option(None, "--stage", "-s", case_sensitive=False, help="New stage."),
    add_dep: Optional[list[str]] = typer.Option(None, "--add-dep", callback=ref_callback, help="Add a dependency. Repeatable."),
    remove_dep: Optional[list[str]] = typer.Option(None, "--remove-dep", callback=ref_callback, help="Remove a dependency. Repeatable."),
    clear_deps: bool = typer.Option(False, "--clear-deps", help="Remove all dependencies."),
    field: Optional[list[str]] = typer.Option(None, "--field", "-f", callback=fields_callback, help="Set a custom field as name=value. Repeatable."),
    unset_field: Optional[list[str]] = typer.Option(None, "--unset-field", help="Remove a custom field value. Repeatable."),
) -> None:
    if title is not None and not title.strip():
        fail("Title cannot be empty.")
    with api_client() as client:
        current = client.get_ticket(ref)
        set_fields = parse_field_assignments(field or [])
        changes = apply_edits(current, title, description, stage, add_dep, remove_dep, clear_deps, set_fields, unset_field)
        if not changes:
            console.print(f"No changes to {ref}.")
            return
        updated = client.save_ticket(replace(current, **changes))
    console.print(f"[green]Updated[/green] [bold]{updated.ref}[/bold]")
    console.print(changes_table(current, changes))


@ticket_app.command("show", help="Show every detail of a ticket.")
def show_ticket(
    ref: str = typer.Argument(..., callback=ref_callback, help="Ticket ref, e.g. TF-12 or 12."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table."),
) -> None:
    with api_client() as client:
        ticket = client.get_ticket(ref)
        if as_json:
            typer.echo(json.dumps(ticket.to_json(), indent=2))
            return
        labels = {f.name: f.label for f in client.list_fields()} if ticket.custom_fields else {}
    console.print(ticket_detail(ticket, labels))


@ticket_app.command("delete", help="Delete a ticket. Other tickets that depend on it lose that link.")
def delete_ticket(
    ref: str = typer.Argument(..., callback=ref_callback, help="Ticket ref, e.g. TF-12 or 12."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    with api_client() as client:
        ticket = client.get_ticket(ref, deep=False)
        if not yes:
            typer.confirm(f"Delete {ticket.ref} \"{ticket.title}\"? Tickets depending on it will lose that link", abort=True)
        client.delete_ticket(ref)
    console.print(f"[green]Deleted[/green] [bold]{ref}[/bold].")


@ticket_app.command("deps", help="Show the dependency tree of a ticket. Cycles are marked.")
def ticket_deps(
    ref: str = typer.Argument(..., callback=ref_callback, help="Ticket ref, e.g. TF-12 or 12."),
    depth: Optional[int] = typer.Option(None, "--depth", min=0, help="Stop after this many levels."),
) -> None:
    with api_client() as client:
        root = build_dep_tree(ref, client.get_ticket, depth)
    console.print(dep_tree(root))


@field_app.command("list", help="List your custom fields.")
def list_fields() -> None:
    with api_client() as client:
        fields = client.list_fields()
    if not fields:
        console.print("No custom fields defined.")
        return
    console.print(fields_table(fields))


@field_app.command("create", help="Define a new custom field.")
def create_field(
    name: str = typer.Argument(..., help="Field name: letters, digits and underscores."),
    label: str = typer.Option(..., "--label", "-l", prompt=True, help="Human-readable label."),
) -> None:
    with api_client() as client:
        field = client.create_field(name, label)
    console.print(f"[green]Created field[/green] [bold]{escape(field.name)}[/bold] ({escape(field.label)}).")


@field_app.command("update", help="Change a custom field's label. The name cannot be changed.")
def update_field(
    name: str = typer.Argument(..., help="Field name."),
    label: str = typer.Option(..., "--label", "-l", prompt=True, help="New label."),
) -> None:
    with api_client() as client:
        field = client.update_field(client.find_field(name).id, label)
    console.print(f"[green]Updated field[/green] [bold]{escape(field.name)}[/bold] ({escape(field.label)}).")


@field_app.command("delete", help="Delete a custom field and its value on every ticket.")
def delete_field(
    name: str = typer.Argument(..., help="Field name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    with api_client() as client:
        field = client.find_field(name)
        if not yes:
            typer.confirm(f"Delete field '{field.name}'? Its value is removed from every ticket", abort=True)
        client.delete_field(field.id)
    console.print(f"[green]Deleted field[/green] [bold]{escape(name)}[/bold].")
