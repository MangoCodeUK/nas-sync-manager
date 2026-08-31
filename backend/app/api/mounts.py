"""rsync environment endpoint: is rsync usable, and which shares are exposed?

Read-only diagnostics. The Jobs UI uses this to list the shares an rsync job may
target, and to explain what to add to docker-compose when one is missing, rather
than letting the job fail later with a raw rsync error.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas.mounts import MountRead, RsyncEnvironment
from app.services import mounts, rsync_client

router = APIRouter(prefix="/api/rsync", tags=["rsync"])


@router.get("/environment", response_model=RsyncEnvironment)
def environment() -> RsyncEnvironment:
    capability = rsync_client.probe()
    return RsyncEnvironment(
        rsync_available=capability.available,
        rsync_version=capability.version,
        rsync_protocol=capability.protocol,
        rsync_error=capability.error,
        mount_root=mounts.mount_root(),
        mounts=[
            MountRead(
                host_path=m.host_path,
                container_path=m.container_path,
                read_only=m.read_only,
            )
            for m in mounts.list_mounts()
        ],
    )
