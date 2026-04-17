from __future__ import annotations
from enum import Enum

EVAL_DEGRADATION_THRESHOLD = 0.15


class Verdict(str, Enum):
    KEEP = "keep"
    REVERT = "revert"
    INCONCLUSIVE = "inconclusive"


class MetaEvaluator:
    def __init__(self, degradation_threshold: float = EVAL_DEGRADATION_THRESHOLD) -> None:
        self._threshold = degradation_threshold

    def evaluate(self, pre: dict[str, float], post: dict[str, float]) -> Verdict:
        improved = 0
        degraded = 0
        for key in pre:
            if key not in post:
                continue
            pre_val = pre[key]
            post_val = post[key]
            if key == "mistake_count":
                # Lower is better
                delta = (pre_val - post_val) / max(pre_val, 1)
            else:
                # Higher is better
                delta = (post_val - pre_val) / max(pre_val, 0.01)

            if delta > self._threshold:
                improved += 1
            elif delta < -self._threshold:
                degraded += 1

        if degraded > 0 and improved == 0:
            return Verdict.REVERT
        if degraded > 0 and improved > 0:
            return Verdict.INCONCLUSIVE
        return Verdict.KEEP
