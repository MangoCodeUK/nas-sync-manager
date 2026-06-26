"""Test fixtures.

Point the app at an isolated temp SQLite DB and a fixed Fernet key BEFORE any app
module is imported, so the cached settings/engine pick them up.
"""
from __future__ import annotations

import os
import tempfile

from cryptography.fernet import Fernet

_DB_PATH = os.path.join(tempfile.gettempdir(), "nas_sync_test.db")
if os.path.exists(_DB_PATH):
    os.remove(_DB_PATH)

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault("APP_SECRET", Fernet.generate_key().decode())
# Don't run the background scheduler thread during tests; scheduler logic is
# tested directly (trigger building / next-run computation).
os.environ["SCHEDULER_AUTOSTART"] = "false"

import threading  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    # Imported lazily so the env vars above are in effect first. Using the
    # context manager runs the lifespan (Alembic migrations + settings seed).
    from app.db.base import SessionLocal
    from app.main import app
    from app.models import Base

    with TestClient(app) as c:
        # Isolate tests: clear all rows (schema + alembic_version stay intact).
        with SessionLocal() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
            db.commit()
        yield c


@pytest.fixture()
def ftp_server(tmp_path):
    """A throwaway local FTP server (pyftpdlib) over a temp directory.

    Lets us exercise the FTP client / connection flow deterministically without
    a real NAS. Yields a config dict ready for FtpClient / the API.
    """
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer

    root = tmp_path / "ftproot"
    (root / "Photos").mkdir(parents=True)
    (root / "Documents").mkdir()  # left empty: a clean destination target
    (root / "Media" / "Movies").mkdir(parents=True)
    (root / "readme.txt").write_text("hello nas")  # 9 bytes
    (root / "Photos" / "pic1.jpg").write_text("x" * 100)
    (root / "Media" / "song.mp3").write_text("m" * 30)
    (root / "Media" / "Movies" / "m1.mp4").write_text("v" * 50)

    user, password = "nas", "secret"
    authorizer = DummyAuthorizer()
    # Full permissions: list, retr, store, delete, mkdir, rename, mdtm (perm 'T').
    authorizer.add_user(user, password, str(root), perm="elradfmwMT")
    # Read-only user (list + retrieve only) for write-failure tests.
    authorizer.add_user("ro", "ro", str(root), perm="elr")

    handler = FTPHandler
    handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), handler)
    port = server.address[1]
    thread = threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True)
    thread.start()
    try:
        yield {
            "host": "127.0.0.1",
            "port": port,
            "username": user,
            "password": password,
            "protocol": "ftp",
            "passive_mode": True,
            "timeout_seconds": 10,
            "root_path": "/",
            "root_dir": root,
        }
    finally:
        server.close_all()
        thread.join(timeout=5)
