import pytest
from factories import make_ticket

from tforge.edits import apply_edits, parse_field_assignments
from tforge.models import Stage


def test_no_options_means_no_changes():
    assert apply_edits(make_ticket("TF-1", dependsOn=["TF-2"])) == {}


def test_only_changed_values_are_returned():
    ticket = make_ticket("TF-1", title="Same", stage="open")

    assert apply_edits(ticket, title="Same", stage=Stage.REVIEW) == {"stage": Stage.REVIEW}


def test_empty_description_clears_it():
    ticket = make_ticket("TF-1", description="old")

    assert apply_edits(ticket, description="") == {"description": None}


def test_add_and_remove_dependencies():
    ticket = make_ticket("TF-1", dependsOn=["TF-2", "TF-3"])

    changes = apply_edits(ticket, add_deps=["TF-4", "TF-2"], remove_deps=["TF-3"])

    assert changes == {"depends_on": ["TF-2", "TF-4"]}


def test_clear_then_add_dependencies():
    ticket = make_ticket("TF-1", dependsOn=["TF-2"])

    assert apply_edits(ticket, clear_deps=True, add_deps=["TF-5"]) == {"depends_on": ["TF-5"]}


def test_parse_field_assignments():
    assert parse_field_assignments(["severity=high", "team = core ", "note=a=b"]) == {"severity": "high", "team": "core", "note": "a=b"}


@pytest.mark.parametrize("value", ["severity", "=high"])
def test_parse_field_assignments_rejects_bad_input(value):
    with pytest.raises(ValueError):
        parse_field_assignments([value])


def test_set_and_unset_fields():
    ticket = make_ticket("TF-1", customFields={"severity": "high", "team": "core"})

    changes = apply_edits(ticket, set_fields={"severity": "low", "area": "api"}, unset_fields=["team"])

    assert changes == {"custom_fields": {"severity": "low", "area": "api"}}


def test_empty_field_value_unsets_it():
    ticket = make_ticket("TF-1", customFields={"severity": "high"})

    assert apply_edits(ticket, set_fields={"severity": ""}) == {"custom_fields": {}}
