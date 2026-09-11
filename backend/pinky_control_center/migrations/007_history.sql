CREATE TABLE IF NOT EXISTS history_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  robot_id TEXT,
  mission_id TEXT,
  occurred_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS history_dedupe_key ON history_events(json_extract(payload_json, '$._dedupe_key')) WHERE json_extract(payload_json, '$._dedupe_key') IS NOT NULL;
CREATE INDEX IF NOT EXISTS history_owner_time ON history_events(user_id, occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS history_filter_time ON history_events(event_type, robot_id, mission_id, occurred_at DESC, id DESC);
