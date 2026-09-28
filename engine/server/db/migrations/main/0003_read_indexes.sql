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

-- target_table: videos
-- target_columns: language
CREATE INDEX IF NOT EXISTS idx_videos_language_normalized
  ON videos (NULLIF(lower(trim(language)), ''));
-- target_table: videos
-- target_columns: category
CREATE INDEX IF NOT EXISTS idx_videos_category_normalized
  ON videos (lower(trim(category)));
-- target_table: videos
-- target_columns: instance_domain
CREATE INDEX IF NOT EXISTS idx_videos_instance_normalized
  ON videos (lower(trim(instance_domain)));

-- target_table: videos
-- target_columns: published_at, instance_domain, video_id
CREATE INDEX IF NOT EXISTS idx_videos_fresh_order
  ON videos (
    CASE WHEN published_at IS NULL THEN 1 ELSE 0 END ASC,
    COALESCE(published_at, 0) DESC,
    instance_domain ASC,
    video_id ASC
  );
-- target_table: videos
-- target_columns: popularity, instance_domain, video_id
CREATE INDEX IF NOT EXISTS idx_videos_trending_order
  ON videos (
    popularity DESC,
    instance_domain ASC,
    video_id ASC
  );

-- target_table: videos
DROP INDEX IF EXISTS main.idx_videos_popularity;
