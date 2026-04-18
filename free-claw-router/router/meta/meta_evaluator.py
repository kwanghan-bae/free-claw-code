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


# --- P5 B-4: consecutive-rollback auto-block tracking ---------------------------
# Counter state persisted alongside the P4 suggestion store. Two consecutive
# rollbacks on the same target_id auto-block further suggestions; a successful
# apply resets the counter. Manual unblock is exposed via POST /meta/unblock.

import json as _b4_json
from pathlib import Path as _B4_Path


def _b4_counter_path(store_dir) -> _B4_Path:
    return _B4_Path(store_dir) / "rollback_counters.json"


def _b4_load(store_dir) -> dict:
    p = _b4_counter_path(store_dir)
    if not p.exists():
        return {}
    try:
        return _b4_json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _b4_save(store_dir, data: dict) -> None:
    _B4_Path(store_dir).mkdir(parents=True, exist_ok=True)
    _b4_counter_path(store_dir).write_text(_b4_json.dumps(data), encoding="utf-8")


def record_rollback(target: str, store_dir) -> None:
    d = _b4_load(store_dir)
    d[target] = d.get(target, 0) + 1
    _b4_save(store_dir, d)
    if d[target] >= 2:
        _b4_emit_critical_alert(target, d[target])


def record_apply_success(target: str, store_dir) -> None:
    d = _b4_load(store_dir)
    d[target] = 0
    _b4_save(store_dir, d)


def is_blocked(target: str, store_dir) -> bool:
    return _b4_load(store_dir).get(target, 0) >= 2


def unblock(target: str, store_dir) -> None:
    d = _b4_load(store_dir)
    d[target] = 0
    _b4_save(store_dir, d)


def _b4_emit_critical_alert(target: str, count: int) -> None:
    """Best-effort critical alert emission. Import lazily to avoid import
    cycles if the telemetry middleware hasn't loaded yet.
    """
    try:
        from router.server._telemetry_middleware import emit_event
        emit_event(kind="meta_alert", payload={
            "level": "critical",
            "target": target,
            "rollback_count": count,
            "message": f"타깃 {target}: 연속 {count}회 롤백 — 자동 블록",
        })
    except Exception:
        pass  # Alert emission is best-effort; blocking logic still applies
