from pathlib import Path
from router.memory.wing_manager import WingManager
from router.telemetry.store import Store

def test_resolve_extracts_basename(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    assert wm.resolve("/Users/joel/Desktop/git/free-claw-code") == "free-claw-code"

def test_resolve_persists_mapping(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    wm.resolve("/Users/joel/Desktop/git/free-claw-code")
    wm2 = WingManager(store=s)
    assert wm2.resolve("/Users/joel/Desktop/git/free-claw-code") == "free-claw-code"

def test_resolve_returns_default_when_no_workspace(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    assert wm.resolve(None) == "default"
    assert wm.resolve("") == "default"

def test_user_wing_is_always_user(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    assert wm.user_wing == "user"
