use std::sync::Arc;

use serde_json::Map;
use telemetry::{MemoryTelemetrySink, SessionTracer, TelemetryEvent};

#[test]
fn execute_tool_emits_child_span_under_session_trace() {
    let sink = Arc::new(MemoryTelemetrySink::default());
    let tracer = SessionTracer::new("s-test", sink.clone());
    let (root_ctx, _guard) = tracer.start_root_span("session", Map::default());

    let _ = tools::test_helpers::execute_tool_with_span(
        &tracer,
        root_ctx,
        "NoopTool",
        serde_json::json!({}),
    );

    let events = sink.events();
    let span_started = events
        .iter()
        .filter(
            |e| matches!(e, TelemetryEvent::SpanStarted { op_name, .. } if op_name == "tool_call"),
        )
        .count();
    let span_ended = events
        .iter()
        .filter(|e| matches!(e, TelemetryEvent::SpanEnded { .. }))
        .count();
    assert_eq!(span_started, 1);
    assert!(span_ended >= 1);
}
