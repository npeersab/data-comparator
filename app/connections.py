"""Persisted connection presets, with passwords encrypted at rest.

Backed by a small SQLite database (path from ``DATA_COMPARATOR_DB``, default
``data/connections.db``). The ``password`` column stores Fernet ciphertext; the
plaintext is only recovered via :func:`to_full` when loading a preset into the
form. The list endpoint never returns passwords.
"""

import os
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base, Session, sessionmaker

from .credentials import encrypt_password, decrypt_password
from .db import list_databases
from .schemas import ConnectionConfig, SavedConnectionIn, SavedConnectionOut, SavedConnectionFull

DEFAULT_DATA_DIR = "data"
DEFAULT_DB_NAME = "connections.db"

Base = declarative_base()


def _utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone concept)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SavedConnection(Base):
    __tablename__ = "connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)
    dialect = Column(String, nullable=False)
    username = Column(String, nullable=False, default="")
    password = Column(String, nullable=False, default="")  # encrypted at rest
    host = Column(String, nullable=False, default="localhost")
    port = Column(Integer, nullable=True)
    # JSON-text list of the server's databases, enumerated from the server and
    # refreshed on save / via the admin "Refresh Databases" button.
    databases = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


_engine = None


def _migrate_schema(engine) -> None:
    """Bring an existing ``connections`` table up to the current schema.

    ``create_all`` does not alter an existing table, so add the new ``databases``
    column and drop the legacy single-``database`` column in place. A brand-new DB
    is created with the current model, so this is a no-op there.
    """
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(connections)"))]
        if "database" in columns:
            conn.execute(text("ALTER TABLE connections DROP COLUMN database"))
        if "databases" not in columns:
            conn.execute(text("ALTER TABLE connections ADD COLUMN databases TEXT"))
        conn.commit()


def get_engine():
    """Return a cached SQLite engine, creating the DB (and table) on first use."""
    global _engine
    if _engine is None:
        db_path = os.environ.get(
            "DATA_COMPARATOR_DB", os.path.join(DEFAULT_DATA_DIR, DEFAULT_DB_NAME)
        )
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        url = f"sqlite:///{os.path.abspath(db_path)}"
        _engine = create_engine(
            url, future=True, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(_engine)
        _migrate_schema(_engine)
    return _engine


def get_session() -> Session:
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return factory()


def list_connections():
    with get_session() as session:
        return (
            session.query(SavedConnection)
            .order_by(SavedConnection.name.asc())
            .all()
        )


def get_connection(conn_id: int):
    with get_session() as session:
        return session.get(SavedConnection, conn_id)


def upsert_connection(data: SavedConnectionIn) -> SavedConnection:
    """Create or update a preset by unique name. Encrypts the password."""
    with get_session() as session:
        conn = (
            session.query(SavedConnection)
            .filter(SavedConnection.name == data.name)
            .one_or_none()
        )
        if conn is None:
            conn = SavedConnection(name=data.name)
            session.add(conn)
        conn.dialect = data.dialect
        conn.username = data.username
        conn.password = encrypt_password(data.password)
        conn.host = data.host
        conn.port = data.port
        session.commit()
        session.refresh(conn)
        return conn


def update_connection(conn_id: int, data: SavedConnectionIn) -> "SavedConnection | None":
    """Update a preset by id (name included). Encrypts the password.

    Returns None if no preset has that id; raises ValueError if the new name
    already belongs to a different preset.
    """
    with get_session() as session:
        conn = session.get(SavedConnection, conn_id)
        if conn is None:
            return None
        if data.name != conn.name and (
            session.query(SavedConnection.id)
            .filter(SavedConnection.name == data.name)
            .filter(SavedConnection.id != conn_id)
            .first()
        ):
            raise ValueError("A connection with that name already exists")
        conn.name = data.name
        conn.dialect = data.dialect
        conn.username = data.username
        conn.password = encrypt_password(data.password)
        conn.host = data.host
        conn.port = data.port
        session.commit()
        session.refresh(conn)
        return conn


def delete_connection(conn_id: int) -> bool:
    with get_session() as session:
        conn = session.get(SavedConnection, conn_id)
        if conn is None:
            return False
        session.delete(conn)
        session.commit()
        return True


def to_public(conn: SavedConnection) -> SavedConnectionOut:
    """Public serialization — no password."""
    return SavedConnectionOut(
        id=conn.id,
        name=conn.name,
        dialect=conn.dialect,
        username=conn.username,
        host=conn.host,
        port=conn.port,
        databases=_databases(conn),
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def to_full(conn: SavedConnection) -> SavedConnectionFull:
    """Full serialization — decrypts the password for loading into the form."""
    return SavedConnectionFull(
        id=conn.id,
        name=conn.name,
        dialect=conn.dialect,
        username=conn.username,
        password=decrypt_password(conn.password),
        host=conn.host,
        port=conn.port,
        databases=_databases(conn),
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def _databases(conn: SavedConnection) -> list[str]:
    """Parse the stored JSON-text database list (empty if unset/corrupt)."""
    if not conn.databases:
        return []
    try:
        return json.loads(conn.databases)
    except (ValueError, TypeError):
        return []


def to_config(conn: SavedConnection, query: str, database: str) -> ConnectionConfig:
    """Build a runtime ConnectionConfig from a preset (decrypts the password).

    The SQL ``query`` and the target ``database`` are both supplied at run time —
    neither is stored with the preset.
    """
    return ConnectionConfig(
        dialect=conn.dialect,
        username=conn.username,
        password=decrypt_password(conn.password),
        host=conn.host,
        port=conn.port,
        database=database,
        query=query,
    )


def refresh_databases(conn_id: int) -> "SavedConnection | None":
    """Re-enumerate a preset's server databases and store the list.

    Returns the updated preset, or None if it does not exist. Connection or
    credential failures are swallowed and recorded as an empty list, so a
    temporarily unreachable server never breaks saving.
    """
    with get_session() as session:
        conn = session.get(SavedConnection, conn_id)
        if conn is None:
            return None
        try:
            cfg = to_config(conn, "", "")
            names = list_databases(cfg)
        except Exception:  # noqa: BLE001 - record failure as an empty list
            names = []
        conn.databases = json.dumps(names)
        session.commit()
        session.refresh(conn)
        return conn
