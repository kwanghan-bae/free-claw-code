"""Server-Sent Events (SSE) passthrough dispatcher.

L2 scope: OpenRouter (canonical). Groq is a bonus if the catalog flag
is set. z.ai / Cerebras / Ollama / LM Studio remain non-stream in L2
and are targeted for L3 SSE support.

Telemetry: span starts on first chunk, ends on [DONE] or connection
close. Real-time tool_call parsing is L3; L2 captures the full text
on stream end only.
"""
from __future__ import annotations
from pathlib import Path
from typing import AsyncIterator, Optional
import json
import logging

import httpx
import yaml

logger = logging.getLogger(__name__)

_CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog" / "data"
_CACHE: Optional[dict[str, bool]] = None


def _load_catalog_sse() -> dict[str, bool]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out: dict[str, bool] = {}
    if not _CATALOG_DIR.exists():
        _CACHE = out
        return out
    for f in sorted(_CATALOG_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        # catalog YAMLs use `provider_id`; fall back to file stem.
        pid = data.get("provider_id") or data.get("id") or f.stem
        caps = data.get("capabilities") or {}
        out[pid] = bool(caps.get("sse", False))
    _CACHE = out
    return out


def provider_supports_sse(provider_id: str) -> bool:
    """Return True if the catalog entry for provider_id has capabilities.sse=true."""
    return _load_catalog_sse().get(provider_id, False)


async def dispatch_sse(
    provider: dict,
    request: dict,
    headers: Optional[dict] = None,
) -> AsyncIterator[bytes]:
    """Stream SSE bytes from provider, passing through unchanged.

    Behavior:
    - First chunk received -> open telemetry span.
    - Any bytes containing [DONE] -> close span OK and stop.
    - Exception during stream -> close span with status, yield a single
      `event: error` SSE frame so the client sees the failure cleanly.

    The span helpers are imported lazily to avoid startup import cycles
    and to remain best-effort (telemetry failures never block routing).
    """
    url = f"{provider['base_url'].rstrip('/')}/chat/completions"
    h = {"accept": "text/event-stream", "cache-control": "no-cache"}
    if headers:
        h.update(headers)

    span_id: Optional[str] = None
    first_chunk = False

    async def _start_span() -> Optional[str]:
        try:
            from router.server._telemetry_middleware import start_span  # type: ignore
            return start_span(
                op_name="sse_dispatch",
                model_id=request.get("model", "?"),
                provider_id=provider.get("id", "?"),
            )
        except Exception:
            return None

    async def _end_span(sid: Optional[str], status: str) -> None:
        if sid is None:
            return
        try:
            from router.server._telemetry_middleware import end_span  # type: ignore
            end_span(sid, status=status)
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=request, headers=h) as resp:
                async for chunk in resp.aiter_bytes():
                    if not first_chunk:
                        first_chunk = True
                        span_id = await _start_span()
                    yield chunk
                    if b"[DONE]" in chunk:
                        await _end_span(span_id, status="ok")
                        return
        await _end_span(span_id, status="ok")
    except Exception as e:
        logger.warning("SSE dispatch failed: %s", e)
        await _end_span(span_id, status=f"error: {e}")
        err_body = json.dumps({"error": str(e)})
        yield f"event: error\ndata: {err_body}\n\n".encode("utf-8")
