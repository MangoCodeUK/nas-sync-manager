"""Transfer engine tests: real file moves against a local pyftpdlib server."""
from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.models import SyncJob
from app.services import transfer_engine
from app.services.transfer_engine import TMP_SUFFIX


def _conn(client, ftp_server, name, root, *, user=None, pw=None):
    body = {
        "name": name,
        "host": ftp_server["host"],
        "port": ftp_server["port"],
        "username": user or ftp_server["username"],
        "password": pw or ftp_server["password"],
        "protocol": "ftp",
        "passive_mode": True,
        "timeout_seconds": 10,
        "root_path": root,
    }
    return client.post("/api/connections", json=body).json()["id"]


def _job(client, src, dst, **over):
    body = {
        "name": "Copy Media",
        "job_type": "copy",
        "source_connection_id": src,
        "source_path": "/Media",
        "destination_connection_id": dst,
        "destination_path": "/Documents",
    }
    body.update(over)
    return client.post("/api/jobs", json=body).json()["id"]


def _run(job_id, run_type="manual"):
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        run = transfer_engine.run_sync(db, job, run_type)
        return {
            "status": run.status,
            "copied": run.files_copied,
            "updated": run.files_updated,
            "skipped": run.files_skipped,
            "failed": run.files_failed,
            "bytes": run.bytes_transferred,
        }


def _tmp_files(root_dir):
    return [p for p in root_dir.rglob("*") if p.name.endswith(TMP_SUFFIX)]


def test_copy_job_lands_files_and_cleans_temp(client, ftp_server):
    root = ftp_server["root_dir"]
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)

    result = _run(job)
    assert result["status"] == "success"
    assert result["copied"] == 2
    assert result["failed"] == 0
    assert result["bytes"] == 80

    # Files actually arrived with correct content.
    assert (root / "Documents" / "song.mp3").read_text() == "m" * 30
    assert (root / "Documents" / "Movies" / "m1.mp4").read_text() == "v" * 50
    # No leftover temp files.
    assert _tmp_files(root) == []


def test_rerun_skips_unchanged(client, ftp_server):
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)

    _run(job)
    second = _run(job)
    assert second["copied"] == 0
    assert second["skipped"] == 2
    assert second["status"] == "success"


def test_verification_level_4_download_and_hash(client, ftp_server):
    root = ftp_server["root_dir"]
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst, verification_level=4)

    result = _run(job)
    assert result["status"] == "success"
    assert result["copied"] == 2
    assert (root / "Documents" / "song.mp3").read_text() == "m" * 30


def test_write_failure_is_logged_not_fatal(client, ftp_server):
    root = ftp_server["root_dir"]
    # Make retries instant so the failure path is fast.
    client.put("/api/settings", json={"retry_count": 0, "retry_delay_seconds": 0})

    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST-RO", "/Documents", user="ro", pw="ro")
    job = _job(client, src, dst)

    result = _run(job)
    assert result["failed"] == 2
    assert result["copied"] == 0
    assert result["status"] == "failed"
    # Nothing was written (and no temp turds left behind).
    assert not (root / "Documents" / "song.mp3").exists()
    assert _tmp_files(root) == []


def test_run_items_recorded(client, ftp_server):
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)
    _run(job)

    runs = client.get(f"/api/jobs/{job}/runs").json()
    manual = [r for r in runs if r["run_type"] == "manual"][0]
    items = client.get(f"/api/jobs/runs/{manual['id']}/items").json()
    actions = {i["action"] for i in items}
    assert "copy" in actions and "mkdir" in actions


@pytest.mark.parametrize("run_type", ["manual"])
def test_overlap_guard_clears_after_run(client, ftp_server, run_type):
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)
    _run(job, run_type)
    assert transfer_engine.is_running(job) is False
