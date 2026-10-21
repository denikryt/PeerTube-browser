/**
 * Runtime schema helpers for the TypeScript crawler database.
 *
 * The helpers apply the current schema.sql file and preserve the compatibility
 * migrations that used to live in db.ts. crawler database split moves ownership only; it must
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

export const CHANNEL_METADATA_V1_COLUMNS = [
  ["owner_account_username", "TEXT"],
  ["owner_account_display_name", "TEXT"],
  ["owner_account_url", "TEXT"],
  ["owner_account_avatar_url", "TEXT"]
] as const;

export const VIDEO_METADATA_V1_COLUMNS = [
  ["metadata_version", "INTEGER NOT NULL DEFAULT 0"],
  ["language", "TEXT"],
  ["language_label", "TEXT"],
  ["category_id", "TEXT"],
  ["licence_id", "TEXT"],
  ["licence", "TEXT"],
  ["sensitive_summary", "TEXT"],
  ["originally_published_at", "INTEGER"],
  ["updated_at", "INTEGER"],
  ["is_live", "INTEGER"],
  ["permanent_live", "INTEGER"],
  ["live_save_replay", "INTEGER"],
  ["aspect_ratio", "REAL"],
  ["support", "TEXT"],
  ["account_username", "TEXT"],
  ["account_avatar_url", "TEXT"],
  ["thumbnail_width", "INTEGER"],
  ["thumbnail_height", "INTEGER"]
] as const;

/** Thumbnail candidate storage has its own refresh lifecycle, not metadata-v1. */
export const VIDEO_THUMBNAIL_COLUMNS = [
  ["thumbnail_candidates_json", "TEXT"]
] as const;

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
  addMetadataV1Columns(db);
  addThumbnailCandidateColumns(db);
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
  const hasThumbnailCandidates = columns.includes("thumbnail_candidates_json");
  const hasThumbnailWidth = columns.includes("thumbnail_width");
  const hasThumbnailHeight = columns.includes("thumbnail_height");

  const lastErrorExpr = hasLastError ? "last_error" : "NULL";
  const lastErrorAtExpr = hasLastErrorAt ? "last_error_at" : "NULL";
  const errorCountExpr = hasErrorCount ? "error_count" : "0";
  const invalidReasonExpr = hasInvalidReason ? "invalid_reason" : "NULL";
  const invalidAtExpr = hasInvalidAt ? "invalid_at" : "NULL";
  const thumbnailCandidatesExpr = hasThumbnailCandidates
    ? "thumbnail_candidates_json"
    : "NULL";
  const thumbnailWidthExpr = hasThumbnailWidth ? "thumbnail_width" : "NULL";
  const thumbnailHeightExpr = hasThumbnailHeight ? "thumbnail_height" : "NULL";

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
      thumbnail_candidates_json TEXT,
      thumbnail_width INTEGER,
      thumbnail_height INTEGER,
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
      thumbnail_candidates_json,
      thumbnail_width,
      thumbnail_height,
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
      ${thumbnailCandidatesExpr},
      ${thumbnailWidthExpr},
      ${thumbnailHeightExpr},
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


/**
 * Add metadata-v1 columns after legacy layout rebuilds. These ALTERs are
 * intentionally additive so existing crawler data is preserved verbatim.
 */
function addMetadataV1Columns(db: Database.Database) {
  addMissingColumns(db, "channels", CHANNEL_METADATA_V1_COLUMNS);
  addMissingColumns(db, "videos", VIDEO_METADATA_V1_COLUMNS);
}

/** Add crawler-owned thumbnail candidate storage without metadata-version coupling. */
function addThumbnailCandidateColumns(db: Database.Database) {
  addMissingColumns(db, "videos", VIDEO_THUMBNAIL_COLUMNS);
}

/**
 * Validate metadata-maintenance schema without applying crawler migrations.
 * Production callers must run migrate-whitelist.py before this data operation.
 */
export function assertMetadataMaintenanceSchema(dbPath: string) {
  const db = new Database(dbPath, { readonly: true, fileMustExist: true });
  try {
    assertRequiredColumns(db, "videos", [
      "video_id",
      "video_uuid",
      "instance_domain",
      ...VIDEO_METADATA_V1_COLUMNS.map(([name]) => name)
    ]);
    assertRequiredColumns(db, "channels", [
      "channel_id",
      "instance_domain",
      ...CHANNEL_METADATA_V1_COLUMNS.map(([name]) => name)
    ]);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `${message} Run engine/server/db/jobs/migrate-whitelist.py before metadata backfill.`
    );
  } finally {
    db.close();
  }
}

/** Validate thumbnail maintenance prerequisites without mutating production schema. */
export function assertThumbnailMaintenanceSchema(dbPath: string) {
  const db = new Database(dbPath, { readonly: true, fileMustExist: true });
  try {
    assertRequiredColumns(db, "videos", [
      "video_id",
      "video_uuid",
      "instance_domain",
      "thumbnail_candidates_json",
      "thumbnail_url",
      "thumbnail_width",
      "thumbnail_height"
    ]);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `${message} Run engine/server/db/jobs/migrate-whitelist.py before thumbnail refresh.`
    );
  } finally {
    db.close();
  }
}

/** Assert one table contains current metadata-maintenance columns and key fields. */
function assertRequiredColumns(db: Database.Database, table: string, required: readonly string[]) {
  const rows = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string; pk: number }>;
  if (rows.length === 0) throw new Error(`Missing required table ${table}.`);
  const columns = new Set(rows.map((row) => row.name));
  const missing = required.filter((column) => !columns.has(column));
  if (missing.length > 0) {
    throw new Error(`Metadata schema for ${table} is missing: ${missing.join(", ")}.`);
  }
  const keyColumns = rows.filter((row) => row.pk > 0).map((row) => row.name);
  const expectedKeys = table === "videos"
    ? ["video_id", "instance_domain"]
    : ["channel_id", "instance_domain"];
  if (expectedKeys.some((key) => !keyColumns.includes(key))) {
    throw new Error(`Metadata schema for ${table} has incompatible primary key.`);
  }
}

/** Add only known columns that are absent from an existing current-shape table. */
function addMissingColumns(
  db: Database.Database,
  table: string,
  columns: ReadonlyArray<readonly [string, string]>
) {
  if (!tableExists(db, table)) return;
  const existing = new Set(getColumns(db, table));
  for (const [name, ddl] of columns) {
    if (existing.has(name)) continue;
    db.exec(`ALTER TABLE ${table} ADD COLUMN ${name} ${ddl}`);
    existing.add(name);
  }
}
