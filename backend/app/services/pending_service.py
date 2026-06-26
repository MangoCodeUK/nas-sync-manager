"""List / approve / reject pending source deletions (the move safety gate)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NasConnection, PendingDeletion, SyncJob, utcnow
from app.services import connection_service


class DeletionError(Exception):
    """Raised when an approved deletion cannot be carried out."""


def list_pending(db: Session, include_resolved: bool = False) -> list[PendingDeletion]:
    query = select(PendingDeletion).order_by(PendingDeletion.created_at.desc())
    if not include_resolved:
        query = query.where(PendingDeletion.deleted.is_(False))
    return list(db.scalars(query))


def get(db: Session, pending_id: int) -> PendingDeletion | None:
    return db.get(PendingDeletion, pending_id)


def approve(db: Session, pending: PendingDeletion) -> PendingDeletion:
    """Carry out the deletion on the source NAS, then mark it done."""
    if pending.deleted:
        return pending
    job = db.get(SyncJob, pending.job_id)
    conn = db.get(NasConnection, job.source_connection_id) if job else None
    if conn is None:
        raise DeletionError("Source connection for this deletion no longer exists")

    client = connection_service.build_client(conn)
    try:
        with client.connection() as ftp:
            ftp.delete(pending.source_path)
    except Exception as exc:  # noqa: BLE001 - surface as a clean API error
        raise DeletionError(f"Could not delete '{pending.source_path}': {exc}") from exc

    pending.approved = True
    pending.approved_at = utcnow()
    pending.deleted = True
    pending.deleted_at = utcnow()
    db.commit()
    db.refresh(pending)
    return pending


def reject(db: Session, pending: PendingDeletion) -> None:
    """Cancel a pending deletion (source is kept)."""
    db.delete(pending)
    db.commit()
