"""Smoke test: build two SQLite DBs, run the SSE comparison, check mismatches."""
import json
import os
import tempfile

from sqlalchemy import create_engine, text

from app.schemas import ConnectionConfig
from app.compare import compare_events


def make_db(path, rows):
    eng = create_engine(f"sqlite:///{path}")
    with eng.connect() as c:
        c.execute(text("DROP TABLE IF EXISTS t"))
        c.execute(text("CREATE TABLE t (id INTEGER, val TEXT)"))
        for i, v in rows:
            c.execute(text("INSERT INTO t VALUES (:i, :v)"), {"i": i, "v": v})
        c.commit()
    return eng


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
    tmp = tempfile.mkdtemp()
    s_path = os.path.join(tmp, "s.db")
    t_path = os.path.join(tmp, "t.db")
    make_db(s_path, [(1, "a"), (2, "b"), (3, "c")])
    make_db(t_path, [(1, "a"), (2, "b"), (4, "d")])

    src = ConnectionConfig(dialect="sqlite", database=s_path, query="SELECT id, val FROM t")
    tgt = ConnectionConfig(dialect="sqlite", database=t_path, query="SELECT id, val FROM t")

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

    # NULLs are treated as values (the vendored shim compares by ==, never ordering).
    make_db(s_path, [(1, None), (2, "b")])
    make_db(t_path, [(1, None), (2, "b")])
    r3 = result_event(run_sse(src, tgt, 10))
    assert r3["source_mismatches"] == [] and r3["target_mismatches"] == [], r3
    print("PASS: NULL rows compared without error")

    # Unsupported dialect -> error event.
    bad = ConnectionConfig(dialect="nope", database=s_path, query="SELECT 1")
    err = error_event(run_sse(bad, tgt, 10))
    assert "Unsupported dialect" in err["message"], err
    print("PASS: unsupported dialect reported as error ->", err["message"])

    # Bad SQL -> error event.
    bad_sql = ConnectionConfig(dialect="sqlite", database=s_path, query="SELECT * FROM does_not_exist")
    err2 = error_event(run_sse(bad_sql, tgt, 10))
    assert err2["message"], err2
    print("PASS: bad SQL reported as error ->", err2["message"][:60])

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
