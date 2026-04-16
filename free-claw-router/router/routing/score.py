from __future__ import annotations
from router.catalog.schema import ModelSpec

def static_score(model: ModelSpec, task_type: str, skill_id: str | None) -> float:
    base = 0.5
    if task_type == "tool_heavy" and model.tool_use:
        base += 0.2
    if task_type == "coding" and model.tool_use:
        base += 0.1
    if model.context_window >= 65536:
        base += 0.1
    return base
