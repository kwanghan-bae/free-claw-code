import pytest
from unittest.mock import AsyncMock, MagicMock
from router.learning.insight_generator import InsightGenerator

@pytest.mark.asyncio
async def test_generates_insights_from_recent_sessions():
    mock_search = MagicMock(return_value={"results": [
        {"content": "Session 1: refactored auth"},
        {"content": "Session 2: fixed caching bug"},
        {"content": "Session 3: added GraphQL endpoint"},
    ]})
    mock_llm = AsyncMock(return_value="- You tend to skip tests after refactoring\n- Good at isolating bugs quickly")
    mock_add = MagicMock()

    gen = InsightGenerator(search_fn=mock_search, llm_fn=mock_llm, add_drawer_fn=mock_add)
    await gen.generate(project_wing="myproj")

    mock_llm.assert_called_once()
    mock_add.assert_called_once()
    assert mock_add.call_args.kwargs["wing"] == "user"
    assert mock_add.call_args.kwargs["room"] == "insights"

@pytest.mark.asyncio
async def test_skips_when_too_few_sessions():
    mock_search = MagicMock(return_value={"results": [{"content": "only one"}]})
    mock_llm = AsyncMock()
    mock_add = MagicMock()

    gen = InsightGenerator(search_fn=mock_search, llm_fn=mock_llm, add_drawer_fn=mock_add, min_sessions=3)
    await gen.generate(project_wing="proj")

    mock_llm.assert_not_called()
    mock_add.assert_not_called()
