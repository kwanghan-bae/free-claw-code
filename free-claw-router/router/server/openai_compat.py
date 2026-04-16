from pathlib import Path
import json
import time
import secrets
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan
from router.catalog.registry import Registry
from router.routing.policy import Policy
from router.routing.hints import classify_task_hint
from router.routing.decide import build_fallback_chain
from router.dispatch.client import DispatchClient, DispatchResult
from router.dispatch.fallback import run_fallback_chain
from router.quota.bucket import BucketStore
from router.quota.predict import estimate_request_tokens
from router.adapters.hermes_ratelimit import RateLimitState
from router.telemetry.spans import parse_traceparent, TraceContext
from router.telemetry import events as ev
from router.telemetry.store import Store

DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"
POLICY_PATH = Path(__file__).resolve().parent.parent / "routing" / "policy.yaml"

app = FastAPI(title="free-claw-router", lifespan=lifespan)

_registry: Registry | None = None
_policy: Policy | None = None
_dispatch = DispatchClient()
_bucket_store = BucketStore()
_telemetry_store: Store | None = None

def _resolve_store() -> Store | None:
    return _telemetry_store or getattr(app.state, 'telemetry_store', None)

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

    # -- telemetry: parse or create trace context --
    store = _resolve_store()
    tp = parse_traceparent(request.headers.get("traceparent"))
    if tp:
        trace_id = tp.trace_id
    else:
        trace_id = secrets.token_bytes(16)
    root_span_id = secrets.token_bytes(8)

    if store:
        try:
            catalog_ver = getattr(app.state, "catalog_version", "unversioned")
            store.insert_trace(
                trace_id=trace_id,
                started_at_ms=int(time.time() * 1000),
                root_op="chat_completions",
                root_session_id=None,
                catalog_version=catalog_ver,
                policy_version="1",
            )
        except Exception:
            pass

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
        bucket = _bucket_store.get(
            cand.provider_id, cand.model_id,
            rpm_limit=cand.model.free_tier.rpm,
            tpm_limit=cand.model.free_tier.tpm,
            daily_limit=cand.model.free_tier.daily,
        )

        span_id = secrets.token_bytes(8)
        span_start = int(time.time() * 1000)

        # Insert span (best-effort)
        if store:
            try:
                store.insert_span(
                    span_id=span_id,
                    trace_id=trace_id,
                    parent_span_id=root_span_id,
                    op_name="llm_call",
                    model_id=cand.model_id,
                    provider_id=cand.provider_id,
                    skill_id=None,
                    task_type=hint,
                    started_at_ms=span_start,
                )
            except Exception:
                pass

        try:
            tok = await bucket.reserve(tokens_estimated=estimated)
        except RuntimeError:
            # Emit quota_reserved event even on exhaustion? No, we failed to reserve.
            if store:
                try:
                    now = int(time.time() * 1000)
                    store.close_span(span_id, ended_at_ms=now, duration_ms=now - span_start, status="quota_exhausted")
                    event_payload = ev.to_payload(ev.DispatchFailed(
                        provider_id=cand.provider_id, model_id=cand.model_id,
                        status=429, error_class="quota_exhausted",
                    ))
                    store.insert_event(span_id=span_id, kind="dispatch_failed",
                                       payload_json=json.dumps(event_payload), ts_ms=now)
                except Exception:
                    pass
            return DispatchResult(429, {"error": "quota_exhausted"}, RateLimitState(), {})

        # Emit quota_reserved event (best-effort)
        if store:
            try:
                event_payload = ev.to_payload(ev.QuotaReserved(
                    provider_id=cand.provider_id, model_id=cand.model_id,
                    tokens_estimated=estimated, bucket_rpm_used=bucket.rpm_used(),
                ))
                store.insert_event(span_id=span_id, kind="quota_reserved",
                                   payload_json=json.dumps(event_payload), ts_ms=int(time.time() * 1000))
            except Exception:
                pass

        result = await _dispatch.call(provider, cand.model, payload, dict(request.headers))

        if result.status == 200:
            await bucket.commit(tok, tokens_actual=estimated)
        else:
            await bucket.rollback(tok)

        # Close span + emit dispatch event (best-effort)
        now = int(time.time() * 1000)
        if store:
            try:
                status = "ok" if result.status == 200 else f"http_{result.status}"
                store.close_span(span_id, ended_at_ms=now, duration_ms=now - span_start, status=status)
                if result.status == 200:
                    event_payload = ev.to_payload(ev.DispatchSucceeded(
                        provider_id=cand.provider_id, model_id=cand.model_id,
                        status=result.status, latency_ms=now - span_start,
                    ))
                    store.insert_event(span_id=span_id, kind="dispatch_succeeded",
                                       payload_json=json.dumps(event_payload), ts_ms=now)
                else:
                    event_payload = ev.to_payload(ev.DispatchFailed(
                        provider_id=cand.provider_id, model_id=cand.model_id,
                        status=result.status, error_class=f"http_{result.status}",
                    ))
                    store.insert_event(span_id=span_id, kind="dispatch_failed",
                                       payload_json=json.dumps(event_payload), ts_ms=now)
            except Exception:
                pass

        return result

    result = await run_fallback_chain(chain, call_one)
    resp = JSONResponse(status_code=result.status, content=result.body)
    for k in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
        if k in result.response_headers:
            resp.headers[k] = result.response_headers[k]
    return resp
