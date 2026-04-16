from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import sqlite3

MIGRATIONS = Path(__file__).parent / "migrations"

class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as c:
            for f in sorted(MIGRATIONS.glob("*.sql")):
                c.executescript(f.read_text())

    def insert_trace(self, *, trace_id: bytes, started_at_ms: int, root_op: str,
                     root_session_id: str | None, catalog_version: str, policy_version: str) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO traces(trace_id, started_at, root_op, root_session_id, catalog_version, policy_version) VALUES(?,?,?,?,?,?)",
                (trace_id, started_at_ms, root_op, root_session_id, catalog_version, policy_version))

    def insert_span(self, *, span_id: bytes, trace_id: bytes, parent_span_id: bytes | None,
                    op_name: str, model_id: str | None, provider_id: str | None,
                    skill_id: str | None, task_type: str | None, started_at_ms: int) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO spans(span_id, trace_id, parent_span_id, op_name, model_id, provider_id, skill_id, task_type, started_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (span_id, trace_id, parent_span_id, op_name, model_id, provider_id, skill_id, task_type, started_at_ms))

    def close_span(self, span_id: bytes, *, ended_at_ms: int, duration_ms: int, status: str) -> None:
        with self.connect() as c:
            c.execute("UPDATE spans SET ended_at=?, duration_ms=?, status=? WHERE span_id=?",
                      (ended_at_ms, duration_ms, status, span_id))

    def insert_event(self, *, span_id: bytes, kind: str, payload_json: str, ts_ms: int) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO events(span_id, kind, payload_json, ts) VALUES(?,?,?,?)",
                      (span_id, kind, payload_json, ts_ms))

    def insert_evaluation(self, *, span_id: bytes, evaluator: str, score_dim: str,
                          score_value: float, rationale: str | None, ts_ms: int) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO evaluations(span_id, evaluator, score_dim, score_value, rationale, ts) VALUES(?,?,?,?,?,?)",
                      (span_id, evaluator, score_dim, score_value, rationale, ts_ms))
