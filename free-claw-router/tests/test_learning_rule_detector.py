from router.learning.rule_detector import RuleDetector
from router.learning.nudge_cache import Nudge

def test_detects_decision_keyword():
    d = RuleDetector()
    nudges = d.scan("We decided to use GraphQL for the API layer.")
    assert any(n.nudge_type == "memory_save" for n in nudges)
    assert any("GraphQL" in n.content for n in nudges)

def test_detects_lesson_keyword():
    d = RuleDetector()
    nudges = d.scan("The bug was caused by stale cache entries.")
    assert any(n.nudge_type == "memory_save" for n in nudges)

def test_detects_explicit_remember():
    d = RuleDetector()
    nudges = d.scan("Remember that the API rate-limits at 100 rpm.")
    assert len(nudges) >= 1

def test_no_nudge_for_plain_response():
    d = RuleDetector()
    nudges = d.scan("Here is the refactored code:\n```python\ndef foo(): pass\n```")
    assert nudges == []

def test_code_repeat_detection():
    d = RuleDetector()
    block = "```python\ndef setup_db(): pass\n```"
    d.record_code_block("t1", block)
    d.record_code_block("t1", block)
    nudges = d.check_repeats("t1", block)
    assert nudges == []  # only 2, need 3
    d.record_code_block("t1", block)
    nudges = d.check_repeats("t1", block)
    assert any(n.nudge_type == "skill_create" for n in nudges)

def test_consecutive_tool_failures():
    d = RuleDetector()
    d.record_tool_result("t1", success=False)
    d.record_tool_result("t1", success=False)
    assert d.check_tool_failures("t1") == []
    d.record_tool_result("t1", success=False)
    nudges = d.check_tool_failures("t1")
    assert any(n.nudge_type == "skill_fix" for n in nudges)
