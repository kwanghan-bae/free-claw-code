"""Local HTML audit report for meta-evolution pipeline.

GET /meta/report -> server-rendered HTML. No JS framework.
Reads telemetry.db + suggestion_store; renders summary, per-target
timelines, PR status, score trends (sparkline), critical alerts.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


def _data_dir() -> Path:
    """Resolve the data directory.

    Check FCR_DATA_DIR override first (used in tests), then fall back
    to ~/.free-claw-router/ for production.
    """
    env = os.getenv("FCR_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".free-claw-router"


_CSS = """
body{font-family:system-ui,sans-serif;max-width:980px;margin:20px auto;padding:0 16px;color:#222}
h1{font-size:22px;margin-bottom:6px}h2{font-size:17px;margin-top:28px;color:#444}
.target-timeline{border-left:3px solid #888;margin:12px 0;padding:4px 12px}
.alert-critical{background:#fee;padding:8px;border-left:4px solid #c00;margin:6px 0}
table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid #eee;padding:4px 8px;text-align:left}
.spark{font-family:monospace;color:#666}
.muted{color:#888;font-style:italic}
"""


@router.get("/meta/report", response_class=HTMLResponse)
def meta_report() -> HTMLResponse:
    d = _data_dir()
    db_path = d / "telemetry.db"
    suggestions_path = d / "meta_suggestions.json"

    summary = _summarize_24h(db_path)
    timelines = _timelines_per_target(suggestions_path)
    pr_status = _pr_status_cached(d)
    trends = _score_trends(db_path)
    alerts = _alerts(db_path)

    html = _render_html(summary, timelines, pr_status, trends, alerts)
    return HTMLResponse(content=html)


@router.post("/meta/unblock/{target}")
def meta_unblock(target: str) -> dict:
    """Clear the consecutive-rollback block for a given target.
    Called by `clawd meta unblock <target>` or manual curl.
    """
    from router.meta.meta_evaluator import unblock as _unblock
    _unblock(target, store_dir=_data_dir())
    return {"ok": True, "target": target}


@router.get("/meta/alerts")
def meta_alerts() -> list[dict]:
    """Return un-acknowledged critical meta_alert events from the last 7 days."""
    d = _data_dir()
    db = d / "telemetry.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    try:
        alert_rows = conn.execute(
            "SELECT payload_json, ts FROM events "
            "WHERE kind='meta_alert' "
            "AND json_extract(payload_json,'$.level')='critical' "
            "AND ts >= DATE('now','-7 days') "
            "ORDER BY ts DESC"
        ).fetchall()
        ack_ids = {
            row[0] for row in conn.execute(
                "SELECT json_extract(payload_json,'$.alert_id') FROM events "
                "WHERE kind='meta_ack'"
            ).fetchall() if row[0]
        }
    finally:
        conn.close()

    out: list[dict] = []
    for payload_json, ts in alert_rows:
        try:
            rec = json.loads(payload_json)
        except Exception:
            continue
        aid = rec.get("alert_id")
        if not aid or aid in ack_ids:
            continue
        out.append({
            "id": aid,
            "level": rec.get("level", "info"),
            "message": rec.get("message", ""),
            "ts": ts,
        })
    return out


@router.post("/meta/ack/{alert_id}")
def meta_ack(alert_id: str) -> dict:
    """Mark a critical alert as acknowledged."""
    d = _data_dir()
    db = d / "telemetry.db"
    if not db.exists():
        return {"ok": False, "reason": "no telemetry db"}
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO events(span_id, kind, payload_json, ts) "
            "VALUES (NULL, 'meta_ack', ?, ?)",
            (json.dumps({"alert_id": alert_id}), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "alert_id": alert_id}


def _summarize_24h(db: Path) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if not db.exists():
        return {"proposed": 0, "voted": 0, "applied": 0, "rolled_back": 0}
    conn = sqlite3.connect(str(db))
    try:
        counts = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM events WHERE ts >= ? GROUP BY kind",
            (cutoff,),
        ).fetchall())
    finally:
        conn.close()
    return {
        "proposed": counts.get("meta_suggestion", 0),
        "voted": counts.get("meta_vote", 0),
        "applied": counts.get("meta_applied", 0),
        "rolled_back": counts.get("meta_rolled_back", 0),
    }


def _timelines_per_target(sug: Path) -> list[dict]:
    """Read MetaSuggestion records from the production JSON-array store
    and group them per target_file for timeline display.

    The file is written by ``SuggestionStore._save`` as ``json.dumps(list[dict], indent=2)``
    where each dict is an ``asdict(MetaSuggestion)`` with fields: id, trace_id,
    target_file, edit_type, direction, rationale, confidence, proposed_diff,
    timestamp (float Unix seconds).
    """
    if not sug.exists():
        return []
    try:
        raw = json.loads(sug.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []

    groups: dict[str, list[dict]] = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        tid = rec.get("target_file", "?")
        ts_raw = rec.get("timestamp")
        try:
            ts_iso = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            ts_iso = ""
        note = (rec.get("rationale") or "")[:80]
        groups.setdefault(tid, []).append({
            "ts": ts_iso,
            "kind": "proposed",
            "note": note,
        })
    return [
        {"target": tid, "events": sorted(items, key=lambda r: r.get("ts", ""))}
        for tid, items in groups.items()
    ]


def _pr_status_cached(data_dir: Path) -> dict:
    """Read cached PR status if available (expected to be refreshed by a
    separate job). Return empty shape if absent - keeps the endpoint
    offline-safe.
    """
    cache = data_dir / "pr_status.json"
    if not cache.exists():
        return {"open": [], "merged": [], "reverted": []}
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        return {"open": [], "merged": [], "reverted": []}


def _score_trends(db: Path) -> dict[str, list[float]]:
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT score_dim, DATE(ts) AS d, AVG(score_value) AS avg_v "
            "FROM evaluations WHERE ts >= DATE('now','-7 days') "
            "GROUP BY score_dim, DATE(ts) ORDER BY score_dim, d"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[float]] = {}
    for dim, _day, avg in rows:
        out.setdefault(dim, []).append(float(avg))
    return out


def _alerts(db: Path) -> list[dict]:
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    out: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT payload_json FROM events WHERE kind='meta_alert' "
            "AND json_extract(payload_json,'$.level')='critical' "
            "AND ts >= DATE('now','-7 days') ORDER BY ts DESC LIMIT 20"
        ).fetchall()
        for (pj,) in rows:
            try:
                out.append(json.loads(pj))
            except Exception:
                continue
    finally:
        conn.close()
    return out


def _spark(vals: list[float]) -> str:
    if not vals:
        return ""
    bars = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    lo, hi = min(vals), max(vals)
    rng = hi - lo if hi > lo else 1.0
    return "".join(bars[min(7, int((v - lo) / rng * 7))] for v in vals)


def _render_html(summary, timelines, pr, trends, alerts) -> str:
    rows_sum = (
        f"<tr><td>제안</td><td>{summary['proposed']}</td>"
        f"<td>표결</td><td>{summary['voted']}</td>"
        f"<td>적용</td><td>{summary['applied']}</td>"
        f"<td>롤백</td><td>{summary['rolled_back']}</td></tr>"
    )

    if not timelines:
        tl_html = '<p class="muted">데이터 없음</p>'
    else:
        parts = []
        for t in timelines:
            evs = "".join(
                f"<li>{e.get('ts','')} — {e.get('kind','')} — {e.get('note','')}</li>"
                for e in t["events"]
            )
            parts.append(f'<div class="target-timeline"><strong>{t["target"]}</strong><ul>{evs}</ul></div>')
        tl_html = "".join(parts)

    if trends:
        trend_html = "".join(
            f'<tr><td>{dim}</td><td class="spark">{_spark(vals)}</td></tr>'
            for dim, vals in trends.items()
        )
    else:
        trend_html = '<tr><td colspan="2" class="muted">데이터 없음</td></tr>'

    if alerts:
        alert_html = "".join(
            f'<div class="alert-critical">{a.get("message","(no message)")}</div>'
            for a in alerts
        )
    else:
        alert_html = '<p class="muted">미해결 경고 없음</p>'

    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<title>Meta Evolution Report</title>'
        f'<style>{_CSS}</style></head><body>'
        '<h1>Meta Evolution Report</h1>'
        '<p>Free Claw Router — 로컬 감사 뷰</p>'
        '<h2>24h 메타 활동 요약</h2>'
        f'<table>{rows_sum}</table>'
        '<h2>편집 대상별 제안 Timeline</h2>'
        f'{tl_html}'
        '<h2>자기수정 PR 상태</h2>'
        f"<p>열린 {len(pr['open'])} / 머지 {len(pr['merged'])} / 롤백 {len(pr['reverted'])}</p>"
        '<h2>평가 추이 (7일, score_dim별)</h2>'
        f'<table><tr><th>차원</th><th>sparkline</th></tr>{trend_html}</table>'
        '<h2>미해결 경고</h2>'
        f'{alert_html}'
        '</body></html>'
    )
