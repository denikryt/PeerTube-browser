CREATE TABLE IF NOT EXISTS similarity_sources (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  computed_at INTEGER NOT NULL,
  PRIMARY KEY (video_id, instance_domain)
);
CREATE TABLE IF NOT EXISTS similarity_items (
  source_video_id TEXT NOT NULL,
  source_instance_domain TEXT NOT NULL,
  similar_video_id TEXT NOT NULL,
  similar_instance_domain TEXT NOT NULL,
  score REAL,
  rank INTEGER NOT NULL,
  PRIMARY KEY (
    source_video_id,
    source_instance_domain,
    similar_video_id,
    similar_instance_domain
  )
);
CREATE INDEX IF NOT EXISTS similarity_source_rank_idx
  ON similarity_items (source_video_id, source_instance_domain, rank);
