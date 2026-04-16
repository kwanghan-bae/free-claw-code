CREATE TABLE IF NOT EXISTS traces(
  trace_id BLOB PRIMARY KEY,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  root_op TEXT NOT NULL,
  root_session_id TEXT,
  catalog_version TEXT NOT NULL,
  policy_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spans(
  span_id BLOB PRIMARY KEY,
  trace_id BLOB NOT NULL REFERENCES traces(trace_id),
  parent_span_id BLOB,
  op_name TEXT NOT NULL,
  model_id TEXT,
  provider_id TEXT,
  skill_id TEXT,
  task_type TEXT,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  duration_ms INTEGER,
  status TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_model_skill ON spans(model_id, skill_id);
CREATE INDEX IF NOT EXISTS idx_spans_task ON spans(task_type, started_at);

CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY,
  span_id BLOB NOT NULL REFERENCES spans(span_id),
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_span ON events(span_id);

CREATE TABLE IF NOT EXISTS evaluations(
  id INTEGER PRIMARY KEY,
  span_id BLOB NOT NULL REFERENCES spans(span_id),
  evaluator TEXT NOT NULL,
  score_dim TEXT NOT NULL,
  score_value REAL NOT NULL,
  rationale TEXT,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evals_span ON evaluations(span_id);
CREATE INDEX IF NOT EXISTS idx_evals_dim ON evaluations(score_dim, ts);
