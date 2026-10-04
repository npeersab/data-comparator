"""Verify saved-connection presets: encryption + CRUD API.

Runs against a throwaway SQLite DB + a fixed Fernet key (via env) so it leaves
no files behind. Must set DATA_COMPARATOR_* before importing app.main so the
cached engine points at the temp DB.
"""

import json
import os
import tempfile

from cryptography.fernet import Fernet

# Isolated store + deterministic key, set before importing the app.
_TMP = tempfile.mkdtemp()
os.environ["DATA_COMPARATOR_DB"] = os.path.join(_TMP, "connections.db")
os.environ["DATA_COMPARATOR_KEY"] = Fernet.generate_key().decode()

from sqlalchemy import create_engine, text

from starlette.testclient import TestClient

from app.main import app


BASE = {
    "dialect": "postgresql",
    "username": "svc",
    "password": "s3cr3t-pw",
    "host": "db.internal",
    "port": 5432,
}


def _payload(name, **over):
    p = dict(BASE)
    p.update(over)
    p["name"] = name
    return p


def main():
    client = TestClient(app)

    # 1. Empty list to start.
    r = client.get("/api/connections")
    assert r.status_code == 200
    assert r.json() == [], r.json()
    print("PASS: starts empty")

    # 2. Create a preset.
    r = client.post("/api/connections", json=_payload("prod-orders"))
    assert r.status_code == 201, r.text
    body = r.json()
    conn_id = body["id"]
    assert "password" not in body, "public view must not include password"
    assert body["name"] == "prod-orders" and body["dialect"] == "postgresql"
    print("PASS: create preset ->", body["name"], "id", conn_id)

    # 3. Ciphertext is stored, not plaintext.
    eng = create_engine(f"sqlite:///{os.environ['DATA_COMPARATOR_DB']}")
    with eng.connect() as c:
        row = c.execute(
            text("SELECT password FROM connections WHERE id = :id"), {"id": conn_id}
        ).fetchone()
        stored = row[0]
    assert stored, "stored password should be non-empty ciphertext"
    assert stored != BASE["password"], "DB must not contain plaintext password"
    assert "s3cr3t-pw" not in stored
    print("PASS: password stored as ciphertext (not plaintext)")

    # 4. List returns no password field.
    r = client.get("/api/connections")
    assert all("password" not in c for c in r.json())
    assert len(r.json()) == 1
    print("PASS: list omits passwords")

    # 5. Full view decrypts the password.
    r = client.get(f"/api/connections/{conn_id}")
    assert r.status_code == 200, r.text
    assert r.json()["password"] == BASE["password"], r.json()["password"]
    assert "password" not in client.get("/api/connections").json()[0]
    print("PASS: full view decrypts password for loading")

    # 6. Update by name (idempotent upsert) — same id, password re-encrypted.
    updated = _payload("prod-orders", port=5433)
    r = client.post("/api/connections", json=updated)
    assert r.status_code == 201
    assert r.json()["id"] == conn_id, "updating by name should keep the same id"
    r = client.get(f"/api/connections/{conn_id}")
    assert r.json()["port"] == 5433
    assert "databases" in r.json()
    print("PASS: upsert by name keeps id and updates fields")

    # 7. Duplicate name does not create a second row.
    client.post("/api/connections", json=_payload("staging"))
    assert len(client.get("/api/connections").json()) == 2
    print("PASS: duplicate names do not duplicate rows")

    # 8. Empty name is rejected.
    r = client.post("/api/connections", json=_payload("", password=""))
    assert r.status_code == 400, r.status_code
    print("PASS: empty name rejected (400)")

    # 9. Delete.
    r = client.delete(f"/api/connections/{conn_id}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(client.get("/api/connections").json()) == 1
    print("PASS: delete removes the preset")

    # 10. Missing ids -> 404.
    assert client.get(f"/api/connections/{conn_id}").status_code == 404
    assert client.delete(f"/api/connections/{conn_id}").status_code == 404
    print("PASS: missing ids return 404")

    # 11. Compare two saved connections by id (credentials stay server-side).
    # Two PostgreSQL databases, each with its own `t` table.
    def seed_pg_db(dbname, rows):
        admin = create_engine(
            "postgresql+psycopg2://tc:tcpass@localhost:5432/postgres",
            isolation_level="AUTOCOMMIT",
        )
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
            c.execute(text(f"CREATE DATABASE {dbname}"))
        eng = create_engine(
            f"postgresql+psycopg2://tc:tcpass@localhost:5432/{dbname}"
        )
        with eng.connect() as c:
            c.execute(text("DROP TABLE IF EXISTS t"))
            c.execute(text("CREATE TABLE t (id INTEGER, val TEXT)"))
            for i, v in rows:
                c.execute(text("INSERT INTO t VALUES (:i, :v)"), {"i": i, "v": v})
            c.commit()

    seed_pg_db("cmpsrc", [(1, "a"), (2, "b")])
    seed_pg_db("cmptgt", [(1, "a"), (3, "c")])

    client.post(
        "/api/connections",
        json=_payload("cmp-src", dialect="postgresql", host="localhost",
                      port=5432, username="tc", password="tcpass"),
    )
    client.post(
        "/api/connections",
        json=_payload("cmp-tgt", dialect="postgresql", host="localhost",
                      port=5432, username="tc", password="tcpass"),
    )

    def find_id(name):
        return next(c["id"] for c in client.get("/api/connections").json() if c["name"] == name)

    src_id, tgt_id = find_id("cmp-src"), find_id("cmp-tgt")

    events = []
    with client.stream(
        "POST", "/api/compare/saved",
        json={"source_id": src_id, "source_query": "SELECT id, val FROM t",
              "source_database": "cmpsrc",
              "target_id": tgt_id, "target_query": "SELECT id, val FROM t",
              "target_database": "cmptgt",
              "max_mismatch_size": 100},
    ) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    result = [e for e in events if "source_mismatches" in e][0]
    assert sorted(map(tuple, result["source_mismatches"])) == [(2, "b")], result
    assert sorted(map(tuple, result["target_mismatches"])) == [(3, "c")], result
    print("PASS: /api/compare/saved resolves presets server-side ->", json.dumps(result))

    # 12. Missing id -> 404.
    r = client.post(
        "/api/compare/saved",
        json={"source_id": 999999, "source_query": "SELECT 1",
              "source_database": "cmpsrc",
              "target_id": tgt_id, "target_query": "SELECT 1",
              "target_database": "cmptgt"},
    )
    assert r.status_code == 404, r.status_code
    print("PASS: /api/compare/saved 404s on missing connection")

    # 13. Update by id (edit targets the preset by id, including its name).
    before = len(client.get("/api/connections").json())
    r = client.post("/api/connections", json=_payload("edit-me"))
    assert r.status_code == 201
    edit_id = r.json()["id"]

    # rename + change fields via PUT by id — same id, no duplicate row.
    r = client.put(
        f"/api/connections/{edit_id}",
        json=_payload("renamed", dialect="mysql", host="h2", port=3306),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == edit_id
    assert body["name"] == "renamed"
    assert body["dialect"] == "mysql" and body["port"] == 3306
    assert len(client.get("/api/connections").json()) == before + 1

    # password round-trips through re-encryption (stored as ciphertext again).
    full = client.get(f"/api/connections/{edit_id}").json()
    assert full["password"] == _payload("renamed")["password"]
    eng = create_engine(f"sqlite:///{os.environ['DATA_COMPARATOR_DB']}")
    with eng.connect() as c:
        stored = c.execute(
            text("SELECT password FROM connections WHERE id = :id"), {"id": edit_id}
        ).fetchone()[0]
    assert stored != _payload("renamed")["password"]

    # Renaming onto an existing preset's name is rejected (unique name).
    r = client.put(f"/api/connections/{edit_id}", json=_payload("staging"))
    assert r.status_code == 409, r.status_code

    # PUT on a missing id -> 404.
    assert client.put("/api/connections/999999", json=_payload("x")).status_code == 404

    client.delete(f"/api/connections/{edit_id}")
    assert len(client.get("/api/connections").json()) == before
    print("PASS: update by id (PUT) renames + updates fields, rejects collisions ->",
          json.dumps(body))

    print("\nALL CONNECTION TESTS PASSED")


if __name__ == "__main__":
    main()
