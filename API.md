# TicketForge API (reverse-engineered)

TicketForge has no public API docs. This file records how the API was mapped and everything the CLI relies on.

## How it was discovered

1. **Browser capture (HAR).** Used every UI feature (register, login, list and paginate tickets, create, edit, custom fields) with DevTools → Network → Fetch/XHR and *Preserve log* on, then exported a HAR. That gave endpoints, payloads, response shapes and rate-limit headers.
   - Chrome sanitises HAR exports and strips `Authorization` / `Cookie`, so the auth scheme was **not** visible in the capture.
2. **JS bundle analysis.** The web app is a Next.js SPA. Downloaded the page chunks for all five routes (`/`, `/login`, `/register`, `/dashboard`, `/ticket/[ref]`) and searched them for `/api/`. That revealed:
   - Auth is **HTTP Basic**. The login page base64-encodes `username:password` and calls `GET /workitems/mine`; a 200 means "logged in". There is no login or token endpoint. The UI keeps the username in `localStorage` and the password in `window.__password`.
   - The stage enum (`open`, `in_progress`, `review`, `closed`) from the edit form's `<select>`.
   - The error body fields the UI reads (`err`, `message`).
3. **Live probing** with throwaway accounts (never the real one): validation edges, `PUT` semantics, a hidden `DELETE`, page-size limits, cursor validation, dependency rules, and the rate-limit scope.

## Basics

| | |
|---|---|
| Base URL | `https://integrations-assignment-ticketforge.vercel.app/api/tforge` |
| Auth | `Authorization: Basic base64(username:password)` on every endpoint except register |
| Format | JSON request and response bodies |

### Error format

```json
{"err": "not_found", "message": "workitem TF-9 does not exist", "retryable": false}
```

**Almost every error returns HTTP 400**, including `not_found` and `forbidden`. Only `unauthorized` (401) and `rate_limit_exceeded` (429) have distinct status codes. Clients must branch on `err`, not on the status code. Unknown paths return Next.js's HTML 404 page, not JSON.

Observed `err` codes: `unauthorized`, `invalid_input`, `missing_fields`, `user_exists`, `duplicate`, `not_found`, `forbidden`, `invalid_cursor`, `rate_limit_exceeded`, `server_error`.

### Rate limiting

- **50 requests per 60 seconds, per user.** A second user on the same IP gets a fresh quota.
- Fixed window. Every authenticated response carries:
  - `X-RateLimit-Limit: 50`
  - `X-RateLimit-Remaining: 49`
  - `X-RateLimit-Reset: 2026-09-18T08:11:37.947Z` (ISO timestamp, not epoch)
- On exhaustion: HTTP **429**, a `Retry-After` header (seconds), and `{"err":"rate_limit_exceeded","message":"Rate limit exceeded. Maximum 50 requests per 60 seconds.","retryable":true}`.
- `POST /user/register` and unauthenticated requests are not counted.
- Assumption: a 429 means the request was rejected before running, so it is safe to retry. This fits the observed behavior (the limiter answers before any validation) but was not verified for `POST /workitem/publish`, and it is not documented.

## Data model

### Workitem (ticket)

| Field | Type | Notes |
|---|---|---|
| `ref` | string | `TF-<n>`, one global counter shared by all users |
| `title` | string | required, non-empty |
| `description` | string \| null | |
| `stage` | enum | `open`, `in_progress`, `review`, `closed`. Any stage can move to any other |
| `created`, `updated` | ISO-8601 | |
| `dependsOn` | string[] | refs; only in single-ticket responses (`view=deep`) and only when non-empty |
| `customFields` | object | `{name: value}`; only in deep view and when non-empty |
| `owner` | `{id, username}` | only in deep view |

### Custom field

`{id, name, label, type, created, updated}`. Defined per user. `type` is always `"text"`; any other value sent is ignored.

## Endpoints

### `POST /user/register` (no auth)
```json
{"username": "alice", "password": "secret1"}
```
→ `{"user": {"id", "username", "created"}}`
- username ≥ 3 chars, password ≥ 6 chars (`invalid_input`); both required (`missing_fields`); taken name gives `user_exists`.
- The server accepts usernames containing `:`, but such users **can never authenticate**, because Basic auth splits on the first colon. The CLI rejects them.

### `GET /workitems/mine?limit=&cursor=`
Only the caller's own tickets, newest first (ordered by `createdAt desc, id desc`).
```json
{"workitems": [ {ref,title,description,stage,created,updated} ],
 "pagination": {"limit": 5, "hasMore": true, "nextCursor": "2026-09-18T08:13:22.381Z:cmu6olqod..."}}
```
- **Page size is capped at 5.** `limit` > 5 is clamped to 5, ≤ 0 becomes 1, and a non-numeric value returns a leaked Prisma error (`server_error`).
- `nextCursor` is `<created>:<id>` of the last item. It is present only when `hasMore` is true.
- The cursor is validated: it must point at an existing ticket (`invalid_cursor`).
- List items **omit** `dependsOn`, `customFields` and `owner`.
- Query filters such as `?stage=` are **ignored**, so filtering has to happen on the client.

### `POST /workitem/publish`
```json
{"title": "Fix login", "description": "…", "dependsOn": ["TF-1"], "customFields": {"severity": "high"}}
```
→ `{"workitem": {...}}`
- `stage` is ignored; new tickets are always `open`.
- Every `dependsOn` ref must exist (`invalid_input`) and be owned by the caller (`forbidden`).
- Unknown custom field names are rejected (`invalid_input`).

### `GET /workitem/{ref}?view=deep`
→ `{"workitem": {...}}`. Without `view=deep` you get the list shape. Another user's ticket gives `forbidden`; a missing one gives `not_found`.

### `PUT /workitem/{ref}` (full replace)
```json
{"title": "…", "description": "…", "stage": "review", "dependsOn": ["TF-1"], "customFields": {"severity": "low"}}
```
- `title` and `stage` are **required**, and **omitted fields are cleared** (`description` becomes null, `dependsOn` and `customFields` are wiped). A safe partial update therefore has to GET the deep view, merge the changes, then PUT the whole object. The web UI does exactly this.
- Unknown extra keys are ignored. There is no optimistic locking, so concurrent edits can overwrite each other.
- `PATCH` returns 405.
- A ticket cannot depend on itself, but **cycles are allowed** (A→B and B→A both accepted).

### `DELETE /workitem/{ref}`
→ `{"message": "workitem TF-9 deleted successfully"}`. **Not exposed in the UI.** Deleting a ticket silently removes it from every other ticket's `dependsOn`.

### `GET /custom-fields` → `{"customFields": [...]}`
### `POST /custom-fields` `{"name", "label"}`
`name` must match `[A-Za-z0-9_]+` and be unique per user (`duplicate`); `label` is required.
### `PUT /custom-fields/{id}` `{"label"}`
Only `label` can be changed; `name` is ignored.
### `DELETE /custom-fields/{id}` → `{"success": true}`
Also removes that field's values from every ticket.
