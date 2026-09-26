CREATE TABLE IF NOT EXISTS interaction_raw_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  actor_id TEXT,
  video_uuid TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  canonical_url TEXT,
  source_instance TEXT,
  published_at INTEGER NOT NULL,
  raw_payload_json TEXT,
  ingested_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS interaction_raw_events_video_idx
  ON interaction_raw_events (video_uuid, instance_domain, published_at DESC);

CREATE TABLE IF NOT EXISTS interaction_signals (
  video_uuid TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  likes_count INTEGER NOT NULL DEFAULT 0,
  undo_likes_count INTEGER NOT NULL DEFAULT 0,
  comments_count INTEGER NOT NULL DEFAULT 0,
  signal_score REAL NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (video_uuid, instance_domain)
);
