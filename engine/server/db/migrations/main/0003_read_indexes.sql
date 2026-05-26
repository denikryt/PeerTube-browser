-- target_table: channels
CREATE INDEX IF NOT EXISTS idx_channels_followers_videos_name
  ON channels (followers_count DESC, videos_count DESC, channel_name ASC);
-- target_table: channels
CREATE INDEX IF NOT EXISTS idx_channels_videos
  ON channels (videos_count DESC);
-- target_table: channels
CREATE INDEX IF NOT EXISTS idx_channels_name
  ON channels (channel_name);
-- target_table: channels
CREATE INDEX IF NOT EXISTS idx_channels_instance
  ON channels (instance_domain);

-- target_table: videos
CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance
  ON videos (video_uuid, instance_domain);
-- target_table: videos
CREATE INDEX IF NOT EXISTS idx_videos_id_instance
  ON videos (video_id, instance_domain);

-- target_table: video_embeddings
CREATE INDEX IF NOT EXISTS idx_video_embeddings_id_instance
  ON video_embeddings (video_id, instance_domain);
