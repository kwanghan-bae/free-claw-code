from __future__ import annotations
from dataclasses import dataclass
import time
from typing import Protocol
from router.telemetry.store import Store

@dataclass
class Evaluation:
    span_id: bytes
    evaluator: str
    score_dim: str
    score_value: float
    rationale: str | None = None

class Evaluator(Protocol):
    evaluator_id: str
    def evaluate(self, store: Store, span_id: bytes) -> list[Evaluation]: ...

class RuleEvaluator:
    evaluator_id = "rule"

    def evaluate(self, store: Store, span_id: bytes) -> list[Evaluation]:
        with store.connect() as c:
            row = c.execute("SELECT status FROM spans WHERE span_id=?", (span_id,)).fetchone()
        status = row[0] if row else None
        if status == "ok":
            return [Evaluation(span_id, self.evaluator_id, "format_correctness", 1.0, "status=ok")]
        if status and status.startswith("http_"):
            return [Evaluation(span_id, self.evaluator_id, "format_correctness", 0.0, f"status={status}")]
        return [Evaluation(span_id, self.evaluator_id, "format_correctness", 0.5, f"status={status}")]

def evaluate_span(store: Store, *, span_id: bytes, evaluators: list[Evaluator]) -> list[Evaluation]:
    out: list[Evaluation] = []
    now = int(time.time() * 1000)
    for ev in evaluators:
        for e in ev.evaluate(store, span_id):
            store.insert_evaluation(span_id=e.span_id, evaluator=e.evaluator, score_dim=e.score_dim,
                                    score_value=e.score_value, rationale=e.rationale, ts_ms=now)
            out.append(e)
    return out
