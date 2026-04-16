import pytest
from router.dispatch.fallback import run_fallback_chain
from router.routing.decide import Candidate
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState

def _cand(id_):
    return Candidate(provider_id=f"p{id_}", model_id=f"m{id_}", model=None, score=0.5)

@pytest.mark.asyncio
async def test_fallback_returns_first_success():
    attempts = []
    async def fake_call(cand):
        attempts.append(cand.model_id)
        return DispatchResult(200, {"ok": True}, RateLimitState(), {})
    out = await run_fallback_chain([_cand(1), _cand(2)], fake_call)
    assert attempts == ["m1"]
    assert out.status == 200

@pytest.mark.asyncio
async def test_fallback_on_429_tries_next():
    async def fake_call(cand):
        if cand.model_id == "m1":
            return DispatchResult(429, {"error": "quota"}, RateLimitState(), {})
        return DispatchResult(200, {"ok": True}, RateLimitState(), {})
    out = await run_fallback_chain([_cand(1), _cand(2)], fake_call)
    assert out.status == 200

@pytest.mark.asyncio
async def test_fallback_on_all_exhausted_returns_last():
    async def fake_call(cand):
        return DispatchResult(503, {"error": "down"}, RateLimitState(), {})
    out = await run_fallback_chain([_cand(1), _cand(2)], fake_call)
    assert out.status == 503
