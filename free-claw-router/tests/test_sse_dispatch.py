from __future__ import annotations
import pytest
import httpx
import yaml
from pathlib import Path


@pytest.mark.asyncio
async def test_sse_passthrough_yields_chunks_in_order(monkeypatch):
    """Verify dispatch_sse streams bytes through unchanged and preserves order."""
    from router.dispatch import sse as sse_mod

    body_text = (
        "data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\n"
        "data: {\"choices\":[{\"delta\":{\"content\":\" there\"}}]}\n\n"
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body_text.encode("utf-8"),
        )

    transport = httpx.MockTransport(handler)

    # Patch the AsyncClient constructor inside sse module to use our transport.
    original = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(sse_mod.httpx, "AsyncClient", _patched)

    chunks: list[bytes] = []
    async for c in sse_mod.dispatch_sse(
        provider={"id": "openrouter", "base_url": "https://openrouter.example/api/v1"},
        request={"model": "x", "messages": [], "stream": True},
    ):
        chunks.append(c)
    joined = b"".join(chunks).decode()
    assert "hi" in joined
    assert "there" in joined
    assert "[DONE]" in joined


def test_provider_supports_sse_reads_catalog():
    from router.dispatch.sse import provider_supports_sse
    # openrouter.yaml should have capabilities.sse: true after C-2
    assert provider_supports_sse("openrouter") is True
    # unknown providers -> False (default-closed)
    assert provider_supports_sse("unknown-provider") is False


def test_provider_sse_flag_false_for_non_streaming_provider():
    from router.dispatch.sse import provider_supports_sse
    # z.ai / cerebras / ollama / lmstudio -> should be False in L2
    assert provider_supports_sse("cerebras") is False


def test_catalog_openrouter_has_sse_true():
    catalog_root = Path(__file__).resolve().parent.parent / "router" / "catalog" / "data"
    data = yaml.safe_load((catalog_root / "openrouter.yaml").read_text())
    assert data["capabilities"]["sse"] is True
