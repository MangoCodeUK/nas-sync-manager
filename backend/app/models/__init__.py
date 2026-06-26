"""SQLAlchemy ORM models for the whole schema (FRD section 16).

Defined together so Alembic generates one coherent initial migration. The auth
``users`` table from the FRD is intentionally omitted (single-user, LAN-only).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class NasConnection(TimestampMixin, Base):
    __tablename__ = "nas_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    host: Mapped[str] = mapped_column(String(255))
    protocol: Mapped[str] = mapped_column(String(8), default="ftp")  # ftp | ftps
    port: Mapped[int] = mapped_column(Integer, default=21)
    username: Mapped[str] = mapped_column(String(255))
    encrypted_password: Mapped[str] = mapped_column(Text)
    root_path: Mapped[str] = mapped_column(String(1024), default="/")
    passive_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_test_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_type: Mapped[str] = mapped_column(String(16))  # copy | mirror | move

    source_connection_id: Mapped[int] = mapped_column(ForeignKey("nas_connections.id"))
    source_path: Mapped[str] = mapped_column(String(1024))
    destination_connection_id: Mapped[int] = mapped_column(ForeignKey("nas_connections.id"))
    destination_path: Mapped[str] = mapped_column(String(1024))

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    conflict_strategy: Mapped[str] = mapped_column(
        String(40), default="overwrite_if_newer_or_size_differs"
    )
    verification_level: Mapped[int] = mapped_column(Integer, default=2)
    delete_strategy: Mapped[str] = mapped_column(String(32), default="manual_approval")
    mirror_mode: Mapped[str] = mapped_column(String(8), default="safe")  # safe | strict
    archive_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    include_filters: Mapped[str | None] = mapped_column(Text, nullable=True)  # newline-separated
    exclude_filters: Mapped[str | None] = mapped_column(Text, nullable=True)

    schedule_type: Mapped[str] = mapped_column(String(16), default="manual")
    schedule_value: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    source_connection: Mapped[NasConnection] = relationship(foreign_keys=[source_connection_id])
    destination_connection: Mapped[NasConnection] = relationship(
        foreign_keys=[destination_connection_id]
    )


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("sync_jobs.id", ondelete="CASCADE"), index=True)
    run_type: Mapped[str] = mapped_column(String(16), default="manual")  # manual|scheduled|dry_run
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)

    files_scanned: Mapped[int] = mapped_column(Integer, default=0)
    files_copied: Mapped[int] = mapped_column(Integer, default=0)
    files_updated: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, default=0)
    files_deleted: Mapped[int] = mapped_column(Integer, default=0)
    bytes_transferred: Mapped[int] = mapped_column(BigInteger, default=0)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["JobRunItem"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class JobRunItem(Base):
    __tablename__ = "job_run_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_run_id: Mapped[int] = mapped_column(
        ForeignKey("job_runs.id", ondelete="CASCADE"), index=True
    )
    source_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    destination_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    action: Mapped[str] = mapped_column(String(16))  # copy|update|skip|delete|archive|mkdir
    status: Mapped[str] = mapped_column(String(16))  # ok|failed|planned|pending
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[JobRun] = relationship(back_populates="items")


class PendingDeletion(Base):
    __tablename__ = "pending_deletions"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("sync_jobs.id", ondelete="CASCADE"), index=True)
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_path: Mapped[str] = mapped_column(String(2048))
    destination_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    verification_status: Mapped[str] = mapped_column(String(16), default="pending")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSettings(Base):
    """Single-row table (id=1) holding global defaults (FRD FR-024)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/London")
    default_verification_level: Mapped[int] = mapped_column(Integer, default=2)
    default_conflict_strategy: Mapped[str] = mapped_column(
        String(40), default="overwrite_if_newer_or_size_differs"
    )
    default_transfer_mode: Mapped[str] = mapped_column(String(16), default="copy")
    max_concurrent_transfers: Mapped[int] = mapped_column(Integer, default=2)
    max_bandwidth_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    archive_path_template: Mapped[str] = mapped_column(
        String(255), default="/_NAS_SYNC_ARCHIVE/{job}/{datetime}/"
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=3)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=30)
    # Safety: never auto-delete by default; require manual approval for all deletes.
    max_auto_source_deletes: Mapped[int] = mapped_column(Integer, default=0)
    max_auto_destination_deletes: Mapped[int] = mapped_column(Integer, default=0)
    require_manual_approval_for_deletes: Mapped[bool] = mapped_column(Boolean, default=True)
    preserve_timestamps: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


__all__ = [
    "Base",
    "utcnow",
    "NasConnection",
    "SyncJob",
    "JobRun",
    "JobRunItem",
    "PendingDeletion",
    "AppSettings",
    "AuditLog",
]
