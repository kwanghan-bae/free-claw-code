import time
from unittest.mock import MagicMock, patch
from router.memory.idle_detector import SessionCloseDetector

def test_detects_session_close_after_timeout():
    miner = MagicMock()
    transcript_fn = MagicMock(return_value="User: hi\nAssistant: hello")
    detector = SessionCloseDetector(
        close_timeout_seconds=1,
        miner=miner,
        transcript_fn=transcript_fn,
        wakeup_invalidate_fn=lambda w: None,
        wing_resolve_fn=lambda t: "proj",
    )
    detector.record_activity(trace_id="t1", workspace="/a/b/proj")
    time.sleep(1.5)
    detector.check_and_mine()
    miner.mine_session.assert_called_once()
    assert "hi" in miner.mine_session.call_args[0][0]

def test_does_not_mine_active_session():
    miner = MagicMock()
    detector = SessionCloseDetector(
        close_timeout_seconds=300,
        miner=miner,
        transcript_fn=MagicMock(return_value=""),
        wakeup_invalidate_fn=lambda w: None,
        wing_resolve_fn=lambda t: "proj",
    )
    detector.record_activity(trace_id="t1", workspace="/a/b/proj")
    detector.check_and_mine()
    miner.mine_session.assert_not_called()
