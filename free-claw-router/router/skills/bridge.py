from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".free-claw-router" / "openspace.db"


class SkillsBridge:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path or DEFAULT_DB)
        self._store = None

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        from router.vendor.openspace_engine.store import SkillStore
        self._store = SkillStore(db_path=self._db_path)
        logger.info("OpenSpace skill store initialized at %s", self._db_path)

    @property
    def store(self):
        if self._store is None:
            raise RuntimeError("SkillsBridge not initialized")
        return self._store
