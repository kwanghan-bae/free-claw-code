import pytest
import httpx
from router.dispatch.client import DispatchClient, DispatchResult
from router.catalog.schema import ProviderSpec, ModelSpec, FreeTier, Pricing, Auth
from router.adapters.hermes_ratelimit import RateLimitState

def _model() -> ModelSpec:
    return ModelSpec(
        model_id="p/m:free",
        status="active",
        context_window=8192,
        tool_use=True,
        structured_output="partial",
        free_tier=FreeTier(rpm=10, tpm=5000, daily=None, reset_policy="minute"),
        pricing=Pricing(input=0, output=0, free=True),
        quirks=[],
        evidence_urls=["https://example.com"],
        last_verified="2026-04-15T00:00:00Z",
        first_seen="2026-04-15",
    )

def _provider() -> ProviderSpec:
    return ProviderSpec(
        provider_id="p",
        base_url="https://example.test/v1",
        auth=Auth(env="P_KEY", scheme="bearer"),
        known_ratelimit_header_schema="generic",
        models=[_model()],
    )

@pytest.mark.asyncio
async def test_client_captures_rate_limit_state(monkeypatch):
    async def fake_post(self, url, json=None, headers=None, timeout=None):
        req = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=req,
            json={"ok": True},
            headers={"x-ratelimit-limit-requests": "30", "x-ratelimit-remaining-requests": "29"},
        )
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv("P_KEY", "sk")

    c = DispatchClient()
    result = await c.call(_provider(), _model(), {"messages": []}, {})
    assert result.status == 200
    assert result.rate_limit_state.requests_min.limit == 30
    assert result.body == {"ok": True}
