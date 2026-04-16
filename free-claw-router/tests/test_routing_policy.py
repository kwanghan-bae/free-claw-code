from pathlib import Path
from router.routing.policy import Policy

POLICY = Path(__file__).resolve().parent.parent / "router" / "routing" / "policy.yaml"

def test_policy_loads_and_has_five_task_types():
    p = Policy.load(POLICY)
    assert set(p.task_types()) >= {"planning", "coding", "tool_heavy", "summary", "chat"}

def test_policy_priority_is_list_of_pairs():
    p = Policy.load(POLICY)
    first = p.priority_for("coding")[0]
    assert isinstance(first, tuple) and len(first) == 2

def test_policy_fallback_any_flag_present():
    p = Policy.load(POLICY)
    assert p.fallback_any("coding") in (True, False)
