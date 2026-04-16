from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    workspace: str
    last_activity: float
    mined_close: bool = False
    idle_mined: bool = False


class SessionCloseDetector:
    def __init__(
        self,
        *,
        close_timeout_seconds: int = 300,
        idle_threshold_seconds: int = 1800,
        miner,  # MemoryMiner
        transcript_fn: Callable[[str], str],  # (trace_id) -> transcript text
        wakeup_invalidate_fn: Callable[[str], None],
        wing_resolve_fn: Callable[[str], str],  # workspace -> wing
    ) -> None:
        self._close_timeout = close_timeout_seconds
        self._idle_threshold = idle_threshold_seconds
        self._miner = miner
        self._transcript_fn = transcript_fn
        self._wakeup_invalidate = wakeup_invalidate_fn
        self._wing_resolve = wing_resolve_fn
        self._sessions: dict[str, _SessionState] = {}

    def record_activity(self, trace_id: str, workspace: str) -> None:
        if trace_id in self._sessions:
            self._sessions[trace_id].last_activity = time.time()
            self._sessions[trace_id].idle_mined = False  # reset on new activity
        else:
            self._sessions[trace_id] = _SessionState(
                workspace=workspace, last_activity=time.time()
            )

    def check_and_mine(self) -> None:
        now = time.time()
        to_remove: list[str] = []
        for trace_id, state in self._sessions.items():
            gap = now - state.last_activity
            if gap >= self._close_timeout and not state.mined_close:
                self._do_mine(trace_id, state, reason="close")
                state.mined_close = True
                to_remove.append(trace_id)
            elif gap >= self._idle_threshold and not state.idle_mined and not state.mined_close:
                self._do_mine(trace_id, state, reason="idle")
                state.idle_mined = True
                self._wakeup_invalidate(self._wing_resolve(state.workspace))
        for tid in to_remove:
            self._sessions.pop(tid, None)

    def _do_mine(self, trace_id: str, state: _SessionState, *, reason: str) -> None:
        try:
            transcript = self._transcript_fn(trace_id)
            if not transcript.strip():
                return
            wing = self._wing_resolve(state.workspace)
            self._miner.mine_session(transcript, project_wing=wing)
            logger.info("mined session %s (reason=%s, wing=%s)", trace_id[:8], reason, wing)
        except Exception:
            logger.warning("mining failed for %s", trace_id[:8], exc_info=True)
