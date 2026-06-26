"""Folder browser endpoints (FRD FR-004/005, FR-020)."""
from __future__ import annotations

import posixpath

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.browse import BrowseEntry, BrowseResponse, FolderSize
from app.services import connection_service
from app.services.ftp_client import FtpError

router = APIRouter(prefix="/api/browse", tags=["browse"])


def _normalise(path: str | None, root: str) -> str:
    if not path:
        return root or "/"
    p = posixpath.normpath(path)
    if not p.startswith("/"):
        p = "/" + p
    return p


def _parent(path: str) -> str | None:
    if path in ("/", ""):
        return None
    return posixpath.dirname(path.rstrip("/")) or "/"


def _get_conn_or_404(db: Session, connection_id: int):
    conn = connection_service.get_connection(db, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@router.get("/{connection_id}", response_model=BrowseResponse)
def browse(connection_id: int, path: str | None = Query(default=None), db: Session = Depends(get_db)):
    conn = _get_conn_or_404(db, connection_id)
    target = _normalise(path, conn.root_path)
    client = connection_service.build_client(conn)
    try:
        entries = client.list_dir(target)
    except FtpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BrowseResponse(
        connection_id=connection_id,
        path=target,
        parent=_parent(target),
        entries=[
            BrowseEntry(
                name=e.name,
                type=e.type,
                path=posixpath.join(target, e.name),
                size=e.size,
                modify=e.modify,
            )
            for e in entries
        ],
    )


@router.get("/{connection_id}/size", response_model=FolderSize)
def folder_size(connection_id: int, path: str | None = Query(default=None), db: Session = Depends(get_db)):
    """Opt-in recursive size of a folder (can be slow over FTP)."""
    conn = _get_conn_or_404(db, connection_id)
    target = _normalise(path, conn.root_path)
    client = connection_service.build_client(conn)
    try:
        total, files, folders = client.walk_size(target)
    except FtpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return FolderSize(
        connection_id=connection_id,
        path=target,
        total_bytes=total,
        file_count=files,
        folder_count=folders,
    )
