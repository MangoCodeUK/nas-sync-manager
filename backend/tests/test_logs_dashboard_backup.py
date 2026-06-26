from app.db.base import SessionLocal
from app.models import SyncJob
from app.services import transfer_engine


def _setup(client, ftp_server):
    base = {k: ftp_server[k] for k in ("host", "port", "username", "password", "protocol", "passive_mode", "timeout_seconds")}
    src = client.post("/api/connections", json={"name": "SRC", "root_path": "/Media", **base}).json()["id"]
    dst = client.post("/api/connections", json={"name": "DST", "root_path": "/Documents", **base}).json()["id"]
    job = client.post("/api/jobs", json={
        "name": "Copy Media", "job_type": "copy",
        "source_connection_id": src, "source_path": "/Media",
        "destination_connection_id": dst, "destination_path": "/Documents",
    }).json()["id"]
    with SessionLocal() as db:
        transfer_engine.run_sync(db, db.get(SyncJob, job), "manual")
    return src, dst, job


def test_runs_log_and_filters(client, ftp_server):
    _setup(client, ftp_server)
    runs = client.get("/api/runs").json()
    assert len(runs) >= 1
    assert runs[0]["job_name"] == "Copy Media"

    assert all(r["status"] == "success" for r in client.get("/api/runs", params={"status": "success"}).json())
    assert client.get("/api/runs", params={"status": "failed"}).json() == []
    assert client.get("/api/runs", params={"error_only": True}).json() == []
    assert all(r["run_type"] == "manual" for r in client.get("/api/runs", params={"run_type": "manual"}).json())


def test_run_items_endpoint(client, ftp_server):
    _setup(client, ftp_server)
    run_id = client.get("/api/runs").json()[0]["id"]
    items = client.get(f"/api/runs/{run_id}/items").json()
    assert any(i["action"] == "copy" for i in items)


def test_dashboard_summary(client, ftp_server):
    _setup(client, ftp_server)
    d = client.get("/api/dashboard").json()
    assert d["connections_total"] == 2
    assert d["jobs_total"] == 1
    assert d["jobs_enabled"] == 1
    assert d["last_success_job"] == "Copy Media"
    assert len(d["recent_runs"]) >= 1
    assert any(a["action"] == "job.created" for a in d["recent_activity"])


def test_backup_export_import_roundtrip(client, ftp_server):
    _setup(client, ftp_server)
    doc = client.post("/api/backup/export").json()
    assert len(doc["connections"]) == 2
    assert len(doc["jobs"]) == 1
    assert "encrypted_password" in doc["connections"][0]

    # Wipe everything.
    client.post("/api/backup/import", json={"connections": [], "jobs": [], "settings": None})
    assert client.get("/api/connections").json() == []
    assert client.get("/api/jobs").json() == []

    # Restore from the backup.
    result = client.post("/api/backup/import", json=doc).json()
    assert result["connections"] == 2 and result["jobs"] == 1
    assert len(client.get("/api/connections").json()) == 2
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    # Job still references a valid connection (names resolve).
    assert jobs[0]["source_connection_name"] == "SRC"
