from router.routing.hints import classify_task_hint

def test_planning_keywords():
    assert classify_task_hint("design the new auth flow") == "planning"

def test_coding_keywords():
    assert classify_task_hint("refactor the module") == "coding"
    assert classify_task_hint("add unit tests for X") == "coding"

def test_tool_heavy_keywords():
    assert classify_task_hint("execute the shell command") == "tool_heavy"
    assert classify_task_hint("grep for FIXME everywhere") == "tool_heavy"

def test_summary_keywords():
    assert classify_task_hint("summarize the README") == "summary"

def test_default_is_chat():
    assert classify_task_hint("hello") == "chat"

def test_runtime_not_confused_with_run():
    assert classify_task_hint("summarize the runtime logs") == "summary"
