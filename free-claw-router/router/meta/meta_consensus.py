from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from .meta_suggestions import MetaSuggestion


@dataclass
class EditPlan:
    target_file: str
    edit_type: str
    direction: str
    proposed_diff: str
    supporting_ids: list[str] = field(default_factory=list)
    avg_confidence: float = 0.0


def build_edit_plans(
    suggestions: list[MetaSuggestion],
    *,
    min_votes: int = 3,
    daily_cap: int = 2,
) -> list[EditPlan]:
    groups: dict[tuple[str, str], list[MetaSuggestion]] = defaultdict(list)
    for s in suggestions:
        key = (s.target_file, s.direction)
        groups[key].append(s)

    plans: list[EditPlan] = []
    for (target, direction), members in groups.items():
        if len(members) < min_votes:
            continue
        avg_conf = sum(m.confidence for m in members) / len(members)
        plans.append(EditPlan(
            target_file=target,
            edit_type=members[0].edit_type,
            direction=direction,
            proposed_diff=members[0].proposed_diff,
            supporting_ids=[m.id for m in members],
            avg_confidence=avg_conf,
        ))

    plans.sort(key=lambda p: p.avg_confidence, reverse=True)
    return plans[:daily_cap]
