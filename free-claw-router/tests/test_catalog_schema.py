import pytest
from pydantic import ValidationError
from router.catalog.schema import ProviderSpec, ModelSpec, FreeTier, Pricing, Auth

def _model(**over):
    base = dict(
        model_id="openrouter/test-model:free",
        status="active",
        context_window=32000,
        tool_use=True,
        structured_output="partial",
        free_tier=FreeTier(rpm=20, tpm=100000, daily=None, reset_policy="minute"),
        pricing=Pricing(input=0.0, output=0.0, free=True),
        quirks=[],
        evidence_urls=["https://example.com/models"],
        last_verified="2026-04-15T00:00:00Z",
        first_seen="2026-03-28",
    )
    base.update(over)
    return ModelSpec(**base)

def test_free_pricing_required():
    with pytest.raises(ValidationError):
        _model(pricing=Pricing(input=1.0, output=1.0, free=False))

def test_context_window_must_be_positive():
    with pytest.raises(ValidationError):
        _model(context_window=0)

def test_evidence_urls_required_non_empty():
    with pytest.raises(ValidationError):
        _model(evidence_urls=[])

def test_model_id_uniqueness_enforced_by_provider():
    p = ProviderSpec(
        provider_id="openrouter",
        base_url="https://openrouter.ai/api/v1",
        auth=Auth(env="OPENROUTER_API_KEY", scheme="bearer"),
        known_ratelimit_header_schema="openrouter_standard",
        models=[_model(), _model()],
    )
    with pytest.raises(ValueError):
        p.validate_unique_models()

def test_happy_path():
    m = _model()
    assert m.pricing.free is True
    assert m.context_window == 32000
