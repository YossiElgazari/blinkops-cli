from enum import Enum
from typing import Callable, Iterable

from tforge.models import Ticket


class SortField(str, Enum):
    REF = "ref"
    TITLE = "title"
    STAGE = "stage"
    CREATED = "created"
    UPDATED = "updated"


SORT_KEYS: dict[SortField, Callable[[Ticket], object]] = {
    SortField.REF: lambda t: t.number,  # Numeric, so TF-9 comes before TF-10.
    SortField.TITLE: lambda t: t.title.casefold(),
    SortField.STAGE: lambda t: t.stage.order,
    SortField.CREATED: lambda t: t.created,
    SortField.UPDATED: lambda t: t.updated or t.created,
}


def sort_tickets(tickets: Iterable[Ticket], by: SortField = SortField.CREATED, reverse: bool = False) -> list[Ticket]:
    key = SORT_KEYS[by]
    # Equal keys are ordered by ref number, so the output order is always the same.
    return sorted(tickets, key=lambda t: (key(t), t.number), reverse=reverse)
