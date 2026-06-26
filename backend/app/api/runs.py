"""Global run log endpoints with filters (FRD FR-023)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import JobRun, JobRunItem, SyncJob
from app.schemas.run import JobRunItemRead, JobRunRead

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _with_job_name(db: Session, run: JobRun) -> JobRunRead:
    read = JobRunRead.model_validate(run)
    job = db.get(SyncJob, run.job_id)
    read.job_name = job.name if job else None
    return read


@router.get("", response_model=list[JobRunRead])
def list_runs(
    job_id: int | None = None,
    status: str | None = None,
    run_type: str | None = None,
    error_only: bool = False,
    start: dt.date | None = Query(default=None),
    end: dt.date | None = Query(default=None),
    limit: int = 200,
    db: Session = Depends(get_db),
):
    query = select(JobRun).order_by(JobRun.started_at.desc())
    if job_id is not None:
        query = query.where(JobRun.job_id == job_id)
    if status:
        query = query.where(JobRun.status == status)
    if run_type:
        query = query.where(JobRun.run_type == run_type)
    if error_only:
        query = query.where(JobRun.status.in_(["failed", "partial"]))
    if start:
        query = query.where(JobRun.started_at >= dt.datetime.combine(start, dt.time.min))
    if end:
        query = query.where(JobRun.started_at <= dt.datetime.combine(end, dt.time.max))
    query = query.limit(limit)
    return [_with_job_name(db, r) for r in db.scalars(query)]


@router.get("/{run_id}", response_model=JobRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(JobRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _with_job_name(db, run)


@router.get("/{run_id}/items", response_model=list[JobRunItemRead])
def run_items(run_id: int, db: Session = Depends(get_db)):
    items = db.scalars(
        select(JobRunItem).where(JobRunItem.job_run_id == run_id).order_by(JobRunItem.id)
    )
    return list(items)
