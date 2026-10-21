/**
 * Runtime schema helpers for the TypeScript crawler database.
 *
 * The helpers apply the current schema.sql file and preserve the compatibility
 * migrations that used to live in db.ts. Stage 7 moves ownership only; it must
 * not change table, column, index, or compatibility migration behavior.
 */

import fs from "node:fs";
import Database from "better-sqlite3";

const schemaSql = fs.readFileSync(new URL("../../schema.sql", import.meta.url), "utf8");

const DEPRECATED_INSTANCE_COLUMNS = new Set([
  "status",
  "invalid_reason",
  "invalid_at",
  "last_success_at",
  "consecutive_failures",
  "last_processed_at",
  "error_count"
]);

const DEPRECATED_CHANNEL_COLUMNS = new Set([
  "last_checked_at",
  "videos_count_error",
  "videos_count_error_at"
]);

/**
 * Handle get columns.
 */
function getColumns(db: Database.Database, table: string): string[] {
  return db
    .prepare(`PRAGMA table_info(${table})`)
    .all()
    .map((row: unknown) => (row as { name: string }).name);
}

/**
 * Handle table exists.
 */
function tableExists(db: Database.Database, table: string): boolean {
  const row = db
    .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?")
    .get(table) as { name: string } | undefined;
  return Boolean(row?.name);
}

/**
 * Handle apply base schema.
 */
export function applyBaseSchema(db: Database.Database) {
  db.exec(schemaSql);
  migrateInstances(db);
  migrateChannels(db);
  migrateVideos(db);
  db.exec(schemaSql);
}

/**
 * Handle migrate instances.
 */
function migrateInstances(db: Database.Database) {
  if (!tableExists(db, "instances")) return;
  const columns = getColumns(db, "instances");
  const needsRebuild =
    columns.some((column) => DEPRECATED_INSTANCE_COLUMNS.has(column)) ||
    !columns.includes("health_status") ||
    !columns.includes("health_checked_at") ||
    !columns.includes("health_error") ||
    !columns.includes("last_error") ||
    !columns.includes("last_error_at") ||
    !columns.includes("last_error_source");
  if (!needsRebuild) return;

  const hasStatus = columns.includes("status");
  const hasHealthStatus = columns.includes("health_status");
  const hasHealthCheckedAt = columns.includes("health_checked_at");
  const hasHealthError = columns.includes("health_error");
  const hasInvalidReason = columns.includes("invalid_reason");
  const hasInvalidAt = columns.includes("invalid_at");
  const hasLastError = columns.includes("last_error");
  const hasLastErrorAt = columns.includes("last_error_at");
  const hasLastErrorSource = columns.includes("last_error_source");
  const hasErrorCount = columns.includes("error_count");
  const hasLastProcessedAt = columns.includes("last_processed_at");

  const healthStatusExpr = hasHealthStatus
    ? "health_status"
    : hasStatus
      ? "CASE status WHEN 'done' THEN 'ok' WHEN 'error' THEN 'error' ELSE 'unknown' END"
      : "NULL";
  const healthCheckedAtExpr = hasHealthCheckedAt
    ? "health_checked_at"
    : hasInvalidAt
      ? "invalid_at"
      : "NULL";
  const healthErrorExpr = hasHealthError
    ? "health_error"
    : hasInvalidReason
      ? "invalid_reason"
      : "NULL";
  const lastErrorExpr = hasLastError ? "last_error" : "NULL";
  const lastErrorAtExpr = hasLastErrorAt ? "last_error_at" : "NULL";
  const lastErrorSourceExpr = hasLastErrorSource ? "last_error_source" : "NULL";
  const progressStatusExpr = hasStatus ? "status" : "'pending'";
  const progressErrorCountExpr = hasErrorCount ? "error_count" : "0";
  const progressUpdatedAtExpr = hasLastProcessedAt ? "last_processed_at" : "0";

  db.exec(`
    CREATE TABLE IF NOT EXISTS instances_new (
      host TEXT PRIMARY KEY,
      health_status TEXT,
      health_checked_at INTEGER,
      health_error TEXT,
      last_error TEXT,
      last_error_at INTEGER,
      last_error_source TEXT
    );
    INSERT INTO instances_new (
      host,
      health_status,
      health_checked_at,
      health_error,
      last_error,
      last_error_at,
      last_error_source
    )
    SELECT
      host,
      ${healthStatusExpr},
      ${healthCheckedAtExpr},
      ${healthErrorExpr},
      ${lastErrorExpr},
      ${lastErrorAtExpr},
      ${lastErrorSourceExpr}
    FROM instances;
    INSERT OR IGNORE INTO instance_crawl_progress (
      host,
      status,
      error_count,
      last_start,
      updated_at
    )
    SELECT
      host,
      ${progressStatusExpr},
      ${progressErrorCountExpr},
      0,
      ${progressUpdatedAtExpr}
    FROM instances;
    DROP TABLE instances;
    ALTER TABLE instances_new RENAME TO instances;
  `);
}

/**
 * Handle migrate channels.
 */
function migrateChannels(db: Database.Database) {
  if (!tableExists(db, "channels")) return;
  const columns = getColumns(db, "channels");
  const needsRebuild =
    columns.some((column) => DEPRECATED_CHANNEL_COLUMNS.has(column)) ||
    !columns.includes("health_status") ||
    !columns.includes("health_checked_at") ||
    !columns.includes("health_error") ||
    !columns.includes("last_error") ||
    !columns.includes("last_error_at") ||
    !columns.includes("last_error_source");
  if (!needsRebuild) return;

  const hasHealthStatus = columns.includes("health_status");
  const hasHealthCheckedAt = columns.includes("health_checked_at");
  const hasHealthError = columns.includes("health_error");
  const hasLastError = columns.includes("last_error");
  const hasLastErrorAt = columns.includes("last_error_at");
  const hasLastErrorSource = columns.includes("last_error_source");
  const hasLastCheckedAt = columns.includes("last_checked_at");
  const hasVideosCountError = columns.includes("videos_count_error");
  const hasVideosCountErrorAt = columns.includes("videos_count_error_at");

  const healthStatusExpr = hasHealthStatus ? "health_status" : "NULL";
  const healthCheckedAtExpr = hasHealthCheckedAt
    ? "health_checked_at"
    : hasLastCheckedAt
      ? "last_checked_at"
      : "NULL";
  const healthErrorExpr = hasHealthError ? "health_error" : "NULL";
  const lastErrorExpr = hasLastError
    ? "last_error"
    : hasVideosCountError
      ? "videos_count_error"
      : "NULL";
  const lastErrorAtExpr = hasLastErrorAt
    ? "last_error_at"
    : hasVideosCountErrorAt
      ? "videos_count_error_at"
      : "NULL";
  const lastErrorSourceExpr = hasLastErrorSource
    ? "last_error_source"
    : hasVideosCountError
      ? "CASE WHEN videos_count_error IS NOT NULL THEN 'videos_count' END"
      : "NULL";

  db.exec(`
    CREATE TABLE IF NOT EXISTS channels_new (
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
    INSERT INTO channels_new (
      channel_id,
      channel_name,
      channel_url,
      display_name,
      instance_domain,
      videos_count,
      followers_count,
      avatar_url,
      health_status,
      health_checked_at,
      health_error,
      last_error,
      last_error_at,
      last_error_source
    )
    SELECT
      channel_id,
      channel_name,
      channel_url,
      display_name,
      instance_domain,
      videos_count,
      followers_count,
      avatar_url,
      ${healthStatusExpr},
      ${healthCheckedAtExpr},
      ${healthErrorExpr},
      ${lastErrorExpr},
      ${lastErrorAtExpr},
      ${lastErrorSourceExpr}
    FROM channels;
    DROP TABLE channels;
    ALTER TABLE channels_new RENAME TO channels;
  `);
}

/**
 * Handle migrate videos.
 */
function migrateVideos(db: Database.Database) {
  if (!tableExists(db, "videos")) return;
  const columns = getColumns(db, "videos");
  const needsRebuild =
    !columns.includes("last_error") ||
    !columns.includes("last_error_at") ||
    !columns.includes("error_count");
  if (!needsRebuild) return;

  const hasLastError = columns.includes("last_error");
  const hasLastErrorAt = columns.includes("last_error_at");
  const hasErrorCount = columns.includes("error_count");
  const hasInvalidReason = columns.includes("invalid_reason");
  const hasInvalidAt = columns.includes("invalid_at");

  const lastErrorExpr = hasLastError ? "last_error" : "NULL";
  const lastErrorAtExpr = hasLastErrorAt ? "last_error_at" : "NULL";
  const errorCountExpr = hasErrorCount ? "error_count" : "0";
  const invalidReasonExpr = hasInvalidReason ? "invalid_reason" : "NULL";
  const invalidAtExpr = hasInvalidAt ? "invalid_at" : "NULL";

  db.exec(`
    CREATE TABLE IF NOT EXISTS videos_new (
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
    INSERT INTO videos_new (
      video_id,
      video_uuid,
      video_numeric_id,
      instance_domain,
      channel_id,
      channel_name,
      channel_url,
      account_name,
      account_url,
      title,
      description,
      tags_json,
      category,
      published_at,
      video_url,
      duration,
      thumbnail_url,
      embed_path,
      views,
      likes,
      dislikes,
      comments_count,
      nsfw,
      preview_path,
      last_checked_at,
      last_error,
      last_error_at,
      error_count,
      invalid_reason,
      invalid_at
    )
    SELECT
      video_id,
      video_uuid,
      video_numeric_id,
      instance_domain,
      channel_id,
      channel_name,
      channel_url,
      account_name,
      account_url,
      title,
      description,
      tags_json,
      category,
      published_at,
      video_url,
      duration,
      thumbnail_url,
      embed_path,
      views,
      likes,
      dislikes,
      comments_count,
      nsfw,
      preview_path,
      last_checked_at,
      ${lastErrorExpr},
      ${lastErrorAtExpr},
      ${errorCountExpr},
      ${invalidReasonExpr},
      ${invalidAtExpr}
    FROM videos;
    DROP TABLE videos;
    ALTER TABLE videos_new RENAME TO videos;
  `);
}
