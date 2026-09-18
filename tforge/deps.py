from dataclasses import dataclass, field
from typing import Callable

from tforge.errors import TicketForgeError
from tforge.models import Ticket


@dataclass
class DepNode:
    ref: str
    ticket: Ticket | None = None
    children: list["DepNode"] = field(default_factory=list)
    cycle: bool = False
    truncated: bool = False
    error: str | None = None


def build_dep_tree(ref: str, fetch: Callable[[str], Ticket], max_depth: int | None = None) -> DepNode:
    # `cache` is shared by the whole walk, so a ticket reached through two paths is fetched only once.
    # `path` holds only the current branch. Seeing a ref again on it means a cycle, which the API allows.
    cache: dict[str, Ticket | TicketForgeError] = {}

    def load(r: str) -> Ticket | TicketForgeError:
        if r not in cache:
            try:
                cache[r] = fetch(r)
            except TicketForgeError as exc:
                cache[r] = exc
        return cache[r]

    def visit(r: str, path: frozenset[str], depth: int) -> DepNode:
        if r in path:
            cached = cache.get(r)
            return DepNode(r, cached if isinstance(cached, Ticket) else None, cycle=True)
        loaded = load(r)
        if isinstance(loaded, TicketForgeError):
            # A missing root is a real error; a missing dependency is just shown in the tree.
            if depth == 0:
                raise loaded
            return DepNode(r, error=loaded.message)
        node = DepNode(r, loaded)
        if max_depth is not None and depth >= max_depth:
            node.truncated = bool(loaded.depends_on)
            return node
        node.children = [visit(child, path | {r}, depth + 1) for child in loaded.depends_on]
        return node

    return visit(ref, frozenset(), 0)
