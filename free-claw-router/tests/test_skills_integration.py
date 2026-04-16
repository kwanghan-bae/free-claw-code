from pathlib import Path
from unittest.mock import MagicMock, patch
from router.skills.bridge import SkillsBridge
from router.skills.analyzer_hook import AnalyzerHook
from router.skills.adapter import build_analysis_context

def test_full_analysis_pipeline(tmp_path: Path):
    """End-to-end: bridge init -> analyzer hook -> context built."""
    bridge = SkillsBridge(db_path=tmp_path / "openspace.db")
    bridge.initialize()

    mock_telemetry = MagicMock()
    mock_telemetry.connect.return_value.__enter__ = MagicMock(
        return_value=MagicMock(execute=MagicMock(return_value=[]))
    )
    mock_telemetry.connect.return_value.__exit__ = MagicMock(return_value=False)

    hook = AnalyzerHook(
        bridge=bridge,
        build_context_fn=build_analysis_context,
        telemetry_store=mock_telemetry,
    )

    hook.on_session_mined(
        trace_id="aa" * 16,
        transcript="User: refactor the auth module\nAssistant: Done, refactored.",
        wing="test-project",
    )
    assert hook.last_analysis_trace == "aa" * 16

def test_bridge_survives_missing_db_dir(tmp_path: Path):
    deep = tmp_path / "a" / "b" / "c" / "openspace.db"
    bridge = SkillsBridge(db_path=deep)
    bridge.initialize()
    assert deep.exists()
