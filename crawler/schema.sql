CREATE TABLE IF NOT EXISTS instances (
  host TEXT PRIMARY KEY,
  health_status TEXT,
  health_checked_at INTEGER,
  health_error TEXT,
  last_error TEXT,
  last_error_at INTEGER,
  last_error_source TEXT
);

CREATE TABLE IF NOT EXISTS channels (
  channel_id TEXT NOT NULL,
  channel_name TEXT,
  channel_url TEXT,
  display_name TEXT,
  instance_domain TEXT NOT NULL,
  videos_count INTEGER,
  followers_count INTEGER,
  avatar_url TEXT,
  health_status TEXT,
  health_checked_at INTEGER,
  health_error TEXT,
  last_error TEXT,
  last_error_at INTEGER,
  last_error_source TEXT,
  PRIMARY KEY (channel_id, instance_domain)
);

CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT NOT NULL,
  video_uuid TEXT,
  video_numeric_id INTEGER,
  instance_domain TEXT NOT NULL,
  channel_id TEXT,
  channel_name TEXT,
  channel_url TEXT,
  account_name TEXT,
  account_url TEXT,
  title TEXT,
  description TEXT,
  tags_json TEXT,
  category TEXT,
  published_at INTEGER,
  video_url TEXT,
  duration INTEGER,
  thumbnail_url TEXT,
  embed_path TEXT,
  views INTEGER,
  likes INTEGER,
  dislikes INTEGER,
  comments_count INTEGER,
  nsfw INTEGER,
  preview_path TEXT,
  last_checked_at INTEGER NOT NULL,
  last_error TEXT,
  last_error_at INTEGER,
  error_count INTEGER NOT NULL DEFAULT 0,
  invalid_reason TEXT,
  invalid_at INTEGER,
  PRIMARY KEY (video_id, instance_domain)
);

CREATE TABLE IF NOT EXISTS instance_crawl_progress (
  host TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  error_count INTEGER NOT NULL DEFAULT 0,
  last_start INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_crawl_progress (
  instance_domain TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  last_start INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS video_crawl_progress (
  instance_domain TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  channel_name TEXT,
  status TEXT NOT NULL,
  last_start INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  last_error_at INTEGER,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (instance_domain, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_channels_followers ON channels (followers_count);
CREATE INDEX IF NOT EXISTS idx_channels_videos ON channels (videos_count);
CREATE INDEX IF NOT EXISTS idx_channels_instance ON channels (instance_domain);

CREATE INDEX IF NOT EXISTS idx_videos_instance ON videos (instance_domain);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos (channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_published ON videos (published_at);
CREATE INDEX IF NOT EXISTS idx_videos_views ON videos (views);
CREATE INDEX IF NOT EXISTS idx_video_progress_instance ON video_crawl_progress (instance_domain);
