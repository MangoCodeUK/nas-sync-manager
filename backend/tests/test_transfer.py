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


def test_run_records_progress_totals(client, ftp_server):
    """The plan totals + live-progress bookkeeping land on the run so the UI can
    show "X of Y"."""
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)
    with SessionLocal() as db:
        run = transfer_engine.run_sync(db, db.get(SyncJob, job))
        assert run.files_total == 2  # two files planned to transfer
        assert run.bytes_total == 80  # 30 + 50
        assert run.bytes_transferred == 80
        assert run.current_item is None  # cleared when the run ends


def test_request_cancel_only_when_running():
    job_id = 987654
    assert transfer_engine.request_cancel(job_id) is False  # not running
    transfer_engine._mark(job_id)
    try:
        assert transfer_engine.request_cancel(job_id) is True
        assert transfer_engine.is_cancelled(job_id) is True
    finally:
        transfer_engine._unmark(job_id)
        transfer_engine._clear_cancel(job_id)
    assert transfer_engine.is_cancelled(job_id) is False


def test_cancel_stops_run(client, ftp_server):
    """A cancel requested before the first file boundary stops the run cleanly."""
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)
    transfer_engine._cancel.add(job)  # pre-arm; run stops at the first loop check
    try:
        result = _run(job)
    finally:
        transfer_engine._cancel.discard(job)
    assert result["status"] == "cancelled"
    assert result["copied"] == 0


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


def test_session_reconnects_when_connection_dies():
    """A dropped connection (the cause of the 'broken pipe after one file' bug)
    must be detected and rebuilt, not reused for every remaining file."""

    class FakeFtp:
        def __init__(self):
            self.alive = True

        def voidcmd(self, cmd):
            if not self.alive:
                raise OSError("connection dropped")
            return "200 ok"

        def quit(self):
            pass

        def close(self):
            pass

    class FakeClient:
        def connect(self):
            return FakeFtp()

    session = transfer_engine._Session(FakeClient(), FakeClient())
    session.open()
    first_src, first_dst = session.sftp, session.dftp

    # Server drops both connections after the previous transfer.
    first_src.alive = False
    first_dst.alive = False

    session.ensure_alive()  # NOOP fails -> reconnect

    assert session.sftp is not first_src
    assert session.dftp is not first_dst
    assert session.sftp.alive and session.dftp.alive


@pytest.mark.parametrize("run_type", ["manual"])
def test_overlap_guard_clears_after_run(client, ftp_server, run_type):
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _job(client, src, dst)
    _run(job, run_type)
    assert transfer_engine.is_running(job) is False
