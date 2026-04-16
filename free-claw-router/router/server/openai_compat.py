from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan
from router.catalog.registry import Registry
from router.routing.policy import Policy
from router.routing.hints import classify_task_hint
from router.routing.decide import build_fallback_chain
from router.dispatch.client import DispatchClient, DispatchResult
from router.dispatch.fallback import run_fallback_chain

DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"
POLICY_PATH = Path(__file__).resolve().parent.parent / "routing" / "policy.yaml"

app = FastAPI(title="free-claw-router", lifespan=lifespan)

_registry: Registry | None = None
_policy: Policy | None = None
_dispatch = DispatchClient()

def _ensure_loaded() -> tuple[Registry, Policy]:
    global _registry, _policy
    if _registry is None:
        _registry = Registry.load_from_dir(DATA_DIR)
    if _policy is None:
        _policy = Policy.load(POLICY_PATH)
    return _registry, _policy

@app.get("/health")
async def health(request: Request) -> JSONResponse:
    registry, _ = _ensure_loaded()
    return JSONResponse({"status": "ok", "catalog_version": registry.version})

@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    payload = await request.json()
    registry, policy = _ensure_loaded()

    hint = request.headers.get("x-free-claw-hints")
    if not hint:
        last_user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, str):
                    last_user = c
        hint = classify_task_hint(last_user) if last_user else "chat"

    chain = build_fallback_chain(registry, policy, task_type=hint, skill_id=None)
    if not chain:
        raise HTTPException(status_code=503, detail=f"no candidates for task_type={hint}")

    async def call_one(cand):
        provider = next(p for p in registry.providers if p.provider_id == cand.provider_id)
        return await _dispatch.call(provider, cand.model, payload, dict(request.headers))

    result = await run_fallback_chain(chain, call_one)
    resp = JSONResponse(status_code=result.status, content=result.body)
    for k in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
        if k in result.response_headers:
            resp.headers[k] = result.response_headers[k]
    return resp
