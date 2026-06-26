"""Audit trail of administrative actions (FRD FR-031)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(db: Session, action: str, detail: str | None = None) -> None:
    db.add(AuditLog(action=action, detail=detail))
    db.commit()
