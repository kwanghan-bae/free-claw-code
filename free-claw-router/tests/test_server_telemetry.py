import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState
from router.telemetry.store import Store
import router.server.openai_compat as mod

@pytest.fixture
def store(tmp_path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    mod._telemetry_store = s
    yield s
    mod._telemetry_store = None

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_span_and_events_recorded_for_successful_dispatch(store, client, monkeypatch):
    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        return DispatchResult(200, {"choices": [{"message": {"content": "hi"}}]}, RateLimitState(), {})
    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor"}]},
        headers={
            "x-free-claw-hints": "coding",
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    assert r.status_code == 200

    with store.connect() as c:
        spans = list(c.execute("SELECT op_name, model_id, status FROM spans ORDER BY started_at"))
        events = list(c.execute("SELECT kind FROM events"))
    assert any(row[0] == "llm_call" for row in spans)
    assert any(row[2] == "ok" for row in spans)
    event_kinds = {e[0] for e in events}
    assert "dispatch_succeeded" in event_kinds
