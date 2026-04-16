from router.skills.adapter import build_analysis_context

def test_build_analysis_context_formats_transcript():
    ctx = build_analysis_context(
        transcript="User: refactor auth\nAssistant: Done.",
        tool_outcomes=[
            {"tool": "bash", "success": True, "latency_ms": 50},
            {"tool": "edit", "success": False, "latency_ms": 200},
        ],
    )
    assert "refactor auth" in ctx
    assert "bash" in ctx
    assert "FAILED" in ctx

def test_build_analysis_context_handles_empty():
    ctx = build_analysis_context(transcript="", tool_outcomes=[])
    assert isinstance(ctx, str)
