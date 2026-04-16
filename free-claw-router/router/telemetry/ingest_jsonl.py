from __future__ import annotations
import json
import time
from router.telemetry.store import Store

def _hex_to_bytes(h: str | None) -> bytes | None:
    if not h:
        return None
    try:
        return bytes.fromhex(h)
    except ValueError:
        return None

def ingest_lines(store: Store, lines, *, default_catalog_version: str, default_policy_version: str) -> int:
    count = 0
    for raw in lines:
        if not raw.strip():
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        if kind == "span_started":
            tid = _hex_to_bytes(ev.get("trace_id"))
            sid = _hex_to_bytes(ev.get("span_id"))
            if tid is None or sid is None:
                continue
            store.insert_trace(
                trace_id=tid, started_at_ms=int(time.time() * 1000),
                root_op=ev.get("op_name", "unknown"),
                root_session_id=ev.get("session_id"),
                catalog_version=default_catalog_version,
                policy_version=default_policy_version)
            store.insert_span(
                span_id=sid, trace_id=tid,
                parent_span_id=_hex_to_bytes(ev.get("parent_span_id")),
                op_name=ev.get("op_name", "unknown"),
                model_id=ev.get("attributes", {}).get("model_id"),
                provider_id=ev.get("attributes", {}).get("provider_id"),
                skill_id=ev.get("attributes", {}).get("skill_id"),
                task_type=ev.get("attributes", {}).get("task_type"),
                started_at_ms=int(time.time() * 1000))
            count += 1
        elif kind == "span_ended":
            sid = _hex_to_bytes(ev.get("span_id"))
            if sid is None:
                continue
            now = int(time.time() * 1000)
            store.close_span(sid, ended_at_ms=now, duration_ms=int(ev.get("duration_ms", 0)),
                             status=str(ev.get("status", "ok")))
            count += 1
    return count
