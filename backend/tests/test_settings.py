def test_settings_defaults(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    # Safety defaults per FRD FR-014 / Q8.
    assert body["timezone"] == "Europe/London"
    assert body["default_verification_level"] == 2
    assert body["max_auto_source_deletes"] == 0
    assert body["max_auto_destination_deletes"] == 0
    assert body["require_manual_approval_for_deletes"] is True
    assert body["preserve_timestamps"] is True


def test_settings_partial_update_persists(client):
    resp = client.put("/api/settings", json={"timezone": "America/New_York", "retry_count": 5})
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "America/New_York"
    assert resp.json()["retry_count"] == 5
    # Untouched field keeps its default.
    assert resp.json()["default_verification_level"] == 2

    # Re-read confirms persistence.
    again = client.get("/api/settings").json()
    assert again["timezone"] == "America/New_York"
    assert again["retry_count"] == 5


def test_settings_validation_rejects_bad_level(client):
    resp = client.put("/api/settings", json={"default_verification_level": 9})
    assert resp.status_code == 422


def test_crypto_round_trip():
    from app.services import crypto

    token = crypto.encrypt("hunter2")
    assert token != "hunter2"
    assert crypto.decrypt(token) == "hunter2"
