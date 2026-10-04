"""SQLAlchemy URL building, lazy row streaming, and database enumeration
for a raw SQL query."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL

from .schemas import ConnectionConfig

# Map friendly form names to SQLAlchemy dialect+driver names. The driver suffix
# matters: bare `mysql://` makes SQLAlchemy default to the MySQLdb (mysqlclient)
# driver, which is NOT a dependency — `requirements.txt` ships pymysql instead.
#
# SQLite is intentionally *not* a comparable target: it is file-based and has no
# server-side list of databases. (It is still used by the app's internal
# connections store.)
SUPPORTED_DIALECTS = {
    "postgresql": "postgresql+psycopg2",
    "postgres": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "mariadb": "mariadb+pymysql",
}


class ConnectionError(Exception):
    """Raised for unsupported dialects or invalid connection configuration."""


def build_url(cfg: ConnectionConfig) -> URL:
    """Build a SQLAlchemy URL object from a connection config."""
    dialect = SUPPORTED_DIALECTS.get(str(cfg.dialect).strip().lower())
    if not dialect:
        raise ConnectionError(f"Unsupported dialect: {cfg.dialect!r}")
    return URL.create(
        drivername=dialect,
        username=cfg.username or None,
        password=cfg.password,
        host=cfg.host or None,
        port=cfg.port,
        database=cfg.database,
    )


# ---- Database enumeration ----
# To list a server's databases we connect to a *maintenance* target: the always-
# present `postgres` database for PostgreSQL, and no database for MySQL/MariaDB
# (the drivers allow an uninitialised connection). The user-supplied `database`
# is ignored here.


def enumeration_url(cfg: ConnectionConfig) -> URL:
    """URL used only to enumerate a server's databases (not to run queries)."""
    dialect = SUPPORTED_DIALECTS.get(str(cfg.dialect).strip().lower())
    if not dialect:
        raise ConnectionError(f"Unsupported dialect: {cfg.dialect!r}")
    maintenance_db = "postgres" if dialect.startswith("postgresql") else None
    return URL.create(
        drivername=dialect,
        username=cfg.username or None,
        password=cfg.password,
        host=cfg.host or None,
        port=cfg.port,
        database=maintenance_db,
    )


def list_databases(cfg: ConnectionConfig) -> list[str]:
    """Return the names of the databases on the server described by ``cfg``.

    Connects to a maintenance database (see :func:`enumeration_url`) and runs a
    server-specific query. Raises on connection/query failure so callers can fall
    back to an empty list.
    """
    dialect = SUPPORTED_DIALECTS.get(str(cfg.dialect).strip().lower())
    if not dialect:
        raise ConnectionError(f"Unsupported dialect: {cfg.dialect!r}")

    if dialect.startswith("postgresql"):
        sql = text(
            "SELECT datname FROM pg_database "
            "WHERE datistemplate = false ORDER BY datname"
        )
    else:  # mysql+pymysql / mariadb+pymysql
        sql = text("SHOW DATABASES")

    engine = create_engine(enumeration_url(cfg))
    try:
        with engine.connect() as conn:
            return [row[0] for row in conn.execute(sql)]
    finally:
        engine.dispose()


def test_connection(cfg: ConnectionConfig) -> None:
    """Verify the server is reachable and the credentials work.

    Connects to a maintenance target (see :func:`enumeration_url`) and runs a
    trivial query; raises on any connection or authentication failure. A
    ``connect_timeout`` bounds the attempt so an unreachable host can't hang.
    """
    url = enumeration_url(cfg).set(query={"connect_timeout": "5"})
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def stream_rows(engine, sql: str, on_row=None):
    """Yield rows from a raw SQL query as tuples, lazily.

    Uses the raw DBAPI cursor so the user query is executed verbatim (no bind
    param parsing). Rows are produced one at a time so the comparator can stop
    early without draining the whole result set. `on_row` is called after each
    row is fetched (used for progress counting).
    """
    conn = engine.connect()
    try:
        try:
            cursor = conn.cursor()
        except AttributeError:
            cursor = conn.connection.cursor()
        cursor.execute(sql)
    except Exception:
        conn.close()
        raise

    def gen():
        try:
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                if on_row:
                    on_row()
                yield tuple(row)
        finally:
            cursor.close()
            conn.close()

    return gen()


def make_engine(url: URL):
    return create_engine(url)
