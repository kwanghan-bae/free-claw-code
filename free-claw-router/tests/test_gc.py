import json
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from router.server.gc import run_gc, GcConfig


@pytest.fixture
def seeded_env(tmp_path):
    db = tmp_path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE spans (span_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
        CREATE TABLE evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, score_dim TEXT, score_value REAL, ts TEXT);
    """)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO spans VALUES ('old', ?, 'ok')", (old_ts,))
    conn.execute("INSERT INTO spans VALUES ('new', ?, 'ok')", (new_ts,))
    conn.commit()
    conn.close()

    sug = tmp_path / "suggestions.jsonl"
    recs = [
        {"id": "s-old", "target_id": "x", "status": "applied", "ts": old_ts},
        {"id": "s-new", "target_id": "x", "status": "pending", "ts": new_ts},
        {"id": "s-rej-old", "target_id": "y", "status": "rejected", "ts": old_ts},
    ]
    sug.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return tmp_path


def test_gc_span_age_drops_old(seeded_env):
    cfg = GcConfig(span_days=30, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    assert stats["spans_deleted"] == 1


def test_gc_suggestions_applied_drops_old(seeded_env):
    cfg = GcConfig(sug_applied_days=30, sug_rejected_days=7, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    # s-old (applied, 60 days) + s-rej-old (rejected, 60 days) both drop
    assert stats["suggestions_deleted"] == 2


def test_gc_dry_run_reports_counts_without_deleting(seeded_env):
    cfg = GcConfig(dry_run=True)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    assert stats["spans_deleted"] == 0
    assert stats["spans_would_delete"] == 1
    # verify data still there
    conn = sqlite3.connect(str(seeded_env / "telemetry.db"))
    count = conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
    conn.close()
    assert count == 2


def test_gc_records_event_log(seeded_env):
    cfg = GcConfig(span_days=30, dry_run=False)
    run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    conn = sqlite3.connect(str(seeded_env / "telemetry.db"))
    rows = conn.execute("SELECT kind FROM events WHERE kind='gc_run'").fetchall()
    conn.close()
    assert len(rows) == 1


def test_gc_paused_returns_early(seeded_env):
    cfg = GcConfig(paused=True, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    assert stats.get("paused") is True
