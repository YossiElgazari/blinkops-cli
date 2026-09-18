# tforge: a TicketForge CLI

`tforge` is a command-line client for [TicketForge](https://integrations-assignment-ticketforge.vercel.app). You can create, list, update, inspect and delete tickets, manage custom fields, and explore ticket dependencies from the terminal.

TicketForge has no public API documentation. The API was reverse-engineered from the web app; the method and full endpoint reference are in [API.md](API.md).

## Features

- `setup` checks your credentials against the server before saving them, and can register a new account.
- Tickets: `create`, `list`, `update`, `show`, `delete`, `deps`.
- Custom fields: `field list/create/update/delete`, plus `--field name=value` on tickets.
- Automatic pagination. The API returns at most 5 tickets per page, so `list` follows cursors until it has enough.
- Rate-limit handling. On HTTP 429 the client waits for `Retry-After` and retries, printing a notice.
- Safe partial updates. The API's `PUT` replaces the whole ticket, so `update` reads the ticket first and only changes the fields you pass.
- Client-side stage filter and sorting (the server ignores filters), and `--json` output for scripting.
- A dependency tree view with cycle detection (the API allows dependency cycles).
- Colored tables, clear errors, and exit codes: `0` success, `1` API or config error, `2` invalid usage.

## Installation

Requires Python 3.10+ (tested on Python 3.12).

```bash
git clone https://github.com/YossiElgazari/blinkops-cli.git
cd blinkops-cli
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # or: pip install -e ".[dev]" to run the tests
```

This installs the `tforge` command. `python -m tforge` works too.

## Setup

Log in with an existing TicketForge account:

```bash
tforge setup
```

Or create a new account and log in with one command:

```bash
tforge setup --register
```

You are prompted for the username and password (the password is hidden). You can also pass `-u/--username`, `-p/--password` and `--url`.

The credentials are checked against the API before anything is saved. The config file is `~/.tforge/config.json`.

Environment variables override the file, which is useful for CI or one-off runs:

| Variable | Meaning |
|---|---|
| `TFORGE_URL` | Base URL (default: the TicketForge instance above) |
| `TFORGE_USERNAME` / `TFORGE_PASSWORD` | Credentials |
| `TFORGE_CONFIG` | Alternative config file path |

`tforge whoami` shows the active account, the server, and how many requests are left in the current rate-limit window.

## Usage

Refs can be written as `TF-12`, `tf-12` or just `12`. Every command has `--help`.

### Create

```bash
tforge ticket create -t "Design database schema" -d "Tables for users and orders"
tforge ticket create -t "Build REST API" --depends-on TF-12 --depends-on TF-13
tforge ticket create -t "Fix crash" -f severity=high      # custom field must exist, see below
```

New tickets always start in the `open` stage (the API ignores a stage on creation).

### List

```bash
tforge ticket list                          # newest 20
tforge ticket list --limit 5
tforge ticket list --all                    # every page
tforge ticket list --stage open --stage review
tforge ticket list --sort stage             # workflow order: open, in_progress, review, closed
tforge ticket list --sort ref               # numeric: TF-9 before TF-10
tforge ticket list --sort ref --reverse     # descending: TF-10 before TF-9
tforge ticket list --json
```

Sort fields: `ref`, `title`, `stage`, `created`, `updated`. Sorting has to see every ticket, so `--sort` fetches all pages first and then applies `--limit`.

```
$ tforge ticket list --limit 4
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Ref    ┃ Title              ┃ Stage ┃ Updated          ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ TF-453 │ Fix flaky test     │ open  │ 2026-09-18 12:22 │
│ TF-452 │ Set up CI pipeline │ open  │ 2026-09-18 12:22 │
│ TF-451 │ Write API docs     │ open  │ 2026-09-18 12:22 │
│ TF-450 │ Build REST API     │ open  │ 2026-09-18 12:22 │
└────────┴────────────────────┴───────┴──────────────────┘
4 ticket(s). More available: raise --limit or use --all.
```

### Update

Only the options you pass are changed.

```bash
tforge ticket update TF-12 --stage in_progress
tforge ticket update 12 --title "New title" --description "New text"
tforge ticket update 12 --description ""                 # clear the description
tforge ticket update 12 --add-dep TF-3 --remove-dep TF-4
tforge ticket update 12 --clear-deps
tforge ticket update 12 -f severity=low --unset-field team
```

The command prints a before/after table of the fields that changed. If nothing would change, the update request (PUT) is skipped.

### Show, delete, dependencies

```bash
tforge ticket show TF-12                    # every detail, including custom fields and owner
tforge ticket show TF-12 --json
tforge ticket delete TF-12                  # asks for confirmation; --yes skips it
tforge ticket deps TF-12                    # dependency tree
tforge ticket deps TF-12 --depth 2
```

```
$ tforge ticket deps 450
TF-450 Build REST API open
└── TF-449 Build REST API v1 review
    └── TF-450 Build REST API open (cycle)
```

### Custom fields

```bash
tforge field create severity --label Severity
tforge field list
tforge field update severity --label "Severity level"    # the name itself cannot be changed
tforge field delete severity                             # also removes the value from every ticket
```

## Evidence

Screenshots of a full run against the live API are in [`docs/screenshots/`](docs/screenshots):

1. [Setup and whoami](docs/screenshots/01-setup.png)
2. [Create and paginated list](docs/screenshots/02-create-list.png)
3. [Update and show](docs/screenshots/03-update-show.png)
4. [Sort, filter and JSON](docs/screenshots/04-sort-filter-json.png)
5. [Dependency tree with a cycle](docs/screenshots/05-deps.png)
6. [Rate limit: wait and retry](docs/screenshots/06-rate-limit.png)

## Design

```
tforge/
  cli.py      Typer commands; thin, no HTTP or business logic
  client.py   TicketForgeClient: auth, error mapping, retry, pagination, safe update
  models.py   Ticket / CustomField / Stage and conversion to and from API JSON
  edits.py    works out which fields an update actually changes
  sorting.py  sort keys
  deps.py     dependency tree (DFS with cycle detection, each ticket fetched once)
  render.py   rich tables and trees
  config.py   config file + env var handling
  errors.py   TicketForgeError, ConfigError
```

- **All HTTP goes through one method** (`TicketForgeClient._request`). Auth, error mapping, retries and rate-limit tracking live in one place.
- **API error codes distinguish failures that share HTTP 400.** The API returns 400 for most errors, including "not found" and "forbidden", so the client raises `TicketForgeError` with the `err` code from the body. The HTTP status is still used for retry decisions and for errors without a JSON body.
- **Retries** happen when the server marks an error as `retryable` (in practice, 429), and on 5xx for GET/PUT/DELETE. Creating a ticket (POST) is retried only on 429: a failed POST may already have created the ticket, and retrying it could create a duplicate. Retrying a rate-limited create assumes the rate limiter rejects requests before they run, which matches what I observed but is not documented.
- **Wait time** comes from `Retry-After`, falling back to `X-RateLimit-Reset`, then to exponential backoff. If the server asks for more than 60 s, the CLI stops and says when to try again instead of retrying too early. At most 3 retries.
- **Pagination is lazy.** `iter_tickets()` is a generator, so without filtering or sorting, `--limit 3` costs a single request. A `--stage` filter may need later pages, and `--sort` fetches all pages.
- **Updates are GET → merge → PUT** because the API's `PUT` wipes any field that isn't sent.
- **No `--cursor` option.** The CLI follows the server-provided `nextCursor` automatically; a manual cursor option is not exposed.
- **Testable by design.** The client takes an injectable `sleep` and callbacks, and the tree builder takes a `fetch` function. The tests (`pytest`, `respx` to fake HTTP) run offline and instantly.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

99 offline tests check models, config precedence, sorting, update merging, the client (auth header, error mapping, retry rules, pagination, lazy fetching), the dependency tree (cycles, repeated dependencies, depth, missing tickets) and the main CLI flows (`whoami` and `version` are not covered).

## Assumptions and limitations

- **The password is stored in plain text** in `~/.tforge/config.json` (file mode 0600 on Unix; on Windows the file relies on your user profile's permissions). The API only supports HTTP Basic, so the password is needed on every request. Storing it in the OS keyring would be the next improvement; env vars are an alternative.
- **Usernames containing `:` are rejected.** The server accepts them at registration, but HTTP Basic auth cannot represent them, so such accounts can never log in.
- **Filtering and sorting happen on the client.** `--sort`, `--all` and very selective `--stage` filters can take many requests on large accounts (5 tickets per page, 50 requests per minute). On a 429 the client waits and retries, but stops if the server asks for more than 60 s or after 3 retries.
- **The list endpoint does not return dependencies, custom fields or owner**, so `list --json` leaves those keys out instead of showing them as empty. Use `show --json` for full details.
- **No optimistic locking.** The API has none, so two people editing the same ticket at once can overwrite each other (last write wins).
- **The dependency tree fetches one ticket per node** (each only once). Very large graphs use a noticeable share of the rate limit.
- Only the caller's own tickets are visible; that is how the API scopes access.
- Behavior was inferred from observation (see [API.md](API.md)). Undocumented server changes could break assumptions such as the page-size cap.

## AI disclosure

I used an AI coding assistant (Claude Code) during this assignment:

- **API reverse engineering:** I captured the browser traffic (HAR) myself. The assistant helped parse it, search the web app's JavaScript bundles for endpoints and the auth scheme, and write probe scripts to test edge cases. The results are documented in API.md.
- **Implementation:** the assistant generated most of the code and tests. I worked layer by layer: I made the design decisions (credential storage, framework, feature scope, command structure), then reviewed, ran and tested each layer before moving on.
- **Documentation:** the assistant drafted this README and API.md, which I reviewed and edited.

The screenshots were taken by me from my own terminal.
