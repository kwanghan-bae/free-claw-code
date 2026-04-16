import json
from pathlib import Path
from router.telemetry.store import Store
from router.memory.transcript import build_transcript

def _seed(store: Store, trace_id: bytes):
    store.insert_trace(trace_id=trace_id, started_at_ms=1000, root_op="session",
                       root_session_id="s1", catalog_version="v", policy_version="1")
    sid1 = b"\x01" * 8
    store.insert_span(span_id=sid1, trace_id=trace_id, parent_span_id=None,
                      op_name="llm_call", model_id="groq/llama", provider_id="groq",
                      skill_id=None, task_type="coding", started_at_ms=1000)
    store.insert_event(span_id=sid1, kind="request",
                       payload_json=json.dumps({"messages": [{"role": "user", "content": "refactor auth"}]}),
                       ts_ms=1000)
    store.insert_event(span_id=sid1, kind="dispatch_succeeded",
                       payload_json=json.dumps({"data": {"provider_id": "groq", "model_id": "llama"}}),
                       ts_ms=1100)
    # Simulate assistant response stored as event
    store.insert_event(span_id=sid1, kind="response",
                       payload_json=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Done, I refactored the auth module."}}]}),
                       ts_ms=1200)

def test_build_transcript_returns_markdown(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    tid = b"\xaa" * 16
    _seed(s, tid)
    text = build_transcript(s, trace_id=tid)
    assert "refactor auth" in text
    assert "refactored the auth module" in text

def test_build_transcript_delta_skips_already_mined(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    tid = b"\xbb" * 16
    _seed(s, tid)
    text = build_transcript(s, trace_id=tid, after_ts=1150)
    assert "refactor auth" not in text  # event at ts=1000 skipped
    assert "refactored the auth module" in text  # event at ts=1200 included

def test_build_transcript_empty_when_no_events(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    text = build_transcript(s, trace_id=b"\xcc" * 16)
    assert text.strip() == ""
