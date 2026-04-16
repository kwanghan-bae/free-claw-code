from __future__ import annotations
from dataclasses import dataclass, asdict
import httpx

@dataclass
class BackpressureHint:
    task_type: str
    suggested_concurrency: int
    reason: str
    ttl_seconds: int

async def notify_claw(claw_base_url: str, hint: BackpressureHint, *, timeout: float = 2.0) -> bool:
    url = f"{claw_base_url.rstrip('/')}/internal/backpressure"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=asdict(hint), timeout=timeout)
        return resp.status_code < 400
    except Exception:
        return False
