from router.telemetry.events import (
    QuotaReserved, DispatchSucceeded, DispatchFailed, to_payload
)

def test_quota_reserved_roundtrip():
    ev = QuotaReserved(provider_id="groq", model_id="x", tokens_estimated=100, bucket_rpm_used=1)
    payload = to_payload(ev)
    assert payload["kind"] == "quota_reserved"
    assert payload["data"]["tokens_estimated"] == 100

def test_dispatch_succeeded_payload_has_status():
    ev = DispatchSucceeded(provider_id="groq", model_id="x", status=200, latency_ms=40)
    p = to_payload(ev)
    assert p["data"]["status"] == 200

def test_dispatch_failed_payload_carries_error():
    ev = DispatchFailed(provider_id="groq", model_id="x", status=503, error_class="io_error")
    p = to_payload(ev)
    assert p["data"]["error_class"] == "io_error"
