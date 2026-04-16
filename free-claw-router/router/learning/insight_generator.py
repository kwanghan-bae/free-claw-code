from __future__ import annotations
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

INSIGHT_PROMPT = """Analyze these recent coding sessions. What patterns do you see?
What is the developer doing well? What mistakes are recurring?
What workflow improvements would help? Be specific and actionable. 3-5 bullets."""


class InsightGenerator:
    def __init__(
        self,
        *,
        search_fn: Callable,
        llm_fn: Callable[..., Awaitable[str]],
        add_drawer_fn: Callable,
        min_sessions: int = 2,
    ) -> None:
        self._search = search_fn
        self._llm = llm_fn
        self._add_drawer = add_drawer_fn
        self._min = min_sessions

    async def generate(self, project_wing: str) -> None:
        try:
            results = self._search(query="session summary", wing=project_wing, n_results=5)
            sessions = results.get("results", [])
            if len(sessions) < self._min:
                logger.debug("Too few sessions (%d) for insight generation", len(sessions))
                return

            context = "\n---\n".join(s.get("content", "") for s in sessions)
            insights = await self._llm(messages=[
                {"role": "system", "content": INSIGHT_PROMPT},
                {"role": "user", "content": context},
            ])
            if insights.strip():
                self._add_drawer(wing="user", room="insights", content=insights.strip())
                logger.info("Generated insights for %s", project_wing)
        except Exception:
            logger.warning("Insight generation failed for %s", project_wing, exc_info=True)
