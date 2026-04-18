"""Verify that skill_id is plumbed from HTTP request through to routing.

Day 7 dogfood gate requires that the affinity bonus can flip a routing
decision; that's only possible if the handler actually passes a real
skill_id into build_fallback_chain. These tests pin the header/body
extraction behavior so a future refactor can't silently regress it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_skill_id_header_is_plumbed_through(client, monkeypatch):
    """X-Skill-ID header should reach build_fallback_chain and the
    skill_id field (if also present in the body) should be stripped
    before reaching the provider."""
    seen_skill_ids: list[str | None] = []
    forwarded_payloads: list[dict] = []

    import router.server.openai_compat as mod

    original_build = mod.build_fallback_chain

    def spy_build(registry, policy, *, task_type, skill_id, **kw):
        seen_skill_ids.append(skill_id)
        return original_build(registry, policy, task_type=task_type, skill_id=skill_id, **kw)

    monkeypatch.setattr(mod, "build_fallback_chain", spy_build)

    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        forwarded_payloads.append(payload)
        return DispatchResult(
            200,
            {"id": "x", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            RateLimitState(),
            {},
        )

    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor"}], "skill_id": "should-be-stripped"},
        headers={"x-free-claw-hints": "coding", "X-Skill-ID": "refactor"},
    )
    assert r.status_code == 200, r.text

    # Header wins over body value; build_fallback_chain saw the real skill_id.
    assert seen_skill_ids == ["refactor"]

    # The skill_id field is not forwarded to the upstream provider.
    assert forwarded_payloads, "dispatch was never invoked"
    assert "skill_id" not in forwarded_payloads[0]


def test_skill_id_body_fallback_when_no_header(client, monkeypatch):
    """Without X-Skill-ID header, a top-level skill_id payload field
    is picked up (and stripped)."""
    seen_skill_ids: list[str | None] = []
    forwarded_payloads: list[dict] = []

    import router.server.openai_compat as mod

    original_build = mod.build_fallback_chain

    def spy_build(registry, policy, *, task_type, skill_id, **kw):
        seen_skill_ids.append(skill_id)
        return original_build(registry, policy, task_type=task_type, skill_id=skill_id, **kw)

    monkeypatch.setattr(mod, "build_fallback_chain", spy_build)

    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        forwarded_payloads.append(payload)
        return DispatchResult(
            200,
            {"id": "x", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            RateLimitState(),
            {},
        )

    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor"}], "skill_id": "from-body"},
        headers={"x-free-claw-hints": "coding"},
    )
    assert r.status_code == 200, r.text
    assert seen_skill_ids == ["from-body"]
    assert "skill_id" not in forwarded_payloads[0]


def test_no_skill_id_still_works(client, monkeypatch):
    """No header, no body field -> skill_id=None, cold-start behavior."""
    seen_skill_ids: list[str | None] = []

    import router.server.openai_compat as mod

    original_build = mod.build_fallback_chain

    def spy_build(registry, policy, *, task_type, skill_id, **kw):
        seen_skill_ids.append(skill_id)
        return original_build(registry, policy, task_type=task_type, skill_id=skill_id, **kw)

    monkeypatch.setattr(mod, "build_fallback_chain", spy_build)

    async def fake_call(*a, **kw):
        return DispatchResult(
            200,
            {"id": "x", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            RateLimitState(),
            {},
        )

    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"x-free-claw-hints": "coding"},
    )
    assert r.status_code == 200, r.text
    assert seen_skill_ids == [None]


def test_empty_skill_id_header_is_treated_as_none(client, monkeypatch):
    """X-Skill-ID: '' should not be forwarded as a non-None value."""
    seen_skill_ids: list[str | None] = []

    import router.server.openai_compat as mod

    original_build = mod.build_fallback_chain

    def spy_build(registry, policy, *, task_type, skill_id, **kw):
        seen_skill_ids.append(skill_id)
        return original_build(registry, policy, task_type=task_type, skill_id=skill_id, **kw)

    monkeypatch.setattr(mod, "build_fallback_chain", spy_build)

    async def fake_call(*a, **kw):
        return DispatchResult(
            200,
            {"id": "x", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            RateLimitState(),
            {},
        )

    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"x-free-claw-hints": "coding", "X-Skill-ID": ""},
    )
    assert r.status_code == 200, r.text
    assert seen_skill_ids == [None]
