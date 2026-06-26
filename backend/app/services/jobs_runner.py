"""Assemble transfer plans and run dry-runs (FR-012/013).

The actual file-moving transfer engine (Stage 5) reuses :func:`assemble_plan` so
a dry-run and a real run see the same set of actions.
"""
from __future__ import annotations

import posixpath
import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import JobRun, NasConnection, SyncJob, utcnow
from app.services import connection_service
from app.services.ftp_client import FtpClient, FtpEntry
from app.services.planner import Plan, build_plan


@dataclass
class PlanContext:
    """A plan plus everything needed to execute it."""

    plan: Plan
    source_client: FtpClient
    dest_client: FtpClient
    source_path: str
    dest_path: str
    source_files: dict[str, FtpEntry]
    dest_files: dict[str, FtpEntry]


def _norm(path: str) -> str:
    p = posixpath.normpath(path or "/")
    return p if p.startswith("/") else "/" + p


def _require_connection(db: Session, conn_id: int) -> NasConnection:
    conn = db.get(NasConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=400, detail=f"Connection {conn_id} does not exist")
    return conn


def prepare(
    db: Session,
    *,
    job_type: str,
    source_connection_id: int,
    source_path: str,
    destination_connection_id: int,
    destination_path: str,
    conflict_strategy: str,
    delete_strategy: str = "manual_approval",
    mirror_mode: str = "safe",
    include_filters: str | None = None,
    exclude_filters: str | None = None,
) -> PlanContext:
    """Build clients, walk both trees, and produce a plan (+ risk warnings)."""
    source_conn = _require_connection(db, source_connection_id)
    dest_conn = _require_connection(db, destination_connection_id)
    source_path = _norm(source_path)
    destination_path = _norm(destination_path)

    source_client = connection_service.build_client(source_conn)
    dest_client = connection_service.build_client(dest_conn)

    source_files, source_dirs = source_client.walk_tree(source_path)
    dest_files, dest_dirs = dest_client.walk_tree(destination_path)

    plan = build_plan(
        job_type=job_type,
        conflict_strategy=conflict_strategy,
        mirror_mode=mirror_mode,
        include_filters=include_filters,
        exclude_filters=exclude_filters,
        source_files=source_files,
        source_dirs=source_dirs,
        dest_files=dest_files,
        dest_dirs=dest_dirs,
        dest_root=destination_path,
        source_root=source_path,
    )

    # Preview risk warnings (FR-013).
    if source_connection_id == destination_connection_id and source_path == destination_path:
        plan.warnings.insert(0, "Source and destination are the same location.")
    if not source_files and not source_dirs:
        plan.warnings.append("Source folder is empty - nothing to transfer.")
    if not dest_files and not dest_dirs:
        plan.warnings.append("Destination folder is empty or does not exist yet.")
    if job_type == "move" and delete_strategy == "auto_delete_after_verification":
        plan.warnings.append("Move job is set to auto-delete the source after verification.")

    return PlanContext(
        plan=plan,
        source_client=source_client,
        dest_client=dest_client,
        source_path=source_path,
        dest_path=destination_path,
        source_files=source_files,
        dest_files=dest_files,
    )


def assemble_plan(db: Session, **kwargs) -> Plan:
    return prepare(db, **kwargs).plan


def prepare_for_job(db: Session, job: SyncJob) -> PlanContext:
    return prepare(
        db,
        job_type=job.job_type,
        source_connection_id=job.source_connection_id,
        source_path=job.source_path,
        destination_connection_id=job.destination_connection_id,
        destination_path=job.destination_path,
        conflict_strategy=job.conflict_strategy,
        delete_strategy=job.delete_strategy,
        mirror_mode=job.mirror_mode,
        include_filters=job.include_filters,
        exclude_filters=job.exclude_filters,
    )


def plan_for_job(db: Session, job: SyncJob) -> Plan:
    return prepare_for_job(db, job).plan


def dry_run(db: Session, job: SyncJob) -> tuple[JobRun, Plan]:
    run = JobRun(job_id=job.id, run_type="dry_run", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    started = time.monotonic()
    try:
        plan = plan_for_job(db, job)
        considered = plan.copy_count + plan.update_count + plan.skip_count
        run.files_scanned = considered
        run.files_copied = plan.copy_count
        run.files_updated = plan.update_count
        run.files_skipped = plan.skip_count
        run.files_deleted = plan.delete_count
        run.bytes_transferred = plan.transfer_bytes
        run.status = "success"
        run.summary = (
            f"Dry-run: {plan.copy_count} new, {plan.update_count} updated, "
            f"{plan.skip_count} skipped, {plan.mkdir_count} folders"
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        run.status = "failed"
        run.error_message = str(exc)
        plan = Plan()
    finally:
        run.completed_at = utcnow()
        run.duration_seconds = round(time.monotonic() - started, 3)
        db.commit()
        db.refresh(run)

    return run, plan
