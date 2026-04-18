"""Quota middleware: bucket reserve/commit/rollback per provider-model, plus a per-candidate
dispatch helper that weaves quota state through the telemetry/dispatch lifecycle.
Extracted from openai_compat.py under P5 A-3.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Callable

from router.adapters.hermes_ratelimit import RateLimitState
from router.dispatch.client import DispatchResult
from router.quota.bucket import BucketStore
from router.server._telemetry_middleware import (
    emit_dispatch_result,
    emit_quota_exhausted,
    emit_quota_reserved,
    emit_request_event,
    emit_response_event,
    start_span,
)


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
    """Reserve tokens from the bucket; return the reservation token or None on exhaustion."""
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


def make_dispatch_call(
    *,
    registry: Any,
    dispatch_client: Any,
    store: Any,
    trace_id: bytes,
    root_span_id: bytes,
    hint: str,
    payload: dict,
    estimated: int,
    request_headers: dict,
) -> Callable:
    """Build the per-candidate dispatcher closure used by run_fallback_chain.

    The returned coroutine: reserves quota → starts a span → dispatches → settles quota →
    records response + close-span events. Telemetry is best-effort on every step.
    """

    async def call_one(cand):
        provider = next(p for p in registry.providers if p.provider_id == cand.provider_id)
        bucket = get_bucket(cand)

        span_id = secrets.token_bytes(8)
        span_start = int(time.time() * 1000)

        start_span(
            store,
            span_id=span_id, trace_id=trace_id, parent_span_id=root_span_id,
            op_name="llm_call", model_id=cand.model_id, provider_id=cand.provider_id,
            task_type=hint, started_at_ms=span_start,
        )

        tok = await reserve_tokens(bucket, tokens_estimated=estimated)
        if tok is None:
            emit_quota_exhausted(
                store,
                span_id=span_id, span_start_ms=span_start,
                provider_id=cand.provider_id, model_id=cand.model_id,
            )
            return quota_exhausted_result()

        emit_quota_reserved(
            store,
            span_id=span_id, provider_id=cand.provider_id, model_id=cand.model_id,
            tokens_estimated=estimated, bucket_rpm_used=bucket.rpm_used(),
        )
        emit_request_event(store, span_id=span_id, messages=payload.get("messages", []))

        result = await dispatch_client.call(provider, cand.model, payload, request_headers)

        if result.status == 200:
            emit_response_event(store, span_id=span_id, body=result.body)

        await settle(bucket, tok, tokens_actual=estimated, success=result.status == 200)

        emit_dispatch_result(
            store,
            span_id=span_id, span_start_ms=span_start,
            provider_id=cand.provider_id, model_id=cand.model_id,
            result=result,
        )

        return result

    return call_one
