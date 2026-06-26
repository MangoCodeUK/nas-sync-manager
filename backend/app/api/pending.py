"""Pending deletion endpoints (FRD FR-014, section 17)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import PendingDeletion, SyncJob
from app.schemas.pending import PendingDeletionRead
from app.services import audit, pending_service
from app.services.pending_service import DeletionError

router = APIRouter(prefix="/api/pending-deletions", tags=["pending-deletions"])


def _to_read(db: Session, pending: PendingDeletion) -> PendingDeletionRead:
    read = PendingDeletionRead.model_validate(pending)
    job = db.get(SyncJob, pending.job_id)
    read.job_name = job.name if job else None
    return read


def _get_or_404(db: Session, pending_id: int) -> PendingDeletion:
    pending = pending_service.get(db, pending_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Pending deletion not found")
    return pending


@router.get("", response_model=list[PendingDeletionRead])
def list_pending(include_resolved: bool = False, db: Session = Depends(get_db)):
    return [_to_read(db, p) for p in pending_service.list_pending(db, include_resolved)]


@router.post("/{pending_id}/approve", response_model=PendingDeletionRead)
def approve(pending_id: int, db: Session = Depends(get_db)):
    pending = _get_or_404(db, pending_id)
    try:
        pending = pending_service.approve(db, pending)
    except DeletionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit.record(db, "deletion.approved", detail=pending.source_path)
    return _to_read(db, pending)


@router.post("/{pending_id}/reject", status_code=204)
def reject(pending_id: int, db: Session = Depends(get_db)):
    pending = _get_or_404(db, pending_id)
    path = pending.source_path
    pending_service.reject(db, pending)
    audit.record(db, "deletion.rejected", detail=path)
