CREATE TABLE IF NOT EXISTS active_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL,
  values_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO active_settings(id, version, values_json, updated_at) VALUES
  (1, 1, '{"active_map_id":"mock_lab","follow_distance_m":0.8,"follow_tolerance_m":0.2,"max_linear_mps":0.15,"max_angular_rps":0.5,"camera_quality":"default"}', CURRENT_TIMESTAMP);
