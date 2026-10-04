# Data Comparator

A web app to compare data between **two relational databases**. Provide a SQL
query for each database, run them, and diff the result rows using the multiset comparison algorithm from
[npeersab/Universal-Data-Comparator](https://github.com/npeersab/Universal-Data-Comparator)
(`app/comparator.py`, adapted from its `comparator.py` — corrected, not verbatim;
see "Notes / limitations").

## Features
- Two pages: a **Compare** page that diffs two saved connections, and an **Admin**
  page (`/admin`) for managing those connections.
- Connect to two databases (PostgreSQL, MySQL/MariaDB).
- Run an arbitrary SQL query on each side (entered on the Compare page at run time).
- Streams progress over Server-Side Events (SSE) — works for large result sets.
- Shows matched / source-only / target-only counts, an on-screen mismatch table,
  and CSV + JSON export.
- Saved connection presets are stored server-side and reused by the compare page;
  passwords are encrypted at rest (Fernet) in a small SQLite database.

## Install
```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

All required drivers are included in `requirements.txt` (`psycopg2-binary` for
PostgreSQL, `pymysql` for MySQL/MariaDB).

## Run
```bash
uvicorn app.main:app --reload
```
Open http://localhost:8000.

## Use
The app has two pages, reached from the header nav:

**Compare** (`/`) — pick a saved connection for **Source** and **Target**, then
run. Enter the SQL query for each side; it is executed verbatim.
1. From each side's dropdown, choose a saved connection (managed on the
   **Admin** page). Its dialect and connection details are shown for reference.
2. From the **Database** dropdown that appears, choose the database to query
   (enumerated from the server when the connection was saved).
3. Enter the SQL query for **Source** and **Target**.
4. Set **Max mismatches to collect** (default 100) and click **Run comparison**.
5. Watch progress, then review the mismatch table. Use **Export CSV / JSON** for
   the full list.

**Admin** (`/admin`) — create, edit, and delete the saved connections the
compare page can use. Each preset stores the connection details under a name you
choose; passwords are encrypted at rest.

## Saved connections
Saved presets live on the **Admin** page (`/admin`). The compare page only
selects from these presets, so it never handles connection credentials directly.
Create a preset by filling in the connection details under a name you choose.
The query itself is entered on the Compare page each time, so it is never stored.
The preset's databases are enumerated from the server when it is saved (and via
the **Refresh Databases** button on the Admin page); that list is stored with the
preset and offered as a dropdown on the Compare page.

Saved presets are stored in a small SQLite database on the server, with passwords
**encrypted at rest** (Fernet). The database lives at `DATA_COMPARATOR_DB`
(default `data/connections.db`). If `DATA_COMPARATOR_KEY` is not set, a random
encryption key is generated on first run and written to `<data_dir>/encryption.key`
(file mode `600`).

> **Security note:** this is a local, single-user tool. Queries run as raw SQL
> against whatever databases you configure — only point it at databases you trust.
> Saved passwords are protected only against someone who steals the DB file; the
> app must decrypt them to use them. **Back up the encryption key alongside the
> database** — if the key is lost, every saved password becomes unrecoverable.

## API
- `POST /api/compare/stream` — `text/event-stream`. Request body:
  ```json
  {
    "source": { "dialect": "postgresql", "host": "localhost", "port": 5432,
                "username": "", "password": "", "database": "db", "query": "SELECT ..." },
    "target": { ... },
    "max_mismatch_size": 100
  }
  ```
- Emits `event: progress` (rows scanned), `event: result` (final mismatches + counts),
  or `event: error` (failure message).
- `POST /api/compare/saved` — compare two **saved** connections, used by the
  compare page. Request body:
  ```json
  { "source_id": 1, "source_query": "SELECT ...",
    "target_id": 2, "target_query": "SELECT ...",
    "max_mismatch_size": 100 }
  ```
  The server resolves each id to a preset (decrypting the password server-side) and
  runs the supplied query. It streams the same `progress` / `result` / `error`
  events. Returns `404` if either id is unknown. The compare page never handles
  credentials directly.
- `GET /api/dialects` — list of supported dialects.
- `GET /api/connections` — list saved presets (passwords omitted).
- `GET /api/connections/{id}` — one preset, with the password decrypted (for
  loading into the admin form).
- `POST /api/connections` — create (or upsert-by-name) a preset. Body:
  `{ "name": "prod-orders", "dialect": "postgresql", "host": "...", "port": 5432,
    "username": "...", "password": "..." }`. The server enumerates the preset's
    databases from the server on save (and on the Admin "Refresh Databases" button);
    that list is stored with the preset and offered as a dropdown on the Compare
    page — the database is intentionally **not** part of the create body.
- `POST /api/connections/{id}/databases/refresh` — re-enumerate a preset's
  databases from the server and store the list (wired to the Admin "Refresh Databases"
  button). Returns `404` if the id is unknown.
- `PUT /api/connections/{id}` — update a preset **by id** (used by the admin
  "Update connection" button). Same body as `POST`; updates every field
  including `name` in place, so renaming does not create a duplicate. Returns
  `404` if the id is unknown and `409` if the new name collides with another
  preset.
- `DELETE /api/connections/{id}` — delete a preset.
- `GET /admin` — serves the connection-administration page.

## Container (Docker)
The app is packaged as a small, multi-stage image that runs as a non-root user.

```bash
# build + run (single command)
docker run -d --name data-comparator -p 8000:8000 --restart unless-stopped data-comparator
# ...or build first, then run
docker build -t data-comparator:latest .
docker run -d --name data-comparator -p 8000:8000 data-comparator:latest
```

Or with the provided compose file:
```bash
docker compose up -d
```

Then open http://localhost:8000. A healthcheck polls `/api/dialects`.

**Saved connections storage.** Presets and their encryption key are written under
`/app/data` inside the container. `docker-compose.yml` bind-mounts a named volume
(`data-comparator-data`) there, so they survive restarts. To keep them across
reinstalls, back up that volume (or mount your own directory). To supply your own
key instead of an auto-generated one, set `DATA_COMPARATOR_KEY` in the container
environment — losing the key makes saved passwords unreadable.

**Connecting to databases from the container.** The app connects only to server
dialects (PostgreSQL, MySQL/MariaDB); there is no file-based SQLite option. Your
database hosts must be reachable from inside the container (use a reachable
host/IP or a `networks` setup in `docker-compose.yml`).

## Testing
Lightweight test scripts (run with any Python that has the deps installed):

```bash
python3 smoke_test.py     # end-to-end: PostgreSQL -> SSE comparison -> assertions
python3 test_app.py       # FastAPI TestClient: homepage, dialects, SSE streaming
python3 test_connections.py  # CRUD + encryption, incl. /api/compare/saved
```

`smoke_test.py` also doubles as a usage example for `compare.compare_events`.

## Notes / limitations
- **Comparator corrected**: the reference `comparator.py` from the linked repo has
  bugs (it can emit a spurious `None` on empty input and undercounts mismatches in
  the stream-exhaustion logic). `app/comparator.py` keeps the same streaming,
  two-buffer design and signature but computes the multiset difference correctly
  (verified against a `Counter`-based reference over 7000 random cases). See the
  header comment in `app/comparator.py`.
- **Comparable values**: the comparison matches rows by `==` (never ordering), so
  `NULL`/`None` values are compared safely and do not raise. Rows just need to have
  the same columns/types on both sides.
- **Early stop**: comparison stops once `max_mismatch_size` mismatches are found;
  counts then reflect rows scanned and are flagged as truncated.
- **Security**: queries are executed as raw SQL against the databases you configure.
  Only run this against databases you trust.

## Project layout
```
app/
  comparator.py   # reference algorithm, corrected (see header comment)
  db.py           # SQLAlchemy URL building + lazy row streaming
  compare.py      # worker thread + SSE event generation
  connections.py  # saved-connection store (SQLite, passwords encrypted at rest)
  credentials.py  # Fernet encryption for saved passwords
  main.py         # FastAPI app + routes (compare page, /admin, connections CRUD)
  schemas.py      # request + connection-preset models (incl. SavedCompareRequest)
  sortedlist.py   # vendored SortedList shim (sortedlist isn't on PyPI)
static/           # index.html, app.js (compare), admin.html, admin.js, style.css
Dockerfile        # multi-stage, non-root runtime
docker-compose.yml
.dockerignore
```
