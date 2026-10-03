from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionConfig(BaseModel):
    """Connection + query for one side of the comparison."""

    dialect: str  # postgresql, mysql, mariadb, sqlite
    username: str = ""
    password: str = ""
    host: str = "localhost"
    port: int | None = None
    database: str  # for sqlite this is the file path
    query: str


class CompareRequest(BaseModel):
    source: ConnectionConfig
    target: ConnectionConfig
    max_mismatch_size: int = Field(default=100, ge=1)


class SavedCompareRequest(BaseModel):
    """Compare two *saved* connections.

    The server resolves each id to a preset (decrypting the password) so the
    comparison UI never handles credentials directly. The SQL query for each side
    is supplied here at run time (it is not stored with the connection).
    """

    source_id: int
    source_query: str
    target_id: int
    target_query: str
    max_mismatch_size: int = Field(default=100, ge=1)


# ---- Saved connection presets ----
# A preset reuses the ConnectionConfig fields plus a unique user-chosen name.
# Passwords are stored encrypted at rest (see app/connections.py + app/credentials.py).


class SavedConnectionIn(BaseModel):
    """Create/update payload. `password` is plaintext here and is encrypted on storage."""

    name: str
    dialect: str
    username: str = ""
    password: str = ""
    host: str = "localhost"
    port: int | None = None
    database: str


class SavedConnectionOut(BaseModel):
    """Public view of a saved connection. Never includes the password."""

    id: int
    name: str
    dialect: str
    username: str
    host: str
    port: int | None
    database: str
    created_at: datetime
    updated_at: datetime


class SavedConnectionFull(BaseModel):
    """Full view including the decrypted password, used only when loading into the form."""

    id: int
    name: str
    dialect: str
    username: str
    password: str
    host: str
    port: int | None
    database: str
    created_at: datetime
    updated_at: datetime
