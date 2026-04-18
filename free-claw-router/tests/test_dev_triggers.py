from fastapi.testclient import TestClient
from router.server.openai_compat import app


def test_dev_triggers_gated_when_flag_off(monkeypatch):
    monkeypatch.delenv("FCR_DEV_TRIGGERS", raising=False)
    client = TestClient(app)
    # All 4 endpoints should 404 without the flag
    assert client.post("/meta/analyze-now").status_code == 404
    assert client.post("/meta/evolve-now").status_code == 404
    assert client.post("/telemetry/readmodel/refresh").status_code == 404
    assert client.get("/healthz/pipeline").status_code == 404


def test_pipeline_healthz_reports_last_24h(monkeypatch, tmp_path):
    import sqlite3, json
    from datetime import datetime, timezone
    monkeypatch.setenv("FCR_DEV_TRIGGERS", "1")
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    db = tmp_path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
    """)
    now = datetime.now(timezone.utc).isoformat()
    for kind in ("memory_mined", "skill_analyzed", "trajectory_compressed", "insight_generated", "meta_suggestion"):
        conn.execute(
            "INSERT INTO events(span_id, kind, payload_json, ts) VALUES (NULL, ?, ?, ?)",
            (kind, json.dumps({}), now),
        )
    conn.commit()
    conn.close()
    client = TestClient(app)
    resp = client.get("/healthz/pipeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    counts = body["last_24h"]
    assert counts["memory_mined"] >= 1
    assert counts["meta_suggestion"] >= 1


def test_readmodel_refresh_endpoint_gated(monkeypatch):
    monkeypatch.setenv("FCR_DEV_TRIGGERS", "1")
    client = TestClient(app)
    resp = client.post("/telemetry/readmodel/refresh")
    # We don't require a specific success code here because the actual
    # readmodel rebuild may fail if no store is present — we just want
    # to confirm the gate is open and the handler attempts to run.
    assert resp.status_code != 404
