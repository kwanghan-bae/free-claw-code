from __future__ import annotations


def build_analysis_context(
    *,
    transcript: str,
    tool_outcomes: list[dict],
) -> str:
    parts = []
    if transcript.strip():
        parts.append("## Session Transcript\n")
        parts.append(transcript.strip())
        parts.append("")

    if tool_outcomes:
        parts.append("## Tool Outcomes\n")
        for t in tool_outcomes:
            status = "OK" if t.get("success") else "FAILED"
            parts.append(f"- {t.get('tool', '?')}: {status} ({t.get('latency_ms', '?')}ms)")
        parts.append("")

    return "\n".join(parts)


def extract_tool_outcomes_from_telemetry(store, trace_id: bytes) -> list[dict]:
    """Read spans for a trace and extract per-tool success/failure."""
    with store.connect() as c:
        rows = list(c.execute(
            """SELECT op_name, status, duration_ms
               FROM spans WHERE trace_id = ? AND op_name = 'tool_call'""",
            (trace_id,),
        ))
    return [
        {"tool": "tool_call", "success": row[1] == "ok", "latency_ms": row[2] or 0}
        for row in rows
    ]
