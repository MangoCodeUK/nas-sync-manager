"""FastAPI application entry point.

On startup it applies Alembic migrations (creating the schema on a fresh DB) and
seeds the single settings row. ``GET /health`` reports live DB status and is what
the Docker healthcheck and the autoheal sidecar depend on.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import backup as backup_api
from app.api import browse as browse_api
from app.api import connections as connections_api
from app.api import dashboard as dashboard_api
from app.api import jobs as jobs_api
from app.api import pending as pending_api
from app.api import runs as runs_api
from app.api import settings as settings_api
from app.db.base import SessionLocal
from app.db.migrate import upgrade_to_head
from app.services import scheduler
from app.services.settings_service import get_settings_row
from app.settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Schema is owned by Alembic; upgrading to head creates a fresh DB too.
    upgrade_to_head()
    with SessionLocal() as db:
        get_settings_row(db)  # ensure the settings row exists
    if settings.scheduler_autostart:
        scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(settings_api.router)
app.include_router(connections_api.router)
app.include_router(browse_api.router)
app.include_router(jobs_api.router)
app.include_router(pending_api.router)
app.include_router(runs_api.router)
app.include_router(dashboard_api.router)
app.include_router(backup_api.router)


def _db_status() -> str:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # pragma: no cover - defensive
        return "error"


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe; always 200 so the container is "up" once serving."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "database": _db_status(),
        "scheduler": scheduler.status(),
    }


@app.get("/api/ping", tags=["health"])
def ping() -> dict[str, str]:
    return {"message": "pong"}
