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

    Returns (0, 0) if skill_id is None or the readmodel has no data for
    this pair. That (0, 0) short-circuits cold-start logic in affinity_bonus.
    """
    if skill_id is None:
        return (0, 0)
    try:
        from router.telemetry.readmodel.skill_model_affinity import get_pair_stats
        return get_pair_stats(skill_id=skill_id, model_id=model_id, window_days=30)
    except (ImportError, AttributeError):
        # readmodel not available (e.g. first-run, migrations not applied) -> cold-start
        return (0, 0)
    except Exception:
        # any other readmodel issue -> cold-start (fail-open for routing)
        return (0, 0)
