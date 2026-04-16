from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolDegradationTrigger:
    """Reads evaluations from telemetry.db, detects tool success rate drops."""

    def __init__(self, *, telemetry_store, skill_bridge) -> None:
        self._telemetry = telemetry_store
        self._bridge = skill_bridge

    def check(self) -> list[str]:
        try:
            with self._telemetry.connect() as c:
                rows = list(c.execute("""
                    SELECT score_dim, AVG(score_value) as avg_score
                    FROM evaluations
                    WHERE ts > (strftime('%s', 'now') * 1000 - 3600000)
                    GROUP BY score_dim
                    HAVING avg_score < 0.7
                """))
            degraded = [r[0] for r in rows]
            if degraded:
                logger.info("Tool degradation detected: %s", degraded)
            return degraded
        except Exception:
            logger.warning("Tool degradation check failed", exc_info=True)
            return []


class MetricMonitorTrigger:
    """Reads skill metrics from openspace.db, flags underperformers."""

    def __init__(self, *, skill_bridge) -> None:
        self._bridge = skill_bridge

    def check(self) -> list[dict]:
        try:
            skills = self._bridge.store.load_all()
            flagged = []
            for skill_id, skill in skills.items():
                applied = getattr(skill, "applied_count", 0) or 0
                errors = getattr(skill, "error_count", 0) or 0
                if applied > 0 and errors / (applied + 1) > 0.3:
                    flagged.append({"skill_id": skill_id, "error_rate": errors / applied})
                    logger.info("Flagged underperforming skill: %s (%.0f%% errors)", skill_id, 100 * errors / applied)
            return flagged
        except Exception:
            logger.warning("Metric monitor check failed", exc_info=True)
            return []


def register_trigger_jobs(scheduler, *, telemetry_store, skill_bridge) -> None:
    degradation = ToolDegradationTrigger(telemetry_store=telemetry_store, skill_bridge=skill_bridge)
    metrics = MetricMonitorTrigger(skill_bridge=skill_bridge)

    scheduler.add_job(degradation.check, "interval", minutes=15, id="skill_tool_degradation")
    scheduler.add_job(metrics.check, "interval", minutes=30, id="skill_metric_monitor")
    logger.info("Registered skill evolution trigger jobs")
