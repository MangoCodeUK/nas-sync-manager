import pytest


@pytest.fixture()
def saved_connection(client, ftp_server):
    cfg = {k: ftp_server[k] for k in ("host", "port", "username", "password", "protocol", "passive_mode", "timeout_seconds", "root_path")}
    resp = client.post("/api/connections", json={"name": "Browse NAS", **cfg})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_browse_root(client, saved_connection):
    resp = client.get(f"/api/browse/{saved_connection}", params={"path": "/"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "/"
    assert body["parent"] is None
    names = {e["name"]: e for e in body["entries"]}
    assert set(names) == {"Photos", "Documents", "Media", "readme.txt"}
    assert names["Photos"]["type"] == "dir"
    assert names["Photos"]["path"] == "/Photos"
    assert names["readme.txt"]["type"] == "file"


def test_browse_subfolder(client, saved_connection):
    resp = client.get(f"/api/browse/{saved_connection}", params={"path": "/Photos"})
    body = resp.json()
    assert body["parent"] == "/"
    assert {e["name"] for e in body["entries"]} == {"pic1.jpg"}


def test_folder_size(client, saved_connection):
    resp = client.get(f"/api/browse/{saved_connection}/size", params={"path": "/Media"})
    assert resp.status_code == 200
    body = resp.json()
    # Media/song.mp3 (30) + Media/Movies/m1.mp4 (50); one subfolder (Movies)
    assert body["file_count"] == 2
    assert body["folder_count"] == 1
    assert body["total_bytes"] == 80


def test_browse_unknown_connection(client):
    assert client.get("/api/browse/9999").status_code == 404
