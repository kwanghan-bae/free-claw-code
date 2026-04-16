from __future__ import annotations
import json
from router.telemetry.store import Store


def build_transcript(store: Store, *, trace_id: bytes, after_ts: int = 0) -> str:
    with store.connect() as c:
        rows = list(c.execute(
            """SELECT e.kind, e.payload_json, e.ts
               FROM events e
               JOIN spans s ON e.span_id = s.span_id
               WHERE s.trace_id = ? AND e.ts > ?
               ORDER BY e.ts ASC""",
            (trace_id, after_ts),
        ))
    parts: list[str] = []
    for kind, payload_json, ts in rows:
        try:
            data = json.loads(payload_json)
        except json.JSONDecodeError:
            continue
        if kind == "request":
            for msg in data.get("messages", []):
                if msg.get("role") == "user":
                    parts.append(f"**User:** {msg.get('content', '')}\n")
        elif kind == "response":
            for choice in data.get("choices", []):
                msg = choice.get("message", {})
                if msg.get("role") == "assistant":
                    parts.append(f"**Assistant:** {msg.get('content', '')}\n")
    return "\n---\n".join(parts) if parts else ""
