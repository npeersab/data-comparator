# Data Comparator — Plan

A web app to compare data between **two relational databases** by running a
user-provided SQL query against each, then diffing the result rows with the
multiset-comparison algorithm from
[npeersab/Universal-Data-Comparator](https://github.com/npeersab/Universal-Data-Comparator)
(`comparator.py`, reused verbatim).

## Stack
- **FastAPI** backend (async, auto API docs, serves the frontend)
- **SQLAlchemy** for database access — one dialect-agnostic layer covering
  PostgreSQL, MySQL/MariaDB, SQLite (add drivers as needed)
- **Vanilla JS + CSS** frontend (no build step)
- **Server-Side Events (SSE)** to stream progress + results for large datasets
- **`comparator.py`** — same streaming two-buffer design as the reference repo, but
  corrected (the original undercounts mismatches and leaks a `None` on empty input).
  See `app/comparator.py` header for details.

## File structure
```
data-comparator/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, /api/compare/stream route, serves UI
│   ├── comparator.py    # the reference algorithm, copied as-is
│   ├── db.py            # build SQLAlchemy URL from form fields, engine + row-streaming
│   ├── compare.py       # worker thread: stream both DBs into compare(), emit SSE
│   └── schemas.py       # request/response models (pydantic)
├── static/
│   ├── index.html       # two connection panels + query editors + results
│   ├── app.js           # POSTs via fetch, parses SSE stream, renders table + exports
│   └── style.css
├── requirements.txt
└── README.md
```

## How it connects to the reference comparator
The comparator only needs two **iterables of tuples** + `max_mismatch_size`, so:
1. `db.py` builds a SQLAlchemy URL from each panel's form (dialect/host/port/db/user/pass)
   and streams rows as tuples lazily via the raw DBAPI cursor (so the user query is
   treated as raw SQL — no bind-param parsing) and memory stays flat for big results.
2. `compare.py` runs the comparison in a **worker thread**; a progress callback counts
   rows scanned and pushes progress onto a queue. The SSE generator (in a threadpool)
   drains the queue and emits `progress` / `result` / `error` events.
3. On completion it emits a final `result` event with both mismatch lists + counts.

## SSE flow
- `POST /api/compare/stream` returns `text/event-stream`.
- The frontend uses `fetch` + a `ReadableStream` reader (not `EventSource`, since
  `EventSource` can't POST a body). It parses `event:`/`data:` lines into SSE events.
- Events: `event: progress` (rows scanned), `event: result` (final mismatches + counts),
  `event: error` (failure message). Progress is emitted every N rows scanned.

## User flow
1. Fill **Source** and **Target** panels (dialect + connection + SQL query each) and set
   `max_mismatch_size` (default 100).
2. Click **Run** → SSE streams progress, then the final result.
3. Results show: **counts** (rows scanned, matched, source-only / target-only mismatches,
   whether truncated at `max_mismatch_size`), a **table** of mismatch rows (tagged
   source-only / target-only), and **CSV / JSON export** buttons (client-side from the
   returned data).

## Caveats handled
- **Orderable values**: the reference `sortedlist` package is not on PyPI, so a small
  dependency-free `SortedList` shim is vendored at `app/sortedlist.py`. The corrected
  algorithm matches rows by `==` only (never ordering), so `NULL`/`None` values
  compare safely and do not raise. Rows just need matching columns/types.
- **Early stop**: once `max_mismatch_size` is hit, the comparator stops; totals then
  reflect "rows scanned", labeled as truncated.
- **Connection safety**: cursors/connections closed in `finally` on early exit or error;
  engines disposed after the run.

## Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```

## Optional (future)
- Run the two queries concurrently (currently sequential)
- Per-dialect port defaults / connection test button
