from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Nudge:
    nudge_type: Literal["memory_save", "skill_create", "skill_fix"]
    content: str
    source: str  # "rule" | "batch"
    confidence: float
    created_at: float = field(default_factory=time.time)


class NudgeCache:
    def __init__(self, max_per_trace: int = 5, ttl_seconds: float = 600) -> None:
        self._max = max_per_trace
        self._ttl = ttl_seconds
        self._queues: dict[str, list[Nudge]] = {}

    def push(self, trace_id: str, nudge: Nudge) -> None:
        q = self._queues.setdefault(trace_id, [])
        q.append(nudge)
        if len(q) > self._max:
            q.sort(key=lambda n: n.confidence, reverse=True)
            self._queues[trace_id] = q[: self._max]

    def peek(self, trace_id: str) -> list[Nudge]:
        self._expire(trace_id)
        return list(self._queues.get(trace_id, []))

    def pop_all(self, trace_id: str) -> list[Nudge]:
        self._expire(trace_id)
        return self._queues.pop(trace_id, [])

    def _expire(self, trace_id: str) -> None:
        now = time.time()
        q = self._queues.get(trace_id)
        if q:
            self._queues[trace_id] = [n for n in q if now - n.created_at < self._ttl]


class ConversationBuffer:
    def __init__(self) -> None:
        self._turns: dict[str, list[dict]] = {}

    def append_user(self, trace_id: str, content: str) -> None:
        self._turns.setdefault(trace_id, []).append({"role": "user", "content": content})

    def append_assistant(self, trace_id: str, content: str) -> None:
        self._turns.setdefault(trace_id, []).append({"role": "assistant", "content": content})

    def recent(self, trace_id: str, n: int = 5) -> list[dict]:
        return self._turns.get(trace_id, [])[-n:]

    def turn_count(self, trace_id: str) -> int:
        return len(self._turns.get(trace_id, []))
