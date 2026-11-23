"""Unit tests: single endpoints in isolation. Gate 1 of the pipeline."""


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_version_reports_env(client):
    body = client.get("/version").get_json()
    assert body == {"version": "9.9.9", "color": "green"}


def test_add_note_requires_text(client):
    r = client.post("/notes", json={"text": "   "})
    assert r.status_code == 400


def test_add_note_rejects_bad_json(client):
    r = client.post("/notes", data="not json", content_type="text/plain")
    assert r.status_code == 400


def test_token_required_when_configured(secured_client):
    r = secured_client.post("/notes", json={"text": "x"})
    assert r.status_code == 401


def test_fail_rate_simulates_bad_release(client, monkeypatch):
    monkeypatch.setenv("FAIL_RATE", "1")
    assert client.get("/notes").status_code == 500


def test_token_accepted(secured_client):
    r = secured_client.post("/notes", json={"text": "x"}, headers={"X-API-Token": "s3cret"})
    assert r.status_code == 201
