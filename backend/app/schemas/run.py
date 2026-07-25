"""Schemas for job runs and run items (FR-023 logs)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class JobRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    run_type: str
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None
    duration_seconds: float | None
    files_scanned: int
    files_copied: int
    files_updated: int
    files_skipped: int
    files_failed: int
    files_deleted: int
    bytes_transferred: int
    files_total: int = 0
    bytes_total: int = 0
    current_item: str | None = None
    summary: str | None
    error_message: str | None
    job_name: str | None = None


class JobRunItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_run_id: int
    source_path: str | None
    destination_path: str | None
    action: str
    status: str
    size_bytes: int
    message: str | None
    created_at: dt.datetime
