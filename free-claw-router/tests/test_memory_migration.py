from pathlib import Path
from router.telemetry.store import Store

def test_memory_tables_created_after_migration(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    with s.connect() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "wing_mappings" in names
    assert "mining_state" in names

def test_wing_mappings_crud(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    with s.connect() as c:
        c.execute("INSERT INTO wing_mappings(workspace_path, wing_name) VALUES(?, ?)",
                  ("/Users/joel/Desktop/git/free-claw-code", "free-claw-code"))
        row = c.execute("SELECT wing_name FROM wing_mappings WHERE workspace_path = ?",
                        ("/Users/joel/Desktop/git/free-claw-code",)).fetchone()
    assert row[0] == "free-claw-code"

def test_mining_state_crud(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    with s.connect() as c:
        c.execute("INSERT INTO mining_state(trace_id, last_mined_event_ts, last_mined_at) VALUES(?, ?, ?)",
                  (b"\x01" * 16, 1000, 2000))
        row = c.execute("SELECT last_mined_event_ts FROM mining_state WHERE trace_id = ?",
                        (b"\x01" * 16,)).fetchone()
    assert row[0] == 1000
