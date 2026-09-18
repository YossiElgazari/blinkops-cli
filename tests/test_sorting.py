from factories import make_ticket

from tforge.sorting import SortField, sort_tickets


def refs(tickets):
    return [t.ref for t in tickets]


def test_ref_sort_is_numeric_not_alphabetical():
    tickets = [make_ticket("TF-10"), make_ticket("TF-9"), make_ticket("TF-100")]

    assert refs(sort_tickets(tickets, SortField.REF)) == ["TF-9", "TF-10", "TF-100"]


def test_stage_sort_follows_workflow_not_alphabet():
    tickets = [
        make_ticket("TF-1", stage="closed"),
        make_ticket("TF-2", stage="review"),
        make_ticket("TF-3", stage="open"),
        make_ticket("TF-4", stage="in_progress"),
    ]

    assert refs(sort_tickets(tickets, SortField.STAGE)) == ["TF-3", "TF-4", "TF-2", "TF-1"]


def test_ties_break_by_ref_number():
    tickets = [make_ticket("TF-5"), make_ticket("TF-2"), make_ticket("TF-3")]

    assert refs(sort_tickets(tickets, SortField.STAGE)) == ["TF-2", "TF-3", "TF-5"]


def test_title_sort_ignores_case():
    tickets = [make_ticket("TF-1", title="banana"), make_ticket("TF-2", title="Apple"), make_ticket("TF-3", title="cherry")]

    assert refs(sort_tickets(tickets, SortField.TITLE)) == ["TF-2", "TF-1", "TF-3"]


def test_reverse():
    tickets = [make_ticket("TF-1"), make_ticket("TF-2"), make_ticket("TF-3")]

    assert refs(sort_tickets(tickets, SortField.REF, reverse=True)) == ["TF-3", "TF-2", "TF-1"]


def test_updated_falls_back_to_created():
    tickets = [
        make_ticket("TF-1", created="2026-09-18T09:00:00Z", updated=None),
        make_ticket("TF-2", created="2026-09-18T08:00:00Z", updated="2026-09-18T10:00:00Z"),
    ]

    assert refs(sort_tickets(tickets, SortField.UPDATED)) == ["TF-1", "TF-2"]
