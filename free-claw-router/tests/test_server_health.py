import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c

def test_health_returns_ok_status(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "catalog_version" in body

def test_chat_completions_no_longer_501(client):
    # The 501 stub has been replaced by real dispatch; an empty-messages
    # request with no matching task_type still returns a structured error
    # (503 for unknown hint) rather than the old not_implemented stub.
    r = client.post(
        "/v1/chat/completions",
        json={"model": "stub", "messages": []},
        headers={"x-free-claw-hints": "nonexistent_type"},
    )
    assert r.status_code == 503
