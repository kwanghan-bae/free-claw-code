from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class TraceContext:
    trace_id: bytes
    span_id: bytes
    sampled: bool

def parse_traceparent(value: str | None) -> TraceContext | None:
    if not value:
        return None
    parts = value.strip().split("-")
    if len(parts) != 4 or parts[0] != "00":
        return None
    if len(parts[1]) != 32 or len(parts[2]) != 16 or len(parts[3]) != 2:
        return None
    try:
        tid = bytes.fromhex(parts[1])
        sid = bytes.fromhex(parts[2])
        flags = int(parts[3], 16)
    except ValueError:
        return None
    return TraceContext(trace_id=tid, span_id=sid, sampled=(flags & 1) == 1)

def encode_traceparent(ctx: TraceContext) -> str:
    return f"00-{ctx.trace_id.hex()}-{ctx.span_id.hex()}-{'01' if ctx.sampled else '00'}"
