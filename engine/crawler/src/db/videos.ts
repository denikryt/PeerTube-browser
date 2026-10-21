/**
 * Video crawl persistence for the TypeScript crawler.
 *
 * VideoStore owns video rows, video progress, tags/comments updates, and
 * invalid/error recording. PeerTube request behavior remains in videos-worker.ts.
 */

import Database from "better-sqlite3";

import { openCrawlerDatabase } from "./connection.js";
import { applyBaseSchema } from "./schema.js";
import { deleteInstancesInChunks } from "./utils.js";
import type {
  VideoChannelRow,
  VideoCrawlStatus,
  VideoProgressRow,
  VideoStoreOptions,
  VideoTagRow,
  VideoUpsertRow
} from "./types.js";

export class VideoStore {
  private db: Database.Database;
  private upsertStmt: Database.Statement;
  private state = new Map<string, string>();

  /**
   * Initialize the instance.
   */
  constructor(options: VideoStoreOptions) {
    this.db = openCrawlerDatabase(options.dbPath);
    this.initSchema();
    this.upsertStmt = this.db.prepare(
      `INSERT INTO videos (
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
        error_count
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0)
      ON CONFLICT(video_id, instance_domain) DO UPDATE SET
        video_uuid = excluded.video_uuid,
        video_numeric_id = excluded.video_numeric_id,
        channel_id = excluded.channel_id,
        channel_name = excluded.channel_name,
        channel_url = excluded.channel_url,
        account_name = excluded.account_name,
        account_url = excluded.account_url,
        title = excluded.title,
        description = excluded.description,
        tags_json = excluded.tags_json,
        category = excluded.category,
        published_at = excluded.published_at,
        video_url = excluded.video_url,
        duration = excluded.duration,
        thumbnail_url = excluded.thumbnail_url,
        embed_path = excluded.embed_path,
        views = excluded.views,
        likes = excluded.likes,
        dislikes = excluded.dislikes,
        comments_count = excluded.comments_count,
        nsfw = excluded.nsfw,
        preview_path = excluded.preview_path,
        last_checked_at = excluded.last_checked_at,
        last_error = NULL,
        last_error_at = NULL,
        error_count = 0`
    );
  }

  /**
   * Handle init schema.
   */
  private initSchema() {
    applyBaseSchema(this.db);
  }

  /**
   * Handle close.
   */
  close() {
    this.db.close();
  }

  /**
   * Handle set state.
   */
  setState(key: string, value: string) {
    this.state.set(key, value);
  }

  /**
   * Handle get state.
   */
  getState(key: string): string | undefined {
    return this.state.get(key);
  }

  /**
   * Handle increment state.
   */
  incrementState(key: string, delta: number) {
    if (!Number.isFinite(delta) || delta === 0) return;
    const current = this.getState(key);
    const currentValue = current ? Number(current) : 0;
    const nextValue = Number.isFinite(currentValue) ? currentValue + delta : delta;
    this.setState(key, String(nextValue));
  }

  /**
   * Handle list instances.
   */
  listInstances(): string[] {
    const rows = this.db.prepare("SELECT host FROM instances ORDER BY host ASC").all() as {
      host: string;
    }[];
    return rows.map((row) => row.host);
  }

  /**
   * Handle list existing video ids.
   */
  listExistingVideoIds(instanceDomain: string, ids: string[]): Set<string> {
    if (ids.length === 0) return new Set();
    const placeholders = ids.map(() => "?").join(", ");
    const rows = this.db
      .prepare(
        `SELECT video_id FROM videos WHERE instance_domain = ? AND video_id IN (${placeholders})`
      )
      .all(instanceDomain, ...ids) as { video_id: string }[];
    return new Set(rows.map((row) => row.video_id));
  }

  /**
   * Handle list channels with videos.
   */
  listChannelsWithVideos(minVideos: number, instances: string[]): VideoChannelRow[] {
    if (instances.length === 0) return [];
    const placeholders = instances.map(() => "?").join(", ");
    const rows = this.db
      .prepare(
        `SELECT channel_id, channel_name, display_name, channel_url, instance_domain, videos_count
         FROM channels
         WHERE videos_count >= ?
           AND channel_name IS NOT NULL
           AND instance_domain IN (${placeholders})`
      )
      .all(minVideos, ...instances) as VideoChannelRow[];
    return rows;
  }

  /**
   * Handle list videos for tags.
   */
  listVideosForTags(mode: "missing" | "present" = "missing"): VideoTagRow[] {
    const whereClause =
      mode === "present"
        ? "AND invalid_reason IS NULL AND tags_json IS NOT NULL AND tags_json != '[]'"
        : "AND invalid_reason IS NULL AND (tags_json IS NULL OR tags_json = '[]')";
    const rows = this.db
      .prepare(
        `SELECT video_id, video_uuid, instance_domain
         FROM videos
         WHERE video_uuid IS NOT NULL
         ${whereClause}`
      )
      .all() as { video_id: string; video_uuid: string; instance_domain: string }[];
    return rows.map((row) => ({
      videoId: row.video_id,
      videoUuid: row.video_uuid,
      instanceDomain: row.instance_domain
    }));
  }

  /**
   * Handle list videos for comments.
   */
  listVideosForComments(resume: boolean): VideoTagRow[] {
    const whereClause = resume
      ? "AND comments_count IS NULL AND invalid_reason IS NULL"
      : "AND invalid_reason IS NULL";
    const rows = this.db
      .prepare(
        `SELECT video_id, video_uuid, instance_domain
         FROM videos
         WHERE video_uuid IS NOT NULL
         ${whereClause}`
      )
      .all() as { video_id: string; video_uuid: string; instance_domain: string }[];
    return rows.map((row) => ({
      videoId: row.video_id,
      videoUuid: row.video_uuid,
      instanceDomain: row.instance_domain
    }));
  }

  /**
   * Handle prepare video progress.
   */
  prepareVideoProgress(channels: VideoChannelRow[], resume: boolean) {
    if (!resume) {
      this.db.prepare("DELETE FROM video_crawl_progress").run();
    }
    this.pruneVideoProgress(channels);

    const now = Date.now();
    const insertStmt = this.db.prepare(
      `INSERT OR IGNORE INTO video_crawl_progress
        (instance_domain, channel_id, channel_name, status, last_start, updated_at)
        VALUES (?, ?, ?, 'pending', 0, ?)`
    );
    const transaction = this.db.transaction((items: VideoChannelRow[]) => {
      for (const channel of items) {
        insertStmt.run(channel.instance_domain, channel.channel_id, channel.channel_name, now);
      }
    });
    transaction(channels);
  }

  /**
   * Handle prune video progress.
   */
  private pruneVideoProgress(channels: VideoChannelRow[]) {
    if (channels.length === 0) {
      this.db.prepare("DELETE FROM video_crawl_progress").run();
      return;
    }
    const instanceSet = new Set(channels.map((channel) => channel.instance_domain));
    const existingInstances = this.db
      .prepare("SELECT DISTINCT instance_domain FROM video_crawl_progress")
      .all() as { instance_domain: string }[];
    const instancesToRemove = existingInstances
      .map((row) => row.instance_domain)
      .filter((instance) => !instanceSet.has(instance));
    deleteInstancesInChunks(this.db, instancesToRemove);

    const tempTable = "temp_video_channels";
    this.db.exec(`CREATE TEMP TABLE IF NOT EXISTS ${tempTable} (channel_id TEXT PRIMARY KEY)`);
    const clearTemp = this.db.prepare(`DELETE FROM ${tempTable}`);
    const insertTemp = this.db.prepare(
      `INSERT OR IGNORE INTO ${tempTable} (channel_id) VALUES (?)`
    );
    const deleteMissing = this.db.prepare(
      `DELETE FROM video_crawl_progress
       WHERE instance_domain = ?
       AND channel_id NOT IN (SELECT channel_id FROM ${tempTable})`
    );

    const channelsByInstance = new Map<string, string[]>();
    for (const channel of channels) {
      const list = channelsByInstance.get(channel.instance_domain) ?? [];
      list.push(channel.channel_id);
      channelsByInstance.set(channel.instance_domain, list);
    }

    const transaction = this.db.transaction(() => {
      for (const [instance, channelIds] of channelsByInstance) {
        clearTemp.run();
        for (const channelId of channelIds) {
          insertTemp.run(channelId);
        }
        deleteMissing.run(instance);
      }
    });
    transaction();
  }

  /**
   * Handle list video work items.
   */
  listVideoWorkItems(statuses: VideoCrawlStatus[]): VideoProgressRow[] {
    const placeholders = statuses.map(() => "?").join(", ");
    const rows = this.db
      .prepare(
        `SELECT instance_domain, channel_id, channel_name, status, last_start, last_error
         FROM video_crawl_progress
         WHERE status IN (${placeholders})
         ORDER BY instance_domain ASC, channel_id ASC`
      )
      .all(...statuses) as {
      instance_domain: string;
      channel_id: string;
      channel_name: string | null;
      status: VideoCrawlStatus;
      last_start: number;
      last_error: string | null;
    }[];
    return rows.map((row) => ({
      instanceDomain: row.instance_domain,
      channelId: row.channel_id,
      channelName: row.channel_name,
      status: row.status,
      lastStart: row.last_start,
      lastError: row.last_error
    }));
  }

  updateVideoProgress(
    instanceDomain: string,
    channelId: string,
    status: VideoCrawlStatus,
    lastStart: number,
    error: string | null
  ) {
    this.db
      .prepare(
        `UPDATE video_crawl_progress
         SET status = ?, last_start = ?, last_error = ?, last_error_at = ?, updated_at = ?
         WHERE instance_domain = ? AND channel_id = ?`
      )
      .run(
        status,
        lastStart,
        error,
        error ? Date.now() : null,
        Date.now(),
        instanceDomain,
        channelId
      );
  }

  /**
   * Handle upsert videos.
   */
  upsertVideos(rows: VideoUpsertRow[]) {
    if (rows.length === 0) return;
    const transaction = this.db.transaction((items: VideoUpsertRow[]) => {
      for (const row of items) {
        this.upsertStmt.run(
          row.videoId,
          row.videoUuid,
          row.videoNumericId,
          row.instanceDomain,
          row.channelId,
          row.channelName,
          row.channelUrl,
          row.accountName,
          row.accountUrl,
          row.title,
          row.description,
          row.tagsJson,
          row.category,
          row.publishedAt,
          row.videoUrl,
          row.duration,
          row.thumbnailUrl,
          row.embedPath,
          row.views,
          row.likes,
          row.dislikes,
          row.commentsCount,
          row.nsfw,
          row.previewPath,
          row.lastCheckedAt
        );
      }
    });
    transaction(rows);
  }

  /**
   * Handle update video tags.
   */
  updateVideoTags(videoId: string, instanceDomain: string, tagsJson: string) {
    this.db
      .prepare(
        `UPDATE videos
         SET tags_json = ?, last_error = NULL, last_error_at = NULL, error_count = 0
         WHERE video_id = ? AND instance_domain = ?`
      )
      .run(tagsJson, videoId, instanceDomain);
  }

  /**
   * Handle update video comments.
   */
  updateVideoComments(videoId: string, instanceDomain: string, commentsCount: number) {
    this.db
      .prepare(
        `UPDATE videos
         SET comments_count = ?, last_error = NULL, last_error_at = NULL, error_count = 0
         WHERE video_id = ? AND instance_domain = ?`
      )
      .run(commentsCount, videoId, instanceDomain);
  }

  /**
   * Handle update video invalid.
   */
  updateVideoInvalid(videoId: string, instanceDomain: string, reason: string) {
    this.db
      .prepare(
        `UPDATE videos
         SET invalid_reason = ?, invalid_at = ?, last_error = ?, last_error_at = ?, error_count = error_count + 1
         WHERE video_id = ? AND instance_domain = ?`
      )
      .run(reason, Date.now(), reason, Date.now(), videoId, instanceDomain);
  }

  /**
   * Handle update video error.
   */
  updateVideoError(videoId: string, instanceDomain: string, message: string) {
    this.db
      .prepare(
        `UPDATE videos
         SET last_error = ?, last_error_at = ?, error_count = error_count + 1
         WHERE video_id = ? AND instance_domain = ?`
      )
      .run(message, Date.now(), videoId, instanceDomain);
  }
}
