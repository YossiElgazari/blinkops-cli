from datetime import timezone

import pytest

from tforge.models import CustomField, Stage, Ticket, normalize_ref


def test_from_api_list_shape_has_empty_extras():
    ticket = Ticket.from_api({
        "ref": "TF-406",
        "title": "new ticket",
        "description": "description",
        "stage": "open",
        "created": "2026-09-18T08:11:25.869Z",
        "updated": "2026-09-18T08:11:25.869Z",
    })

    assert ticket.stage is Stage.OPEN
    assert ticket.depends_on == []
    assert ticket.custom_fields == {}
    assert ticket.owner is None
    assert ticket.created.tzinfo == timezone.utc


def test_from_api_deep_shape():
    ticket = Ticket.from_api({
        "ref": "TF-407",
        "title": "new ticket2",
        "description": None,
        "stage": "in_progress",
        "created": "2026-09-18T08:13:22.381Z",
        "updated": "2026-09-18T08:13:54.027Z",
        "dependsOn": ["TF-406"],
        "customFields": {"severity": "high"},
        "owner": {"id": "u1", "username": "alice"},
    })

    assert ticket.stage is Stage.IN_PROGRESS
    assert ticket.depends_on == ["TF-406"]
    assert ticket.custom_fields == {"severity": "high"}
    assert ticket.owner == "alice"


def test_from_api_create_response_without_updated():
    ticket = Ticket.from_api({
        "ref": "TF-1",
        "title": "t",
        "description": None,
        "stage": "open",
        "created": "2026-09-18T08:00:00.000Z",
    })

    assert ticket.updated is None


def test_number_is_numeric_part_of_ref():
    assert Ticket.from_api({"ref": "TF-1024", "title": "t", "stage": "open", "created": "2026-09-18T08:00:00Z"}).number == 1024


def test_to_payload_sends_full_object_for_put():
    ticket = Ticket.from_api({
        "ref": "TF-7",
        "title": "Fix login",
        "description": "desc",
        "stage": "review",
        "created": "2026-09-18T08:00:00Z",
        "dependsOn": ["TF-1"],
        "customFields": {"severity": "low"},
    })

    assert ticket.to_payload() == {
        "title": "Fix login",
        "description": "desc",
        "stage": "review",
        "dependsOn": ["TF-1"],
        "customFields": {"severity": "low"},
    }


def test_to_payload_sends_null_when_no_dependencies():
    ticket = Ticket.from_api({"ref": "TF-7", "title": "t", "stage": "open", "created": "2026-09-18T08:00:00Z"})

    assert ticket.to_payload()["dependsOn"] is None


def test_stage_order_follows_workflow():
    assert [s.value for s in sorted(Stage, key=lambda s: s.order)] == ["open", "in_progress", "review", "closed"]


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError):
        Ticket.from_api({"ref": "TF-1", "title": "t", "stage": "done", "created": "2026-09-18T08:00:00Z"})


def test_custom_field_from_api():
    field = CustomField.from_api({"id": "c1", "name": "severity", "label": "Severity", "type": "text"})

    assert (field.id, field.name, field.label, field.type) == ("c1", "severity", "Severity", "text")


@pytest.mark.parametrize("value, expected", [("TF-12", "TF-12"), ("tf-12", "TF-12"), ("12", "TF-12"), (" 7 ", "TF-7")])
def test_normalize_ref(value, expected):
    assert normalize_ref(value) == expected


@pytest.mark.parametrize("value", ["", "TF-", "abc", "TF-12x", "XX-1"])
def test_normalize_ref_rejects_garbage(value):
    with pytest.raises(ValueError):
        normalize_ref(value)
