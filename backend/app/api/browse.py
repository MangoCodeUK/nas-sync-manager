"""Folder browser endpoints (FRD FR-004/005, FR-020)."""
from __future__ import annotations

import posixpath

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.constants import Transport
from app.schemas.browse import BrowseEntry, BrowseResponse, FolderSize
from app.services import browsing, connection_service, crypto, rsync_client
from app.services.ftp_client import FtpError
from app.services.rsync_client import RsyncError

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


def _rsync_password(conn) -> str | None:
    return crypto.decrypt(conn.rsync_encrypted_password) if conn.rsync_encrypted_password else None


@router.get("/{connection_id}", response_model=BrowseResponse)
def browse(
    connection_id: int,
    path: str | None = Query(default=None),
    transport: Transport = Query(default="ftp"),
    db: Session = Depends(get_db),
):
    """List a folder over the chosen transport.

    The transport decides the path vocabulary, not just the plumbing: FTP returns
    FTP-relative paths and rsync returns the device's real filesystem paths, so
    whatever is copied out of here is directly usable by a job of that transport.
    Defaults to FTP, leaving every existing caller unchanged.
    """
    conn = _get_conn_or_404(db, connection_id)

    if transport == "rsync":
        try:
            target, entries = browsing.browse(conn, path, _rsync_password(conn))
        except RsyncError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return BrowseResponse(
            connection_id=connection_id,
            path=target,
            parent=_parent(target) if target != browsing.fs_root(conn) else None,
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
def folder_size(
    connection_id: int,
    path: str | None = Query(default=None),
    transport: Transport = Query(default="ftp"),
    db: Session = Depends(get_db),
):
    """Recursive size of a folder.

    Opt-in because it is slow over FTP, which has to walk the tree one command at
    a time. Over rsync it is cheap: a bind-mounted folder is walked locally, and a
    remote one is listed with --list-only, which transfers no file data.
    """
    conn = _get_conn_or_404(db, connection_id)

    if transport == "rsync":
        target = _normalise(path, browsing.fs_root(conn))
        try:
            endpoint = rsync_client.build_endpoint(conn, target, write=False)
            listed = rsync_client.list_files(endpoint, _rsync_password(conn))
        except RsyncError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if listed is None:
            raise HTTPException(status_code=502, detail=f"Could not read '{target}'.")
        folders = {f.rsplit("/", 1)[0] for f, _ in listed if "/" in f}
        return FolderSize(
            connection_id=connection_id,
            path=target,
            total_bytes=sum(size for _, size in listed),
            file_count=len(listed),
            folder_count=len(folders),
        )

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
