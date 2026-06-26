"""Symmetric encryption for FTP passwords at rest (FR-003).

Key resolution order:
  1. ``APP_SECRET`` env var, if set (lets the operator manage the key).
  2. A key file next to the SQLite database (on the data volume), generated on
     first use. Keeping it beside the DB means a volume backup captures both, so a
     restored database stays decryptable.
"""
from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import make_url

from app.settings import get_settings

settings = get_settings()


def _key_path() -> str:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        return os.path.join(os.path.dirname(os.path.abspath(url.database)), "app_secret.key")
    return os.path.abspath(os.path.join("data", "app_secret.key"))


@lru_cache
def _fernet() -> Fernet:
    if settings.app_secret:
        return Fernet(settings.app_secret.encode())

    path = _key_path()
    if os.path.exists(path):
        with open(path, "rb") as fh:
            key = fh.read().strip()
    else:
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(key)
        try:
            os.chmod(path, 0o600)  # best-effort; no-op on some filesystems
        except OSError:
            pass
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a secret, returning a URL-safe token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`.

    Raises :class:`cryptography.fernet.InvalidToken` if the key no longer matches
    (e.g. the DB was restored without its key file).
    """
    return _fernet().decrypt(token.encode()).decode()


__all__ = ["encrypt", "decrypt", "InvalidToken"]
