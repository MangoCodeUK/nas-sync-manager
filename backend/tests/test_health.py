def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "version" in body
    assert "scheduler" in body


def test_ping(client):
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.json()["message"] == "pong"
