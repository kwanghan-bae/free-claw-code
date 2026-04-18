"""Quota middleware: bucket reserve/commit/rollback per provider-model. Extracted from openai_compat.py under P5 A-3.
"""
from __future__ import annotations

from typing import Any

from router.adapters.hermes_ratelimit import RateLimitState
from router.dispatch.client import DispatchResult
from router.quota.bucket import BucketStore


# Shared bucket store singleton — reused across requests so per-provider limits are tracked.
bucket_store = BucketStore()


def get_bucket(candidate: Any):
    """Fetch the bucket for a candidate (provider, model) pair with its free-tier limits."""
    return bucket_store.get(
        candidate.provider_id, candidate.model_id,
        rpm_limit=candidate.model.free_tier.rpm,
        tpm_limit=candidate.model.free_tier.tpm,
        daily_limit=candidate.model.free_tier.daily,
    )


async def reserve_tokens(bucket, *, tokens_estimated: int):
    """Reserve tokens from the bucket.

    Returns the reservation token on success, or None if the bucket is exhausted.
    """
    try:
        return await bucket.reserve(tokens_estimated=tokens_estimated)
    except RuntimeError:
        return None


def quota_exhausted_result() -> DispatchResult:
    """Build the canonical DispatchResult returned when a bucket is exhausted."""
    return DispatchResult(429, {"error": "quota_exhausted"}, RateLimitState(), {})


async def settle(bucket, reservation, *, tokens_actual: int, success: bool) -> None:
    """Commit the reservation on success, or roll it back on failure."""
    if success:
        await bucket.commit(reservation, tokens_actual=tokens_actual)
    else:
        await bucket.rollback(reservation)
