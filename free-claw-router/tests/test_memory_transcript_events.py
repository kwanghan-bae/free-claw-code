import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState
from router.telemetry.store import Store
from router.memory.transcript import build_transcript
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

def test_request_and_response_events_enable_transcript(store, client, monkeypatch):
    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        return DispatchResult(
            200,
            {"choices": [{"message": {"role": "assistant", "content": "I refactored it."}}]},
            RateLimitState(), {},
        )
    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor auth"}]},
        headers={"x-free-claw-hints": "coding",
                 "traceparent": "00-dddddddddddddddddddddddddddddddd-eeeeeeeeeeeeeeee-01"},
    )
    assert r.status_code == 200

    tid = bytes.fromhex("dddddddddddddddddddddddddddddddd")
    transcript = build_transcript(store, trace_id=tid)
    assert "refactor auth" in transcript
    assert "refactored it" in transcript
