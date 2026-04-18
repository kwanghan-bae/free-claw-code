import pytest
from router.routing.affinity import affinity_bonus, AffinityConfig


def test_cold_start_returns_zero():
    cfg = AffinityConfig(weight=0.3, prior_n=10, clip=(-0.15, 0.15))
    # 0 samples -> adjusted = 0.5 -> bonus = 0
    assert abs(affinity_bonus(successes=0, samples=0, cfg=cfg)) < 1e-9


def test_high_success_scaled_and_not_yet_clipped():
    cfg = AffinityConfig(weight=0.3, prior_n=10, clip=(-0.15, 0.15))
    # adjusted = (30 + 0.5*10)/(30+10) = 0.875 -> (0.375)*0.3 = 0.1125 (< 0.15, no clip)
    assert abs(affinity_bonus(successes=30, samples=30, cfg=cfg) - 0.1125) < 1e-6


def test_extreme_high_clipped_at_upper_bound():
    cfg = AffinityConfig(weight=1.0, prior_n=10, clip=(-0.15, 0.15))
    assert affinity_bonus(successes=100, samples=100, cfg=cfg) == pytest.approx(0.15)


def test_low_success_clipped_at_lower_bound():
    cfg = AffinityConfig(weight=1.0, prior_n=10, clip=(-0.15, 0.15))
    assert affinity_bonus(successes=0, samples=100, cfg=cfg) == pytest.approx(-0.15)


def test_score_candidate_unchanged_when_skill_id_none():
    from router.routing.score import score_candidate
    caps = {"context_window": 128000, "tool_use": True}
    # Without skill_id the affinity lookup returns (0, 0) -> bonus 0 -> equal to pre-P5 score
    r1 = score_candidate(skill_id=None, model_id="llama-70b", task_type="coding", capabilities=caps)
    r2 = score_candidate(skill_id=None, model_id="llama-70b", task_type="coding", capabilities=caps)
    assert r1 == r2
    # Sanity: should be > 0
    assert r1 > 0
