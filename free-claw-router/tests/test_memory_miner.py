import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from router.memory.miner import MemoryMiner

def test_mine_session_calls_convos_and_general():
    calls = []
    def fake_mine_convos(convo_dir, palace_path, wing=None, **kw):
        calls.append(("convos", wing))
    def fake_extract(text, **kw):
        calls.append(("general", None))
        return [
            {"content": "decided to use REST", "memory_type": "decision", "chunk_index": 0},
            {"content": "prefers TDD", "memory_type": "preference", "chunk_index": 1},
        ]
    mock_add = MagicMock()

    with patch("router.memory.miner.mine_convos", fake_mine_convos), \
         patch("router.memory.miner.extract_memories", fake_extract), \
         patch("router.memory.miner._add_drawer", mock_add):
        m = MemoryMiner(palace_path="/tmp/palace")
        m.mine_session("This is a test transcript.", project_wing="myproj")

    assert ("convos", "myproj") in calls
    assert ("general", None) in calls
    # preferences go to user wing
    user_calls = [c for c in mock_add.call_args_list if c.kwargs.get("wing") == "user"]
    assert len(user_calls) >= 1

def test_mine_session_handles_empty_transcript():
    m = MemoryMiner(palace_path="/tmp/palace")
    m.mine_session("", project_wing="proj")  # should not raise

def test_mine_session_handles_extraction_error():
    with patch("router.memory.miner.mine_convos", side_effect=RuntimeError("fail")), \
         patch("router.memory.miner.extract_memories", return_value=[]):
        m = MemoryMiner(palace_path="/tmp/palace")
        m.mine_session("some text", project_wing="proj")  # should not raise
