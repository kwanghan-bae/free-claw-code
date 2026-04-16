from __future__ import annotations
from dataclasses import dataclass
from router.catalog.registry import Registry
from router.catalog.schema import ModelSpec
from router.routing.policy import Policy
from router.routing.score import static_score

@dataclass
class Candidate:
    provider_id: str
    model_id: str
    model: ModelSpec
    score: float

def build_fallback_chain(
    registry: Registry,
    policy: Policy,
    *,
    task_type: str,
    skill_id: str | None,
    max_chain: int = 4,
) -> list[Candidate]:
    if task_type not in policy.task_types():
        return []

    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []

    for provider_id, model_id in policy.priority_for(task_type):
        hit = registry.find_model(model_id)
        if not hit:
            continue
        prov, model = hit
        if prov.provider_id != provider_id:
            continue
        out.append(Candidate(
            provider_id=provider_id,
            model_id=model_id,
            model=model,
            score=static_score(model, task_type, skill_id),
        ))
        seen.add((provider_id, model_id))
        if len(out) >= max_chain:
            return out

    if policy.fallback_any(task_type):
        for prov, model in registry.find_models_for(task_type=task_type):
            key = (prov.provider_id, model.model_id)
            if key in seen:
                continue
            out.append(Candidate(
                provider_id=prov.provider_id,
                model_id=model.model_id,
                model=model,
                score=static_score(model, task_type, skill_id),
            ))
            if len(out) >= max_chain:
                break

    return out
