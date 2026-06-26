import pytest


@pytest.fixture()
def two_connections(client, ftp_server):
    """Source = /Media (has files+subdir), Destination = /Documents (empty)."""
    base = {k: ftp_server[k] for k in ("host", "port", "username", "password", "protocol", "passive_mode", "timeout_seconds")}
    src = client.post("/api/connections", json={"name": "SRC", "root_path": "/Media", **base}).json()
    dst = client.post("/api/connections", json={"name": "DST", "root_path": "/Documents", **base}).json()
    return src["id"], dst["id"]


def _job_body(src_id, dst_id, **over):
    body = {
        "name": "Copy Media",
        "job_type": "copy",
        "source_connection_id": src_id,
        "source_path": "/Media",
        "destination_connection_id": dst_id,
        "destination_path": "/Documents",
    }
    body.update(over)
    return body


def test_create_and_get_job(client, two_connections):
    src, dst = two_connections
    resp = client.post("/api/jobs", json=_job_body(src, dst))
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_connection_name"] == "SRC"
    assert body["destination_connection_name"] == "DST"
    assert body["delete_strategy"] == "manual_approval"
    assert client.get(f"/api/jobs/{body['id']}").status_code == 200


def test_create_job_rejects_bad_connection(client, two_connections):
    src, _ = two_connections
    resp = client.post("/api/jobs", json=_job_body(src, 9999))
    assert resp.status_code == 400


def test_dry_run_plans_copy(client, two_connections):
    src, dst = two_connections
    job = client.post("/api/jobs", json=_job_body(src, dst)).json()
    resp = client.post(f"/api/jobs/{job['id']}/dry-run")
    assert resp.status_code == 200
    data = resp.json()
    plan = data["plan"]
    # Media has song.mp3 + Movies/m1.mp4, and folder Movies.
    assert plan["copy_count"] == 2
    assert plan["mkdir_count"] == 1
    assert plan["transfer_bytes"] == 80
    assert data["run"]["run_type"] == "dry_run"
    assert data["run"]["status"] == "success"
    # Dry-run is recorded as a run.
    runs = client.get(f"/api/jobs/{job['id']}/runs").json()
    assert len(runs) == 1 and runs[0]["run_type"] == "dry_run"


def test_dry_run_makes_no_changes(client, two_connections):
    src, dst = two_connections
    job = client.post("/api/jobs", json=_job_body(src, dst)).json()
    client.post(f"/api/jobs/{job['id']}/dry-run")
    # Destination still empty after a dry-run.
    listing = client.get(f"/api/browse/{dst}", params={"path": "/Documents"}).json()
    assert listing["entries"] == []


def test_preview_with_exclude_filter(client, two_connections):
    src, dst = two_connections
    body = {
        "job_type": "copy",
        "source_connection_id": src,
        "source_path": "/Media",
        "destination_connection_id": dst,
        "destination_path": "/Documents",
        "exclude_filters": "*.mp3",
    }
    plan = client.post("/api/jobs/preview", json=body).json()
    # song.mp3 filtered out -> only Movies/m1.mp4 copied.
    assert plan["copy_count"] == 1
    assert any(i["reason"] == "filtered" for i in plan["items"])


def test_enable_disable(client, two_connections):
    src, dst = two_connections
    job = client.post("/api/jobs", json=_job_body(src, dst)).json()
    assert client.post(f"/api/jobs/{job['id']}/disable").json()["enabled"] is False
    assert client.post(f"/api/jobs/{job['id']}/enable").json()["enabled"] is True
