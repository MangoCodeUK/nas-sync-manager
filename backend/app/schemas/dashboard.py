"""Dashboard summary schema (FRD FR-018)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class ConnectionStatus(BaseModel):
    id: int
    name: str
    last_test_status: str | None


class RecentRun(BaseModel):
    id: int
    job_name: str | None
    run_type: str
    status: str
    started_at: dt.datetime


class ActivityEntry(BaseModel):
    action: str
    detail: str | None
    created_at: dt.datetime


class DashboardRead(BaseModel):
    connections_total: int
    connections: list[ConnectionStatus]
    jobs_total: int
    jobs_enabled: int
    jobs_running: int
    jobs_failed: int
    pending_deletions: int
    last_success_job: str | None
    last_success_at: dt.datetime | None
    next_run_job: str | None
    next_run_at: dt.datetime | None
    recent_runs: list[RecentRun]
    recent_activity: list[ActivityEntry]
