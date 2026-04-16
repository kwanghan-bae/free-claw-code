import pytest
import httpx
from router.quota.backpressure import notify_claw, BackpressureHint

@pytest.mark.asyncio
async def test_notify_claw_posts_hint(monkeypatch):
    captured: dict = {}
    async def fake_post(self, url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        req = httpx.Request("POST", url, json=json)
        return httpx.Response(204, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    ok = await notify_claw(
        "http://127.0.0.1:7901",
        BackpressureHint(task_type="coding", suggested_concurrency=2, reason="tight", ttl_seconds=60),
    )
    assert ok
    assert captured["url"].endswith("/internal/backpressure")
    assert captured["json"]["task_type"] == "coding"

@pytest.mark.asyncio
async def test_notify_claw_returns_false_on_error(monkeypatch):
    async def fake_post(self, url, json=None, timeout=None):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    ok = await notify_claw(
        "http://127.0.0.1:1",
        BackpressureHint(task_type="coding", suggested_concurrency=1, reason="x", ttl_seconds=60),
    )
    assert ok is False
