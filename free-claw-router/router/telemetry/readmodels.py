from __future__ import annotations
from router.telemetry.store import Store

def skill_model_affinity(store: Store, *, skill_id: str | None = None) -> list[dict]:
    maybe_filter = "AND s.skill_id = ?" if skill_id else ""
    q = f"""
      SELECT s.skill_id, s.model_id,
             COUNT(*) AS trials,
             AVG(CASE WHEN s.status='ok' THEN 1.0 ELSE 0.0 END) AS success_rate,
             AVG(e.score_value) AS avg_score
      FROM spans s
      LEFT JOIN evaluations e ON e.span_id = s.span_id AND e.score_dim = 'format_correctness'
      WHERE s.skill_id IS NOT NULL
      {maybe_filter}
      GROUP BY s.skill_id, s.model_id
      ORDER BY trials DESC
    """
    args = (skill_id,) if skill_id else ()
    with store.connect() as c:
        cur = c.execute(q, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

def quota_health(store: Store) -> list[dict]:
    q = """
      SELECT provider_id, model_id,
             COUNT(*) AS requests,
             AVG(CASE WHEN status LIKE 'http_429%' THEN 1.0 ELSE 0.0 END) AS rate_limited_fraction
      FROM spans
      WHERE provider_id IS NOT NULL
      GROUP BY provider_id, model_id
    """
    with store.connect() as c:
        cur = c.execute(q)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
