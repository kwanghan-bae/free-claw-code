import time
from router.learning.nudge_cache import NudgeCache, Nudge, ConversationBuffer

def test_push_and_pop_nudges():
    c = NudgeCache()
    c.push("t1", Nudge(nudge_type="memory_save", content="decided to use GraphQL", source="rule", confidence=0.9))
    c.push("t1", Nudge(nudge_type="skill_create", content="graphql-schema pattern", source="rule", confidence=0.7))
    nudges = c.pop_all("t1")
    assert len(nudges) == 2
    assert c.pop_all("t1") == []

def test_max_5_nudges_keeps_highest_confidence():
    c = NudgeCache(max_per_trace=5)
    for i in range(8):
        c.push("t1", Nudge(nudge_type="memory_save", content=f"item {i}", source="rule", confidence=i * 0.1))
    nudges = c.peek("t1")
    assert len(nudges) == 5
    assert all(n.confidence >= 0.3 for n in nudges)

def test_expired_nudges_are_dropped():
    c = NudgeCache(max_per_trace=5, ttl_seconds=0)
    c.push("t1", Nudge(nudge_type="memory_save", content="old", source="rule", confidence=0.5))
    time.sleep(0.01)
    assert c.pop_all("t1") == []

def test_conversation_buffer_tracks_turns():
    b = ConversationBuffer()
    b.append_user("t1", "hello")
    b.append_assistant("t1", "hi there")
    b.append_user("t1", "refactor auth")
    assert b.turn_count("t1") == 3
    recent = b.recent("t1", n=2)
    assert len(recent) == 2
    assert recent[-1]["content"] == "refactor auth"

def test_conversation_buffer_empty_trace():
    b = ConversationBuffer()
    assert b.recent("nope") == []
    assert b.turn_count("nope") == 0
