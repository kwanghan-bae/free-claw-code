from pathlib import Path
from router.catalog.registry import Registry
from router.routing.policy import Policy
from router.routing.decide import build_fallback_chain

DATA = Path(__file__).resolve().parent.parent / "router" / "catalog" / "data"
POLICY = Path(__file__).resolve().parent.parent / "router" / "routing" / "policy.yaml"

def test_chain_for_coding_prefers_groq_first():
    registry = Registry.load_from_dir(DATA)
    policy = Policy.load(POLICY)
    chain = build_fallback_chain(registry, policy, task_type="coding", skill_id=None)
    first = chain[0]
    assert first.provider_id == "groq"
    assert first.model_id == "llama-3.3-70b-versatile"

def test_chain_empty_when_task_type_unknown():
    registry = Registry.load_from_dir(DATA)
    policy = Policy.load(POLICY)
    chain = build_fallback_chain(registry, policy, task_type="nope", skill_id=None)
    assert chain == []

def test_chain_has_correct_length():
    registry = Registry.load_from_dir(DATA)
    policy = Policy.load(POLICY)
    chain = build_fallback_chain(registry, policy, task_type="coding", skill_id=None)
    assert 1 <= len(chain) <= 4
