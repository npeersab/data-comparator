"""Smoke test: run the SSE comparison against PostgreSQL tables, check mismatches.

Uses a live PostgreSQL server (see test_app.py for the container setup). SQLite
is intentionally no longer a comparable target.
"""
import json

from sqlalchemy import create_engine, text

from app.schemas import ConnectionConfig
from app.compare import compare_events

PG_URL = {"dialect": "postgresql", "host": "localhost", "port": 5432,
          "username": "tc", "password": "tcpass", "database": "tcdb"}
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


def run_sse(cfg_source, cfg_target, max_mm):
    events = []
    for chunk in compare_events(cfg_source, cfg_target, max_mm):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    return events


def result_event(events):
    return [e for e in events if "source_mismatches" in e][0]


def error_event(events):
    return [e for e in events if "message" in e][0]


def main():
    src = ConnectionConfig(query="SELECT id, val FROM t_source", **PG_URL)
    tgt = ConnectionConfig(query="SELECT id, val FROM t_target", **PG_URL)

    seed_tables([(1, "a"), (2, "b"), (3, "c")], [(1, "a"), (2, "b"), (4, "d")])
    result = result_event(run_sse(src, tgt, 100))
    src_mm = sorted(map(tuple, result["source_mismatches"]))
    tgt_mm = sorted(map(tuple, result["target_mismatches"]))
    assert src_mm == [(3, "c")], src_mm
    assert tgt_mm == [(4, "d")], tgt_mm
    assert result["source_scanned"] == 3 and result["target_scanned"] == 3
    assert result["truncated"] is False
    print("PASS: basic mismatch detection")

    # Early truncation flag.
    r2 = result_event(run_sse(src, tgt, 1))
    assert r2["truncated"] is True, r2
    print("PASS: truncation flag set when max_mismatch_size reached")

    # NULLs are treated as values (rows are compared by ==, never ordering).
    seed_tables([(1, None), (2, "b")], [(1, None), (2, "b")])
    r3 = result_event(run_sse(src, tgt, 10))
    assert r3["source_mismatches"] == [] and r3["target_mismatches"] == [], r3
    print("PASS: NULL rows compared without error")

    # Unsupported dialect -> error event (build_url rejects it before connecting).
    bad = ConnectionConfig(dialect="nope", database="tcdb", query="SELECT 1")
    err = error_event(run_sse(bad, tgt, 10))
    assert "Unsupported dialect" in err["message"], err
    print("PASS: unsupported dialect reported as error ->", err["message"])

    # Bad SQL -> error event.
    bad_sql = ConnectionConfig(
        dialect="postgresql", host="localhost", port=5432,
        username="tc", password="tcpass", database="tcdb",
        query="SELECT * FROM does_not_exist",
    )
    err2 = error_event(run_sse(bad_sql, tgt, 10))
    assert err2["message"], err2
    print("PASS: bad SQL reported as error ->", err2["message"][:60])

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
