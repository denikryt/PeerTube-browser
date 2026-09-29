/**
 * Video crawl persistence for the TypeScript crawler.
 *
 * VideoStore owns video rows, video progress, tags/comments updates, and
 * invalid/error recording. PeerTube request behavior remains in videos-worker.ts.
 */

import Database from "better-sqlite3";

import { openCrawlerDatabase } from "./connection.js";
import { applyBaseSchema } from "./schema.js";
import { CURRENT_VIDEO_METADATA_VERSION } from "../video-metadata.js";
import type { ThumbnailCandidate } from "../video-media.js";
import { deleteInstancesInChunks } from "./utils.js";
import type {
  ExistingVideoRefresh,
  VideoActivityPubMetadataPatch,
  VideoChannelRow,
  VideoCrawlStatus,
  VideoDetailMetadataPatch,
  VideoProgressRow,
  VideoMetadataWorkRow,
  VideoThumbnailRow,
  VideoStoreOptions,
  VideoTagRow,
  VideoUpsertRow
} from "./types.js";

export class VideoStore {
  private db: Database.Database;
  private insertStmt: Database.Statement;
  private baseRefreshStmt: Database.Statement;
  private detailRefreshStmt: Database.Statement;
  private categoryIdRefreshStmt: Database.Statement;
  private thumbnailCandidatesRefreshStmt: Database.Statement;
  private permanentLiveRefreshStmt: Database.Statement;
  private liveSaveReplayRefreshStmt: Database.Statement;
  private state = new Map<string, string>();

  /** Open crawler persistence, optionally skipping schema mutation for maintenance. */
  constructor(options: VideoStoreOptions) {
    this.db = openCrawlerDatabase(options.dbPath);
    if (options.initializeSchema !== false) {
      this.initSchema();
    }
    this.insertStmt = this.db.prepare(`
      INSERT OR IGNORE INTO videos (
        video_id, video_uuid, video_numeric_id, instance_domain,
        channel_id, channel_name, channel_url, account_name, account_url,
        title, description, tags_json, category, category_id, licence_id, licence,
        language, language_label, published_at, originally_published_at, updated_at,
        video_url, duration, thumbnail_url, thumbnail_candidates_json, thumbnail_width, thumbnail_height,
        embed_path, views, likes, dislikes, comments_count, nsfw, sensitive_summary,
        is_live, permanent_live, live_save_replay, aspect_ratio, support,
        account_username, account_avatar_url, metadata_version, preview_path,
        last_checked_at, last_error, last_error_at, error_count
      ) VALUES (
        @videoId, @videoUuid, @videoNumericId, @instanceDomain,
        @channelId, @channelName, @channelUrl, @accountName, @accountUrl,
        @title, @description, @tagsJson, @category, @categoryId, @licenceId, @licence,
        @language, @languageLabel, @publishedAt, @originallyPublishedAt, @updatedAt,
        @videoUrl, @duration, @thumbnailUrl, @thumbnailCandidatesJson, @thumbnailWidth, @thumbnailHeight,
        @embedPath, @views, @likes, @dislikes, @commentsCount, @nsfw, @sensitiveSummary,
        @isLive, @permanentLive, @liveSaveReplay, @aspectRatio, @support,
        @accountUsername, @accountAvatarUrl, @metadataVersion, @previewPath,
        @lastCheckedAt, NULL, NULL, 0
      )
    `);
    this.baseRefreshStmt = this.db.prepare(`
      UPDATE videos SET
        video_uuid = @videoUuid,
        video_numeric_id = @videoNumericId,
        channel_id = @safeChannelId,
        channel_url = @safeChannelUrl,
        account_name = @accountName,
        account_url = @accountUrl,
        published_at = @publishedAt,
        video_url = @videoUrl,
        duration = @duration,
        embed_path = @embedPath,
        views = COALESCE(@views, views),
        likes = COALESCE(@likes, likes),
        dislikes = COALESCE(@dislikes, dislikes),
        comments_count = COALESCE(@commentsCount, comments_count),
        nsfw = @nsfw,
        is_live = @isLive,
        preview_path = @previewPath,
        metadata_version = MAX(metadata_version, @metadataVersion),
        last_checked_at = @lastCheckedAt,
        last_error = NULL,
        last_error_at = NULL,
        error_count = 0
      WHERE video_id = @videoId AND instance_domain = @instanceDomain
    `);
    this.detailRefreshStmt = this.db.prepare(`
      UPDATE videos SET
        language = @language,
        language_label = @languageLabel,
        licence_id = @licenceId,
        licence = @licence,
        sensitive_summary = @sensitiveSummary,
        originally_published_at = @originallyPublishedAt,
        updated_at = @updatedAt,
        aspect_ratio = @aspectRatio,
        support = @support,
        account_username = @accountUsername,
        account_avatar_url = @accountAvatarUrl
      WHERE video_id = @videoId AND instance_domain = @instanceDomain
    `);
    this.categoryIdRefreshStmt = this.db.prepare(`
      UPDATE videos SET category_id = @categoryId
      WHERE video_id = @videoId AND instance_domain = @instanceDomain
    `);
    this.thumbnailCandidatesRefreshStmt = this.db.prepare(`
      UPDATE videos SET
        thumbnail_candidates_json = @thumbnailCandidatesJson,
        thumbnail_url = @thumbnailUrl,
        thumbnail_width = @thumbnailWidth,
        thumbnail_height = @thumbnailHeight,
        last_checked_at = @lastCheckedAt
      WHERE video_id = @videoId AND instance_domain = @instanceDomain
    `);
    this.permanentLiveRefreshStmt = this.db.prepare(`
      UPDATE videos SET permanent_live = @permanentLive
      WHERE video_id = @videoId AND instance_domain = @instanceDomain
    `);
    this.liveSaveReplayRefreshStmt = this.db.prepare(`
      UPDATE videos SET live_save_replay = @liveSaveReplay
      WHERE video_id = @videoId AND instance_domain = @instanceDomain
    `);
  }

  /** Apply the normal crawler schema/migration path. */
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

  /** Persist the authoritative total returned by a channel video-list page. */
  updateChannelVideosCount(channelId: string, instanceDomain: string, videosCount: number) {
    this.db
      .prepare(
        `UPDATE channels
         SET videos_count = ?,
             last_error = CASE WHEN last_error_source = 'videos_count' THEN NULL ELSE last_error END,
             last_error_at = CASE WHEN last_error_source = 'videos_count' THEN NULL ELSE last_error_at END,
             last_error_source = CASE WHEN last_error_source = 'videos_count' THEN NULL ELSE last_error_source END
         WHERE channel_id = ? AND instance_domain = ?`
      )
      .run(videosCount, channelId, instanceDomain);
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
   * Handle list videos for thumbnail refresh.
   *
   * The refresh job revisits live PeerTube video detail pages so stale feed
   * thumbnails can be replaced without re-running the full channel crawl.
   */
  listVideosForThumbnailRefresh(resume = false): VideoThumbnailRow[] {
    const pendingPredicate = resume ? "AND thumbnail_candidates_json IS NULL" : "";
    const rows = this.db
      .prepare(
        `SELECT video_id, video_uuid, instance_domain
         FROM videos
         WHERE video_uuid IS NOT NULL
           AND invalid_reason IS NULL
         ${pendingPredicate}
         ORDER BY instance_domain ASC, video_id ASC`
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
  prepareVideoProgress(channels: VideoChannelRow[], resume: boolean, scopedInstances?: string[]) {
    if (!resume) {
      if (scopedInstances) {
        deleteInstancesInChunks(this.db, scopedInstances);
      } else {
        this.db.prepare("DELETE FROM video_crawl_progress").run();
      }
    }
    this.pruneVideoProgress(channels, scopedInstances);

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
  private pruneVideoProgress(channels: VideoChannelRow[], scopedInstances?: string[]) {
    if (channels.length === 0 && !scopedInstances) {
      this.db.prepare("DELETE FROM video_crawl_progress").run();
      return;
    }
    const instanceSet = new Set(channels.map((channel) => channel.instance_domain));
    const targetInstances = scopedInstances ?? (this.db
      .prepare("SELECT DISTINCT instance_domain FROM video_crawl_progress")
      .all() as { instance_domain: string }[]).map((row) => row.instance_domain);
    const instancesToRemove = targetInstances.filter((instance) => !instanceSet.has(instance));
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
  listVideoWorkItems(statuses: VideoCrawlStatus[], scopedInstances?: string[]): VideoProgressRow[] {
    if (scopedInstances && scopedInstances.length === 0) return [];
    const placeholders = statuses.map(() => "?").join(", ");
    const instanceFilter = scopedInstances
      ? `AND instance_domain IN (${scopedInstances.map(() => "?").join(", ")})`
      : "";
    const rows = this.db
      .prepare(
        `SELECT instance_domain, channel_id, channel_name, status, last_start, last_error
         FROM video_crawl_progress
         WHERE status IN (${placeholders})
         ${instanceFilter}
         ORDER BY instance_domain ASC, channel_id ASC`
      )
      .all(...statuses, ...(scopedInstances ?? [])) as {
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

  /** Insert newly discovered videos without rewriting an existing row on conflict. */
  insertNewVideos(rows: VideoUpsertRow[]) {
    if (rows.length === 0) return;
    const transaction = this.db.transaction((items: VideoUpsertRow[]) => {
      for (const row of items) {
        this.insertStmt.run(this.bindRow(row));
      }
    });
    transaction(rows);
  }

  /**
   * Refresh only non-embedding metadata for existing rows. Protected semantic
   * fields are deliberately absent from the UPDATE statement.
   */
  refreshExistingVideoMetadata(rows: ExistingVideoRefresh[]) {
    if (rows.length === 0) return;
    const transaction = this.db.transaction((items: ExistingVideoRefresh[]) => {
      for (const refresh of items) {
        this.applySafeRefresh(refresh);
      }
    });
    transaction(rows);
  }

  /** Return rows eligible for metadata-v1 maintenance. */
  listVideosForMetadata(updateCompleted: boolean): VideoMetadataWorkRow[] {
    const versionPredicate = updateCompleted
      ? "metadata_version >= 0"
      : `metadata_version < ${CURRENT_VIDEO_METADATA_VERSION}`;
    return this.db
      .prepare(
        `SELECT video_id AS videoId, video_uuid AS videoUuid,
                instance_domain AS instanceDomain, metadata_version AS metadataVersion,
                video_url AS videoUrl
         FROM videos
         WHERE video_uuid IS NOT NULL
           AND invalid_reason IS NULL
           AND ${versionPredicate}
         ORDER BY instance_domain ASC, video_id ASC`
      )
      .all() as VideoMetadataWorkRow[];
  }

  /** Return the normalized instance hosts currently eligible for healthy-only metadata work. */
  listHealthyInstanceHosts(): Set<string> {
    return new Set(
      (this.db
        .prepare("SELECT host FROM instances WHERE health_status = 'ok' ORDER BY host ASC")
        .all() as { host: string }[])
        .map((row) => row.host.toLowerCase())
    );
  }

  /**
   * Apply one historical metadata item atomically with opportunistic channel
   * owner enrichment. The version checkpoint commits only with the video row.
   */
  applyMetadataBackfill(refresh: ExistingVideoRefresh) {
    const transaction = this.db.transaction((item: ExistingVideoRefresh) => {
      const row = item.base;
      const stored = this.getStoredIdentity(row.videoId, row.instanceDomain);
      if (!stored) return;
      const sameChannel = isSameChannelIdentity(stored, row);
      if (sameChannel && stored.channel_id) {
        this.db
          .prepare(
            `UPDATE channels SET
               owner_account_username = COALESCE(?, owner_account_username),
               owner_account_display_name = COALESCE(?, owner_account_display_name),
               owner_account_url = COALESCE(?, owner_account_url),
               owner_account_avatar_url = COALESCE(?, owner_account_avatar_url)
             WHERE channel_id = ? AND instance_domain = ?`
          )
          .run(
            item.detail?.accountUsername ?? null,
            row.accountName,
            row.accountUrl,
            item.detail?.accountAvatarUrl ?? null,
            stored.channel_id,
            row.instanceDomain
          );
      }
      this.applySafeRefresh(item, stored);
    });
    transaction(refresh);
  }

  /** Build named bindings and normalize optional metadata fields to SQLite nulls. */
  private bindRow(row: VideoUpsertRow) {
    return {
      ...row,
      categoryId: row.categoryId ?? null,
      licenceId: row.licenceId ?? null,
      licence: row.licence ?? null,
      language: row.language ?? null,
      languageLabel: row.languageLabel ?? null,
      originallyPublishedAt: row.originallyPublishedAt ?? null,
      updatedAt: row.updatedAt ?? null,
      thumbnailCandidatesJson: row.thumbnailCandidatesJson ?? null,
      thumbnailWidth: row.thumbnailWidth ?? null,
      thumbnailHeight: row.thumbnailHeight ?? null,
      sensitiveSummary: row.sensitiveSummary ?? null,
      isLive: row.isLive ?? null,
      permanentLive: row.permanentLive ?? null,
      liveSaveReplay: row.liveSaveReplay ?? null,
      aspectRatio: row.aspectRatio ?? null,
      support: row.support ?? null,
      accountUsername: row.accountUsername ?? null,
      accountAvatarUrl: row.accountAvatarUrl ?? null,
      metadataVersion: row.metadataVersion ?? 0
    };
  }

  /** Apply the protected existing-row semantics using the stored identity tuple. */
  private applySafeRefresh(
    refresh: ExistingVideoRefresh,
    preloaded?: StoredVideoIdentity | null
  ) {
    const row = refresh.base;
    const stored = preloaded ?? this.getStoredIdentity(row.videoId, row.instanceDomain);
    if (!stored) return;
    const sameChannel = isSameChannelIdentity(stored, row);

    this.baseRefreshStmt.run({
      ...this.bindRow(row),
      safeChannelId: sameChannel ? row.channelId ?? stored.channel_id : stored.channel_id,
      safeChannelUrl: sameChannel ? row.channelUrl ?? stored.channel_url : stored.channel_url
    });

    if (refresh.detail) {
      this.applyDetailRefresh(row, refresh.detail, stored);
    }
    if (refresh.activityPub) {
      this.applyActivityPubRefresh(row, refresh.activityPub);
    }
    if (refresh.thumbnail !== undefined) {
      this.updateVideoThumbnailCandidates(
        row.videoId,
        row.instanceDomain,
        refresh.thumbnail,
        row.lastCheckedAt
      );
    }
  }

  /** Apply fields that are trustworthy only after a successful detail request. */
  private applyDetailRefresh(
    row: VideoUpsertRow,
    detail: VideoDetailMetadataPatch,
    stored: StoredVideoIdentity
  ) {
    this.detailRefreshStmt.run({
      videoId: row.videoId,
      instanceDomain: row.instanceDomain,
      ...detail
    });

    // Category label is an embedding input, so its identifier is safe only
    // when it still describes the protected stored label.
    if (detail.categoryId !== null && detail.category !== null && detail.category === stored.category) {
      this.categoryIdRefreshStmt.run({
        videoId: row.videoId,
        instanceDomain: row.instanceDomain,
        categoryId: detail.categoryId
      });
    }
    this.applyLivePatch(row, detail);
  }

  /** Apply optional AP live fields without inventing values for absent keys. */
  private applyActivityPubRefresh(
    row: VideoUpsertRow,
    activityPub: VideoActivityPubMetadataPatch
  ) {
    this.applyLivePatch(row, activityPub);
  }

  /** Apply only explicitly supplied live values from a successful source. */
  private applyLivePatch(
    row: VideoUpsertRow,
    patch: Pick<VideoDetailMetadataPatch, "permanentLive" | "liveSaveReplay">
  ) {
    if (patch.permanentLive !== undefined && patch.permanentLive !== null) {
      this.permanentLiveRefreshStmt.run({
        videoId: row.videoId,
        instanceDomain: row.instanceDomain,
        permanentLive: patch.permanentLive
      });
    }
    if (patch.liveSaveReplay !== undefined && patch.liveSaveReplay !== null) {
      this.liveSaveReplayRefreshStmt.run({
        videoId: row.videoId,
        instanceDomain: row.instanceDomain,
        liveSaveReplay: patch.liveSaveReplay
      });
    }
  }

  /** Read only the protected identity fields needed to decide a safe refresh. */
  private getStoredIdentity(videoId: string, instanceDomain: string): StoredVideoIdentity | null {
    return (
      (this.db
        .prepare(
          `SELECT channel_id, channel_url, channel_name, category, category_id
           FROM videos WHERE video_id = ? AND instance_domain = ?`
        )
        .get(videoId, instanceDomain) as StoredVideoIdentity | undefined) ?? null
    );
  }

  /** Serialize one authoritative candidate set and mirror candidate zero atomically. */
  updateVideoThumbnailCandidates(
    videoId: string,
    instanceDomain: string,
    candidates: ThumbnailCandidate[],
    lastCheckedAt: number
  ) {
    const primary = candidates[0] ?? null;
    this.thumbnailCandidatesRefreshStmt.run({
      videoId,
      instanceDomain,
      thumbnailCandidatesJson: JSON.stringify(candidates),
      thumbnailUrl: primary?.url ?? null,
      thumbnailWidth: primary?.width ?? null,
      thumbnailHeight: primary?.height ?? null,
      lastCheckedAt
    });
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

interface StoredVideoIdentity {
  channel_id: string | null;
  channel_url: string | null;
  channel_name: string | null;
  category: string | null;
  category_id: string | null;
}

/**
 * Prove that incoming channel identity is the same before filling identity
 * fields while the embedding-protected channel_name remains unchanged.
 */
function isSameChannelIdentity(stored: StoredVideoIdentity, incoming: VideoUpsertRow): boolean {
  if (stored.channel_url && incoming.channelUrl) {
    return canonicalProtocolUrl(stored.channel_url) === canonicalProtocolUrl(incoming.channelUrl);
  }
  if (stored.channel_id && incoming.channelId) {
    return stored.channel_id === incoming.channelId;
  }
  return false;
}

/** Canonicalize protocol URLs only for equality checks; invalid values never match. */
function canonicalProtocolUrl(value: string): string {
  try {
    const url = new URL(value);
    url.hash = "";
    const text = url.toString();
    return text.endsWith("/") ? text.slice(0, -1) : text;
  } catch {
    return value.trim();
  }
}
