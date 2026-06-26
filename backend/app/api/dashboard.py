"""Dashboard summary endpoint (FRD FR-018)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import AuditLog, JobRun, NasConnection, PendingDeletion, SyncJob
from app.schemas.dashboard import (
    ActivityEntry,
    ConnectionStatus,
    DashboardRead,
    RecentRun,
)
from app.services import transfer_engine

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardRead)
def dashboard(db: Session = Depends(get_db)):
    connections = list(db.scalars(select(NasConnection).order_by(NasConnection.name)))
    jobs = list(db.scalars(select(SyncJob)))

    jobs_running = sum(1 for j in jobs if transfer_engine.is_running(j.id))
    jobs_failed = sum(1 for j in jobs if j.last_status in ("failed", "partial"))
    pending = db.scalar(
        select(func.count()).select_from(PendingDeletion).where(PendingDeletion.deleted.is_(False))
    )

    last_success = db.scalars(
        select(JobRun)
        .where(JobRun.status == "success", JobRun.run_type != "dry_run")
        .order_by(JobRun.completed_at.desc())
        .limit(1)
    ).first()
    last_success_job = db.get(SyncJob, last_success.job_id) if last_success else None

    # Soonest next run among enabled, scheduled jobs.
    next_job = db.scalars(
        select(SyncJob)
        .where(SyncJob.enabled.is_(True), SyncJob.next_run_at.is_not(None))
        .order_by(SyncJob.next_run_at.asc())
        .limit(1)
    ).first()

    recent = db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(10))
    job_names = {j.id: j.name for j in jobs}
    recent_runs = [
        RecentRun(
            id=r.id,
            job_name=job_names.get(r.job_id),
            run_type=r.run_type,
            status=r.status,
            started_at=r.started_at,
        )
        for r in recent
    ]

    activity = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12))

    return DashboardRead(
        connections_total=len(connections),
        connections=[
            ConnectionStatus(id=c.id, name=c.name, last_test_status=c.last_test_status)
            for c in connections
        ],
        jobs_total=len(jobs),
        jobs_enabled=sum(1 for j in jobs if j.enabled),
        jobs_running=jobs_running,
        jobs_failed=jobs_failed,
        pending_deletions=pending or 0,
        last_success_job=last_success_job.name if last_success_job else None,
        last_success_at=last_success.completed_at if last_success else None,
        next_run_job=next_job.name if next_job else None,
        next_run_at=next_job.next_run_at if next_job else None,
        recent_runs=recent_runs,
        recent_activity=[
            ActivityEntry(action=a.action, detail=a.detail, created_at=a.created_at)
            for a in activity
        ],
    )
