from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

COMPRESS_PROMPT = """Compress this coding session transcript into a structured JSON object with these fields:
- "summary": 1-3 sentence summary
- "decisions": [{"what": str, "why": str, "outcome": "success"|"failure"|"pending"}]
- "mistakes": [{"what": str, "lesson": str}]
- "reusable_patterns": [{"pattern": str, "context": str}]

Return ONLY valid JSON, no markdown fences, no explanation."""


class TrajectoryCompressor:
    def __init__(
        self,
        *,
        llm_fn: Callable[..., Awaitable[str]],
        add_drawer_fn: Callable,
    ) -> None:
        self._llm = llm_fn
        self._add_drawer = add_drawer_fn

    async def compress(self, *, trace_id: str, transcript: str, project_wing: str) -> None:
        if not transcript.strip():
            return
        try:
            raw = await self._llm(messages=[
                {"role": "system", "content": COMPRESS_PROMPT},
                {"role": "user", "content": transcript[:8000]},  # truncate to fit context
            ])
            # Strip markdown fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                logger.warning("Trajectory output not a dict for %s", trace_id[:8])
                return
            parsed["session_id"] = trace_id
            parsed["timestamp"] = datetime.now(timezone.utc).isoformat()
            self._add_drawer(
                wing=project_wing,
                room="trajectories",
                content=json.dumps(parsed, ensure_ascii=False, indent=2),
            )
            logger.info("Compressed trajectory for session %s", trace_id[:8])
        except json.JSONDecodeError:
            logger.warning("Trajectory compressor: unparseable LLM output for %s", trace_id[:8])
        except Exception:
            logger.warning("Trajectory compression failed for %s", trace_id[:8], exc_info=True)
