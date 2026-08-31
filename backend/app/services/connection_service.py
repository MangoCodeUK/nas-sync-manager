"""CRUD + testing for NAS connection profiles."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NasConnection, utcnow
from app.services import crypto
from app.services.ftp_client import ConnectionTestResult, FtpClient


def list_connections(db: Session) -> list[NasConnection]:
    return list(db.scalars(select(NasConnection).order_by(NasConnection.name)))


def get_connection(db: Session, conn_id: int) -> NasConnection | None:
    return db.get(NasConnection, conn_id)


def create_connection(db: Session, data: dict) -> NasConnection:
    password = data.pop("password")
    # The rsync secret is separate from the FTP one: the same device often has
    # different accounts for each service (here, "Admin" for FTP and "nassync"
    # for rsync). Both are Fernet-encrypted with the same key.
    rsync_password = data.pop("rsync_password", None)
    conn = NasConnection(**data, encrypted_password=crypto.encrypt(password))
    if rsync_password:
        conn.rsync_encrypted_password = crypto.encrypt(rsync_password)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def update_connection(db: Session, conn: NasConnection, data: dict) -> NasConnection:
    password = data.pop("password", None)
    rsync_password = data.pop("rsync_password", None)
    if password:
        conn.encrypted_password = crypto.encrypt(password)
    # Absent means "leave the stored secret alone", so an edit that does not
    # retype the password cannot silently wipe it.
    if rsync_password:
        conn.rsync_encrypted_password = crypto.encrypt(rsync_password)
    for key, value in data.items():
        setattr(conn, key, value)
    db.commit()
    db.refresh(conn)
    return conn


def delete_connection(db: Session, conn: NasConnection) -> None:
    db.delete(conn)
    db.commit()


def build_client(conn: NasConnection) -> FtpClient:
    """Construct an FtpClient from a stored profile (decrypts the password)."""
    return FtpClient(
        host=conn.host,
        port=conn.port,
        username=conn.username,
        password=crypto.decrypt(conn.encrypted_password),
        protocol=conn.protocol,
        passive_mode=conn.passive_mode,
        timeout_seconds=conn.timeout_seconds,
        root_path=conn.root_path,
    )


def client_from_config(data: dict) -> FtpClient:
    """Construct an FtpClient from a raw config dict (unsaved test)."""
    return FtpClient(
        host=data["host"],
        port=data.get("port", 21),
        username=data["username"],
        password=data["password"],
        protocol=data.get("protocol", "ftp"),
        passive_mode=data.get("passive_mode", True),
        timeout_seconds=data.get("timeout_seconds", 30),
        root_path=data.get("root_path", "/"),
    )


def test_and_record(db: Session, conn: NasConnection) -> ConnectionTestResult:
    result = build_client(conn).test_connection()
    conn.last_test_status = result.summary()
    conn.last_test_at = utcnow()
    db.commit()
    db.refresh(conn)
    return result
