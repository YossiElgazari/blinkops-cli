import json

import httpx
import pytest
import respx
from factories import api_ticket
from typer.testing import CliRunner

from tforge.cli import app
from tforge.config import config_path

BASE = "https://tf.test"
API = BASE + "/api/tforge"

runner = CliRunner()


def page(refs, next_cursor=None):
    pagination = {"limit": 5, "hasMore": next_cursor is not None}
    if next_cursor:
        pagination["nextCursor"] = next_cursor
    return {"workitems": [api_ticket(ref) for ref in refs], "pagination": pagination}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TFORGE_URL", BASE)
    monkeypatch.setenv("TFORGE_USERNAME", "alice")
    monkeypatch.setenv("TFORGE_PASSWORD", "secret1")


@respx.mock
def test_setup_validates_and_saves_config():
    respx.get(f"{API}/workitems/mine").respond(json=page([]))

    result = runner.invoke(app, ["setup", "--url", BASE, "-u", "alice", "-p", "secret1"])

    assert result.exit_code == 0, result.output
    assert json.loads(config_path().read_text()) == {"url": BASE, "username": "alice", "password": "secret1"}


@respx.mock
def test_setup_register_creates_account_first():
    register = respx.post(f"{API}/user/register").respond(json={"user": {"id": "u1", "username": "alice"}})
    respx.get(f"{API}/workitems/mine").respond(json=page([]))

    result = runner.invoke(app, ["setup", "--url", BASE, "-u", "alice", "-p", "secret1", "--register"])

    assert result.exit_code == 0, result.output
    assert register.called


@respx.mock
def test_setup_with_bad_credentials_does_not_save():
    respx.get(f"{API}/workitems/mine").respond(401, json={"err": "unauthorized", "message": "valid basic auth required", "retryable": False})

    result = runner.invoke(app, ["setup", "--url", BASE, "-u", "alice", "-p", "wrong1"])

    assert result.exit_code == 1
    assert "unauthorized" in result.output
    assert not config_path().exists()


def test_setup_rejects_colon_in_username():
    result = runner.invoke(app, ["setup", "--url", BASE, "-u", "co:lon", "-p", "secret1"])

    assert result.exit_code == 1
    assert "cannot contain ':'" in result.output


def test_commands_require_setup():
    result = runner.invoke(app, ["ticket", "list"])

    assert result.exit_code == 1
    assert "tforge setup" in result.output


@respx.mock
def test_create_ticket(configured):
    route = respx.post(f"{API}/workitem/publish").respond(json={"workitem": api_ticket("TF-8", title="Fix login")})

    result = runner.invoke(app, ["ticket", "create", "-t", "Fix login", "-d", "desc", "--depends-on", "3"])

    assert result.exit_code == 0, result.output
    assert "TF-8" in result.output
    assert json.loads(route.calls.last.request.content)["dependsOn"] == ["TF-3"]


def test_create_rejects_bad_ref(configured):
    result = runner.invoke(app, ["ticket", "create", "-t", "x", "--depends-on", "abc"])

    assert result.exit_code == 2


@respx.mock
def test_list_respects_limit_and_reports_more(configured):
    respx.get(f"{API}/workitems/mine").mock(side_effect=[
        httpx.Response(200, json=page(["TF-9", "TF-8", "TF-7"], next_cursor="c1")),
        httpx.Response(200, json=page(["TF-6"])),
    ])

    result = runner.invoke(app, ["ticket", "list", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert "TF-9" in result.output and "TF-8" in result.output and "TF-7" not in result.output
    assert "More available" in result.output


@respx.mock
def test_list_all_follows_pages(configured):
    respx.get(f"{API}/workitems/mine").mock(side_effect=[
        httpx.Response(200, json=page(["TF-9"], next_cursor="c1")),
        httpx.Response(200, json=page(["TF-8"])),
    ])

    result = runner.invoke(app, ["ticket", "list", "--all"])

    assert "TF-9" in result.output and "TF-8" in result.output
    assert "More available" not in result.output


@respx.mock
def test_update_merges_and_prints_changes(configured):
    current = api_ticket("TF-7", description="keep me", dependsOn=["TF-1"])
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": current})
    put = respx.put(f"{API}/workitem/TF-7").respond(json={"workitem": {**current, "stage": "review"}})

    result = runner.invoke(app, ["ticket", "update", "tf-7", "--stage", "review"])

    assert result.exit_code == 0, result.output
    body = json.loads(put.calls.last.request.content)
    assert (body["stage"], body["description"], body["dependsOn"]) == ("review", "keep me", ["TF-1"])
    assert "open" in result.output and "review" in result.output


@respx.mock
def test_update_without_changes_skips_put(configured):
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": api_ticket("TF-7")})
    put = respx.put(f"{API}/workitem/TF-7")

    result = runner.invoke(app, ["ticket", "update", "TF-7", "--stage", "open"])

    assert result.exit_code == 0
    assert "No changes" in result.output
    assert not put.called


@respx.mock
def test_api_error_exits_with_message(configured):
    respx.get(f"{API}/workitem/TF-99").respond(400, json={"err": "not_found", "message": "workitem TF-99 does not exist", "retryable": False})

    result = runner.invoke(app, ["ticket", "update", "TF-99", "--stage", "closed"])

    assert result.exit_code == 1
    assert "not_found" in result.output and "TF-99 does not exist" in result.output


@respx.mock
def test_show_ticket_uses_field_labels(configured):
    ticket = api_ticket("TF-7", description="details", dependsOn=["TF-1"], customFields={"severity": "high"}, owner={"id": "u1", "username": "alice"})
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": ticket})
    respx.get(f"{API}/custom-fields").respond(json={"customFields": [{"id": "c1", "name": "severity", "label": "Severity", "type": "text"}]})

    result = runner.invoke(app, ["ticket", "show", "7"])

    assert result.exit_code == 0, result.output
    for text in ("TF-7", "details", "TF-1", "Severity", "high", "alice"):
        assert text in result.output


@respx.mock
def test_show_skips_field_lookup_without_custom_fields(configured):
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": api_ticket("TF-7")})
    fields = respx.get(f"{API}/custom-fields")

    result = runner.invoke(app, ["ticket", "show", "TF-7"])

    assert result.exit_code == 0
    assert not fields.called


@respx.mock
def test_delete_with_confirmation(configured):
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": api_ticket("TF-7")})
    delete = respx.delete(f"{API}/workitem/TF-7").respond(json={"message": "deleted"})

    result = runner.invoke(app, ["ticket", "delete", "TF-7"], input="y\n")

    assert result.exit_code == 0, result.output
    assert delete.called


@respx.mock
def test_delete_aborted_does_not_call_api(configured):
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": api_ticket("TF-7")})
    delete = respx.delete(f"{API}/workitem/TF-7")

    result = runner.invoke(app, ["ticket", "delete", "TF-7"], input="n\n")

    assert result.exit_code == 1
    assert not delete.called


@respx.mock
def test_delete_yes_skips_prompt(configured):
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": api_ticket("TF-7")})
    delete = respx.delete(f"{API}/workitem/TF-7").respond(json={"message": "deleted"})

    result = runner.invoke(app, ["ticket", "delete", "TF-7", "--yes"])

    assert result.exit_code == 0
    assert delete.called


FIELDS = {"customFields": [{"id": "c1", "name": "severity", "label": "Severity", "type": "text"}]}


@respx.mock
def test_create_with_custom_field(configured):
    route = respx.post(f"{API}/workitem/publish").respond(json={"workitem": api_ticket("TF-8")})

    result = runner.invoke(app, ["ticket", "create", "-t", "x", "--field", "severity=high"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content)["customFields"] == {"severity": "high"}


def test_bad_field_syntax_is_usage_error(configured):
    result = runner.invoke(app, ["ticket", "create", "-t", "x", "--field", "severity"])

    assert result.exit_code == 2


@respx.mock
def test_update_custom_fields(configured):
    current = api_ticket("TF-7", customFields={"severity": "high", "team": "core"})
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": current})
    put = respx.put(f"{API}/workitem/TF-7").respond(json={"workitem": current})

    result = runner.invoke(app, ["ticket", "update", "TF-7", "-f", "severity=low", "--unset-field", "team"])

    assert result.exit_code == 0, result.output
    assert json.loads(put.calls.last.request.content)["customFields"] == {"severity": "low"}


@respx.mock
def test_field_list(configured):
    respx.get(f"{API}/custom-fields").respond(json=FIELDS)

    result = runner.invoke(app, ["field", "list"])

    assert "severity" in result.output and "Severity" in result.output


@respx.mock
def test_field_update_resolves_name_to_id(configured):
    respx.get(f"{API}/custom-fields").respond(json=FIELDS)
    put = respx.put(f"{API}/custom-fields/c1").respond(json={"customField": {"id": "c1", "name": "severity", "label": "Sev", "type": "text"}})

    result = runner.invoke(app, ["field", "update", "severity", "--label", "Sev"])

    assert result.exit_code == 0, result.output
    assert json.loads(put.calls.last.request.content) == {"label": "Sev"}


@respx.mock
def test_field_delete_unknown_name(configured):
    respx.get(f"{API}/custom-fields").respond(json=FIELDS)

    result = runner.invoke(app, ["field", "delete", "nope", "--yes"])

    assert result.exit_code == 1
    assert "does not exist" in result.output


@respx.mock
def test_field_delete(configured):
    respx.get(f"{API}/custom-fields").respond(json=FIELDS)
    delete = respx.delete(f"{API}/custom-fields/c1").respond(json={"success": True})

    result = runner.invoke(app, ["field", "delete", "severity", "--yes"])

    assert result.exit_code == 0, result.output
    assert delete.called


def three_pages():
    return [
        httpx.Response(200, json={"workitems": [api_ticket("TF-9", stage="open"), api_ticket("TF-8", stage="closed")], "pagination": {"limit": 5, "hasMore": True, "nextCursor": "c1"}}),
        httpx.Response(200, json={"workitems": [api_ticket("TF-10", stage="review"), api_ticket("TF-6", stage="closed")], "pagination": {"limit": 5, "hasMore": True, "nextCursor": "c2"}}),
        httpx.Response(200, json={"workitems": [api_ticket("TF-5", stage="open")], "pagination": {"limit": 5, "hasMore": False}}),
    ]


def json_refs(output):
    return [t["ref"] for t in json.loads(output)]


@respx.mock
def test_list_filters_by_stage_across_pages(configured):
    respx.get(f"{API}/workitems/mine").mock(side_effect=three_pages())

    result = runner.invoke(app, ["ticket", "list", "--stage", "closed", "--json"])

    assert result.exit_code == 0, result.output
    assert json_refs(result.output) == ["TF-8", "TF-6"]
    assert "dependsOn" not in json.loads(result.output)[0]


@respx.mock
def test_list_multiple_stages(configured):
    respx.get(f"{API}/workitems/mine").mock(side_effect=three_pages())

    result = runner.invoke(app, ["ticket", "list", "-s", "open", "-s", "REVIEW", "--json"])

    assert json_refs(result.output) == ["TF-9", "TF-10", "TF-5"]


@respx.mock
def test_list_sort_fetches_everything_then_limits(configured):
    respx.get(f"{API}/workitems/mine").mock(side_effect=three_pages())

    result = runner.invoke(app, ["ticket", "list", "--sort", "ref", "--limit", "3", "--json"])

    assert json_refs(result.output) == ["TF-5", "TF-6", "TF-8"]


@respx.mock
def test_list_sort_reverse(configured):
    respx.get(f"{API}/workitems/mine").mock(side_effect=three_pages())

    result = runner.invoke(app, ["ticket", "list", "--sort", "ref", "--reverse", "--limit", "2", "--json"])

    assert json_refs(result.output) == ["TF-10", "TF-9"]


@respx.mock
def test_show_json(configured):
    respx.get(f"{API}/workitem/TF-7").respond(json={"workitem": api_ticket("TF-7", dependsOn=["TF-1"], customFields={"severity": "high"})})

    result = runner.invoke(app, ["ticket", "show", "TF-7", "--json"])

    data = json.loads(result.output)
    assert (data["ref"], data["dependsOn"], data["customFields"]) == ("TF-7", ["TF-1"], {"severity": "high"})


def test_invalid_sort_field_is_usage_error(configured):
    result = runner.invoke(app, ["ticket", "list", "--sort", "priority"])

    assert result.exit_code == 2


@respx.mock
def test_deps_tree_marks_cycle(configured):
    respx.get(f"{API}/workitem/TF-1").respond(json={"workitem": api_ticket("TF-1", title="Root", dependsOn=["TF-2"])})
    respx.get(f"{API}/workitem/TF-2").respond(json={"workitem": api_ticket("TF-2", title="Child", dependsOn=["TF-1"])})

    result = runner.invoke(app, ["ticket", "deps", "TF-1"])

    assert result.exit_code == 0, result.output
    assert "Root" in result.output and "Child" in result.output and "(cycle)" in result.output
