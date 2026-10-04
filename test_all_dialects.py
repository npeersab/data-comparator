"""End-to-end dialect tests: connect to each supported DB, run queries, diff rows.

Each DB gets two tables, t_source and t_target, with known data. We point the
app's compare_events() at each side and assert the multiset diff is correct.
Includes a NULL row to verify NULL == NULL (rows are compared by ==, never ordered).
"""
import json

from sqlalchemy import create_engine, text

from app.schemas import ConnectionConfig
from app.compare import compare_events

# Known data. (6, NULL) appears on both sides -> should match. (7, NULL) only on
# source -> source-only. bob vs BOB is case-sensitive -> distinct.
SRC = [(1, "alice"), (2, "bob"), (3, "carol"), (5, "eve"), (6, None), (7, None)]
TGT = [(1, "alice"), (2, "BOB"), (4, "dave"), (5, "eve"), (6, None)]

EXPECTED = {
    "source_scanned": 6,
    "target_scanned": 5,
    "source_only": 3,   # bob, carol, (7,NULL)
    "target_only": 2,   # BOB, dave
    "matched": 3,       # alice, eve, (6,NULL)
    "truncated": False,
}


def parse_events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    return events


def result(cfg_src, cfg_tgt, max_mm=100):
    events = parse_events(compare_events(cfg_src, cfg_tgt, max_mm))
    res = [e for e in events if "source_mismatches" in e]
    if not res:
        errs = [e.get("error") for e in events if "error" in e]
        raise RuntimeError(f"no result event; events={events}; errors={errs}")
    return res[0]


def seed_remote(url, rows):
    eng = create_engine(url)
    with eng.connect() as c:
        c.execute(text("DROP TABLE IF EXISTS t_source"))
        c.execute(text("DROP TABLE IF EXISTS t_target"))
        c.execute(text("CREATE TABLE t_source (id INTEGER, name TEXT)"))
        c.execute(text("CREATE TABLE t_target (id INTEGER, name TEXT)"))
        for i, n in rows:
            c.execute(text("INSERT INTO t_source VALUES (:i, :n)"), {"i": i, "n": n})
        for i, n in TGT:
            c.execute(text("INSERT INTO t_target VALUES (:i, :n)"), {"i": i, "n": n})
        c.commit()


def check(name, res):
    got = {
        "source_scanned": res["source_scanned"],
        "target_scanned": res["target_scanned"],
        "source_only": len(res["source_mismatches"]),
        "target_only": len(res["target_mismatches"]),
        "matched": res["source_scanned"] - len(res["source_mismatches"]),
        "truncated": res.get("truncated", False),
    }
    ok = got == EXPECTED
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"       expected {EXPECTED}")
        print(f"       got      {got}")
        print(f"       source_mismatches={res['source_mismatches']}")
        print(f"       target_mismatches={res['target_mismatches']}")
    return ok


def main():
    results = []

    src_q = "SELECT id, name FROM t_source"
    tgt_q = "SELECT id, name FROM t_target"

    # PostgreSQL
    seed_remote("postgresql+psycopg2://tc:tcpass@localhost:5432/tcdb", SRC)
    results.append(check("postgresql", result(
        ConnectionConfig(dialect="postgresql", username="tc", password="tcpass",
                         host="localhost", port=5432, database="tcdb", query=src_q),
        ConnectionConfig(dialect="postgresql", username="tc", password="tcpass",
                         host="localhost", port=5432, database="tcdb", query=tgt_q),
    )))

    # MySQL / MariaDB (same container, two dialect spellings)
    seed_remote("mysql+pymysql://tc:tcpass@localhost:3306/tcdb", SRC)
    results.append(check("mysql (against MariaDB)", result(
        ConnectionConfig(dialect="mysql", username="tc", password="tcpass",
                         host="localhost", port=3306, database="tcdb", query=src_q),
        ConnectionConfig(dialect="mysql", username="tc", password="tcpass",
                         host="localhost", port=3306, database="tcdb", query=tgt_q),
    )))
    results.append(check("mariadb (against MariaDB)", result(
        ConnectionConfig(dialect="mariadb", username="tc", password="tcpass",
                         host="localhost", port=3306, database="tcdb", query=src_q),
        ConnectionConfig(dialect="mariadb", username="tc", password="tcpass",
                         host="localhost", port=3306, database="tcdb", query=tgt_q),
    )))

    print()
    print(f"{sum(results)}/{len(results)} dialects passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
