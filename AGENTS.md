# AGENTS.md

Compact, repo-specific guidance for future OpenCode sessions. Low-signal or
README-duplicated content is intentionally omitted.

## What this is
Data Comparator: a FastAPI web app that diffs result rows between two relational
databases, using one user-supplied SQL query per side. Setup/run is in `README.md`.

## Run & verify
- Run: `uvicorn app.main:app --reload` → http://localhost:8000
- All tests need deps from `requirements.txt` installed first. The comparison
  tests need a **live PostgreSQL** on localhost (test DBs hardcode
  `tc/tcpass`, db `tcdb`, e.g. `docker run -d --name dc-postgres -e POSTGRES_USER=tc
  -e POSTGRES_PASSWORD=tcpass -e POSTGRES_DB=tcdb -p 5432:5432 postgres:15`):
  - `python3 test_connections.py` — CRUD + Fernet encryption incl. `/api/compare/saved`; the compare steps need live PostgreSQL.
  - `python3 smoke_test.py` — end-to-end: PostgreSQL → SSE comparison → assertions (also a usage example for `compare.compare_events`).
  - `python3 test_app.py` — FastAPI TestClient: homepage, dialects, SSE streaming.
  - `python3 test_all_dialects.py` — per-dialect integration test (postgresql,
    mysql, mariadb; **no sqlite**); needs **live servers** (e.g. also
    `docker run` `mariadb:11` mapped to a host port) plus `psycopg2`/`pymysql`.

## Gotchas (read before editing — easy to get wrong)
- **`app/comparator.py` is corrected, not verbatim.** Adapted from
  npeersab/Universal-Data-Comparator; the upstream version is buggy (leaks a
  `None` on empty input, undercounts mismatches). Do **not** "fix" it back to
  match upstream. It computes a multiset difference, order-independent, early
  stopping at `max_mismatch_size`. See its header comment.
- **`sortedlist` is not on PyPI.** A compatible `SortedList` is vendored at
  `app/sortedlist.py` (imported by `comparator.py`). Don't add `sortedlist` to
  `requirements.txt` or try to `pip install` it.
- **Queries run verbatim via a raw DBAPI cursor** (`app/db.py::stream_rows`).
  They are **not** passed through SQLAlchemy's `text()`, so `:name` placeholders
  are sent to the DB as-is — no bind-param parsing, can't be parameterized here.
- **Rows are compared by `==`, never ordered.** `NULL`/`None` compare safely;
  just ensure both sides return the same columns/types.
- **Connections CRUD: create ≠ update.** `POST /api/connections` is an
  **upsert-by-name** (used for create); `PUT /api/connections/{id}` updates **by
  id** (used by the admin "Update connection" button). The admin form routes
  create→`POST`, edit→`PUT`. Editing **through `POST`** matches by name, so
  renaming a preset that way creates a duplicate instead of renaming in place.
  `PUT` returns `404` for a missing id and `409` for a name collision.
- **The connections store engine is cached on first use.** `test_connections.py`
  sets `DATA_COMPARATOR_DB` + `DATA_COMPARATOR_KEY` in `os.environ` **before**
  `from app.main import app`, so it runs against a throwaway temp DB. If you add
  a test that exercises the connections endpoints, set these first — otherwise
  the cached engine hits the real `data/connections.db`.
- **Saved connections no longer store a single `database`.** A preset stores a
  `databases` **list** that is enumerated from the server on save (and via
  `POST /api/connections/{id}/databases/refresh`, wired to the Admin "Refresh Databases"
  button). `refresh_databases()` swallows connection/credential errors and stores
  `[]` so an unreachable server never breaks saving. The runtime DB is supplied at
  compare time via `source_database`/`target_database` in `SavedCompareRequest`
  (see `to_config(conn, query, database)`). The schema migration drops the legacy
  `database` column and adds `databases` (in `get_engine()` via `_migrate_schema`).
- **SQLite is no longer a comparable target dialect.** Only `postgresql`,
  `mysql`, `mariadb` are supported for comparison (db.py `SUPPORTED_DIALECTS`).
  SQLite is still used only for the internal connections store. Dialect tests need
  live servers (e.g. `postgres:15` + `mariadb:11` on host ports); `smoke_test.py`
  and `test_app.py` now target PostgreSQL.

## How it's wired
- `app/main.py` — FastAPI app. SSE compare (`POST /api/compare/stream`,
  `POST /api/compare/saved`), `GET /api/dialects`, the `/` and `/admin` pages,
  and the connections CRUD (`GET/POST/PUT/DELETE /api/connections`).
- `app/connections.py` + `app/credentials.py` — saved-connection store: a SQLite
  table with **Fernet-encrypted** passwords. `DATA_COMPARATOR_DB` (default
  `data/connections.db`) sets the file; `DATA_COMPARATOR_KEY` sets the key
  (auto-generated to `<data_dir>/encryption.key`, mode 600, if unset).
- `app/compare.py::compare_events` — runs the diff in a **worker thread**, pushes
  `progress`/`result`/`error` onto a queue, and the SSE generator drains it.
  Progress fires only every `PROGRESS_EVERY` (1000) rows, so tiny test datasets
  emit none.
- `app/db.py` — builds SQLAlchemy URLs from `ConnectionConfig`; for SQLite,
  host/port/user/password are ignored and `database` is the file path.
- **`build_url` uses full `dialect+driver` URLs** (e.g. `mysql+pymysql`,
  `postgresql+psycopg2`). Don't strip the driver suffix — bare `mysql://` makes
  SQLAlchemy default to the MySQLdb driver, which isn't installed (only `pymysql`
  is), breaking MySQL/MariaDB.
- Static assets are served by FastAPI (`/static` mounted, `/` serves `index.html`);
  see **UI (static/)** for the frontend model.

## UI (static/)
- The whole frontend is plain HTML/CSS/JS in `static/` (`index.html`, `app.js`,
  `style.css`): **no build step, no framework, no CDN**. Don't introduce one.
- Styled to match the shadcn/ui look of
  `/home/noor/programs/dependency-manager` (same light/dark tokens, cards,
  buttons, header, theme toggle). Match that look when changing the UI.
- `app.js` uses `fetch` + `ReadableStream`, **not** `EventSource` — it must POST
  the request body and still read SSE. `EventSource` can't POST a body.
- The page is driven by element IDs in `index.html`; keep those stable when editing
  the markup. The header toggle flips the `.dark` class on `<html>` and persists to
  localStorage (system default).
- The **admin page** (`admin.html` + `admin.js`) manages connections in a **modal**:
  an "Add connection" button opens `#conn-modal`; `openModal("new")` /
  `openModal("edit", cfg)` drive it, and `closeModal()` closes it. The form lives
  inside the dialog (`#conn-form`), not inline on the page. Submit routes
  create→`POST /api/connections`, edit→`PUT /api/connections/{id}` (by id, so a
  rename doesn't duplicate a preset). Backdrop click (outside `#modal-panel`), the
  close button, and Escape all close it; focus returns to the trigger and body
  scroll is locked while open. `initDialectSelect()` returns a promise — set edit
  field values in its `.then()` so they land after the options load.
- A **delete confirmation** reuses the same modal system via `#confirm-modal`:
  `confirmDelete(id, name)` opens it (warning icon + Cancel/Delete footer),
  `cancelDelete()` closes it, and `performDelete()` issues the `DELETE`. The Delete
  button's label comes from the row's connection name. All three exit paths
  (Cancel button, backdrop click, Escape) route through `cancelDelete()`.
- **Static JS is served without cache-busting.** After editing `static/*.js`, do a
  hard reload (`location.reload(true)`) — the browser may keep serving the old
  `admin.js`/`app.js`, so a change looks like it didn't apply.

## Docker
- Multi-stage image, runs as non-root `app` (uid 1000). Recent `slim` base images
  ship no `python` user — the Dockerfile creates `app` explicitly; don't revert to
  `USER python`.
- For SQLite over a volume mount, the DB folder must be readable/writable by uid
  1000 (SQLite writes a journal). See README "Container" section.
