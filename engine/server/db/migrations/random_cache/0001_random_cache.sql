CREATE TABLE IF NOT EXISTS random_cache_meta (
  singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
  schema_version INTEGER NOT NULL,
  build_id TEXT NOT NULL,
  built_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS random_index_ids (
  position INTEGER PRIMARY KEY,
  index_id INTEGER NOT NULL UNIQUE
);
