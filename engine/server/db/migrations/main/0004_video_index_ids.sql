CREATE TABLE IF NOT EXISTS video_index_ids (
  index_id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  retired_at INTEGER,
  retired_reason TEXT,
  UNIQUE (video_id, instance_domain)
);

CREATE INDEX IF NOT EXISTS idx_video_index_ids_active
  ON video_index_ids (is_active, index_id);

CREATE INDEX IF NOT EXISTS idx_video_index_ids_identity
  ON video_index_ids (video_id, instance_domain);
