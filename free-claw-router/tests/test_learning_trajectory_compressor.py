import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from router.learning.trajectory_compressor import TrajectoryCompressor

MOCK_LLM_OUTPUT = json.dumps({
    "summary": "Refactored auth module",
    "decisions": [{"what": "Extract AuthService", "why": "SRP", "outcome": "success"}],
    "mistakes": [{"what": "Forgot imports", "lesson": "Run grep after extract"}],
    "reusable_patterns": [{"pattern": "Service extraction", "context": "Monolith > 500 LOC"}],
})

@pytest.mark.asyncio
async def test_compresses_transcript_to_structured_json():
    mock_llm = AsyncMock(return_value=MOCK_LLM_OUTPUT)
    mock_add = MagicMock()

    comp = TrajectoryCompressor(llm_fn=mock_llm, add_drawer_fn=mock_add)
    await comp.compress(trace_id="aabb", transcript="User: refactor\nAssistant: Done.", project_wing="proj")

    mock_add.assert_called_once()
    stored = mock_add.call_args.kwargs["content"]
    parsed = json.loads(stored)
    assert parsed["summary"] == "Refactored auth module"
    assert len(parsed["decisions"]) == 1
    assert mock_add.call_args.kwargs["wing"] == "proj"
    assert mock_add.call_args.kwargs["room"] == "trajectories"

@pytest.mark.asyncio
async def test_survives_llm_error():
    mock_llm = AsyncMock(side_effect=RuntimeError("down"))
    mock_add = MagicMock()
    comp = TrajectoryCompressor(llm_fn=mock_llm, add_drawer_fn=mock_add)
    await comp.compress(trace_id="ccdd", transcript="text", project_wing="proj")
    mock_add.assert_not_called()

@pytest.mark.asyncio
async def test_survives_unparseable_output():
    mock_llm = AsyncMock(return_value="not json")
    mock_add = MagicMock()
    comp = TrajectoryCompressor(llm_fn=mock_llm, add_drawer_fn=mock_add)
    await comp.compress(trace_id="eeff", transcript="text", project_wing="proj")
    mock_add.assert_not_called()
