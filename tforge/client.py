import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Iterator

import httpx

from tforge.errors import TicketForgeError
from tforge.models import CustomField, Ticket, parse_time

API_PREFIX = "/api/tforge"
# The server silently caps page size at 5, whatever limit is requested.
PAGE_SIZE = 5
MAX_WAIT_SECONDS = 60


@dataclass
class Page:
    tickets: list[Ticket]
    next_cursor: str | None


@dataclass
class RateLimit:
    limit: int | None = None
    remaining: int | None = None
    reset: datetime | None = None


def retry_delay(headers: httpx.Headers, attempt: int, now: datetime | None = None) -> float:
    retry_after = headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        seconds = float(retry_after)
    elif headers.get("X-RateLimit-Reset"):
        now = now or datetime.now(timezone.utc)
        seconds = (parse_time(headers["X-RateLimit-Reset"]) - now).total_seconds()
    else:
        seconds = 2.0 ** attempt
    return max(seconds, 1.0)


def error_from_response(response: httpx.Response) -> TicketForgeError:
    # The API returns 400 for almost every error (even not_found and forbidden), so we read the `err` code from the body.
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "err" in body:
        return TicketForgeError(
            code=body["err"],
            message=body.get("message", body["err"]),
            status=response.status_code,
            retryable=bool(body.get("retryable")) or response.status_code == 429,
        )
    return TicketForgeError(
        code=f"http_{response.status_code}",
        message=f"Unexpected HTTP {response.status_code} from {response.request.url.path}",
        status=response.status_code,
        retryable=response.status_code == 429 or response.status_code >= 500,
    )


class TicketForgeClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        on_wait: Callable[[float, TicketForgeError], None] | None = None,
    ):
        self.max_retries = max_retries
        self.sleep = sleep
        self.on_wait = on_wait
        self.rate_limit = RateLimit()
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + API_PREFIX,
            auth=httpx.BasicAuth(username, password),
            timeout=15.0,
        )

    def __enter__(self) -> "TicketForgeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.RequestError as exc:
                raise TicketForgeError("network_error", f"Could not reach TicketForge: {exc}") from exc
            self._record_rate_limit(response.headers)
            if response.is_success:
                return response.json()
            error = error_from_response(response)
            if not self._should_retry(method, error, attempt):
                raise error
            attempt += 1
            wait = retry_delay(response.headers, attempt)
            # Retrying early would fail again, and a long wait would freeze the CLI, so stop and say when to retry.
            if wait > MAX_WAIT_SECONDS:
                raise TicketForgeError(error.code, f"{error.message} Try again in {wait:.0f}s.", error.status, error.retryable)
            if self.on_wait:
                self.on_wait(wait, error)
            self.sleep(wait)

    def _should_retry(self, method: str, error: TicketForgeError, attempt: int) -> bool:
        if not error.retryable or attempt >= self.max_retries:
            return False
        # A failed POST may still have created the ticket. A 429 is retried because this API's rate limiter
        # appears to reject requests before they run (observed behavior, not documented).
        return method != "POST" or error.status == 429

    def _record_rate_limit(self, headers: httpx.Headers) -> None:
        if "X-RateLimit-Remaining" not in headers:
            return
        self.rate_limit = RateLimit(
            limit=int(headers["X-RateLimit-Limit"]),
            remaining=int(headers["X-RateLimit-Remaining"]),
            reset=parse_time(headers.get("X-RateLimit-Reset")),
        )

    def register(self, username: str, password: str) -> None:
        self._request("POST", "/user/register", json={"username": username, "password": password})

    def check_auth(self) -> None:
        # There is no login endpoint; any cheap authenticated call validates the credentials.
        self.list_page(limit=1)

    def list_page(self, limit: int = PAGE_SIZE, cursor: str | None = None) -> Page:
        params: dict = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = self._request("GET", "/workitems/mine", params=params)
        pagination = data.get("pagination") or {}
        next_cursor = pagination.get("nextCursor") if pagination.get("hasMore") else None
        return Page([Ticket.from_api(item) for item in data.get("workitems", [])], next_cursor)

    def iter_tickets(self) -> Iterator[Ticket]:
        cursor = None
        while True:
            page = self.list_page(cursor=cursor)
            yield from page.tickets
            if not page.next_cursor:
                return
            cursor = page.next_cursor

    def get_ticket(self, ref: str, deep: bool = True) -> Ticket:
        # Only view=deep includes dependsOn, customFields and owner.
        params = {"view": "deep"} if deep else None
        return Ticket.from_api(self._request("GET", f"/workitem/{ref}", params=params)["workitem"])

    def create_ticket(
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        custom_fields: dict[str, str] | None = None,
    ) -> Ticket:
        body: dict = {"title": title, "description": description, "dependsOn": depends_on or None}
        if custom_fields:
            body["customFields"] = custom_fields
        return Ticket.from_api(self._request("POST", "/workitem/publish", json=body)["workitem"])

    def save_ticket(self, ticket: Ticket) -> Ticket:
        data = self._request("PUT", f"/workitem/{ticket.ref}", json=ticket.to_payload())
        return Ticket.from_api(data["workitem"])

    def update_ticket(self, ref: str, **changes) -> Ticket:
        # PUT replaces the whole ticket and clears omitted fields, so merge into the current state first.
        current = self.get_ticket(ref)
        return self.save_ticket(replace(current, **changes))

    def delete_ticket(self, ref: str) -> None:
        self._request("DELETE", f"/workitem/{ref}")

    def list_fields(self) -> list[CustomField]:
        return [CustomField.from_api(item) for item in self._request("GET", "/custom-fields")["customFields"]]

    def find_field(self, name: str) -> CustomField:
        for field in self.list_fields():
            if field.name == name:
                return field
        raise TicketForgeError("not_found", f"custom field '{name}' does not exist")

    def create_field(self, name: str, label: str) -> CustomField:
        data = self._request("POST", "/custom-fields", json={"name": name, "label": label})
        return CustomField.from_api(data["customField"])

    def update_field(self, field_id: str, label: str) -> CustomField:
        data = self._request("PUT", f"/custom-fields/{field_id}", json={"label": label})
        return CustomField.from_api(data["customField"])

    def delete_field(self, field_id: str) -> None:
        self._request("DELETE", f"/custom-fields/{field_id}")
