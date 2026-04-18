"""Store garbage collection with two-phase (dry-run + commit) safety.

Retention policy (overridable via env):
    spans:        30 days  (FCR_GC_SPAN_DAYS)
    events:       90 days  (FCR_GC_EVENT_DAYS)
    evaluations:  180 days (FCR_GC_EVAL_DAYS)
    suggestions:  30 days  (FCR_GC_SUGGESTION_DAYS)

FCR_GC_DRY_RUN=1 reports counts without deleting.
FCR_GC_PAUSED=1 disables GC entirely (audit mode).

The suggestion store is the canonical ``meta_suggestions.json`` (JSON array
of MetaSuggestion records written by ``SuggestionStore``). MetaSuggestion
has no status field — retention is purely age-based on ``timestamp``
(float Unix seconds).
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class GcConfig:
    span_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SPAN_DAYS", "30")))
    event_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_EVENT_DAYS", "90")))
    eval_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_EVAL_DAYS", "180")))
    sug_applied_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SUGGESTION_DAYS", "30")))
    dry_run: bool = field(default_factory=lambda: os.getenv("FCR_GC_DRY_RUN", "0") == "1")
    paused: bool = field(default_factory=lambda: os.getenv("FCR_GC_PAUSED", "0") == "1")


def _iso_cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _epoch_cutoff(days: int) -> float:
    return time.time() - days * 86400


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
        try:
            raw = json.loads(suggestions_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = []
        if not isinstance(raw, list):
            raw = []

        cutoff = _epoch_cutoff(cfg.sug_applied_days)
        kept_items: list[dict] = []
        would_delete = 0
        for rec in raw:
            if not isinstance(rec, dict):
                kept_items.append(rec)
                continue
            ts = rec.get("timestamp")
            try:
                ts_f = float(ts)
            except (TypeError, ValueError):
                # Unparseable timestamp — keep the record (safe default).
                kept_items.append(rec)
                continue
            if ts_f < cutoff:
                would_delete += 1
                if cfg.dry_run:
                    kept_items.append(rec)
                continue
            kept_items.append(rec)

        if cfg.dry_run:
            stats["suggestions_would_delete"] = would_delete
        else:
            stats["suggestions_deleted"] = would_delete
            suggestions_path.parent.mkdir(parents=True, exist_ok=True)
            suggestions_path.write_text(json.dumps(kept_items, indent=2), encoding="utf-8")

    return stats
