"""Memory + nudge injection middleware: P1 memory context and P3 learning nudges.
Extracted from openai_compat.py under P5 A-3.
"""
from __future__ import annotations

import time as _time
from typing import Any

from router.routing.hints import classify_task_hint


class RequestGapTracker:
    """Tracks wall-clock gap between successive requests sharing a trace_id (for P1 injection heuristics)."""

    def __init__(self):
        self._last_ts: dict[str, float] = {}

    def get_gap(self, trace_id: str) -> float:
        now = _time.time()
        last = self._last_ts.get(trace_id, now)
        self._last_ts[trace_id] = now
        return now - last


# Module-level singleton preserved for parity with the pre-split openai_compat.
request_gap_tracker = RequestGapTracker()


def inject_memory(app_state, payload: dict, *, trace_hex: str, workspace: str | None) -> dict:
    """P1 memory injection: if an injector is wired onto app.state, let it maybe-augment the payload."""
    injector = getattr(app_state, "injector", None)
    if injector is None:
        return payload
    gap = request_gap_tracker.get_gap(trace_hex)
    return injector.maybe_inject(
        payload,
        trace_id=trace_hex,
        workspace=workspace,
        last_request_gap_seconds=gap,
    )


def inject_nudges(app_state, payload: dict, *, trace_hex: str) -> dict:
    """P3 learning-nudge injection: inject queued nudges for the trace if a nudge_injector is wired."""
    nudge_inj = getattr(app_state, "nudge_injector", None)
    if nudge_inj is None:
        return payload
    return nudge_inj.inject(payload, trace_id=trace_hex)


def resolve_task_hint(payload: dict, header_hint: str | None) -> str:
    """Use the caller-supplied hint, or infer one from the most recent user message."""
    if header_hint:
        return header_hint
    last_user = ""
    for m in payload.get("messages", []):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                last_user = c
    return classify_task_hint(last_user) if last_user else "chat"


def record_session_activity(app_state, *, trace_hex: str, workspace: str) -> None:
    """Record per-request activity so the session detector can fire session-close events."""
    detector = getattr(app_state, "session_detector", None)
    if detector is None:
        return
    detector.record_activity(trace_id=trace_hex, workspace=workspace)


def scan_and_buffer(app_state, *, payload: dict, result: Any, trace_hex: str) -> None:
    """P3: scan response for rule-based nudges and append turns to the conversation buffer."""
    rule_det = getattr(app_state, "rule_detector", None)
    conv_buf = getattr(app_state, "conv_buffer", None)
    ncache = getattr(app_state, "nudge_cache", None)

    if rule_det and ncache and result.status == 200:
        assistant_text = ""
        for ch in result.body.get("choices", []):
            msg = ch.get("message", {})
            if msg.get("role") == "assistant":
                assistant_text = msg.get("content", "")
        if assistant_text:
            for nudge in rule_det.scan(assistant_text):
                ncache.push(trace_hex, nudge)

    if conv_buf:
        for m in payload.get("messages", []):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                conv_buf.append_user(trace_hex, m["content"])
        if result.status == 200:
            for ch in result.body.get("choices", []):
                msg = ch.get("message", {})
                if msg.get("role") == "assistant":
                    conv_buf.append_assistant(trace_hex, msg.get("content", ""))


async def maybe_batch_analyze(app_state, *, trace_hex: str) -> None:
    """P3: every 5 turns, invoke the batch analyzer and push any nudges it yields into the cache."""
    conv_buf = getattr(app_state, "conv_buffer", None)
    batch = getattr(app_state, "batch_analyzer", None)
    ncache = getattr(app_state, "nudge_cache", None)
    if not (conv_buf and batch and ncache):
        return
    if conv_buf.turn_count(trace_hex) % 5 != 0 or conv_buf.turn_count(trace_hex) <= 0:
        return
    try:
        batch_nudges = await batch.analyze(trace_hex, conv_buf)
        for n in batch_nudges:
            ncache.push(trace_hex, n)
    except Exception:
        pass  # batch analysis is best-effort
