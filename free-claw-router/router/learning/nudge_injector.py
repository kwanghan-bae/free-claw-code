from __future__ import annotations
import copy
from .nudge_cache import NudgeCache, Nudge

_ICON = {"memory_save": "\U0001f4be", "skill_create": "\U0001f527", "skill_fix": "\u2699\ufe0f"}
_ACTION = {
    "memory_save": "call mempalace_add_drawer(wing=project, room=decisions, content=...)",
    "skill_create": "call delegate-task to create a reusable skill",
    "skill_fix": "call delegate-task to fix the failing skill",
}


class NudgeInjector:
    def __init__(self, cache: NudgeCache) -> None:
        self._cache = cache

    def inject(self, payload: dict, *, trace_id: str) -> dict:
        nudges = self._cache.pop_all(trace_id)
        if not nudges:
            return payload
        payload = copy.deepcopy(payload)
        block = self._format(nudges)
        messages = payload.setdefault("messages", [])
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0].get("content", "") + block
        else:
            messages.insert(0, {"role": "system", "content": block.lstrip()})
        return payload

    def _format(self, nudges: list[Nudge]) -> str:
        lines = ["\n\n## Learning Nudges\n"]
        for n in nudges:
            icon = _ICON.get(n.nudge_type, "")
            action = _ACTION.get(n.nudge_type, "")
            lines.append(f"- {icon} **{n.nudge_type}**: {n.content}")
            if action:
                lines.append(f"  -> {action}")
        return "\n".join(lines) + "\n"
