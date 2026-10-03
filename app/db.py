"""SQLAlchemy URL building and lazy row streaming for a raw SQL query."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL

from .schemas import ConnectionConfig

# Map friendly form names to SQLAlchemy dialect+driver names. The driver suffix
# matters: bare `mysql://` makes SQLAlchemy default to the MySQLdb (mysqlclient)
# driver, which is NOT a dependency — `requirements.txt` ships pymysql instead.
SUPPORTED_DIALECTS = {
    "postgresql": "postgresql+psycopg2",
    "postgres": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "mariadb": "mariadb+pymysql",
    "sqlite": "sqlite",
}


class ConnectionError(Exception):
    """Raised for unsupported dialects or invalid connection configuration."""


def build_url(cfg: ConnectionConfig) -> URL:
    """Build a SQLAlchemy URL object from a connection config."""
    dialect = SUPPORTED_DIALECTS.get(str(cfg.dialect).strip().lower())
    if not dialect:
        raise ConnectionError(f"Unsupported dialect: {cfg.dialect!r}")
    # SQLite is file/socket based: host, port, user, and password are ignored.
    if dialect == "sqlite":
        return URL.create(drivername="sqlite", database=cfg.database)
    return URL.create(
        drivername=dialect,
        username=cfg.username or None,
        password=cfg.password,
        host=cfg.host or None,
        port=cfg.port,
        database=cfg.database,
    )


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
