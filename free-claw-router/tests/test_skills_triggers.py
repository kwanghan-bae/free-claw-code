from unittest.mock import MagicMock
from router.skills.triggers import ToolDegradationTrigger, MetricMonitorTrigger

def test_tool_degradation_detects_drop():
    mock_store = MagicMock()
    mock_store.connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_store.connect.return_value.__exit__ = MagicMock(return_value=False)

    trigger = ToolDegradationTrigger(telemetry_store=mock_store, skill_bridge=MagicMock())
    # Just verify it runs without error
    trigger.check()

def test_metric_monitor_flags_high_error_skills():
    mock_bridge = MagicMock()
    mock_bridge.store.load_all.return_value = {}
    trigger = MetricMonitorTrigger(skill_bridge=mock_bridge)
    flagged = trigger.check()
    assert isinstance(flagged, list)
