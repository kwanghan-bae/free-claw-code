from unittest.mock import MagicMock
from router.skills.analyzer_hook import AnalyzerHook

def test_hook_calls_analyzer_with_transcript():
    mock_bridge = MagicMock()
    mock_adapter = MagicMock(return_value="formatted context")
    mock_telemetry = MagicMock()
    mock_telemetry.connect.return_value.__enter__ = MagicMock(
        return_value=MagicMock(execute=MagicMock(return_value=[]))
    )
    mock_telemetry.connect.return_value.__exit__ = MagicMock(return_value=False)

    hook = AnalyzerHook(bridge=mock_bridge, build_context_fn=mock_adapter, telemetry_store=mock_telemetry)
    hook.on_session_mined(trace_id="aabb" * 8, transcript="User: hi\nAssistant: hello", wing="proj")

    mock_adapter.assert_called_once()
    # The hook should have attempted to analyze (even if analyzer is mocked)
    assert hook.last_analysis_trace == "aabb" * 8

def test_hook_survives_analyzer_error():
    mock_bridge = MagicMock()
    mock_bridge.store.load_all.side_effect = RuntimeError("db locked")
    mock_adapter = MagicMock(side_effect=RuntimeError("boom"))
    mock_telemetry = MagicMock()
    mock_telemetry.connect.return_value.__enter__ = MagicMock(
        return_value=MagicMock(execute=MagicMock(return_value=[]))
    )
    mock_telemetry.connect.return_value.__exit__ = MagicMock(return_value=False)

    hook = AnalyzerHook(bridge=mock_bridge, build_context_fn=mock_adapter, telemetry_store=mock_telemetry)
    hook.on_session_mined(trace_id="ccdd" * 8, transcript="text", wing="proj")
    # Should not raise — the hook catches exceptions
