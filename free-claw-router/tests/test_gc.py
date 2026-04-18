import json
import sqlite3
import time
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

    # Canonical production format: JSON array of MetaSuggestion records
    # (see router/meta/meta_suggestions.py). ``timestamp`` is Unix seconds.
    now_epoch = time.time()
    old_epoch = now_epoch - 60 * 86400  # 60 days ago
    sug = tmp_path / "meta_suggestions.json"
    records = [
        {
            "id": "s-old-1",
            "trace_id": "t1",
            "target_file": "x.py",
            "edit_type": "prompt",
            "direction": "old edit",
            "rationale": "too old",
            "confidence": 0.6,
            "proposed_diff": "",
            "timestamp": old_epoch,
        },
        {
            "id": "s-new",
            "trace_id": "t2",
            "target_file": "x.py",
            "edit_type": "prompt",
            "direction": "fresh",
            "rationale": "fresh rationale",
            "confidence": 0.6,
            "proposed_diff": "",
            "timestamp": now_epoch,
        },
        {
            "id": "s-old-2",
            "trace_id": "t3",
            "target_file": "y.py",
            "edit_type": "prompt",
            "direction": "older still",
            "rationale": "also too old",
            "confidence": 0.6,
            "proposed_diff": "",
            "timestamp": old_epoch,
        },
    ]
    sug.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return tmp_path


def test_gc_span_age_drops_old(seeded_env):
    cfg = GcConfig(span_days=30, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "meta_suggestions.json", cfg)
    assert stats["spans_deleted"] == 1


def test_gc_suggestions_age_drops_old(seeded_env):
    cfg = GcConfig(sug_applied_days=30, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "meta_suggestions.json", cfg)
    # Both 60-day-old records drop (MetaSuggestion has no status — age only).
    assert stats["suggestions_deleted"] == 2
    # File should be rewritten as a JSON array with only the fresh record.
    remaining = json.loads((seeded_env / "meta_suggestions.json").read_text())
    assert len(remaining) == 1
    assert remaining[0]["id"] == "s-new"


def test_gc_dry_run_reports_counts_without_deleting(seeded_env):
    cfg = GcConfig(dry_run=True)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "meta_suggestions.json", cfg)
    assert stats["spans_deleted"] == 0
    assert stats["spans_would_delete"] == 1
    assert stats["suggestions_would_delete"] == 2
    assert stats["suggestions_deleted"] == 0
    # verify DB rows still there
    conn = sqlite3.connect(str(seeded_env / "telemetry.db"))
    count = conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
    conn.close()
    assert count == 2
    # verify suggestion file untouched
    remaining = json.loads((seeded_env / "meta_suggestions.json").read_text())
    assert len(remaining) == 3


def test_gc_records_event_log(seeded_env):
    cfg = GcConfig(span_days=30, dry_run=False)
    run_gc(seeded_env / "telemetry.db", seeded_env / "meta_suggestions.json", cfg)
    conn = sqlite3.connect(str(seeded_env / "telemetry.db"))
    rows = conn.execute("SELECT kind FROM events WHERE kind='gc_run'").fetchall()
    conn.close()
    assert len(rows) == 1


def test_gc_paused_returns_early(seeded_env):
    cfg = GcConfig(paused=True, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "meta_suggestions.json", cfg)
    assert stats.get("paused") is True
