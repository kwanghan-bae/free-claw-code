import json
import sqlite3
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app

def _seed_fixtures(path):
    db = path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE spans (span_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
        CREATE TABLE evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, score_dim TEXT, score_value REAL, ts TEXT);
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO spans VALUES ('s1', ?, 'ok')", (now,))
    for kind in ("meta_suggestion", "meta_vote", "meta_applied", "meta_rolled_back"):
        conn.execute(
            "INSERT INTO events(span_id, kind, payload_json, ts) VALUES (?,?,?,?)",
            ("s1", kind, json.dumps({"level": "info"}), now),
        )
    for dim in ("quality", "latency"):
        conn.execute(
            "INSERT INTO evaluations(span_id, score_dim, score_value, ts) VALUES (?,?,?,?)",
            ("s1", dim, 0.8, now),
        )
    conn.commit()
    conn.close()
    sug = path / "suggestions.jsonl"
    targets = [f"target_{i}" for i in range(10)]
    with sug.open("w") as f:
        for t in targets:
            f.write(json.dumps({"target_id": t, "kind": "proposed", "note": "x", "ts": now, "status": "pending"}) + "\n")

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    _seed_fixtures(tmp_path)
    return TestClient(app)

@pytest.fixture
def client_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    return TestClient(app)

def test_meta_report_renders_24h_summary(client):
    resp = client.get("/meta/report")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "24h 메타 활동 요약" in body
    assert "제안" in body
    assert "롤백" in body

def test_meta_report_timeline_per_target(client):
    resp = client.get("/meta/report")
    body = resp.text
    assert body.count('class="target-timeline"') >= 10

def test_meta_report_handles_empty_store(client_empty):
    resp = client_empty.get("/meta/report")
    assert resp.status_code == 200
    assert "데이터 없음" in resp.text
