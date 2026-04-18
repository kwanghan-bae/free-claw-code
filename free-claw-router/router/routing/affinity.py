"""Bayesian smoothing of (skill, model) success rates for adaptive routing.

affinity_bonus is in [clip_lo, clip_hi] and is added to the base score in
routing/score.py. Params are registered in meta_targets.yaml as
config_only so the P4 meta-evolution pipeline can self-tune them
within bounded ranges.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

# P4-editable knobs (config_only in meta_targets.yaml)
AFFINITY_WEIGHT: float = 0.3
PRIOR_N: int = 10
CLIP_LO: float = -0.15
CLIP_HI: float = 0.15


@dataclass(frozen=True)
class AffinityConfig:
    weight: float = AFFINITY_WEIGHT
    prior_n: int = PRIOR_N
    clip: tuple[float, float] = (CLIP_LO, CLIP_HI)


def affinity_bonus(successes: int, samples: int, cfg: Optional[AffinityConfig] = None) -> float:
    """Compute the affinity bonus as a Bayesian-smoothed, clipped deviation from 0.5.

    Cold-start safety: PRIOR_N acts as a virtual sample count at 0.5 prior,
    so tiny observed samples can't dominate. Clipping prevents any single
    (skill, model) pair from capturing routing entirely.
    """
    cfg = cfg or AffinityConfig()
    denom = samples + cfg.prior_n
    if denom <= 0:
        return 0.0
    adjusted = (successes + 0.5 * cfg.prior_n) / denom
    raw = (adjusted - 0.5) * cfg.weight
    return max(cfg.clip[0], min(cfg.clip[1], raw))


def lookup_affinity(skill_id: Optional[str], model_id: str) -> tuple[int, int]:
    """Read (successes, samples) from the skill_model_affinity readmodel.

    The canonical readmodel (router/telemetry/readmodels.py) returns
    rows shaped like ``{skill_id, model_id, trials, success_rate, avg_score}``.
    We derive ``(successes, samples) = (round(trials * success_rate), trials)``.

    Returns (0, 0) if skill_id is None, the readmodel has no data for
    this (skill, model) pair, or any error occurs (fail-open so routing
    is never blocked by telemetry unavailability).
    """
    if skill_id is None:
        return (0, 0)
    try:
        import os
        from pathlib import Path
        from router.telemetry.readmodels import skill_model_affinity
        from router.telemetry.store import Store

        # Resolve telemetry db path. Mirrors router.server.meta_report._data_dir:
        # FCR_DATA_DIR override (tests) -> ~/.free-claw-router (production).
        data_dir = Path(os.getenv("FCR_DATA_DIR") or (Path.home() / ".free-claw-router"))
        db_path = data_dir / "telemetry.db"
        if not db_path.exists():
            return (0, 0)

        store = Store(path=db_path)
        rows = skill_model_affinity(store, skill_id=skill_id)
        for row in rows:
            if row.get("model_id") == model_id:
                trials = int(row.get("trials", 0) or 0)
                rate = float(row.get("success_rate", 0.0) or 0.0)
                successes = int(round(trials * rate))
                return (successes, trials)
        return (0, 0)
    except Exception:
        # any readmodel issue -> cold-start (fail-open for routing)
        return (0, 0)
