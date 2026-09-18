from tforge.models import Ticket


def api_ticket(ref: str, **overrides) -> dict:
    data = {
        "ref": ref,
        "title": f"Ticket {ref}",
        "description": None,
        "stage": "open",
        "created": "2026-09-18T08:00:00.000Z",
        "updated": "2026-09-18T08:00:00.000Z",
    }
    data.update(overrides)
    return data


def make_ticket(ref: str, **overrides) -> Ticket:
    return Ticket.from_api(api_ticket(ref, **overrides))
