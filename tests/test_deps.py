import pytest
from factories import make_ticket

from tforge.deps import build_dep_tree
from tforge.errors import TicketForgeError


def fake_fetch(graph: dict[str, list[str]]):
    calls = []

    def fetch(ref):
        calls.append(ref)
        if ref not in graph:
            raise TicketForgeError("not_found", f"workitem {ref} does not exist")
        return make_ticket(ref, dependsOn=graph[ref])

    return fetch, calls


def child_refs(node):
    return [c.ref for c in node.children]


def test_chain():
    fetch, _ = fake_fetch({"TF-1": ["TF-2"], "TF-2": ["TF-3"], "TF-3": []})

    root = build_dep_tree("TF-1", fetch)

    assert child_refs(root) == ["TF-2"]
    assert child_refs(root.children[0]) == ["TF-3"]


def test_diamond_fetches_each_ticket_once():
    fetch, calls = fake_fetch({"TF-1": ["TF-2", "TF-3"], "TF-2": ["TF-4"], "TF-3": ["TF-4"], "TF-4": []})

    root = build_dep_tree("TF-1", fetch)

    assert sorted(calls) == ["TF-1", "TF-2", "TF-3", "TF-4"]
    assert [child_refs(c) for c in root.children] == [["TF-4"], ["TF-4"]]
    assert not any(c.cycle for c in root.children[0].children)


def test_cycle_is_marked_and_stops():
    fetch, _ = fake_fetch({"TF-1": ["TF-2"], "TF-2": ["TF-1"]})

    root = build_dep_tree("TF-1", fetch)

    back_edge = root.children[0].children[0]
    assert (back_edge.ref, back_edge.cycle, back_edge.children) == ("TF-1", True, [])
    assert back_edge.ticket.ref == "TF-1"


def test_depth_limit_marks_truncated():
    fetch, calls = fake_fetch({"TF-1": ["TF-2"], "TF-2": ["TF-3"], "TF-3": []})

    root = build_dep_tree("TF-1", fetch, max_depth=1)

    assert root.children[0].truncated
    assert root.children[0].children == []
    assert "TF-3" not in calls


def test_missing_dependency_becomes_error_node():
    fetch, _ = fake_fetch({"TF-1": ["TF-9"]})

    root = build_dep_tree("TF-1", fetch)

    assert root.children[0].error == "workitem TF-9 does not exist"


def test_missing_root_raises():
    fetch, _ = fake_fetch({})

    with pytest.raises(TicketForgeError):
        build_dep_tree("TF-1", fetch)
