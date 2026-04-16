from __future__ import annotations
from typing import Awaitable, Callable
from router.routing.decide import Candidate
from router.dispatch.client import DispatchResult

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

async def run_fallback_chain(
    chain: list[Candidate],
    call_one: Callable[[Candidate], Awaitable[DispatchResult]],
) -> DispatchResult:
    last: DispatchResult | None = None
    for cand in chain:
        last = await call_one(cand)
        if last.status == 200:
            return last
        if last.status not in RETRY_STATUSES:
            return last
    assert last is not None, "chain must be non-empty"
    return last
