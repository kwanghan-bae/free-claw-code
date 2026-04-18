"""Telemetry middleware: trace/span insertion, event emission. Extracted from openai_compat.py under P5 A-3.
"""
from __future__ import annotations

import json
import time
from typing import Any

from router.dispatch.client import DispatchResult
from router.telemetry import events as ev
from router.telemetry.store import Store


def start_trace(
    store: Store | None,
    *,
    trace_id: bytes,
    root_op: str,
    catalog_version: str,
    policy_version: str = "1",
) -> None:
    """Insert a trace row (best-effort)."""
    if not store:
        return
    try:
        store.insert_trace(
            trace_id=trace_id,
            started_at_ms=int(time.time() * 1000),
            root_op=root_op,
            root_session_id=None,
            catalog_version=catalog_version,
            policy_version=policy_version,
        )
    except Exception:
        pass


def start_span(
    store: Store | None,
    *,
    span_id: bytes,
    trace_id: bytes,
    parent_span_id: bytes,
    op_name: str,
    model_id: str,
    provider_id: str,
    task_type: str,
    started_at_ms: int,
) -> None:
    """Insert a span row (best-effort)."""
    if not store:
        return
    try:
        store.insert_span(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            op_name=op_name,
            model_id=model_id,
            provider_id=provider_id,
            skill_id=None,
            task_type=task_type,
            started_at_ms=started_at_ms,
        )
    except Exception:
        pass


def end_span(
    store: Store | None,
    *,
    span_id: bytes,
    span_start_ms: int,
    status: str,
) -> int:
    """Close a span and return the closing timestamp (best-effort)."""
    now = int(time.time() * 1000)
    if not store:
        return now
    try:
        store.close_span(span_id, ended_at_ms=now, duration_ms=now - span_start_ms, status=status)
    except Exception:
        pass
    return now


def emit_event(
    store: Store | None,
    *,
    span_id: bytes,
    kind: str,
    payload_json: str,
    ts_ms: int | None = None,
) -> None:
    """Emit a telemetry event (best-effort)."""
    if not store:
        return
    try:
        store.insert_event(
            span_id=span_id,
            kind=kind,
            payload_json=payload_json,
            ts_ms=ts_ms if ts_ms is not None else int(time.time() * 1000),
        )
    except Exception:
        pass


def emit_quota_reserved(
    store: Store | None,
    *,
    span_id: bytes,
    provider_id: str,
    model_id: str,
    tokens_estimated: int,
    bucket_rpm_used: int,
) -> None:
    """Emit a QuotaReserved event (best-effort)."""
    if not store:
        return
    try:
        payload = ev.to_payload(ev.QuotaReserved(
            provider_id=provider_id, model_id=model_id,
            tokens_estimated=tokens_estimated, bucket_rpm_used=bucket_rpm_used,
        ))
        emit_event(store, span_id=span_id, kind="quota_reserved", payload_json=json.dumps(payload))
    except Exception:
        pass


def emit_quota_exhausted(
    store: Store | None,
    *,
    span_id: bytes,
    span_start_ms: int,
    provider_id: str,
    model_id: str,
) -> None:
    """Close the span + emit dispatch_failed event on quota exhaustion (best-effort)."""
    if not store:
        return
    try:
        now = end_span(store, span_id=span_id, span_start_ms=span_start_ms, status="quota_exhausted")
        payload = ev.to_payload(ev.DispatchFailed(
            provider_id=provider_id, model_id=model_id,
            status=429, error_class="quota_exhausted",
        ))
        emit_event(store, span_id=span_id, kind="dispatch_failed",
                   payload_json=json.dumps(payload), ts_ms=now)
    except Exception:
        pass


def emit_request_event(
    store: Store | None,
    *,
    span_id: bytes,
    messages: Any,
) -> None:
    """Record a request event for transcript mining (best-effort)."""
    if not store:
        return
    try:
        emit_event(store, span_id=span_id, kind="request",
                   payload_json=json.dumps({"messages": messages}))
    except Exception:
        pass


def emit_response_event(
    store: Store | None,
    *,
    span_id: bytes,
    body: Any,
) -> None:
    """Record a response event for transcript mining (best-effort)."""
    if not store:
        return
    try:
        emit_event(store, span_id=span_id, kind="response",
                   payload_json=json.dumps(body))
    except Exception:
        pass


def emit_dispatch_result(
    store: Store | None,
    *,
    span_id: bytes,
    span_start_ms: int,
    provider_id: str,
    model_id: str,
    result: DispatchResult,
) -> None:
    """Close span + emit dispatch_succeeded or dispatch_failed (best-effort)."""
    if not store:
        return
    try:
        status = "ok" if result.status == 200 else f"http_{result.status}"
        now = end_span(store, span_id=span_id, span_start_ms=span_start_ms, status=status)
        if result.status == 200:
            payload = ev.to_payload(ev.DispatchSucceeded(
                provider_id=provider_id, model_id=model_id,
                status=result.status, latency_ms=now - span_start_ms,
            ))
            emit_event(store, span_id=span_id, kind="dispatch_succeeded",
                       payload_json=json.dumps(payload), ts_ms=now)
        else:
            payload = ev.to_payload(ev.DispatchFailed(
                provider_id=provider_id, model_id=model_id,
                status=result.status, error_class=f"http_{result.status}",
            ))
            emit_event(store, span_id=span_id, kind="dispatch_failed",
                       payload_json=json.dumps(payload), ts_ms=now)
    except Exception:
        pass
