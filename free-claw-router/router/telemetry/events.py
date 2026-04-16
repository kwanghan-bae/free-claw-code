from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Union

@dataclass
class QuotaReserved:
    provider_id: str
    model_id: str
    tokens_estimated: int
    bucket_rpm_used: int

@dataclass
class QuotaCommitted:
    provider_id: str
    model_id: str
    tokens_actual: int

@dataclass
class QuotaRolledBack:
    provider_id: str
    model_id: str
    reason: str

@dataclass
class DispatchSucceeded:
    provider_id: str
    model_id: str
    status: int
    latency_ms: int

@dataclass
class DispatchFailed:
    provider_id: str
    model_id: str
    status: int
    error_class: str

@dataclass
class BackpressureEmitted:
    task_type: str
    suggested_concurrency: int

Event = Union[
    QuotaReserved, QuotaCommitted, QuotaRolledBack,
    DispatchSucceeded, DispatchFailed, BackpressureEmitted,
]

_KINDS: dict[type, str] = {
    QuotaReserved: "quota_reserved",
    QuotaCommitted: "quota_committed",
    QuotaRolledBack: "quota_rolled_back",
    DispatchSucceeded: "dispatch_succeeded",
    DispatchFailed: "dispatch_failed",
    BackpressureEmitted: "backpressure_emitted",
}

def to_payload(ev: Event) -> dict:
    return {"kind": _KINDS[type(ev)], "data": asdict(ev)}
