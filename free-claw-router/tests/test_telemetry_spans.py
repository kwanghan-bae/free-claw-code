from router.telemetry.spans import parse_traceparent, TraceContext

def test_parse_valid_traceparent():
    ctx = parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
    assert isinstance(ctx, TraceContext)
    assert len(ctx.trace_id) == 16
    assert len(ctx.span_id) == 8
    assert ctx.sampled is True

def test_parse_rejects_bad_version():
    assert parse_traceparent("ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") is None

def test_parse_rejects_wrong_segment_count():
    assert parse_traceparent("00-abc-01") is None
