"""Sync job endpoints (FRD FR-021/022, FR-012/013)."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import JobRun, SyncJob
from app.schemas.job import (
    JobCreate,
    JobPreviewRequest,
    JobRead,
    JobUpdate,
    PlanItemRead,
    PlanRead,
)
from app.schemas.run import JobRunItemRead, JobRunRead
from app.services import (
    audit,
    job_service,
    jobs_runner,
    providers,
    scheduler,
    transfer_engine,
)
from app.services.rsync_client import RsyncError
from app.services.planner import Plan

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_MAX_PLAN_ITEMS = 2000


def _get_or_404(db: Session, job_id: int) -> SyncJob:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _plan_to_read(plan: Plan) -> PlanRead:
    items = plan.items[:_MAX_PLAN_ITEMS]
    return PlanRead(
        items=[
            PlanItemRead(
                action=i.action,
                source_path=i.source_path,
                destination_path=i.destination_path,
                size=i.size,
                reason=i.reason,
            )
            for i in items
        ],
        warnings=plan.warnings,
        copy_count=plan.copy_count,
        update_count=plan.update_count,
        skip_count=plan.skip_count,
        mkdir_count=plan.mkdir_count,
        delete_count=plan.delete_count,
        archive_count=plan.archive_count,
        transfer_bytes=plan.transfer_bytes,
        inplace_count=plan.inplace_count,
        inplace_bytes=plan.inplace_bytes,
        truncated=len(plan.items) > _MAX_PLAN_ITEMS,
        command=plan.command,
    )


@router.get("", response_model=list[JobRead])
def list_jobs(db: Session = Depends(get_db)):
    return [job_service.to_read(j) for j in job_service.list_jobs(db)]


@router.post("", response_model=JobRead, status_code=201)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    job = job_service.create_job(db, payload.model_dump())
    scheduler.sync_job(db, job)
    audit.record(db, "job.created", detail=job.name)
    return job_service.to_read(job)


@router.post("/preview", response_model=PlanRead)
def preview(payload: JobPreviewRequest, db: Session = Depends(get_db)):
    # An unsaved config is duck-typed into the shape a provider reads, so
    # Preview works identically before and after the job is saved.
    config = SimpleNamespace(**payload.model_dump())
    try:
        plan = providers.plan_for_job(db, config)
    except RsyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _plan_to_read(plan)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return job_service.to_read(_get_or_404(db, job_id))


@router.put("/{job_id}", response_model=JobRead)
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = _get_or_404(db, job_id)
    job = job_service.update_job(db, job, payload.model_dump(exclude_unset=True))
    scheduler.sync_job(db, job)
    audit.record(db, "job.updated", detail=job.name)
    return job_service.to_read(job)


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = _get_or_404(db, job_id)
    name = job.name
    scheduler.unschedule(job.id)
    job_service.delete_job(db, job)
    audit.record(db, "job.deleted", detail=name)


@router.post("/{job_id}/enable", response_model=JobRead)
def enable_job(job_id: int, db: Session = Depends(get_db)):
    job = _get_or_404(db, job_id)
    job = job_service.update_job(db, job, {"enabled": True})
    scheduler.sync_job(db, job)
    audit.record(db, "job.enabled", detail=job.name)
    return job_service.to_read(job)


@router.post("/{job_id}/disable", response_model=JobRead)
def disable_job(job_id: int, db: Session = Depends(get_db)):
    job = _get_or_404(db, job_id)
    job = job_service.update_job(db, job, {"enabled": False})
    scheduler.sync_job(db, job)
    audit.record(db, "job.disabled", detail=job.name)
    return job_service.to_read(job)


@router.post("/{job_id}/dry-run")
def dry_run(job_id: int, db: Session = Depends(get_db)):
    job = _get_or_404(db, job_id)
    run, plan = jobs_runner.dry_run(db, job)
    audit.record(db, "job.dry_run", detail=job.name)
    return {"run": JobRunRead.model_validate(run), "plan": _plan_to_read(plan)}


@router.post("/{job_id}/run", response_model=JobRunRead, status_code=202)
def run_now(job_id: int, db: Session = Depends(get_db)):
    job = _get_or_404(db, job_id)
    if transfer_engine.is_running(job.id):
        raise HTTPException(status_code=409, detail="Job is already running")
    run = transfer_engine.begin(db, job, run_type="manual")
    transfer_engine.execute_async(run.id, job.id)
    audit.record(db, "job.run", detail=job.name)
    return JobRunRead.model_validate(run)


@router.post("/{job_id}/cancel", status_code=202)
def cancel_run(job_id: int, db: Session = Depends(get_db)):
    """Ask a running job to stop (cooperative - stops at the next file, or mid-file
    for the one currently streaming)."""
    job = _get_or_404(db, job_id)
    if not transfer_engine.request_cancel(job.id):
        raise HTTPException(status_code=409, detail="Job is not running")
    audit.record(db, "job.cancel_requested", detail=job.name)
    return {"status": "cancelling", "job_id": job.id}


@router.get("/{job_id}/runs", response_model=list[JobRunRead])
def list_runs(job_id: int, limit: int = 50, db: Session = Depends(get_db)):
    _get_or_404(db, job_id)
    runs = db.scalars(
        select(JobRun).where(JobRun.job_id == job_id).order_by(JobRun.started_at.desc()).limit(limit)
    )
    return list(runs)


@router.get("/runs/{run_id}", response_model=JobRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(JobRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/items", response_model=list[JobRunItemRead])
def get_run_items(run_id: int, db: Session = Depends(get_db)):
    from app.models import JobRunItem

    items = db.scalars(
        select(JobRunItem).where(JobRunItem.job_run_id == run_id).order_by(JobRunItem.id)
    )
    return list(items)
