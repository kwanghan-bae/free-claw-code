import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_chat_completions_dispatches_via_fallback_chain(client, monkeypatch):
    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        return DispatchResult(
            200,
            {"id": "x", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            RateLimitState(),
            {},
        )
    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor"}]},
        headers={"x-free-claw-hints": "coding"},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hi"

def test_503_when_unknown_task_type(client, monkeypatch):
    # Mock dispatch so we don't hit real networks
    async def fake_call(*a, **kw):
        return DispatchResult(200, {}, RateLimitState(), {})
    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-free-claw-hints": "nonexistent_type"},
    )
    assert r.status_code == 503
