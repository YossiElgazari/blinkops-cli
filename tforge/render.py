from datetime import datetime

from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from tforge.deps import DepNode
from tforge.models import CustomField, Stage, Ticket

STAGE_STYLES = {
    Stage.OPEN: "cyan",
    Stage.IN_PROGRESS: "yellow",
    Stage.REVIEW: "magenta",
    Stage.CLOSED: "green",
}


def stage_text(stage: Stage) -> Text:
    return Text(stage.value, style=STAGE_STYLES[stage])


def format_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def display_value(value) -> str:
    if isinstance(value, Stage):
        return value.value
    if isinstance(value, list):
        return ", ".join(value) or "(none)"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items()) or "(none)"
    if value is None or value == "":
        return "(empty)"
    return str(value)


def tickets_table(tickets: list[Ticket]) -> Table:
    table = Table(show_lines=False, header_style="bold")
    table.add_column("Ref", style="bold", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("Stage", no_wrap=True)
    table.add_column("Updated", no_wrap=True)
    for ticket in tickets:
        table.add_row(ticket.ref, ticket.title, stage_text(ticket.stage), format_time(ticket.updated or ticket.created))
    return table


def ticket_detail(ticket: Ticket, labels: dict[str, str] | None = None) -> Table:
    labels = labels or {}
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column(overflow="fold")
    grid.add_row("Ref", ticket.ref)
    grid.add_row("Title", ticket.title)
    grid.add_row("Stage", stage_text(ticket.stage))
    grid.add_row("Description", ticket.description or Text("(none)", style="dim"))
    grid.add_row("Depends on", ", ".join(ticket.depends_on) or Text("(none)", style="dim"))
    for name, value in ticket.custom_fields.items():
        grid.add_row(labels.get(name, name), value)
    grid.add_row("Owner", ticket.owner or "-")
    grid.add_row("Created", format_time(ticket.created))
    grid.add_row("Updated", format_time(ticket.updated))
    return grid


def dep_label(node: DepNode) -> Text:
    label = Text(node.ref, style="bold")
    if node.ticket:
        label.append(f" {node.ticket.title} ")
        label.append_text(stage_text(node.ticket.stage))
    if node.cycle:
        label.append(" (cycle)", style="bold red")
    if node.error:
        label.append(f" ({node.error})", style="red")
    if node.truncated:
        label.append(" ...", style="dim")
    return label


def dep_tree(root: DepNode) -> Tree:
    tree = Tree(dep_label(root))

    def add(branch: Tree, node: DepNode) -> None:
        for child in node.children:
            add(branch.add(dep_label(child)), child)

    add(tree, root)
    return tree


def fields_table(fields: list[CustomField]) -> Table:
    table = Table(header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("Label")
    table.add_column("Type", style="dim")
    for field in fields:
        table.add_row(field.name, field.label, field.type)
    return table


def changes_table(before: Ticket, changes: dict) -> Table:
    table = Table(header_style="bold")
    table.add_column("Field")
    table.add_column("Before")
    table.add_column("After")
    for key, value in changes.items():
        table.add_row(key, display_value(getattr(before, key)), display_value(value))
    return table
