"""Persisted connection presets, with passwords encrypted at rest.

Backed by a small SQLite database (path from ``DATA_COMPARATOR_DB``, default
``data/connections.db``). The ``password`` column stores Fernet ciphertext; the
plaintext is only recovered via :func:`to_full` when loading a preset into the
form. The list endpoint never returns passwords.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, Session, sessionmaker

from .credentials import encrypt_password, decrypt_password
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
    database = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


_engine = None


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
        conn.database = data.database
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
        conn.database = data.database
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
        database=conn.database,
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
        database=conn.database,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def to_config(conn: SavedConnection, query: str) -> ConnectionConfig:
    """Build a runtime ConnectionConfig from a preset (decrypts the password).

    The SQL ``query`` is supplied at run time — it is not stored with the preset.
    """
    return ConnectionConfig(
        dialect=conn.dialect,
        username=conn.username,
        password=decrypt_password(conn.password),
        host=conn.host,
        port=conn.port,
        database=conn.database,
        query=query,
    )
