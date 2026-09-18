import base64
import json
from datetime import datetime, timedelta, timezone
from itertools import islice

import httpx
import pytest
import respx
from factories import api_ticket

from tforge.client import MAX_WAIT_SECONDS, TicketForgeClient, retry_delay
from tforge.errors import TicketForgeError
from tforge.models import Stage

BASE = "https://tf.test"
API = BASE + "/api/tforge"
RATE_HEADERS = {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "42", "X-RateLimit-Reset": "2026-09-18T08:11:37.947Z"}


def page(refs, next_cursor=None):
    pagination = {"limit": 5, "hasMore": next_cursor is not None}
    if next_cursor:
        pagination["nextCursor"] = next_cursor
    return {"workitems": [api_ticket(ref) for ref in refs], "pagination": pagination}


def rate_limited(retry_after="7"):
    body = {"err": "rate_limit_exceeded", "message": "Rate limit exceeded.", "retryable": True}
    return httpx.Response(429, json=body, headers={"Retry-After": retry_after})


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(sleeps):
    with TicketForgeClient(BASE, "alice", "secret1", sleep=sleeps.append) as c:
        yield c


@respx.mock
def test_sends_basic_auth(client):
    route = respx.get(f"{API}/workitems/mine").respond(json=page([]))

    client.check_auth()

    expected = "Basic " + base64.b64encode(b"alice:secret1").decode()
    assert route.calls.last.request.headers["Authorization"] == expected


@respx.mock
def test_error_body_becomes_ticketforge_error(client):
    respx.get(f"{API}/workitem/TF-9").respond(400, json={"err": "not_found", "message": "workitem TF-9 does not exist", "retryable": False})

    with pytest.raises(TicketForgeError) as exc:
        client.get_ticket("TF-9")

    assert (exc.value.code, exc.value.status, exc.value.retryable) == ("not_found", 400, False)


@respx.mock
def test_non_json_error_body(client):
    respx.get(f"{API}/workitem/TF-9").respond(404, text="<!DOCTYPE html>")

    with pytest.raises(TicketForgeError) as exc:
        client.get_ticket("TF-9")

    assert exc.value.code == "http_404"


@respx.mock
def test_network_error(client):
    respx.get(f"{API}/workitem/TF-9").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(TicketForgeError) as exc:
        client.get_ticket("TF-9")

    assert exc.value.code == "network_error"


@respx.mock
def test_rate_limit_waits_retry_after_then_succeeds(sleeps):
    waits = []
    respx.get(f"{API}/workitems/mine").mock(side_effect=[rate_limited("7"), httpx.Response(200, json=page(["TF-1"]))])

    with TicketForgeClient(BASE, "alice", "secret1", sleep=sleeps.append, on_wait=lambda s, e: waits.append(e.code)) as c:
        tickets = c.list_page().tickets

    assert [t.ref for t in tickets] == ["TF-1"]
    assert sleeps == [7.0]
    assert waits == ["rate_limit_exceeded"]


@respx.mock
def test_gives_up_after_max_retries(sleeps):
    route = respx.get(f"{API}/workitems/mine").mock(return_value=rate_limited("1"))

    with TicketForgeClient(BASE, "alice", "secret1", max_retries=2, sleep=sleeps.append) as c:
        with pytest.raises(TicketForgeError) as exc:
            c.list_page()

    assert exc.value.code == "rate_limit_exceeded"
    assert route.call_count == 3
    assert len(sleeps) == 2


@respx.mock
def test_non_retryable_error_is_not_retried(client, sleeps):
    route = respx.post(f"{API}/workitem/publish").respond(400, json={"err": "invalid_input", "message": "title is required", "retryable": False})

    with pytest.raises(TicketForgeError):
        client.create_ticket("")

    assert route.call_count == 1
    assert sleeps == []


def test_retry_delay_prefers_retry_after():
    assert retry_delay(httpx.Headers({"Retry-After": "12"}), attempt=1) == 12


def test_retry_delay_falls_back_to_reset_header():
    now = datetime(2026, 9, 18, 8, 0, 0, tzinfo=timezone.utc)
    reset = (now + timedelta(seconds=20)).isoformat().replace("+00:00", "Z")

    assert retry_delay(httpx.Headers({"X-RateLimit-Reset": reset}), attempt=1, now=now) == 20


def test_retry_delay_is_at_least_one_second():
    assert retry_delay(httpx.Headers({"Retry-After": "0"}), attempt=1) == 1


@respx.mock
def test_long_retry_after_fails_fast_instead_of_retrying_early(client, sleeps):
    route = respx.get(f"{API}/workitems/mine").mock(return_value=rate_limited(str(MAX_WAIT_SECONDS + 60)))

    with pytest.raises(TicketForgeError) as exc:
        client.list_page()

    assert route.call_count == 1
    assert sleeps == []
    assert f"Try again in {MAX_WAIT_SECONDS + 60}s" in exc.value.message


@respx.mock
def test_server_error_on_get_is_retried(client, sleeps):
    route = respx.get(f"{API}/workitems/mine").mock(side_effect=[httpx.Response(503), httpx.Response(200, json=page(["TF-1"]))])

    assert [t.ref for t in client.list_page().tickets] == ["TF-1"]
    assert route.call_count == 2


@respx.mock
def test_server_error_on_create_is_not_retried(client, sleeps):
    route = respx.post(f"{API}/workitem/publish").respond(503)

    with pytest.raises(TicketForgeError) as exc:
        client.create_ticket("Fix login")

    assert exc.value.code == "http_503"
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_rate_limited_create_is_retried(client, sleeps):
    route = respx.post(f"{API}/workitem/publish").mock(side_effect=[rate_limited("3"), httpx.Response(200, json={"workitem": api_ticket("TF-8")})])

    assert client.create_ticket("Fix login").ref == "TF-8"
    assert route.call_count == 2
    assert sleeps == [3.0]


@respx.mock
def test_rate_limit_headers_are_recorded(client):
    respx.get(f"{API}/workitems/mine").respond(json=page([]), headers=RATE_HEADERS)

    client.check_auth()

    assert (client.rate_limit.limit, client.rate_limit.remaining) == (50, 42)


@respx.mock
def test_iter_tickets_follows_cursors(client):
    route = respx.get(f"{API}/workitems/mine").mock(side_effect=[
        httpx.Response(200, json=page(["TF-9", "TF-8"], next_cursor="c1")),
        httpx.Response(200, json=page(["TF-7", "TF-6"], next_cursor="c2")),
        httpx.Response(200, json=page(["TF-5"])),
    ])

    refs = [t.ref for t in client.iter_tickets()]

    assert refs == ["TF-9", "TF-8", "TF-7", "TF-6", "TF-5"]
    assert [call.request.url.params.get("cursor") for call in route.calls] == [None, "c1", "c2"]


@respx.mock
def test_iter_tickets_is_lazy(client):
    route = respx.get(f"{API}/workitems/mine").mock(side_effect=[
        httpx.Response(200, json=page(["TF-9", "TF-8", "TF-7"], next_cursor="c1")),
        httpx.Response(200, json=page(["TF-6"])),
    ])

    list(islice(client.iter_tickets(), 2))

    assert route.call_count == 1


@respx.mock
def test_update_preserves_untouched_fields(client):
    current = api_ticket("TF-7", description="keep me", dependsOn=["TF-1"], customFields={"severity": "high"})
    respx.get(f"{API}/workitem/TF-7", params={"view": "deep"}).respond(json={"workitem": current})
    put = respx.put(f"{API}/workitem/TF-7").respond(json={"workitem": {**current, "stage": "review"}})

    updated = client.update_ticket("TF-7", stage=Stage.REVIEW)

    assert json.loads(put.calls.last.request.content) == {
        "title": "Ticket TF-7",
        "description": "keep me",
        "stage": "review",
        "dependsOn": ["TF-1"],
        "customFields": {"severity": "high"},
    }
    assert updated.stage is Stage.REVIEW


@respx.mock
def test_create_sends_dependencies_and_fields(client):
    route = respx.post(f"{API}/workitem/publish").respond(json={"workitem": api_ticket("TF-8")})

    client.create_ticket("Fix login", "desc", depends_on=["TF-1"], custom_fields={"severity": "high"})

    assert json.loads(route.calls.last.request.content) == {
        "title": "Fix login",
        "description": "desc",
        "dependsOn": ["TF-1"],
        "customFields": {"severity": "high"},
    }


@respx.mock
def test_find_field_by_name(client):
    respx.get(f"{API}/custom-fields").respond(json={"customFields": [{"id": "c1", "name": "severity", "label": "Severity", "type": "text"}]})

    assert client.find_field("severity").id == "c1"
    with pytest.raises(TicketForgeError) as exc:
        client.find_field("missing")
    assert exc.value.code == "not_found"
