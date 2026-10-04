"""Verify the FastAPI app: homepage, dialects endpoint, and SSE streaming.

Uses a live PostgreSQL server (start one, e.g.:
  docker run -d --name dc-postgres -e POSTGRES_USER=tc -e POSTGRES_PASSWORD=tcpass \
    -e POSTGRES_DB=tcdb -p 5432:5432 postgres:15
SQLite is intentionally no longer a comparable target, so all data lives in PG).
"""
import json

from sqlalchemy import create_engine, text

from starlette.testclient import TestClient

from app.main import app

PG = "postgresql+psycopg2://tc:tcpass@localhost:5432/tcdb"


def seed_tables(source_rows, target_rows):
    eng = create_engine(PG)
    with eng.connect() as c:
        c.execute(text("DROP TABLE IF EXISTS t_source"))
        c.execute(text("DROP TABLE IF EXISTS t_target"))
        c.execute(text("CREATE TABLE t_source (id INTEGER, val TEXT)"))
        c.execute(text("CREATE TABLE t_target (id INTEGER, val TEXT)"))
        for i, v in source_rows:
            c.execute(text("INSERT INTO t_source VALUES (:i, :v)"), {"i": i, "v": v})
        for i, v in target_rows:
            c.execute(text("INSERT INTO t_target VALUES (:i, :v)"), {"i": i, "v": v})
        c.commit()


def cfg(query):
    return {
        "dialect": "postgresql", "host": "localhost", "port": 5432,
        "username": "tc", "password": "tcpass", "database": "tcdb", "query": query,
    }


def main():
    seed_tables([(1, "a"), (2, "b"), (3, "c")], [(1, "a"), (2, "b"), (4, "d")])

    client = TestClient(app)

    # 1. Homepage
    r = client.get("/")
    assert r.status_code == 200, r.status_code
    assert "Data Comparator" in r.text
    print("PASS: homepage serves HTML")

    # 2. Dialects (SQLite must no longer be offered as a target).
    r = client.get("/api/dialects")
    assert r.status_code == 200
    assert "postgresql" in r.json()["dialects"]
    assert "sqlite" not in r.json()["dialects"]
    print("PASS: /api/dialects ->", sorted(r.json()["dialects"]))

    # 3. SSE streaming comparison
    body = {
        "source": cfg("SELECT id, val FROM t_source"),
        "target": cfg("SELECT id, val FROM t_target"),
        "max_mismatch_size": 100,
    }
    events = []
    with client.stream("POST", "/api/compare/stream", json=body) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

    result = [e for e in events if "source_mismatches" in e][0]
    assert sorted(map(tuple, result["source_mismatches"])) == [(3, "c")], result
    assert sorted(map(tuple, result["target_mismatches"])) == [(4, "d")], result
    assert result["source_scanned"] == 3 and result["target_scanned"] == 3
    print("PASS: SSE /api/compare/stream ->", json.dumps(result))

    # 4. Progress events are emitted during scanning (needs >PROGRESS_EVERY rows).
    seed_tables([(i, f"v{i}") for i in range(2500)], [(i, f"v{i}") for i in range(2500)])
    body2 = {
        "source": cfg("SELECT id, val FROM t_source"),
        "target": cfg("SELECT id, val FROM t_target"),
        "max_mismatch_size": 100,
    }
    prog_count = 0
    with client.stream("POST", "/api/compare/stream", json=body2) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if "source_mismatches" not in payload:
                    prog_count += 1
    assert prog_count >= 1, "expected progress events for a large comparison"
    print(f"PASS: progress events streamed for large dataset -> {prog_count} event(s)")

    print("\nALL APP TESTS PASSED")


if __name__ == "__main__":
    main()
