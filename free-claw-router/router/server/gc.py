"""Store garbage collection with two-phase (dry-run + commit) safety.

Retention policy (overridable via env):
    spans:                   30 days (FCR_GC_SPAN_DAYS)
    events:                  90 days (FCR_GC_EVENT_DAYS)
    evaluations:             180 days (FCR_GC_EVAL_DAYS)
    suggestions (applied):   30 days (FCR_GC_SUGGESTION_DAYS)
    suggestions (rejected):  7 days  (FCR_GC_SUGGESTION_REJECTED_DAYS)
    pending suggestions:     retained indefinitely

FCR_GC_DRY_RUN=1 reports counts without deleting.
FCR_GC_PAUSED=1 disables GC entirely (audit mode).
"""
from __future__ import annotations
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class GcConfig:
    span_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SPAN_DAYS", "30")))
    event_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_EVENT_DAYS", "90")))
    eval_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_EVAL_DAYS", "180")))
    sug_applied_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SUGGESTION_DAYS", "30")))
    sug_rejected_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SUGGESTION_REJECTED_DAYS", "7")))
    dry_run: bool = field(default_factory=lambda: os.getenv("FCR_GC_DRY_RUN", "0") == "1")
    paused: bool = field(default_factory=lambda: os.getenv("FCR_GC_PAUSED", "0") == "1")


def _iso_cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def run_gc(db_path: Path, suggestions_path: Path, cfg: GcConfig) -> dict:
    """Run one GC pass. Returns stats dict.

    In dry_run mode, returns `*_would_delete` counts without deleting.
    In committed mode, records a `gc_run` event with stats.
    """
    if cfg.paused:
        return {"paused": True}

    stats: dict = {
        "spans_deleted": 0,
        "events_deleted": 0,
        "evals_deleted": 0,
        "suggestions_deleted": 0,
        "spans_would_delete": 0,
        "events_would_delete": 0,
        "evals_would_delete": 0,
        "suggestions_would_delete": 0,
    }

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            if cfg.dry_run:
                stats["spans_would_delete"] = conn.execute(
                    "SELECT COUNT(*) FROM spans WHERE started_at < ?",
                    (_iso_cutoff(cfg.span_days),),
                ).fetchone()[0]
                stats["events_would_delete"] = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE ts < ?",
                    (_iso_cutoff(cfg.event_days),),
                ).fetchone()[0]
                stats["evals_would_delete"] = conn.execute(
                    "SELECT COUNT(*) FROM evaluations WHERE ts < ?",
                    (_iso_cutoff(cfg.eval_days),),
                ).fetchone()[0]
            else:
                cur = conn.execute("DELETE FROM spans WHERE started_at < ?",
                                   (_iso_cutoff(cfg.span_days),))
                stats["spans_deleted"] = cur.rowcount or 0
                cur = conn.execute("DELETE FROM events WHERE ts < ?",
                                   (_iso_cutoff(cfg.event_days),))
                stats["events_deleted"] = cur.rowcount or 0
                cur = conn.execute("DELETE FROM evaluations WHERE ts < ?",
                                   (_iso_cutoff(cfg.eval_days),))
                stats["evals_deleted"] = cur.rowcount or 0
                conn.execute(
                    "INSERT INTO events(span_id, kind, payload_json, ts) "
                    "VALUES (NULL, 'gc_run', ?, ?)",
                    (json.dumps(stats), datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        finally:
            conn.close()

    if suggestions_path.exists():
        lines = suggestions_path.read_text(encoding="utf-8").splitlines()
        kept: list[str] = []
        would_delete = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            ts = rec.get("ts", "")
            status = rec.get("status", "pending")
            if status == "applied" and ts < _iso_cutoff(cfg.sug_applied_days):
                would_delete += 1
                if cfg.dry_run:
                    kept.append(line)
                continue
            if status == "rejected" and ts < _iso_cutoff(cfg.sug_rejected_days):
                would_delete += 1
                if cfg.dry_run:
                    kept.append(line)
                continue
            kept.append(line)

        if cfg.dry_run:
            stats["suggestions_would_delete"] = would_delete
        else:
            stats["suggestions_deleted"] = would_delete
            content = "\n".join(kept)
            if content:
                content += "\n"
            suggestions_path.write_text(content, encoding="utf-8")

    return stats
