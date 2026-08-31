"""NAS connection endpoints (FRD FR-001/002, FR-019)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionTestRequest,
    ConnectionTestResponse,
    ConnectionUpdate,
)
from app.services import audit, connection_service
from app.services.ftp_client import ConnectionTestResult, FtpError

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _to_read(conn) -> ConnectionRead:
    """Serialise a connection, reporting only WHETHER an rsync secret exists."""
    read = ConnectionRead.model_validate(conn)
    read.rsync_password_set = bool(conn.rsync_encrypted_password)
    return read


def _get_or_404(db: Session, conn_id: int):
    conn = connection_service.get_connection(db, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _test_to_response(result: ConnectionTestResult) -> ConnectionTestResponse:
    return ConnectionTestResponse(
        ok=result.ok,
        connectivity=result.connectivity,
        authentication=result.authentication,
        can_list=result.can_list,
        can_write=result.can_write,
        can_delete=result.can_delete,
        summary=result.summary(),
        messages=result.messages,
    )


@router.get("", response_model=list[ConnectionRead])
def list_connections(db: Session = Depends(get_db)):
    return [_to_read(c) for c in connection_service.list_connections(db)]


@router.post("", response_model=ConnectionRead, status_code=201)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db)):
    conn = connection_service.create_connection(db, payload.model_dump())
    audit.record(db, "connection.created", detail=conn.name)
    return _to_read(conn)


@router.post("/test", response_model=ConnectionTestResponse)
def test_unsaved(payload: ConnectionTestRequest):
    """Test a connection config before saving it."""
    client = connection_service.client_from_config(payload.model_dump())
    try:
        return _test_to_response(client.test_connection())
    except FtpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{conn_id}", response_model=ConnectionRead)
def get_connection(conn_id: int, db: Session = Depends(get_db)):
    return _to_read(_get_or_404(db, conn_id))


@router.put("/{conn_id}", response_model=ConnectionRead)
def update_connection(conn_id: int, payload: ConnectionUpdate, db: Session = Depends(get_db)):
    conn = _get_or_404(db, conn_id)
    conn = connection_service.update_connection(db, conn, payload.model_dump(exclude_unset=True))
    audit.record(db, "connection.updated", detail=conn.name)
    return _to_read(conn)


@router.delete("/{conn_id}", status_code=204)
def delete_connection(conn_id: int, db: Session = Depends(get_db)):
    conn = _get_or_404(db, conn_id)
    name = conn.name
    connection_service.delete_connection(db, conn)
    audit.record(db, "connection.deleted", detail=name)


@router.post("/{conn_id}/test", response_model=ConnectionTestResponse)
def test_connection(conn_id: int, db: Session = Depends(get_db)):
    conn = _get_or_404(db, conn_id)
    result = connection_service.test_and_record(db, conn)
    return _test_to_response(result)
