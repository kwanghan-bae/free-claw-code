from __future__ import annotations
import copy
from pathlib import Path
from typing import Callable


MEMORY_HEADER = "\n\n## Memory Context (auto-injected by mempalace)\n\n"


class Injector:
    def __init__(
        self,
        wakeup_fn: Callable[[str], str],
        idle_threshold_seconds: int = 1800,
    ) -> None:
        self._wakeup_fn = wakeup_fn
        self._idle_threshold = idle_threshold_seconds
        self._injected_traces: dict[str, float] = {}  # trace_id -> last_inject_ts

    def maybe_inject(
        self,
        payload: dict,
        *,
        trace_id: str,
        workspace: str | None,
        last_request_gap_seconds: float,
    ) -> dict:
        should_inject = False
        if trace_id not in self._injected_traces:
            should_inject = True
        elif last_request_gap_seconds >= self._idle_threshold:
            should_inject = True

        if not should_inject:
            return payload

        wing = Path(workspace).name if workspace else "default"
        wakeup_text = self._wakeup_fn(wing)
        if not wakeup_text.strip():
            return payload

        payload = copy.deepcopy(payload)
        messages = payload.setdefault("messages", [])

        block = MEMORY_HEADER + wakeup_text

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0].get("content", "") + block
        else:
            messages.insert(0, {"role": "system", "content": block.lstrip()})

        self._injected_traces[trace_id] = 0.0
        return payload
