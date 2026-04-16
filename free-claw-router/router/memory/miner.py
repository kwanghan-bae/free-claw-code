from __future__ import annotations
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_PALACE_PATH = os.environ.get("MEMPALACE_PALACE_PATH", os.path.expanduser("~/.mempalace/palace"))


def mine_convos(convo_dir, palace_path, wing=None, **kw):
    from mempalace.convo_miner import mine_convos as _mine
    _mine(convo_dir, palace_path, wing=wing, **kw)


def extract_memories(text, **kw):
    from mempalace.general_extractor import extract_memories as _extract
    return _extract(text, **kw)


def _add_drawer(wing: str, room: str, content: str, palace_path: str):
    from mempalace.mcp_server import tool_add_drawer
    tool_add_drawer(wing=wing, room=room, content=content, source_file="auto-mining")


_ROOM_MAP = {
    "decision": "decisions",
    "problem": "problems",
    "milestone": "milestones",
    "preference": "preferences",
    "emotion": "conversations",
}


class MemoryMiner:
    def __init__(self, palace_path: str | None = None) -> None:
        self._palace_path = palace_path or _PALACE_PATH

    def mine_session(self, transcript: str, *, project_wing: str) -> None:
        if not transcript.strip():
            return
        self._mine_convos(transcript, project_wing)
        self._mine_general(transcript, project_wing)

    def _mine_convos(self, transcript: str, project_wing: str) -> None:
        try:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "session.md"
                p.write_text(transcript)
                mine_convos(td, self._palace_path, wing=project_wing)
        except Exception:
            logger.warning("convos mining failed", exc_info=True)

    def _mine_general(self, transcript: str, project_wing: str) -> None:
        try:
            memories = extract_memories(transcript)
        except Exception:
            logger.warning("general extraction failed", exc_info=True)
            return
        for mem in memories:
            mem_type = mem.get("memory_type", "")
            content = mem.get("content", "")
            if not content.strip():
                continue
            room = _ROOM_MAP.get(mem_type, "conversations")
            wing = "user" if mem_type == "preference" else project_wing
            try:
                _add_drawer(wing=wing, room=room, content=content, palace_path=self._palace_path)
            except Exception:
                logger.warning("add_drawer failed for %s/%s", wing, room, exc_info=True)
