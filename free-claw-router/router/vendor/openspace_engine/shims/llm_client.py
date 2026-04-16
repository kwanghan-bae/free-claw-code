"""Replace openspace.llm.LLMClient with our sidecar dispatch."""
from __future__ import annotations
from typing import Any


class LLMClient:
    """Shim that routes LLM calls through our DispatchClient.
    Actual implementation wired in bridge.py at init time."""
    _dispatch_fn = None

    @classmethod
    def set_dispatch(cls, fn):
        cls._dispatch_fn = fn

    async def chat(self, messages: list[dict], model: str = None, **kw) -> str:
        if self._dispatch_fn is None:
            raise RuntimeError("LLMClient shim not initialized — call set_dispatch first")
        return await self._dispatch_fn(messages, model)

    async def generate(self, prompt: str, system: str = "", **kw) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages)
