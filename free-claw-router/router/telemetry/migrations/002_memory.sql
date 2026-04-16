CREATE TABLE IF NOT EXISTS wing_mappings(
  workspace_path TEXT PRIMARY KEY,
  wing_name TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS mining_state(
  trace_id BLOB PRIMARY KEY,
  last_mined_event_ts INTEGER NOT NULL,
  last_mined_at INTEGER NOT NULL
);
