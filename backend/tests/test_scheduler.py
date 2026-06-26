"""Scheduler logic: trigger building and next-run computation (no live threads)."""
from __future__ import annotations

import datetime as dt

import pytz

from app.models import SyncJob
from app.services import scheduler


def _job(schedule_type, schedule_value=None, enabled=True):
    return SyncJob(
        name="x",
        job_type="copy",
        source_connection_id=1,
        source_path="/a",
        destination_connection_id=2,
        destination_path="/b",
        enabled=enabled,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
    )


TZ = pytz.timezone("Europe/London")


def test_manual_has_no_trigger():
    assert scheduler.trigger_for(_job("manual"), TZ) is None


def test_interval_trigger_and_next_run():
    job = _job("interval", "30")
    trig = scheduler.trigger_for(job, TZ)
    assert trig is not None
    nxt = scheduler.compute_next_run(job, TZ)
    assert isinstance(nxt, dt.datetime)
    assert nxt > dt.datetime.now(TZ)


def test_daily_trigger_fires_at_time():
    job = _job("daily", "02:30")
    nxt = scheduler.compute_next_run(job, TZ)
    assert nxt.hour == 2 and nxt.minute == 30


def test_weekly_trigger():
    job = _job("weekly", "SUN 02:30")
    nxt = scheduler.compute_next_run(job, TZ)
    assert nxt.weekday() == 6  # Sunday
    assert nxt.hour == 2 and nxt.minute == 30


def test_monthly_trigger():
    job = _job("monthly", "1 03:00")
    nxt = scheduler.compute_next_run(job, TZ)
    assert nxt.day == 1 and nxt.hour == 3


def test_cron_trigger():
    job = _job("cron", "0 4 * * *")
    nxt = scheduler.compute_next_run(job, TZ)
    assert nxt.hour == 4 and nxt.minute == 0


def test_invalid_schedule_returns_none():
    assert scheduler.trigger_for(_job("interval", "not-a-number"), TZ) is None
    assert scheduler.trigger_for(_job("daily", "25:99"), TZ) is None


def test_create_job_populates_next_run_at(client, ftp_server):
    base = {k: ftp_server[k] for k in ("host", "port", "username", "password", "protocol", "passive_mode", "timeout_seconds")}
    src = client.post("/api/connections", json={"name": "S", "root_path": "/Media", **base}).json()["id"]
    dst = client.post("/api/connections", json={"name": "D", "root_path": "/Documents", **base}).json()["id"]
    body = {
        "name": "Nightly",
        "job_type": "copy",
        "source_connection_id": src,
        "source_path": "/Media",
        "destination_connection_id": dst,
        "destination_path": "/Documents",
        "schedule_type": "daily",
        "schedule_value": "02:30",
    }
    job = client.post("/api/jobs", json=body).json()
    assert job["next_run_at"] is not None

    # Disabling clears the next run time.
    disabled = client.post(f"/api/jobs/{job['id']}/disable").json()
    assert disabled["next_run_at"] is None
