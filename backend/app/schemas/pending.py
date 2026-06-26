"""Schemas for pending source deletions from move jobs (FRD section 16.5, FR-014)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class PendingDeletionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    job_run_id: int | None
    source_path: str
    destination_path: str | None
    size_bytes: int
    verification_status: str
    approved: bool
    approved_at: dt.datetime | None
    deleted: bool
    deleted_at: dt.datetime | None
    created_at: dt.datetime
    job_name: str | None = None
