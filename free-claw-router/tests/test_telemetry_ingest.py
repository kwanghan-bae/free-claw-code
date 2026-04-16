from pathlib import Path
import json
from router.telemetry.store import Store
from router.telemetry.ingest_jsonl import ingest_lines

def test_ingest_translates_span_started_and_ended(tmp_path: Path):
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    tid = "4bf92f3577b34da6a3ce929d0e0e4736"
    sid = "00f067aa0ba902b7"
    lines = [
        json.dumps({
            "type": "span_started",
            "trace_id": tid,
            "span_id": sid,
            "parent_span_id": None,
            "op_name": "tool_call",
            "session_id": "s1",
            "attributes": {"tool_name": "Read"},
        }),
        json.dumps({
            "type": "span_ended",
            "span_id": sid,
            "status": "ok",
            "duration_ms": 42,
            "attributes": {},
        }),
    ]
    ingest_lines(store, lines, default_catalog_version="2026-04-15", default_policy_version="1")
    with store.connect() as c:
        spans = list(c.execute("SELECT op_name, status, duration_ms FROM spans"))
    assert spans == [("tool_call", "ok", 42)]
