"""Pydantic schemas for the global settings (FRD FR-024)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.constants import ConflictStrategy, JobType, VerificationLevel


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timezone: str
    default_verification_level: int
    default_conflict_strategy: str
    default_transfer_mode: str
    max_concurrent_transfers: int
    max_bandwidth_kbps: int | None
    log_retention_days: int
    archive_path_template: str
    retry_count: int
    retry_delay_seconds: int
    max_auto_source_deletes: int
    max_auto_destination_deletes: int
    require_manual_approval_for_deletes: bool
    preserve_timestamps: bool
    updated_at: dt.datetime


class SettingsUpdate(BaseModel):
    """All fields optional: partial update (PUT merges)."""

    timezone: str | None = None
    default_verification_level: VerificationLevel | None = None
    default_conflict_strategy: ConflictStrategy | None = None
    default_transfer_mode: JobType | None = None
    max_concurrent_transfers: int | None = Field(default=None, ge=1, le=16)
    max_bandwidth_kbps: int | None = Field(default=None, ge=0)
    log_retention_days: int | None = Field(default=None, ge=1, le=3650)
    archive_path_template: str | None = None
    retry_count: int | None = Field(default=None, ge=0, le=20)
    retry_delay_seconds: int | None = Field(default=None, ge=0, le=3600)
    max_auto_source_deletes: int | None = Field(default=None, ge=0)
    max_auto_destination_deletes: int | None = Field(default=None, ge=0)
    require_manual_approval_for_deletes: bool | None = None
    preserve_timestamps: bool | None = None
