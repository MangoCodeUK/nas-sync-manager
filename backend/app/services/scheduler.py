"""Job scheduling with APScheduler (FRD FR-009/010/011).

Schedule types: manual, interval (minutes), hourly, daily (HH:MM),
weekly (DOW HH:MM), monthly (DOM HH:MM), cron (expression). The job's timezone
comes from global settings. Overlapping runs are prevented two ways: APScheduler
``max_instances=1`` and the transfer engine's own running-guard - a scheduled run
that collides with an in-progress one is recorded as ``skipped`` (FR-011).
"""
from __future__ import annotations

import datetime as dt
import logging

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import JobRun, SyncJob, utcnow
from app.services import settings_service, transfer_engine

log = logging.getLogger("nas_sync.scheduler")

_scheduler: BackgroundScheduler | None = None
_DOW = {"mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun"}


def _tz(db: Session) -> pytz.BaseTzInfo:
    name = settings_service.get_settings_row(db).timezone
    try:
        return pytz.timezone(name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("Europe/London")


def _parse_hm(value: str) -> tuple[int, int]:
    hh, mm = value.strip().split(":")
    return int(hh), int(mm)


def trigger_for(job: SyncJob, tz: pytz.BaseTzInfo) -> BaseTrigger | None:
    """Build an APScheduler trigger for a job, or None if it isn't scheduled."""
    stype = job.schedule_type
    value = (job.schedule_value or "").strip()
    try:
        if stype == "manual":
            return None
        if stype == "interval":
            minutes = int(value)
            if minutes <= 0:
                return None
            return IntervalTrigger(minutes=minutes, timezone=tz)
        if stype == "hourly":
            return CronTrigger(minute=0, timezone=tz)
        if stype == "daily":
            hour, minute = _parse_hm(value)
            return CronTrigger(hour=hour, minute=minute, timezone=tz)
        if stype == "weekly":
            dow, hm = value.split(" ", 1)
            hour, minute = _parse_hm(hm)
            return CronTrigger(day_of_week=_DOW.get(dow.lower()[:3], dow), hour=hour, minute=minute, timezone=tz)
        if stype == "monthly":
            dom, hm = value.split(" ", 1)
            hour, minute = _parse_hm(hm)
            return CronTrigger(day=int(dom), hour=hour, minute=minute, timezone=tz)
        if stype == "cron":
            return CronTrigger.from_crontab(value, timezone=tz)
    except (ValueError, TypeError):
        log.warning("Invalid schedule for job %s: %s '%s'", job.id, stype, value)
        return None
    return None


def compute_next_run(job: SyncJob, tz: pytz.BaseTzInfo) -> dt.datetime | None:
    trigger = trigger_for(job, tz)
    if trigger is None:
        return None
    return trigger.get_next_fire_time(None, dt.datetime.now(tz))


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


def status() -> str:
    return "running" if is_running() else "stopped"


def start() -> None:
    global _scheduler
    if is_running():
        return
    with SessionLocal() as db:
        tz = _tz(db)
        _scheduler = BackgroundScheduler(timezone=tz)
        _scheduler.start()
        reschedule_all(db)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        finally:
            _scheduler = None


def sync_job(db: Session, job: SyncJob) -> None:
    """(Re)schedule a job and persist its next run time. No-op if not scheduled."""
    tz = _tz(db)
    next_run = compute_next_run(job, tz) if job.enabled else None
    job.next_run_at = next_run
    db.commit()

    if not is_running():
        return
    job_key = str(job.id)
    assert _scheduler is not None
    _scheduler.remove_job(job_key) if _scheduler.get_job(job_key) else None
    trigger = trigger_for(job, tz) if job.enabled else None
    if trigger is not None:
        _scheduler.add_job(
            _execute_scheduled,
            trigger=trigger,
            id=job_key,
            args=[job.id],
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )


def unschedule(job_id: int) -> None:
    if is_running() and _scheduler is not None and _scheduler.get_job(str(job_id)):
        _scheduler.remove_job(str(job_id))


def reschedule_all(db: Session) -> None:
    for job in db.scalars(select(SyncJob)):
        sync_job(db, job)


def _execute_scheduled(job_id: int) -> None:
    """Run a scheduled job (own session). Records a skipped run on overlap."""
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        if job is None or not job.enabled:
            return
        try:
            transfer_engine.run_sync(db, job, run_type="scheduled")
        except transfer_engine.AlreadyRunning:
            db.add(
                JobRun(
                    job_id=job.id,
                    run_type="scheduled",
                    status="skipped",
                    summary="Skipped: previous run still in progress",
                    completed_at=utcnow(),
                )
            )
            job.last_status = "skipped"
            db.commit()
        # Refresh next run time after firing.
        sync_job(db, job)
