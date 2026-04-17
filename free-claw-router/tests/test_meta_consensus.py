from router.meta.meta_consensus import build_edit_plans, EditPlan
from router.meta.meta_suggestions import MetaSuggestion

def _sug(target, direction, trace="t", confidence=0.8):
    return MetaSuggestion(trace_id=trace, target_file=target, edit_type="yaml",
                          direction=direction, rationale="r", confidence=confidence, proposed_diff="d")

def test_consensus_reached_with_3_matching():
    suggestions = [_sug("policy.yaml", "promote groq", f"t{i}") for i in range(3)]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert len(plans) == 1
    assert plans[0].target_file == "policy.yaml"
    assert len(plans[0].supporting_ids) == 3

def test_no_consensus_with_2():
    suggestions = [_sug("policy.yaml", "promote groq", f"t{i}") for i in range(2)]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert plans == []

def test_different_directions_not_grouped():
    suggestions = [
        _sug("policy.yaml", "promote groq", "t1"),
        _sug("policy.yaml", "promote groq", "t2"),
        _sug("policy.yaml", "demote groq", "t3"),
    ]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert plans == []

def test_multiple_targets_independent():
    suggestions = [
        _sug("policy.yaml", "promote groq", "t1"),
        _sug("policy.yaml", "promote groq", "t2"),
        _sug("policy.yaml", "promote groq", "t3"),
        _sug("triggers.py", "lower threshold", "t1"),
        _sug("triggers.py", "lower threshold", "t2"),
    ]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert len(plans) == 1
    assert plans[0].target_file == "policy.yaml"

def test_daily_cap():
    suggestions = [_sug(f"file{i}.yaml", "change", f"t{j}") for i in range(5) for j in range(3)]
    plans = build_edit_plans(suggestions, min_votes=3, daily_cap=2)
    assert len(plans) <= 2
