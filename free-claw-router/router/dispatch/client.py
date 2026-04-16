from __future__ import annotations
from dataclasses import dataclass
import httpx
from router.catalog.schema import ProviderSpec, ModelSpec
from router.adapters.hermes_credentials import resolve_api_key
from router.adapters.hermes_ratelimit import parse_rate_limit_headers, RateLimitState

@dataclass
class DispatchResult:
    status: int
    body: dict
    rate_limit_state: RateLimitState
    response_headers: dict[str, str]

class DispatchClient:
    async def call(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        payload: dict,
        upstream_headers: dict[str, str],
        *,
        timeout: float = 60.0,
    ) -> DispatchResult:
        headers: dict[str, str] = {}
        if provider.auth.scheme == "bearer":
            key = resolve_api_key(provider.auth.env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        for h in ("traceparent", "x-free-claw-hints"):
            if h in upstream_headers:
                headers[h] = upstream_headers[h]

        body = {**payload, "model": model.model_id}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{provider.base_url.rstrip('/')}/chat/completions",
                json=body,
                headers=headers,
            )
        resp_headers = dict(resp.headers)
        try:
            resp_body = resp.json()
        except Exception:
            resp_body = {"raw": resp.text}
        return DispatchResult(
            status=resp.status_code,
            body=resp_body,
            rate_limit_state=parse_rate_limit_headers(resp_headers),
            response_headers=resp_headers,
        )
