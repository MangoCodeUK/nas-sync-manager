"""Configuration backup / restore (FRD FR-029/030).

Exports settings, connections (with encrypted passwords) and jobs as a JSON
document. Restore replaces those tables and re-applies the settings. The Fernet
key lives on the data volume, so a backup restored onto the same instance stays
decryptable.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import JobRun, JobRunItem, NasConnection, PendingDeletion, SyncJob, utcnow
from app.services import settings_service

_CONNECTION_FIELDS = [
    "id", "name", "host", "protocol", "port", "username", "encrypted_password",
    "root_path", "passive_mode", "timeout_seconds", "description",
]
_JOB_FIELDS = [
    "id", "name", "description", "job_type", "source_connection_id", "source_path",
    "destination_connection_id", "destination_path", "enabled", "conflict_strategy",
    "verification_level", "delete_strategy", "mirror_mode", "archive_path",
    "include_filters", "exclude_filters", "schedule_type", "schedule_value",
]
_SETTINGS_FIELDS = [
    "timezone", "default_verification_level", "default_conflict_strategy",
    "default_transfer_mode", "max_concurrent_transfers", "max_bandwidth_kbps",
    "log_retention_days", "archive_path_template", "retry_count", "retry_delay_seconds",
    "max_auto_source_deletes", "max_auto_destination_deletes",
    "require_manual_approval_for_deletes", "preserve_timestamps",
]


def _row_to_dict(row, fields: list[str]) -> dict:
    return {f: getattr(row, f) for f in fields}


def export_all(db: Session) -> dict:
    settings_row = settings_service.get_settings_row(db)
    connections = db.query(NasConnection).order_by(NasConnection.id).all()
    jobs = db.query(SyncJob).order_by(SyncJob.id).all()
    return {
        "version": 1,
        "exported_at": utcnow().isoformat(),
        "settings": _row_to_dict(settings_row, _SETTINGS_FIELDS),
        "connections": [_row_to_dict(c, _CONNECTION_FIELDS) for c in connections],
        "jobs": [_row_to_dict(j, _JOB_FIELDS) for j in jobs],
    }


def _filtered(data: dict, fields: list[str]) -> dict:
    return {k: v for k, v in data.items() if k in fields}


def import_all(db: Session, doc: dict) -> dict:
    # Wipe child-to-parent so there are no dangling references.
    for table in (
        PendingDeletion.__table__,
        JobRunItem.__table__,
        JobRun.__table__,
        SyncJob.__table__,
        NasConnection.__table__,
    ):
        db.execute(table.delete())

    for c in doc.get("connections", []):
        db.add(NasConnection(**_filtered(c, _CONNECTION_FIELDS)))
    for j in doc.get("jobs", []):
        db.add(SyncJob(**_filtered(j, _JOB_FIELDS)))
    db.commit()

    if doc.get("settings"):
        settings_service.update_settings(db, _filtered(doc["settings"], _SETTINGS_FIELDS))

    return {
        "connections": len(doc.get("connections", [])),
        "jobs": len(doc.get("jobs", [])),
        "settings_updated": bool(doc.get("settings")),
    }
