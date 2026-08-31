"""Schemas for the rsync environment / mount registry (see services/mounts.py)."""
from __future__ import annotations

from pydantic import BaseModel


class MountRead(BaseModel):
    host_path: str  # what TOS calls it, e.g. /Volume1/RsyncTest
    container_path: str  # where the app sees it, e.g. /nas/Volume1/RsyncTest
    read_only: bool


class RsyncEnvironment(BaseModel):
    """Everything the UI needs to say whether rsync jobs can run at all."""

    rsync_available: bool
    rsync_version: str | None = None
    rsync_protocol: int | None = None
    rsync_error: str | None = None
    mount_root: str
    mounts: list[MountRead]
