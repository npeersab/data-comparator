"""Password encryption for saved connection presets.

Passwords are stored encrypted at rest in the connections database. The key is
sourced from the ``DATA_COMPARATOR_KEY`` env var, or generated once and stored in
a key file next to the database (mode 0600).

WARNING: the key is required to decrypt stored passwords. If the key is lost,
every saved password becomes unrecoverable — back up the key file alongside the
database. Encryption at rest protects the DB file if stolen; it does not protect
against a fully compromised host (the app must decrypt to use the passwords).
"""

import os

from cryptography.fernet import Fernet

DEFAULT_DATA_DIR = "data"
KEY_FILENAME = "encryption.key"

_fernet = None


def _data_dir():
    """Directory that holds the connections DB (and, by default, the key file)."""
    db_path = os.environ.get(
        "DATA_COMPARATOR_DB", os.path.join(DEFAULT_DATA_DIR, "connections.db")
    )
    return os.path.dirname(os.path.abspath(db_path)) or "."


def get_key() -> bytes:
    """Return the Fernet key, generating and persisting a key file if needed.

    Priority: ``DATA_COMPARATOR_KEY`` env var, else ``<data_dir>/encryption.key``.
    """
    env_key = os.environ.get("DATA_COMPARATOR_KEY")
    if env_key:
        return env_key.encode()

    key_path = os.path.join(_data_dir(), KEY_FILENAME)
    if os.path.exists(key_path):
        with open(key_path, "rb") as fh:
            return fh.read()

    key = Fernet.generate_key()
    os.makedirs(_data_dir(), exist_ok=True)
    with open(key_path, "wb") as fh:
        fh.write(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        # chmod is best-effort; some filesystems don't support it.
        pass
    return key


_instance = None


def _fernet() -> Fernet:
    global _instance
    if _instance is None:
        _instance = Fernet(get_key())
    return _instance


def encrypt_password(plaintext: str) -> str:
    """Encrypt a password for storage. Empty input is stored as empty string."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_password(token: str) -> str:
    """Decrypt a stored password token. Empty input returns empty string."""
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()
