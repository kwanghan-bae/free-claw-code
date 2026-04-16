import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState
import router.server.openai_compat as mod

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_first_request_contains_memory_context(client, monkeypatch):
    captured_payload = {}
    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        captured_payload.update(payload)
        return DispatchResult(200, {"choices": [{"message": {"content": "hi"}}]}, RateLimitState(), {})
    monkeypatch.setattr(_dispatch, "call", fake_call)

    with patch("router.memory.wakeup._get_palace") as mock_palace_fn:
        mock_palace = mock_palace_fn.return_value
        mock_palace.wake_up.return_value = "You decided to use GraphQL."

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}]},
            headers={"x-free-claw-hints": "chat", "x-free-claw-workspace": "/a/b/testproject",
                     "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1-bbbbbbbbbbbbbbbb-01"},
        )
    assert r.status_code == 200
    system_msg = captured_payload["messages"][0]["content"]
    assert "Memory Context" in system_msg
