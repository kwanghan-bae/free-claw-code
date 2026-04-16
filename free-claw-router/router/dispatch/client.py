from __future__ import annotations
import os
from dataclasses import dataclass
import httpx
from router.catalog.schema import ProviderSpec, ModelSpec

@dataclass
class DispatchResult:
    status: int
    body: dict
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
            key = os.environ.get(provider.auth.env, "")
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
            response_headers=resp_headers,
        )
