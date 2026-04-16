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

def test_chat_completions_returns_501_stub(client):
    r = client.post("/v1/chat/completions", json={"model": "stub", "messages": []})
    assert r.status_code == 501
    assert "not_implemented" in r.json()["error"]["code"]
