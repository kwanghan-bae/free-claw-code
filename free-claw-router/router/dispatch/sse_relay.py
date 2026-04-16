from __future__ import annotations
import json
from typing import AsyncIterator, AsyncIterable

async def relay_sse_stream(source: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    try:
        async for chunk in source:
            yield chunk
    except Exception as e:
        payload = json.dumps({"error": {"code": "upstream_dropped", "message": str(e)}})
        yield f"data: {payload}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
