"""CRUD + read helpers for sync jobs."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NasConnection, SyncJob
from app.schemas.job import JobRead


def _require_connection(db: Session, conn_id: int) -> NasConnection:
    conn = db.get(NasConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=400, detail=f"Connection {conn_id} does not exist")
    return conn


def list_jobs(db: Session) -> list[SyncJob]:
    return list(db.scalars(select(SyncJob).order_by(SyncJob.name)))


def get_job(db: Session, job_id: int) -> SyncJob | None:
    return db.get(SyncJob, job_id)


def create_job(db: Session, data: dict) -> SyncJob:
    _require_connection(db, data["source_connection_id"])
    _require_connection(db, data["destination_connection_id"])
    job = SyncJob(**data)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: SyncJob, data: dict) -> SyncJob:
    if "source_connection_id" in data:
        _require_connection(db, data["source_connection_id"])
    if "destination_connection_id" in data:
        _require_connection(db, data["destination_connection_id"])
    for key, value in data.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job: SyncJob) -> None:
    db.delete(job)
    db.commit()


def to_read(job: SyncJob) -> JobRead:
    read = JobRead.model_validate(job)
    read.source_connection_name = job.source_connection.name if job.source_connection else None
    read.destination_connection_name = (
        job.destination_connection.name if job.destination_connection else None
    )
    return read
