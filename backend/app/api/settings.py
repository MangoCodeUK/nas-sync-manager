"""Settings endpoints (FRD FR-024)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.services import audit, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
def read_settings(db: Session = Depends(get_db)) -> SettingsRead:
    return SettingsRead.model_validate(settings_service.get_settings_row(db))


@router.put("", response_model=SettingsRead)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsRead:
    data = payload.model_dump(exclude_unset=True)
    row = settings_service.update_settings(db, data)
    audit.record(db, "settings.updated", detail=", ".join(sorted(data.keys())) or "(no changes)")
    return SettingsRead.model_validate(row)
