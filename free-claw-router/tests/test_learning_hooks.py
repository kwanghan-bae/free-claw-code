from unittest.mock import MagicMock, AsyncMock
from router.learning.insight_generator import InsightGenerator
from router.learning.trajectory_compressor import TrajectoryCompressor

def test_insight_generator_callable_as_hook():
    mock_search = MagicMock(return_value={"results": [{"content": "s1"}, {"content": "s2"}, {"content": "s3"}]})
    mock_llm = AsyncMock(return_value="insight text")
    mock_add = MagicMock()
    gen = InsightGenerator(search_fn=mock_search, llm_fn=mock_llm, add_drawer_fn=mock_add)

    # Simulate calling as a hook (sync wrapper around async)
    import asyncio
    asyncio.run(gen.generate(project_wing="proj"))
    mock_add.assert_called_once()

def test_trajectory_compressor_callable_as_hook():
    mock_llm = AsyncMock(return_value='{"summary":"x","decisions":[],"mistakes":[],"reusable_patterns":[]}')
    mock_add = MagicMock()
    comp = TrajectoryCompressor(llm_fn=mock_llm, add_drawer_fn=mock_add)

    import asyncio
    asyncio.run(comp.compress(trace_id="aabb", transcript="User: hi\nAssist: hello", project_wing="proj"))
    mock_add.assert_called_once()
