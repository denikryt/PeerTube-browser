CREATE TABLE IF NOT EXISTS instance_denylist (
  host TEXT PRIMARY KEY,
  is_active INTEGER NOT NULL DEFAULT 1,
  reason TEXT,
  note TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instance_denylist_active
  ON instance_denylist (is_active, host);

CREATE TABLE IF NOT EXISTS channel_moderation (
  channel_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('blocked', 'allowed')),
  reason TEXT,
  source_video_url TEXT,
  updated_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (channel_id, instance_domain)
);
CREATE INDEX IF NOT EXISTS idx_channel_moderation_status_instance
  ON channel_moderation (status, instance_domain);
