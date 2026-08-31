"""Move job safety: copy -> verify -> pending deletion -> approval -> delete."""
from __future__ import annotations

from app.db.base import SessionLocal
from app.models import SyncJob
from app.services import transfer_engine


def _conn(client, ftp_server, name, root):
    body = {k: ftp_server[k] for k in ("host", "port", "username", "password", "protocol", "passive_mode", "timeout_seconds")}
    return client.post("/api/connections", json={"name": name, "root_path": root, **body}).json()["id"]


def _move_job(client, src, dst, **over):
    body = {
        "name": "Move Media",
        "job_type": "move",
        "source_connection_id": src,
        "source_path": "/Media",
        "destination_connection_id": dst,
        "destination_path": "/Documents",
    }
    body.update(over)
    return client.post("/api/jobs", json=body).json()["id"]


def _run(job_id):
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        run = transfer_engine.run_sync(db, job, "manual")
        return {"status": run.status, "copied": run.files_copied, "deleted": run.files_deleted}


def test_move_manual_approval_queues_then_deletes(client, ftp_server):
    root = ftp_server["root_dir"]
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _move_job(client, src, dst)  # default delete_strategy = manual_approval

    result = _run(job)
    assert result["copied"] == 2
    assert result["deleted"] == 0  # nothing deleted automatically

    # Files copied to destination, source still present.
    assert (root / "Documents" / "song.mp3").read_text() == "m" * 30
    assert (root / "Media" / "song.mp3").exists()

    pending = client.get("/api/pending-deletions").json()
    assert len(pending) == 2
    assert all(p["verification_status"] == "verified" for p in pending)
    assert pending[0]["job_name"] == "Move Media"

    # Approve both -> source files actually deleted.
    for p in pending:
        assert client.post(f"/api/pending-deletions/{p['id']}/approve").status_code == 200
    assert not (root / "Media" / "song.mp3").exists()
    assert not (root / "Media" / "Movies" / "m1.mp4").exists()
    # Queue cleared.
    assert client.get("/api/pending-deletions").json() == []


def test_move_reject_keeps_source(client, ftp_server):
    root = ftp_server["root_dir"]
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _move_job(client, src, dst)
    _run(job)

    pending = client.get("/api/pending-deletions").json()
    for p in pending:
        assert client.post(f"/api/pending-deletions/{p['id']}/reject").status_code == 204

    # Source kept; queue empty.
    assert (root / "Media" / "song.mp3").exists()
    assert client.get("/api/pending-deletions").json() == []


def test_move_auto_delete_blocked_by_default_safety(client, ftp_server):
    root = ftp_server["root_dir"]
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _move_job(client, src, dst, delete_strategy="auto_delete_after_verification")

    result = _run(job)
    # Default settings require manual approval -> auto delete falls back to pending.
    assert result["deleted"] == 0
    assert (root / "Media" / "song.mp3").exists()
    assert len(client.get("/api/pending-deletions").json()) == 2


def test_move_auto_delete_when_allowed(client, ftp_server):
    root = ftp_server["root_dir"]
    client.put("/api/settings", json={
        "require_manual_approval_for_deletes": False,
        "max_auto_source_deletes": 10,
    })
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _move_job(client, src, dst, delete_strategy="auto_delete_after_verification")

    result = _run(job)
    assert result["deleted"] == 2
    assert not (root / "Media" / "song.mp3").exists()
    assert client.get("/api/pending-deletions").json() == []


def test_move_archive_strategy(client, ftp_server):
    root = ftp_server["root_dir"]
    src = _conn(client, ftp_server, "SRC", "/Media")
    dst = _conn(client, ftp_server, "DST", "/Documents")
    job = _move_job(
        client, src, dst,
        delete_strategy="archive",
        archive_path="/_ARCHIVE/{job}/{datetime}/",
    )

    _run(job)
    # Original gone from source; an archived copy exists somewhere under _ARCHIVE.
    assert not (root / "Media" / "song.mp3").exists()
    archived = list((root / "_ARCHIVE").rglob("song.mp3"))
    assert len(archived) == 1
    assert archived[0].read_text() == "m" * 30


# --- rsync move must never queue a file it did not transfer -----------------
def test_move_never_queues_an_excluded_source_file(monkeypatch):
    """Found live: a scheduled rsync move queued five #recycle files for deletion.

    The job excluded #recycle/, so those files were never transferred and are not
    verified at the destination - yet they were offered for deletion from the
    source, which for excluded data is the only copy in existence. Only files the
    job actually transfers may ever be queued.
    """
    from types import SimpleNamespace

    from app.services import providers, rsync_client

    source_listing = [
        ("Test1.txt", 11),
        ("TestNEW.txt", 0),
        ("#recycle/NewFile.txt", 5),
        ("#recycle/New A/test2.csv", 7),
        ("#recycle/.data", 3),
    ]

    queued: list[str] = []

    class _DB:
        def add(self, row):
            queued.append(row.source_path)

        def commit(self):
            pass

    verified = SimpleNamespace(returncode=0, stdout="", stderr="", argv=[])
    monkeypatch.setattr(rsync_client, "run", lambda *a, **k: verified)
    monkeypatch.setattr(rsync_client, "build_argv", lambda **k: ["rsync"])
    monkeypatch.setattr(rsync_client, "list_files", lambda *a, **k: source_listing)

    job = SimpleNamespace(
        id=1,
        job_type="move",
        mirror_mode="safe",
        conflict_strategy="overwrite_if_newer_or_size_differs",
        include_filters=None,
        exclude_filters="#recycle/",
        rsync_compress=False,
        rsync_bandwidth_kbps=None,
        source_path="/mnt/md0/RsyncSourceTest",
        destination_path="/Volume1/RsyncTest",
    )
    run = SimpleNamespace(id=9, status="success", error_message=None, summary="")
    endpoint = rsync_client.Endpoint(spec="x", is_local=True)

    providers.RsyncProvider()._queue_source_deletions(_DB(), run, job, endpoint, endpoint, None)

    assert queued == [
        "/mnt/md0/RsyncSourceTest/Test1.txt",
        "/mnt/md0/RsyncSourceTest/TestNEW.txt",
    ]
    assert not any("#recycle" in p for p in queued)
