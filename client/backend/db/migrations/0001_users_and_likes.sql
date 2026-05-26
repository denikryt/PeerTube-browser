CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  username TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
  user_id TEXT NOT NULL,
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  video_uuid TEXT,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, video_id, instance_domain)
);
CREATE INDEX IF NOT EXISTS likes_user_updated_idx
  ON likes (user_id, updated_at DESC);
