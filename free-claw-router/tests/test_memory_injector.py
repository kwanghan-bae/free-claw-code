from router.memory.injector import Injector

def _make_payload(system_content="You are helpful.", user_content="hello"):
    return {
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
    }

def test_injects_on_first_request_for_trace():
    inj = Injector(wakeup_fn=lambda wing: f"[memory:{wing}]")
    payload = _make_payload()
    result = inj.maybe_inject(payload, trace_id="t1", workspace="/a/b/myproject", last_request_gap_seconds=0)
    assert "## Memory Context" in result["messages"][0]["content"]
    assert "[memory:myproject]" in result["messages"][0]["content"]

def test_skips_on_repeat_request_same_trace():
    inj = Injector(wakeup_fn=lambda wing: "[mem]")
    inj.maybe_inject(_make_payload(), trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=0)
    payload2 = _make_payload()
    result = inj.maybe_inject(payload2, trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=5)
    assert "## Memory Context" not in result["messages"][0]["content"]

def test_reinjects_after_idle_gap():
    inj = Injector(wakeup_fn=lambda wing: "[refreshed]", idle_threshold_seconds=1800)
    inj.maybe_inject(_make_payload(), trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=0)
    payload2 = _make_payload()
    result = inj.maybe_inject(payload2, trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=2000)
    assert "[refreshed]" in result["messages"][0]["content"]

def test_creates_system_message_if_missing():
    inj = Injector(wakeup_fn=lambda wing: "[mem]")
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    result = inj.maybe_inject(payload, trace_id="t2", workspace="/a/b/p", last_request_gap_seconds=0)
    assert result["messages"][0]["role"] == "system"
    assert "[mem]" in result["messages"][0]["content"]

def test_returns_unmodified_when_wakeup_empty():
    inj = Injector(wakeup_fn=lambda wing: "")
    payload = _make_payload()
    result = inj.maybe_inject(payload, trace_id="t3", workspace="/a/b/p", last_request_gap_seconds=0)
    assert "## Memory Context" not in result["messages"][0]["content"]
