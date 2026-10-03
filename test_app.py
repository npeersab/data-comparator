"""Verify the FastAPI app: homepage, dialects endpoint, and SSE streaming."""
import json
import os
import tempfile
from sqlalchemy import create_engine, text

from starlette.testclient import TestClient

from app.main import app
from app.schemas import ConnectionConfig


def make_db(path, rows):
    eng = create_engine(f"sqlite:///{path}")
    with eng.connect() as c:
        c.execute(text("DROP TABLE IF EXISTS t"))
        c.execute(text("CREATE TABLE t (id INTEGER, val TEXT)"))
        for i, v in rows:
            c.execute(text("INSERT INTO t VALUES (:i, :v)"), {"i": i, "v": v})
        c.commit()


def main():
    tmp = tempfile.mkdtemp()
    sp = os.path.join(tmp, "s.db")
    tp = os.path.join(tmp, "t.db")
    make_db(sp, [(1, "a"), (2, "b"), (3, "c")])
    make_db(tp, [(1, "a"), (2, "b"), (4, "d")])

    client = TestClient(app)

    # 1. Homepage
    r = client.get("/")
    assert r.status_code == 200, r.status_code
    assert "Data Comparator" in r.text
    print("PASS: homepage serves HTML")

    # 2. Dialects
    r = client.get("/api/dialects")
    assert r.status_code == 200
    assert "postgresql" in r.json()["dialects"]
    print("PASS: /api/dialects ->", sorted(r.json()["dialects"]))

    # 3. SSE streaming comparison
    body = {
        "source": {"dialect": "sqlite", "database": sp, "query": "SELECT id, val FROM t"},
        "target": {"dialect": "sqlite", "database": tp, "query": "SELECT id, val FROM t"},
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
    big_s = os.path.join(tmp, "big_s.db")
    big_t = os.path.join(tmp, "big_t.db")
    make_db(big_s, [(i, f"v{i}") for i in range(2500)])
    make_db(big_t, [(i, f"v{i}") for i in range(2500)])
    body2 = {
        "source": {"dialect": "sqlite", "database": big_s, "query": "SELECT id, val FROM t"},
        "target": {"dialect": "sqlite", "database": big_t, "query": "SELECT id, val FROM t"},
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
