from __future__ import annotations
import json
import logging
from typing import Awaitable, Callable
from .nudge_cache import Nudge, ConversationBuffer

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a learning-opportunity detector. Given a conversation excerpt, identify:
- Decisions worth saving to long-term memory (nudge_type: "memory_save")
- Code patterns worth extracting as reusable skills (nudge_type: "skill_create")
- Failing tools/approaches that need fixing (nudge_type: "skill_fix")

Return a JSON array of objects: [{"nudge_type": "...", "content": "...", "confidence": 0.0-1.0}]
Return [] if nothing noteworthy. Be selective — only flag genuinely valuable learning opportunities."""


class BatchAnalyzer:
    def __init__(self, llm_fn: Callable[..., Awaitable[str]]) -> None:
        self._llm = llm_fn

    async def analyze(self, trace_id: str, buffer: ConversationBuffer) -> list[Nudge]:
        turns = buffer.recent(trace_id, n=10)
        if not turns:
            return []
        conversation = "\n".join(f"**{t['role']}:** {t['content']}" for t in turns)
        try:
            raw = await self._llm(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": conversation},
                ],
            )
            items = json.loads(raw)
            if not isinstance(items, list):
                return []
            return [
                Nudge(
                    nudge_type=item.get("nudge_type", "memory_save"),
                    content=item.get("content", ""),
                    source="batch",
                    confidence=float(item.get("confidence", 0.5)),
                )
                for item in items
                if item.get("content")
            ]
        except (json.JSONDecodeError, ValueError):
            logger.warning("Batch analyzer: unparseable LLM output for %s", trace_id[:8])
            return []
        except Exception:
            logger.warning("Batch analyzer failed for %s", trace_id[:8], exc_info=True)
            return []
