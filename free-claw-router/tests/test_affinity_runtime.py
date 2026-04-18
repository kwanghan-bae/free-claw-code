"""Runtime-level test: does lookup_affinity return real counts when
telemetry has entries for the (skill, model) pair?

Unlike the pure-function unit tests in test_affinity.py, this test
exercises the full path: FCR_DATA_DIR -> Store -> skill_model_affinity
readmodel -> lookup_affinity.
"""
from __future__ import annotations

import pytest

from router.routing.affinity import lookup_affinity
from router.telemetry.store import Store


@pytest.fixture
def seeded_telemetry(tmp_path, monkeypatch):
    """Seed telemetry.db at tmp_path with spans for (refactor, llama-70b).

    Layout mirrors production: FCR_DATA_DIR/telemetry.db. The spans/
    traces/evaluations schema comes from migrations/001_initial.sql via
    Store.initialize(); span_id/trace_id must be BLOBs so we use the
    Store API rather than raw sqlite inserts.
    """
    db = tmp_path / "telemetry.db"
    store = Store(path=db)
    store.initialize()

    trace_id = b"\xAA" * 16
    store.insert_trace(
        trace_id=trace_id,
        started_at_ms=1,
        root_op="test",
        root_session_id=None,
        catalog_version="v",
        policy_version="1",
    )

    # 3 successful spans for (refactor, llama-70b)
    for i in range(3):
        sid = bytes([0x10 + i]) * 8
        store.insert_span(
            span_id=sid,
            trace_id=trace_id,
            parent_span_id=None,
            op_name="llm_call",
            model_id="llama-70b",
            provider_id="groq",
            skill_id="refactor",
            task_type="coding",
            started_at_ms=1,
        )
        store.close_span(sid, ended_at_ms=2, duration_ms=1, status="ok")

    # 1 failure for same pair
    sid_err = b"\xFE" * 8
    store.insert_span(
        span_id=sid_err,
        trace_id=trace_id,
        parent_span_id=None,
        op_name="llm_call",
        model_id="llama-70b",
        provider_id="groq",
        skill_id="refactor",
        task_type="coding",
        started_at_ms=1,
    )
    store.close_span(sid_err, ended_at_ms=2, duration_ms=1, status="http_503")

    # Point the router at this db
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    return tmp_path


def test_lookup_affinity_finds_data(seeded_telemetry):
    """With 3 ok + 1 error for (refactor, llama-70b), the readmodel
    reports trials=4, success_rate=0.75, so we expect (3, 4)."""
    s, n = lookup_affinity(skill_id="refactor", model_id="llama-70b")
    assert n == 4, f"expected 4 trials, got ({s}, {n})"
    assert s == 3, f"expected 3 successes, got ({s}, {n})"


def test_lookup_affinity_unknown_pair_cold_start(seeded_telemetry):
    """A model that doesn't appear in telemetry must cold-start to (0,0)."""
    s, n = lookup_affinity(skill_id="refactor", model_id="never-seen")
    assert (s, n) == (0, 0)


def test_lookup_affinity_no_skill_id_cold_start():
    """skill_id=None short-circuits without any DB access; must return (0,0)."""
    s, n = lookup_affinity(skill_id=None, model_id="llama-70b")
    assert (s, n) == (0, 0)
