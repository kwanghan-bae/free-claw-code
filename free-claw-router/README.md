# free-claw-router

OpenAI-compatible sidecar for free-claw-code. See
[`docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md`](../docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md).

## Quick start (dev)

```bash
cd free-claw-router
uv sync --extra dev
uv run uvicorn router.server.openai_compat:app --reload --port 7801
```
