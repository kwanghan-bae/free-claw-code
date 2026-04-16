import asyncio
import pytest
from router.quota.bucket import Bucket, BucketStore

@pytest.mark.asyncio
async def test_reserve_commit_decreases_remaining():
    b = Bucket(rpm_limit=10, tpm_limit=1000)
    tok = await b.reserve(tokens_estimated=100)
    await b.commit(tok, tokens_actual=80)
    assert b.tpm_used() == 80
    assert b.rpm_used() == 1

@pytest.mark.asyncio
async def test_rollback_releases_reservation():
    b = Bucket(rpm_limit=10, tpm_limit=1000)
    tok = await b.reserve(tokens_estimated=100)
    await b.rollback(tok)
    assert b.tpm_used() == 0
    assert b.rpm_used() == 0

@pytest.mark.asyncio
async def test_reserve_fails_when_rpm_exhausted():
    b = Bucket(rpm_limit=2, tpm_limit=1000)
    await b.reserve(tokens_estimated=10)
    await b.reserve(tokens_estimated=10)
    with pytest.raises(RuntimeError):
        await b.reserve(tokens_estimated=10)

@pytest.mark.asyncio
async def test_store_resolves_bucket_per_pair():
    s = BucketStore()
    b1 = s.get("groq", "llama-3.3-70b-versatile", rpm_limit=30, tpm_limit=6000)
    b2 = s.get("groq", "llama-3.3-70b-versatile", rpm_limit=30, tpm_limit=6000)
    assert b1 is b2
    b3 = s.get("openrouter", "z-ai/glm-4.6:free", rpm_limit=20, tpm_limit=100000)
    assert b1 is not b3
