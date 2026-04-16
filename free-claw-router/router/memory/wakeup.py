from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _get_palace():
    from mempalace.layers import PalaceLayer
    return PalaceLayer()


@dataclass
class _CacheEntry:
    text: str
    expires_at: float


class WakeupService:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def get_wakeup(self, project_wing: str) -> str:
        cache_key = project_wing
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > now:
            return cached.text
        try:
            palace = _get_palace()
            project_text = palace.wake_up(wing=project_wing) or ""
            user_text = palace.wake_up(wing="user") or ""
        except Exception:
            logger.warning("mempalace wake_up failed", exc_info=True)
            return ""
        combined = ""
        if project_text.strip():
            combined += f"### Project: {project_wing}\n{project_text.strip()}\n\n"
        if user_text.strip():
            combined += f"### Your preferences & patterns\n{user_text.strip()}\n"
        self._cache[cache_key] = _CacheEntry(text=combined, expires_at=now + self._ttl)
        return combined

    def invalidate(self, project_wing: str) -> None:
        self._cache.pop(project_wing, None)
