from router.learning.nudge_injector import NudgeInjector
from router.learning.nudge_cache import NudgeCache, Nudge

def test_injects_nudges_into_system_message():
    cache = NudgeCache()
    cache.push("t1", Nudge(nudge_type="memory_save", content="use GraphQL", source="rule", confidence=0.9))
    inj = NudgeInjector(cache=cache)
    payload = {"messages": [{"role": "system", "content": "You are helpful."}]}
    result = inj.inject(payload, trace_id="t1")
    assert "Learning Nudge" in result["messages"][0]["content"]
    assert "use GraphQL" in result["messages"][0]["content"]
    assert "mempalace_add_drawer" in result["messages"][0]["content"]

def test_no_injection_when_cache_empty():
    cache = NudgeCache()
    inj = NudgeInjector(cache=cache)
    payload = {"messages": [{"role": "system", "content": "You are helpful."}]}
    result = inj.inject(payload, trace_id="t1")
    assert "Learning Nudge" not in result["messages"][0]["content"]

def test_skill_create_nudge_suggests_delegate_task():
    cache = NudgeCache()
    cache.push("t1", Nudge(nudge_type="skill_create", content="pattern X", source="rule", confidence=0.8))
    inj = NudgeInjector(cache=cache)
    payload = {"messages": [{"role": "system", "content": "Base."}]}
    result = inj.inject(payload, trace_id="t1")
    assert "delegate-task" in result["messages"][0]["content"]

def test_pops_nudges_after_injection():
    cache = NudgeCache()
    cache.push("t1", Nudge(nudge_type="memory_save", content="X", source="rule", confidence=0.9))
    inj = NudgeInjector(cache=cache)
    inj.inject({"messages": [{"role": "system", "content": ""}]}, trace_id="t1")
    assert cache.peek("t1") == []
