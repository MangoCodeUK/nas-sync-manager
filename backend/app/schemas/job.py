"""Pydantic schemas for sync jobs and dry-run plans (FRD section 8, FR-012/013/022)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.constants import (
    ConflictStrategy,
    DeleteStrategy,
    JobType,
    MirrorMode,
    ScheduleType,
    VerificationLevel,
)


class JobBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    job_type: JobType
    source_connection_id: int
    source_path: str = Field(min_length=1)
    destination_connection_id: int
    destination_path: str = Field(min_length=1)
    enabled: bool = True
    conflict_strategy: ConflictStrategy = "overwrite_if_newer_or_size_differs"
    verification_level: VerificationLevel = 2
    delete_strategy: DeleteStrategy = "manual_approval"
    mirror_mode: MirrorMode = "safe"
    archive_path: str | None = None
    include_filters: str | None = None
    exclude_filters: str | None = None
    schedule_type: ScheduleType = "manual"
    schedule_value: str | None = None


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    job_type: JobType | None = None
    source_connection_id: int | None = None
    source_path: str | None = Field(default=None, min_length=1)
    destination_connection_id: int | None = None
    destination_path: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    conflict_strategy: ConflictStrategy | None = None
    verification_level: VerificationLevel | None = None
    delete_strategy: DeleteStrategy | None = None
    mirror_mode: MirrorMode | None = None
    archive_path: str | None = None
    include_filters: str | None = None
    exclude_filters: str | None = None
    schedule_type: ScheduleType | None = None
    schedule_value: str | None = None


class JobRead(JobBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_connection_name: str | None = None
    destination_connection_name: str | None = None
    last_run_at: dt.datetime | None = None
    next_run_at: dt.datetime | None = None
    last_status: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


# --- Dry-run / preview ------------------------------------------------------
class PlanItemRead(BaseModel):
    action: str
    source_path: str | None
    destination_path: str | None
    size: int
    reason: str


class PlanRead(BaseModel):
    items: list[PlanItemRead]
    warnings: list[str]
    copy_count: int
    update_count: int
    skip_count: int
    mkdir_count: int
    delete_count: int
    archive_count: int
    transfer_bytes: int
    truncated: bool = False


class JobPreviewRequest(BaseModel):
    """A possibly-unsaved job config to preview (FR-013)."""

    job_type: JobType
    source_connection_id: int
    source_path: str = Field(min_length=1)
    destination_connection_id: int
    destination_path: str = Field(min_length=1)
    conflict_strategy: ConflictStrategy = "overwrite_if_newer_or_size_differs"
    delete_strategy: DeleteStrategy = "manual_approval"
    mirror_mode: MirrorMode = "safe"
    include_filters: str | None = None
    exclude_filters: str | None = None
