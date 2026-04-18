import json
import sqlite3
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    db = tmp_path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE spans (span_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
    """)
    now = datetime.now(timezone.utc).isoformat()
    for aid, msg in (("a1", "first"), ("a2", "second")):
        conn.execute(
            "INSERT INTO events(span_id, kind, payload_json, ts) VALUES (NULL, 'meta_alert', ?, ?)",
            (json.dumps({"level": "critical", "alert_id": aid, "message": msg}), now),
        )
    conn.commit()
    conn.close()
    return TestClient(app)


def test_alerts_lists_critical(client):
    resp = client.get("/meta/alerts")
    assert resp.status_code == 200
    data = resp.json()
    ids = {a["id"] for a in data}
    assert ids == {"a1", "a2"}


def test_ack_removes_alert(client):
    resp = client.post("/meta/ack/a1")
    assert resp.status_code == 200
    resp = client.get("/meta/alerts")
    ids = {a["id"] for a in resp.json()}
    assert ids == {"a2"}


def test_alerts_ignores_non_critical(tmp_path, monkeypatch):
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    db = tmp_path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE spans (span_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO events(span_id, kind, payload_json, ts) VALUES (NULL, 'meta_alert', ?, ?)",
        (json.dumps({"level": "warn", "alert_id": "w1", "message": "x"}), now),
    )
    conn.commit()
    conn.close()
    c2 = TestClient(app)
    resp = c2.get("/meta/alerts")
    assert resp.json() == []
