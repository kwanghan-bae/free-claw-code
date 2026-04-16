import pytest
from unittest.mock import AsyncMock
from router.learning.batch_analyzer import BatchAnalyzer
from router.learning.nudge_cache import ConversationBuffer

@pytest.mark.asyncio
async def test_analyze_returns_nudges_from_llm():
    buf = ConversationBuffer()
    for i in range(5):
        buf.append_user("t1", f"user message {i}")
        buf.append_assistant("t1", f"assistant response {i}")

    mock_llm = AsyncMock(return_value='[{"nudge_type":"memory_save","content":"important pattern","confidence":0.8}]')
    analyzer = BatchAnalyzer(llm_fn=mock_llm)
    nudges = await analyzer.analyze("t1", buf)
    assert len(nudges) >= 1
    assert nudges[0].nudge_type == "memory_save"
    assert nudges[0].source == "batch"

@pytest.mark.asyncio
async def test_analyze_returns_empty_on_llm_error():
    buf = ConversationBuffer()
    buf.append_user("t1", "hi")
    mock_llm = AsyncMock(side_effect=RuntimeError("quota exhausted"))
    analyzer = BatchAnalyzer(llm_fn=mock_llm)
    nudges = await analyzer.analyze("t1", buf)
    assert nudges == []

@pytest.mark.asyncio
async def test_analyze_returns_empty_on_unparseable_output():
    buf = ConversationBuffer()
    buf.append_user("t1", "hi")
    mock_llm = AsyncMock(return_value="not json at all")
    analyzer = BatchAnalyzer(llm_fn=mock_llm)
    nudges = await analyzer.analyze("t1", buf)
    assert nudges == []
