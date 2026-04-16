import pytest
from router.dispatch.sse_relay import relay_sse_stream

class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks
    async def __aiter__(self):
        for c in self._chunks:
            yield c

@pytest.mark.asyncio
async def test_relay_forwards_chunks_unchanged():
    src = _FakeStream([b"data: one\n\n", b"data: two\n\n", b"data: [DONE]\n\n"])
    out = []
    async for ch in relay_sse_stream(src):
        out.append(ch)
    assert out == [b"data: one\n\n", b"data: two\n\n", b"data: [DONE]\n\n"]

@pytest.mark.asyncio
async def test_relay_emits_terminal_error_on_exception():
    async def bad_stream():
        yield b"data: one\n\n"
        raise RuntimeError("upstream dropped")
    out = []
    async for ch in relay_sse_stream(bad_stream()):
        out.append(ch)
    assert out[0] == b"data: one\n\n"
    assert b'"error"' in out[-2] or b'"error"' in out[-1]
