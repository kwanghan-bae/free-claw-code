"""Port of Hermes rate_limit_tracker bucket state.
Wraps parsed rate-limit headers into structured buckets.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Mapping

@dataclass
class Bucket:
    limit: int = 0
    remaining: int = 0
    reset_seconds: float = 0.0
    captured_at: float = field(default_factory=time.time)

    @property
    def used(self) -> int:
        return max(0, self.limit - self.remaining)

    @property
    def usage_pct(self) -> float:
        if self.limit <= 0:
            return 0.0
        return 100.0 * self.used / self.limit

@dataclass
class RateLimitState:
    requests_min: Bucket = field(default_factory=Bucket)
    requests_hour: Bucket = field(default_factory=Bucket)
    tokens_min: Bucket = field(default_factory=Bucket)
    tokens_hour: Bucket = field(default_factory=Bucket)

def _int(v: str | None, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default

def _float(v: str | None, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default

def parse_rate_limit_headers(headers: Mapping[str, str]) -> RateLimitState:
    h = {k.lower(): v for k, v in headers.items()}
    now = time.time()
    return RateLimitState(
        requests_min=Bucket(
            limit=_int(h.get("x-ratelimit-limit-requests")),
            remaining=_int(h.get("x-ratelimit-remaining-requests")),
            reset_seconds=_float(h.get("x-ratelimit-reset-requests")),
            captured_at=now,
        ),
        requests_hour=Bucket(
            limit=_int(h.get("x-ratelimit-limit-requests-1h")),
            remaining=_int(h.get("x-ratelimit-remaining-requests-1h")),
            reset_seconds=_float(h.get("x-ratelimit-reset-requests-1h")),
            captured_at=now,
        ),
        tokens_min=Bucket(
            limit=_int(h.get("x-ratelimit-limit-tokens")),
            remaining=_int(h.get("x-ratelimit-remaining-tokens")),
            reset_seconds=_float(h.get("x-ratelimit-reset-tokens")),
            captured_at=now,
        ),
        tokens_hour=Bucket(
            limit=_int(h.get("x-ratelimit-limit-tokens-1h")),
            remaining=_int(h.get("x-ratelimit-remaining-tokens-1h")),
            reset_seconds=_float(h.get("x-ratelimit-reset-tokens-1h")),
            captured_at=now,
        ),
    )
