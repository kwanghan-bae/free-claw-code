from pathlib import Path
import time as _time
import time
import secrets
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan
from router.server._telemetry_middleware import (
    start_trace,
    start_span,
    emit_event,
    emit_quota_reserved,
    emit_quota_exhausted,
    emit_request_event,
    emit_response_event,
    emit_dispatch_result,
)
from router.server._quota_middleware import (
    get_bucket,
    reserve_tokens,
    quota_exhausted_result,
    settle,
)
from router.catalog.registry import Registry
from router.routing.policy import Policy
from router.routing.hints import classify_task_hint
from router.routing.decide import build_fallback_chain
from router.dispatch.client import DispatchClient, DispatchResult
from router.dispatch.fallback import run_fallback_chain
from router.quota.predict import estimate_request_tokens
from router.telemetry.spans import parse_traceparent, TraceContext
from router.telemetry.store import Store

DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"
POLICY_PATH = Path(__file__).resolve().parent.parent / "routing" / "policy.yaml"

app = FastAPI(title="free-claw-router", lifespan=lifespan)

_policy: Policy | None = None
_dispatch = DispatchClient()
_telemetry_store: Store | None = None


class _RequestGapTracker:
    def __init__(self):
        self._last_ts: dict[str, float] = {}
    def get_gap(self, trace_id: str) -> float:
        now = _time.time()
        last = self._last_ts.get(trace_id, now)
        self._last_ts[trace_id] = now
        return now - last

_request_gap_tracker = _RequestGapTracker()

def _resolve_store() -> Store | None:
    return _telemetry_store or getattr(app.state, 'telemetry_store', None)

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

    # -- telemetry: parse or create trace context --
    store = _resolve_store()
    tp = parse_traceparent(request.headers.get("traceparent"))
    if tp:
        trace_id = tp.trace_id
    else:
        trace_id = secrets.token_bytes(16)
    root_span_id = secrets.token_bytes(8)

    catalog_ver = getattr(app.state, "catalog_version", "unversioned")
    start_trace(store, trace_id=trace_id, root_op="chat_completions", catalog_version=catalog_ver)

    # Memory injection (P1)
    _trace_hex = trace_id.hex() if trace_id else ""
    injector = getattr(app.state, "injector", None)
    if injector is not None:
        _workspace = request.headers.get("x-free-claw-workspace")
        _gap = _request_gap_tracker.get_gap(_trace_hex)
        payload = injector.maybe_inject(
            payload, trace_id=_trace_hex, workspace=_workspace,
            last_request_gap_seconds=_gap,
        )

    # Learning nudge injection (P3)
    _nudge_inj = getattr(app.state, "nudge_injector", None)
    if _nudge_inj is not None:
        payload = _nudge_inj.inject(payload, trace_id=_trace_hex)

    # Record activity for session-close detection
    detector = getattr(app.state, "session_detector", None)
    if detector is not None:
        detector.record_activity(
            trace_id=_trace_hex,
            workspace=request.headers.get("x-free-claw-workspace", ""),
        )

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

    estimated = estimate_request_tokens(payload)

    async def call_one(cand):
        provider = next(p for p in registry.providers if p.provider_id == cand.provider_id)
        bucket = get_bucket(cand)

        span_id = secrets.token_bytes(8)
        span_start = int(time.time() * 1000)

        start_span(
            store,
            span_id=span_id, trace_id=trace_id, parent_span_id=root_span_id,
            op_name="llm_call", model_id=cand.model_id, provider_id=cand.provider_id,
            task_type=hint, started_at_ms=span_start,
        )

        tok = await reserve_tokens(bucket, tokens_estimated=estimated)
        if tok is None:
            emit_quota_exhausted(
                store,
                span_id=span_id, span_start_ms=span_start,
                provider_id=cand.provider_id, model_id=cand.model_id,
            )
            return quota_exhausted_result()

        emit_quota_reserved(
            store,
            span_id=span_id, provider_id=cand.provider_id, model_id=cand.model_id,
            tokens_estimated=estimated, bucket_rpm_used=bucket.rpm_used(),
        )
        emit_request_event(store, span_id=span_id, messages=payload.get("messages", []))

        result = await _dispatch.call(provider, cand.model, payload, dict(request.headers))

        if result.status == 200:
            emit_response_event(store, span_id=span_id, body=result.body)

        await settle(bucket, tok, tokens_actual=estimated, success=result.status == 200)

        emit_dispatch_result(
            store,
            span_id=span_id, span_start_ms=span_start,
            provider_id=cand.provider_id, model_id=cand.model_id,
            result=result,
        )

        return result

    result = await run_fallback_chain(chain, call_one)

    # Learning: scan response + buffer conversation (P3)
    _rule_det = getattr(app.state, "rule_detector", None)
    _conv_buf = getattr(app.state, "conv_buffer", None)
    _ncache = getattr(app.state, "nudge_cache", None)
    if _rule_det and _ncache and result.status == 200:
        assistant_text = ""
        for ch in result.body.get("choices", []):
            msg = ch.get("message", {})
            if msg.get("role") == "assistant":
                assistant_text = msg.get("content", "")
        if assistant_text:
            for nudge in _rule_det.scan(assistant_text):
                _ncache.push(_trace_hex, nudge)
    if _conv_buf:
        for m in payload.get("messages", []):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                _conv_buf.append_user(_trace_hex, m["content"])
        if result.status == 200:
            for ch in result.body.get("choices", []):
                msg = ch.get("message", {})
                if msg.get("role") == "assistant":
                    _conv_buf.append_assistant(_trace_hex, msg.get("content", ""))

    # Batch analysis every 5 turns (P3)
    _batch = getattr(app.state, "batch_analyzer", None)
    if _conv_buf and _batch and _ncache:
        if _conv_buf.turn_count(_trace_hex) % 5 == 0 and _conv_buf.turn_count(_trace_hex) > 0:
            try:
                batch_nudges = await _batch.analyze(_trace_hex, _conv_buf)
                for n in batch_nudges:
                    _ncache.push(_trace_hex, n)
            except Exception:
                pass  # batch analysis is best-effort

    resp = JSONResponse(status_code=result.status, content=result.body)
    for k in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
        if k in result.response_headers:
            resp.headers[k] = result.response_headers[k]
    return resp


from fastapi import Body
from router.catalog.refresh.scheduler import CronScheduler, CronJob

_cron = CronScheduler()

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
