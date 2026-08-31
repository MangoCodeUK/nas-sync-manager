def test_ftp_client_lists_and_tests(ftp_server):
    from app.services.ftp_client import FtpClient

    client = FtpClient(
        host=ftp_server["host"],
        port=ftp_server["port"],
        username=ftp_server["username"],
        password=ftp_server["password"],
        passive_mode=True,
        timeout_seconds=10,
    )

    entries = {e.name: e for e in client.list_dir("/")}
    assert set(entries) == {"Photos", "Documents", "Media", "readme.txt"}
    assert entries["Photos"].is_dir
    assert not entries["readme.txt"].is_dir

    result = client.test_connection()
    assert result.ok
    assert result.connectivity and result.authentication and result.can_list
    assert result.can_write is True
    assert result.can_delete is True


def test_test_connection_bad_password(ftp_server):
    from app.services.ftp_client import FtpClient

    client = FtpClient(
        host=ftp_server["host"],
        port=ftp_server["port"],
        username=ftp_server["username"],
        password="wrong",
        timeout_seconds=10,
    )
    result = client.test_connection()
    assert not result.ok
    assert result.authentication is False
    assert result.messages


def test_connection_crud_and_test_via_api(client, ftp_server):
    cfg = {k: ftp_server[k] for k in ("host", "port", "username", "password", "protocol", "passive_mode", "timeout_seconds", "root_path")}

    # Test before saving.
    pre = client.post("/api/connections/test", json={"name": "probe", **cfg})
    assert pre.status_code == 200
    assert pre.json()["ok"] is True
    assert pre.json()["can_delete"] is True

    # Create.
    created = client.post("/api/connections", json={"name": "Old NAS", **cfg})
    assert created.status_code == 201
    body = created.json()
    assert "password" not in body
    assert "encrypted_password" not in body
    conn_id = body["id"]

    # Test the saved connection (records status).
    test = client.post(f"/api/connections/{conn_id}/test")
    assert test.status_code == 200 and test.json()["ok"] is True

    fetched = client.get(f"/api/connections/{conn_id}").json()
    assert fetched["last_test_status"].startswith("OK")

    # List.
    assert any(c["name"] == "Old NAS" for c in client.get("/api/connections").json())

    # Update name.
    upd = client.put(f"/api/connections/{conn_id}", json={"name": "Old TerraMaster"})
    assert upd.status_code == 200 and upd.json()["name"] == "Old TerraMaster"

    # Delete.
    assert client.delete(f"/api/connections/{conn_id}").status_code == 204
    assert client.get(f"/api/connections/{conn_id}").status_code == 404


def test_create_requires_password(client, ftp_server):
    cfg = {k: ftp_server[k] for k in ("host", "port", "username", "protocol", "passive_mode", "timeout_seconds", "root_path")}
    resp = client.post("/api/connections", json={"name": "No password", **cfg})
    assert resp.status_code == 422


def test_rsync_is_reported_separately_from_ftp(client, ftp_server, monkeypatch):
    """A device can have a working FTP login and a broken rsync one.

    Collapsing both into a single verdict would hide exactly the case worth
    catching, so the rsync result is its own block - and it is produced for an
    unsaved form too, which is when a wrong module is cheapest to fix.
    """
    from app.services import rsync_client

    monkeypatch.setattr(
        rsync_client,
        "test_connection",
        lambda conn, password=None: rsync_client.RsyncTestResult(
            reachable=True,
            authenticated=True,
            module_found=False,
            modules=["SomethingElse"],
            messages=["Module 'Wanted' is not published by this device."],
        ),
    )

    payload = {
        **{k: v for k, v in ftp_server.items() if k != "root_dir"},
        "name": "probe",
        "fs_root": "/mnt/md0",
        "rsync_enabled": True,
        "rsync_mode": "daemon",
        "rsync_module": "Wanted",
        "rsync_username": "nassync",
        "rsync_password": "secret",
    }
    body = client.post("/api/connections/test", json=payload).json()

    assert body["ok"] is True  # FTP is fine...
    assert body["rsync"]["ok"] is False  # ...while rsync is not
    assert body["rsync"]["module_found"] is False
    assert "SomethingElse" in body["rsync"]["modules"]


def test_no_rsync_block_when_the_connection_does_not_use_rsync(client, ftp_server):
    payload = {
        **{k: v for k, v in ftp_server.items() if k != "root_dir"},
        "name": "ftp-only",
    }
    assert client.post("/api/connections/test", json=payload).json()["rsync"] is None
