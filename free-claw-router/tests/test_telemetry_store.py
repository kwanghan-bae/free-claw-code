from pathlib import Path
from router.telemetry.store import Store

def test_store_creates_schema_on_init(tmp_path: Path):
    db = tmp_path / "t.db"
    s = Store(path=db)
    s.initialize()
    with s.connect() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"traces", "spans", "events", "evaluations"} <= names

def test_store_insert_trace_and_span(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    s.insert_trace(trace_id=b"\x01" * 16, started_at_ms=1, root_op="session",
                   root_session_id="s", catalog_version="2026-04-15", policy_version="1")
    s.insert_span(span_id=b"\x02" * 8, trace_id=b"\x01" * 16, parent_span_id=None,
                  op_name="llm_call", model_id="groq/llama", provider_id="groq",
                  skill_id=None, task_type="coding", started_at_ms=2)
    with s.connect() as c:
        rows = list(c.execute("SELECT op_name, model_id FROM spans"))
    assert rows == [("llm_call", "groq/llama")]
