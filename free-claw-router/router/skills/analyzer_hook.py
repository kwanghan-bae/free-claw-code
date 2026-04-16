from __future__ import annotations
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class AnalyzerHook:
    def __init__(self, *, bridge, build_context_fn: Callable, telemetry_store) -> None:
        self._bridge = bridge
        self._build_context = build_context_fn
        self._telemetry_store = telemetry_store
        self.last_analysis_trace: str | None = None

    def on_session_mined(self, trace_id: str, transcript: str, wing: str) -> None:
        try:
            self.last_analysis_trace = trace_id
            tid_bytes = bytes.fromhex(trace_id) if len(trace_id) == 32 else b""
            from router.skills.adapter import extract_tool_outcomes_from_telemetry
            tool_outcomes = extract_tool_outcomes_from_telemetry(self._telemetry_store, tid_bytes)
            context = self._build_context(transcript=transcript, tool_outcomes=tool_outcomes)
            logger.info("Skill analysis for session %s: context=%d chars", trace_id[:8], len(context))
            # TODO(P2-M2): Wire to vendored analyzer.analyze_execution() when LLM shim is ready.
            # For M0, we just log the context and record that analysis was attempted.
        except Exception:
            logger.warning("Skill analysis failed for session %s", trace_id[:8], exc_info=True)
