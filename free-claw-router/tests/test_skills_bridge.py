from pathlib import Path
from router.skills.bridge import SkillsBridge

def test_bridge_creates_db(tmp_path: Path):
    b = SkillsBridge(db_path=tmp_path / "openspace.db")
    b.initialize()
    assert (tmp_path / "openspace.db").exists()

def test_bridge_provides_store(tmp_path: Path):
    b = SkillsBridge(db_path=tmp_path / "openspace.db")
    b.initialize()
    store = b.store
    assert store is not None
    # Store should have the skills table — load_all returns a dict
    skills = store.load_all()
    assert isinstance(skills, dict)
