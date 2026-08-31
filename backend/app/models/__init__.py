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

    # --- rsync transport (optional; every FTP field above is untouched) -----
    # A connection describes a NAS, not a protocol: the same device may be
    # reachable over FTP, over rsync, or both. Jobs pick a transport per job.
    #
    # fs_root is the device's real filesystem root (/Volume1 on the new NAS,
    # /mnt/md0 on the old one) as opposed to the FTP-relative root_path above -
    # they are different namespaces for the same files. Whether a path is
    # reachable *locally* is not stored: services/mounts.py answers that from
    # what is actually bind-mounted, so it cannot go stale.
    fs_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    rsync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rsync_mode: Mapped[str] = mapped_column(String(8), default="daemon")  # daemon | ssh
    rsync_host: Mapped[str | None] = mapped_column(String(255), nullable=True)  # falls back to host
    rsync_port: Mapped[int] = mapped_column(Integer, default=873)
    rsync_module: Mapped[str | None] = mapped_column(String(255), nullable=True)  # daemon mode
    rsync_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rsync_encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    rsync_ssh_port: Mapped[int] = mapped_column(Integer, default=22)


class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The two independent axes: WHAT the job does, and HOW bytes move. job_type
    # predates rsync and already means the right thing, so transport is simply
    # added alongside it. Defaulting to "ftp" keeps every existing job identical.
    job_type: Mapped[str] = mapped_column(String(16))  # copy | mirror | move
    transport: Mapped[str] = mapped_column(String(8), default="ftp")  # ftp | rsync

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

    # rsync-only tuning. Compression defaults OFF: on a gigabit LAN full of
    # already-compressed media it burns CPU these devices do not have, for
    # nothing (FRD performance note).
    rsync_compress: Mapped[bool] = mapped_column(Boolean, default=False)
    rsync_bandwidth_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    # Live progress: totals known up-front from the plan, plus the file in flight,
    # so a polling UI can show "X of Y" and what's currently transferring.
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    bytes_total: Mapped[int] = mapped_column(BigInteger, default=0)
    current_item: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which transport ran, and rsync's raw exit code when one was involved -
    # the single most useful thing when diagnosing a failure after the fact.
    transport: Mapped[str | None] = mapped_column(String(8), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What the deletion guards actually checked, recorded for destructive runs.
    safety_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    # Proportional guard, which the absolute limits above cannot express: a
    # job that would remove most of a large destination is almost always a
    # mistake (a mistyped path, or a source that came back empty), however
    # small the file count happens to be.
    max_delete_percent: Mapped[int] = mapped_column(Integer, default=10)
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
