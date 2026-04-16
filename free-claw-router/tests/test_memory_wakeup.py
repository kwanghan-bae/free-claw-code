import time
from unittest.mock import MagicMock, patch
from router.memory.wakeup import WakeupService

def test_wakeup_combines_project_and_user_wings():
    mock_palace = MagicMock()
    mock_palace.wake_up.side_effect = lambda wing=None: f"[wake:{wing}]"
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        result = svc.get_wakeup("free-claw-code")
    assert "[wake:free-claw-code]" in result
    assert "[wake:user]" in result

def test_wakeup_caches_within_ttl():
    mock_palace = MagicMock()
    call_count = 0
    def fake_wake_up(wing=None):
        nonlocal call_count
        call_count += 1
        return f"[wake:{wing}:{call_count}]"
    mock_palace.wake_up.side_effect = fake_wake_up
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        r1 = svc.get_wakeup("proj")
        r2 = svc.get_wakeup("proj")
    assert r1 == r2
    assert call_count == 2  # project + user, called once each

def test_wakeup_invalidate_clears_cache():
    mock_palace = MagicMock()
    mock_palace.wake_up.return_value = "text"
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        svc.get_wakeup("proj")
        svc.invalidate("proj")
        svc.get_wakeup("proj")
    assert mock_palace.wake_up.call_count == 4  # 2 initial + 2 after invalidate

def test_wakeup_returns_empty_on_error():
    mock_palace = MagicMock()
    mock_palace.wake_up.side_effect = RuntimeError("chromadb down")
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        result = svc.get_wakeup("proj")
    assert result == ""
