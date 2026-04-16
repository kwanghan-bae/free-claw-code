from pathlib import Path
from router.telemetry.store import Store
from router.telemetry.readmodels import skill_model_affinity, quota_health

def _setup(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    tid = b"\x01" * 16
    for i, (skill, model, status) in enumerate([
        ("build", "groq/llama", "ok"),
        ("build", "groq/llama", "ok"),
        ("build", "groq/llama", "http_503"),
        ("build", "openrouter/glm", "ok"),
    ]):
        sid = bytes([i + 1]) * 8
        s.insert_trace(trace_id=tid, started_at_ms=1, root_op="x", root_session_id=None,
                       catalog_version="v", policy_version="1")
        s.insert_span(span_id=sid, trace_id=tid, parent_span_id=None, op_name="llm_call",
                      model_id=model, provider_id=model.split("/")[0],
                      skill_id=skill, task_type="coding", started_at_ms=1)
        s.close_span(sid, ended_at_ms=2, duration_ms=1, status=status)
        s.insert_evaluation(span_id=sid, evaluator="rule", score_dim="format_correctness",
                            score_value=1.0 if status == "ok" else 0.0, rationale=None, ts_ms=2)
    return s

def test_skill_model_affinity_returns_rates(tmp_path: Path):
    s = _setup(tmp_path)
    rows = skill_model_affinity(s, skill_id="build")
    by_model = {r["model_id"]: r for r in rows}
    assert by_model["groq/llama"]["trials"] == 3
    assert abs(by_model["groq/llama"]["success_rate"] - 2/3) < 1e-6

def test_quota_health_per_provider(tmp_path: Path):
    s = _setup(tmp_path)
    rows = quota_health(s)
    names = {r["provider_id"] for r in rows}
    assert {"groq", "openrouter"} <= names
