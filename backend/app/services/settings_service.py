"""Read/update the single-row global settings."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AppSettings


def get_settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_settings(db: Session, data: dict) -> AppSettings:
    row = get_settings_row(db)
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
