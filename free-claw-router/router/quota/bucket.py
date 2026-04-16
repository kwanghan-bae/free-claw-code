from __future__ import annotations
import asyncio
import time
import uuid
from dataclasses import dataclass, field

@dataclass
class ReservationToken:
    id: str
    tokens_estimated: int

@dataclass
class Bucket:
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    daily_limit: int | None = None

    _rpm_window: list[float] = field(default_factory=list)
    _tpm_window: list[tuple[float, int]] = field(default_factory=list)
    _daily_used: int = 0
    _daily_reset: float = field(default_factory=lambda: _next_midnight())
    _reservations: dict[str, int] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reserve(self, tokens_estimated: int) -> ReservationToken:
        async with self._lock:
            self._trim()
            if self.rpm_limit is not None and self._effective_rpm() >= self.rpm_limit:
                raise RuntimeError("rpm_exhausted")
            if self.tpm_limit is not None and self._effective_tpm() + tokens_estimated > self.tpm_limit:
                raise RuntimeError("tpm_exhausted")
            if self.daily_limit is not None and self._daily_used + tokens_estimated > self.daily_limit:
                raise RuntimeError("daily_exhausted")
            tok = ReservationToken(id=uuid.uuid4().hex, tokens_estimated=tokens_estimated)
            self._reservations[tok.id] = tokens_estimated
            self._rpm_window.append(time.time())
            self._tpm_window.append((time.time(), tokens_estimated))
            return tok

    async def commit(self, token: ReservationToken, tokens_actual: int) -> None:
        async with self._lock:
            if token.id not in self._reservations:
                return
            estimated = self._reservations.pop(token.id)
            delta = tokens_actual - estimated
            if delta != 0:
                self._tpm_window.append((time.time(), delta))
            self._daily_used += tokens_actual

    async def rollback(self, token: ReservationToken) -> None:
        async with self._lock:
            est = self._reservations.pop(token.id, None)
            if est is None:
                return
            if self._rpm_window:
                self._rpm_window.pop()
            self._tpm_window.append((time.time(), -est))

    def _trim(self) -> None:
        cutoff = time.time() - 60.0
        self._rpm_window = [t for t in self._rpm_window if t >= cutoff]
        self._tpm_window = [(t, n) for (t, n) in self._tpm_window if t >= cutoff]
        if time.time() >= self._daily_reset:
            self._daily_used = 0
            self._daily_reset = _next_midnight()

    def _effective_rpm(self) -> int:
        return len(self._rpm_window)

    def _effective_tpm(self) -> int:
        return sum(n for _, n in self._tpm_window)

    def rpm_used(self) -> int:
        return self._effective_rpm()

    def tpm_used(self) -> int:
        return self._effective_tpm()

def _next_midnight() -> float:
    now = time.time()
    return now + (86400 - (now % 86400))

class BucketStore:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], Bucket] = {}

    def get(self, provider_id: str, model_id: str, *, rpm_limit: int | None, tpm_limit: int | None, daily_limit: int | None = None) -> Bucket:
        key = (provider_id, model_id)
        if key not in self._buckets:
            self._buckets[key] = Bucket(rpm_limit=rpm_limit, tpm_limit=tpm_limit, daily_limit=daily_limit)
        return self._buckets[key]
