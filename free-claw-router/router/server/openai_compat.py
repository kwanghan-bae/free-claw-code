from pathlib import Path
import secrets
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan
from router.server._telemetry_middleware import start_trace
from router.server._quota_middleware import make_dispatch_call
from router.server._injection import (
    inject_memory,
    inject_nudges,
    record_session_activity,
    resolve_task_hint,
    scan_and_buffer,
    maybe_batch_analyze,
)
from router.catalog.registry import Registry
from router.catalog.refresh.scheduler import CronScheduler, CronJob
from router.routing.policy import Policy
from router.routing.decide import build_fallback_chain
from router.dispatch.client import DispatchClient
from router.dispatch.fallback import run_fallback_chain
from router.quota.predict import estimate_request_tokens
from router.telemetry.spans import parse_traceparent
from router.telemetry.store import Store
from router.server.meta_report import router as meta_report_router

DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"
POLICY_PATH = Path(__file__).resolve().parent.parent / "routing" / "policy.yaml"

app = FastAPI(title="free-claw-router", lifespan=lifespan)
app.include_router(meta_report_router)

_policy: Policy | None = None
_dispatch = DispatchClient()
_telemetry_store: Store | None = None
_cron = CronScheduler()


def _resolve_store() -> Store | None:
    return _telemetry_store or getattr(app.state, "telemetry_store", None)


def _ensure_loaded() -> tuple[Registry, Policy]:
    global _policy
    live = getattr(app.state, "catalog_live", None)
    if live:
        registry = live.snapshot()
    else:
        if not hasattr(_ensure_loaded, "_fallback"):
            _ensure_loaded._fallback = Registry.load_from_dir(DATA_DIR)
        registry = _ensure_loaded._fallback
    if _policy is None:
        _policy = Policy.load(POLICY_PATH)
    return registry, _policy


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    registry, _ = _ensure_loaded()
    return JSONResponse({"status": "ok", "catalog_version": registry.version})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    payload = await request.json()
    registry, policy = _ensure_loaded()

    store = _resolve_store()
    tp = parse_traceparent(request.headers.get("traceparent"))
    trace_id = tp.trace_id if tp else secrets.token_bytes(16)
    root_span_id = secrets.token_bytes(8)
    trace_hex = trace_id.hex() if trace_id else ""

    catalog_ver = getattr(app.state, "catalog_version", "unversioned")
    start_trace(store, trace_id=trace_id, root_op="chat_completions", catalog_version=catalog_ver)

    workspace = request.headers.get("x-free-claw-workspace")
    payload = inject_memory(app.state, payload, trace_hex=trace_hex, workspace=workspace)
    payload = inject_nudges(app.state, payload, trace_hex=trace_hex)
    record_session_activity(app.state, trace_hex=trace_hex, workspace=workspace or "")

    hint = resolve_task_hint(payload, request.headers.get("x-free-claw-hints"))

    chain = build_fallback_chain(registry, policy, task_type=hint, skill_id=None)
    if not chain:
        raise HTTPException(status_code=503, detail=f"no candidates for task_type={hint}")

    estimated = estimate_request_tokens(payload)
    call_one = make_dispatch_call(
        registry=registry, dispatch_client=_dispatch, store=store,
        trace_id=trace_id, root_span_id=root_span_id, hint=hint,
        payload=payload, estimated=estimated, request_headers=dict(request.headers),
    )
    result = await run_fallback_chain(chain, call_one)

    scan_and_buffer(app.state, payload=payload, result=result, trace_hex=trace_hex)
    await maybe_batch_analyze(app.state, trace_hex=trace_hex)

    resp = JSONResponse(status_code=result.status, content=result.body)
    for k in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
        if k in result.response_headers:
            resp.headers[k] = result.response_headers[k]
    return resp


@app.post("/cron/register")
async def cron_register(body: dict = Body(...)) -> JSONResponse:
    try:
        job = CronJob(job_id=body["job_id"], cron_expr=body["cron_expr"], payload=body.get("payload", {}))
        _cron.register(job)
        return JSONResponse({"ok": True, "job_id": job.job_id})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=409)
    except KeyError as e:
        return JSONResponse({"ok": False, "error": f"missing: {e}"}, status_code=422)


@app.get("/cron/list")
async def cron_list() -> JSONResponse:
    return JSONResponse({"jobs": [{"job_id": j.job_id, "cron_expr": j.cron_expr, "payload": j.payload} for j in _cron.list_jobs()]})
