from __future__ import annotations
from typing import Any, Mapping, Optional
from router.catalog.schema import ModelSpec
from router.routing.affinity import affinity_bonus, lookup_affinity


def _base_score(task_type: str, tool_use: bool, context_window: int) -> float:
    base = 0.5
    if task_type == "tool_heavy" and tool_use:
        base += 0.2
    if task_type == "coding" and tool_use:
        base += 0.1
    if context_window >= 65536:
        base += 0.1
    return base


def static_score(model: ModelSpec, task_type: str, skill_id: str | None) -> float:
    """Legacy typed entrypoint (kept for existing call-sites).

    P5: applies the Bayesian-smoothed affinity bonus from the
    skill_model_affinity readmodel. Cold-start (0, 0) -> bonus 0, so
    behavior is unchanged until the readmodel carries data.
    """
    base = _base_score(task_type, model.tool_use, model.context_window)
    s, n = lookup_affinity(skill_id, model.model_id)
    return base + affinity_bonus(s, n)


def score_candidate(
    *,
    skill_id: Optional[str],
    model_id: str,
    task_type: str,
    capabilities: Mapping[str, Any],
) -> float:
    """Dict-shaped entrypoint used by the adaptive-routing layer.

    capabilities is a permissive mapping (usually the model's catalog
    entry as dict). Only context_window and tool_use are read here;
    extra keys are ignored.
    """
    tool_use = bool(capabilities.get("tool_use", False))
    ctx = int(capabilities.get("context_window", 0))
    base = _base_score(task_type, tool_use, ctx)
    s, n = lookup_affinity(skill_id, model_id)
    return base + affinity_bonus(s, n)
