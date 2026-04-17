import pytest
from unittest.mock import AsyncMock
from router.meta.meta_analyzer import MetaAnalyzer
from router.meta.meta_suggestions import MetaSuggestion

SAMPLE_TRAJECTORY = {
    "session_id": "aabb",
    "summary": "Refactored auth",
    "decisions": [{"what": "Use REST", "why": "simpler", "outcome": "success"}],
    "mistakes": [{"what": "Wrong model for tool calls", "lesson": "Groq is better for tools"}],
    "reusable_patterns": [],
    "model_performance": {"groq/llama-3.3-70b-versatile": {"turns": 8, "tool_success_rate": 0.95},
                          "openrouter/z-ai/glm-4.6:free": {"turns": 4, "tool_success_rate": 0.62}},
}

@pytest.mark.asyncio
async def test_analyzer_generates_suggestions_from_trajectory():
    mock_llm = AsyncMock(return_value='[{"target_file":"router/routing/policy.yaml","edit_type":"yaml","direction":"promote groq for tool_heavy","rationale":"95% vs 62%","confidence":0.85,"proposed_diff":"tool_heavy.priority[0]=[groq,llama-3.3-70b-versatile]"}]')
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=None)
    suggestions = await analyzer.analyze(trace_id="aabb", trajectory=SAMPLE_TRAJECTORY)
    assert len(suggestions) >= 1
    assert suggestions[0].target_file == "router/routing/policy.yaml"

@pytest.mark.asyncio
async def test_analyzer_returns_empty_on_error():
    mock_llm = AsyncMock(side_effect=RuntimeError("down"))
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=None)
    suggestions = await analyzer.analyze(trace_id="ccdd", trajectory={})
    assert suggestions == []

@pytest.mark.asyncio
async def test_analyzer_filters_invalid_targets():
    mock_llm = AsyncMock(return_value='[{"target_file":"INVALID_FILE","edit_type":"yaml","direction":"x","rationale":"y","confidence":0.9,"proposed_diff":"z"}]')
    from pathlib import Path
    targets_path = Path(__file__).resolve().parent.parent / "router" / "meta" / "meta_targets.yaml"
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=targets_path)
    suggestions = await analyzer.analyze(trace_id="eeff", trajectory=SAMPLE_TRAJECTORY)
    assert suggestions == []
