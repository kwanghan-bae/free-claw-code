from pathlib import Path
from router.telemetry.store import Store
from router.telemetry.evaluations import RuleEvaluator, evaluate_span

def test_rule_evaluator_scores_successful_span_high(tmp_path: Path):
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    tid = b"\x01" * 16
    sid = b"\x02" * 8
    store.insert_trace(trace_id=tid, started_at_ms=1, root_op="x", root_session_id=None,
                       catalog_version="v", policy_version="1")
    store.insert_span(span_id=sid, trace_id=tid, parent_span_id=None, op_name="llm_call",
                      model_id="m", provider_id="p", skill_id=None, task_type="coding", started_at_ms=1)
    store.close_span(sid, ended_at_ms=2, duration_ms=1, status="ok")
    evals = evaluate_span(store, span_id=sid, evaluators=[RuleEvaluator()])
    dims = {e.score_dim: e.score_value for e in evals}
    assert dims.get("format_correctness") == 1.0

def test_rule_evaluator_scores_failed_span_low(tmp_path: Path):
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    tid = b"\x03" * 16
    sid = b"\x04" * 8
    store.insert_trace(trace_id=tid, started_at_ms=1, root_op="x", root_session_id=None,
                       catalog_version="v", policy_version="1")
    store.insert_span(span_id=sid, trace_id=tid, parent_span_id=None, op_name="llm_call",
                      model_id="m", provider_id="p", skill_id=None, task_type="coding", started_at_ms=1)
    store.close_span(sid, ended_at_ms=2, duration_ms=1, status="http_503")
    evals = evaluate_span(store, span_id=sid, evaluators=[RuleEvaluator()])
    dims = {e.score_dim: e.score_value for e in evals}
    assert dims.get("format_correctness") == 0.0
