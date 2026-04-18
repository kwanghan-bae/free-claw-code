"""Dev-only forced triggers for dogfood validation.

Gated by `FCR_DEV_TRIGGERS=1`. Returns 404 otherwise so production
runs aren't exposed. Useful to short-circuit the natural daily crons
while shaking out the pipeline:

    POST /meta/analyze-now               MetaAnalyzer 즉시 실행
    POST /meta/evolve-now                build_edit_plans 즉시
    POST /telemetry/readmodel/refresh    skill_model_affinity 재계산
    GET  /healthz/pipeline               P1~P4 훅 최근 24h 발화 여부
"""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _gate():
    if os.getenv("FCR_DEV_TRIGGERS") != "1":
        raise HTTPException(status_code=404)


def _data_dir() -> Path:
    env = os.getenv("FCR_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".free-claw-router"


@router.post("/meta/analyze-now")
async def analyze_now() -> dict:
    _gate()
    try:
        from router.meta.meta_analyzer import analyze_open_trajectories
        result = await analyze_open_trajectories()
        return {"ok": True, "suggestions_added": result.get("added", 0)}
    except (ImportError, AttributeError) as e:
        return {"ok": False, "reason": f"analyzer API unavailable: {e}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@router.post("/meta/evolve-now")
async def evolve_now() -> dict:
    _gate()
    try:
        from router.meta.meta_consensus import build_edit_plans
        from router.meta.meta_editor import MetaEditor
        from router.meta.meta_pr import MetaPR
        plans = build_edit_plans(force=True)
        applied: list[str] = []
        for plan in plans:
            MetaEditor.apply(plan)
            MetaPR.submit(plan)
            applied.append(getattr(plan, "target", "?"))
        return {"ok": True, "applied": applied}
    except (ImportError, AttributeError) as e:
        return {"ok": False, "reason": f"meta API unavailable: {e}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@router.post("/telemetry/readmodel/refresh")
async def refresh_readmodel() -> dict:
    _gate()
    try:
        # The real readmodel lives at router/telemetry/readmodels.py — it's
        # a computed view, not a materialized cache, so "refresh" is a
        # no-op today. We return a friendly indicator so the dogfood
        # timeline has an entry.
        from router.telemetry.readmodels import skill_model_affinity  # noqa: F401
        return {"ok": True, "note": "computed view — no materialization needed"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@router.get("/healthz/pipeline")
async def pipeline_health() -> dict:
    _gate()
    d = _data_dir()
    db = d / "telemetry.db"
    if not db.exists():
        return {"ok": True, "last_24h": {}, "note": "no telemetry yet"}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    kinds = [
        "memory_mined",
        "skill_analyzed",
        "trajectory_compressed",
        "insight_generated",
        "meta_suggestion",
    ]
    conn = sqlite3.connect(str(db))
    try:
        seen: dict[str, int] = {}
        for k in kinds:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind=? AND ts>=?",
                (k, cutoff),
            ).fetchone()
            seen[k] = int(row[0]) if row else 0
    finally:
        conn.close()
    return {"ok": True, "last_24h": seen}
