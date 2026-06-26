"""Backup / restore endpoints (FRD FR-029/030, section 17)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.services import audit, backup_service, scheduler

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.post("/export")
def export_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    doc = backup_service.export_all(db)
    audit.record(db, "backup.export", detail=f"{len(doc['connections'])} connections, {len(doc['jobs'])} jobs")
    return doc


@router.post("/import")
def import_config(doc: dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    result = backup_service.import_all(db, doc)
    scheduler.reschedule_all(db)
    audit.record(db, "backup.import", detail=f"{result['connections']} connections, {result['jobs']} jobs")
    return result
