CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  scope TEXT NOT NULL,
  robot_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('ACTIVE', 'RESOLVED')),
  severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARNING', 'CRITICAL')),
  payload_json TEXT NOT NULL,
  acknowledged_at TEXT,
  acknowledged_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(code, scope)
);

CREATE INDEX IF NOT EXISTS alerts_state_updated ON alerts(state, updated_at DESC);
