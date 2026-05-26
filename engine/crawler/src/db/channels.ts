/**
 * Channel crawl persistence for the TypeScript crawler.
 *
 * ChannelStore owns channel rows, channel progress, instance health fields, and
 * videos_count updates. It does not own PeerTube traversal or CLI parsing.
 */

import Database from "better-sqlite3";

import { openCrawlerDatabase } from "./connection.js";
import { applyBaseSchema } from "./schema.js";
import type {
  ChannelCounts,
  ChannelCrawlStatus,
  ChannelProgressRow,
  ChannelRow,
  ChannelStoreOptions,
  ChannelUpsertRow
} from "./types.js";

export class ChannelStore {
  private db: Database.Database;
  private upsertStmt: Database.Statement;

  /**
   * Initialize the instance.
   */
  constructor(options: ChannelStoreOptions) {
    this.db = openCrawlerDatabase(options.dbPath);
    this.initSchema();
    this.upsertStmt = this.db.prepare(
      `INSERT INTO channels (
        channel_id,
        channel_name,
        channel_url,
        display_name,
        instance_domain,
        videos_count,
        followers_count,
        avatar_url
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(channel_id, instance_domain) DO UPDATE SET
        channel_name = excluded.channel_name,
        channel_url = excluded.channel_url,
        display_name = excluded.display_name,
        videos_count = excluded.videos_count,
        followers_count = excluded.followers_count,
        avatar_url = excluded.avatar_url`
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
   * Handle ensure instance.
   */
  private ensureInstance(host: string) {
    this.db
      .prepare("INSERT OR IGNORE INTO instances (host) VALUES (?)")
      .run(host);
  }

  /**
   * Handle mark instance done.
   */
  markInstanceDone(host: string) {
    this.ensureInstance(host);
    this.db
      .prepare(
        "UPDATE instances SET last_error = NULL, last_error_at = NULL, last_error_source = NULL WHERE host = ?"
      )
      .run(host);
  }

  /**
   * Handle mark instance error.
   */
  markInstanceError(host: string, error: string) {
    this.ensureInstance(host);
    const now = Date.now();
    this.db
      .prepare(
        "UPDATE instances SET last_error = ?, last_error_at = ?, last_error_source = ? WHERE host = ?"
      )
      .run(error, now, "channels", host);
  }

  /**
   * Handle mark instance health ok.
   */
  markInstanceHealthOk(host: string) {
    this.ensureInstance(host);
    const now = Date.now();
    this.db
      .prepare(
        "UPDATE instances SET health_status = ?, health_checked_at = ?, health_error = NULL WHERE host = ?"
      )
      .run("ok", now, host);
  }

  /**
   * Handle mark instance health error.
   */
  markInstanceHealthError(host: string, error: string) {
    this.ensureInstance(host);
    const now = Date.now();
    this.db
      .prepare(
        "UPDATE instances SET health_status = ?, health_checked_at = ?, health_error = ? WHERE host = ?"
      )
      .run("error", now, error, host);
  }

  /**
   * Handle list instances.
   */
  listInstances(): string[] {
    const rows = this.db
      .prepare("SELECT host FROM instances ORDER BY host ASC")
      .all() as { host: string }[];
    return rows.map((row) => row.host);
  }

  /**
   * Handle list existing channel ids.
   */
  listExistingChannelIds(instanceDomain: string, ids: string[]): Set<string> {
    if (ids.length === 0) return new Set();
    const placeholders = ids.map(() => "?").join(", ");
    const rows = this.db
      .prepare(
        `SELECT channel_id
         FROM channels
         WHERE instance_domain = ?
           AND channel_id IN (${placeholders})`
      )
      .all(instanceDomain, ...ids) as { channel_id: string }[];
    return new Set(rows.map((row) => row.channel_id));
  }

  /**
   * Handle list instances needing health.
   */
  listInstancesNeedingHealth(minAgeMs: number): string[] {
    const cutoff = Date.now() - Math.max(0, minAgeMs);
    const rows = this.db
      .prepare(
        `SELECT host
         FROM instances
         WHERE health_checked_at IS NULL OR health_checked_at <= ?
         ORDER BY host ASC`
      )
      .all(cutoff) as { host: string }[];
    return rows.map((row) => row.host);
  }

  /**
   * Handle list error instances needing health.
   */
  listErrorInstancesNeedingHealth(minAgeMs: number): string[] {
    const cutoff = Date.now() - Math.max(0, minAgeMs);
    const rows = this.db
      .prepare(
        `SELECT host
         FROM instances
         WHERE health_status = 'error'
           AND (health_checked_at IS NULL OR health_checked_at <= ?)
         ORDER BY host ASC`
      )
      .all(cutoff) as { host: string }[];
    return rows.map((row) => row.host);
  }

  /**
   * Handle list channel instances.
   */
  listChannelInstances(): string[] {
    const rows = this.db
      .prepare(
        `SELECT DISTINCT c.instance_domain
         FROM channels c
         JOIN instances i ON i.host = c.instance_domain
         ORDER BY c.instance_domain ASC`
      )
      .all() as { instance_domain: string }[];
    return rows.map((row) => row.instance_domain);
  }

  /**
   * Handle prepare channel progress.
   */
  prepareChannelProgress(hosts: string[], resume: boolean) {
    if (!resume) {
      this.db.prepare("DELETE FROM channel_crawl_progress").run();
    }
    this.pruneChannelProgress(hosts);

    const now = Date.now();
    const insertStmt = this.db.prepare(
      `INSERT OR IGNORE INTO channel_crawl_progress
        (instance_domain, status, last_start, updated_at)
        VALUES (?, 'pending', 0, ?)`
    );
    const transaction = this.db.transaction((items: string[]) => {
      for (const host of items) {
        insertStmt.run(host, now);
      }
    });
    transaction(hosts);
  }

  /**
   * Handle prune channel progress.
   */
  private pruneChannelProgress(hosts: string[]) {
    if (hosts.length === 0) {
      this.db.prepare("DELETE FROM channel_crawl_progress").run();
      return;
    }

    const placeholders = hosts.map(() => "?").join(", ");
    this.db
      .prepare(
        `DELETE FROM channel_crawl_progress WHERE instance_domain NOT IN (${placeholders})`
      )
      .run(...hosts);
  }

  /**
   * Handle list channel work items.
   */
  listChannelWorkItems(): ChannelProgressRow[] {
    const rows = this.db
      .prepare(
        `SELECT instance_domain, status, last_start
         FROM channel_crawl_progress
         WHERE status IN ('pending', 'in_progress')
         ORDER BY instance_domain ASC`
      )
      .all() as { instance_domain: string; status: ChannelCrawlStatus; last_start: number }[];
    return rows.map((row) => ({
      instanceDomain: row.instance_domain,
      status: row.status,
      lastStart: row.last_start
    }));
  }

  /**
   * Handle update channel progress.
   */
  updateChannelProgress(host: string, status: ChannelCrawlStatus, lastStart: number) {
    this.db
      .prepare(
        `UPDATE channel_crawl_progress
         SET status = ?, last_start = ?, updated_at = ?
         WHERE instance_domain = ?`
      )
      .run(status, lastStart, Date.now(), host);
  }

  /**
   * Handle upsert channels.
   */
  upsertChannels(rows: ChannelUpsertRow[]) {
    if (rows.length === 0) return;
    const transaction = this.db.transaction((items: ChannelUpsertRow[]) => {
      for (const row of items) {
        this.upsertStmt.run(
          row.channelId,
          row.channelName,
          row.channelUrl,
          row.displayName,
          row.instanceDomain,
          row.videosCount,
          row.followersCount,
          row.avatarUrl
        );
      }
    });
    transaction(rows);
  }

  /**
   * Handle list channels for instance.
   */
  listChannelsForInstance(instanceDomain: string): ChannelRow[] {
    const rows = this.db
      .prepare(
        `SELECT channel_id, channel_name, instance_domain, videos_count,
                health_status, health_checked_at, health_error,
                last_error, last_error_at, last_error_source
         FROM channels
         WHERE instance_domain = ?`
      )
      .all(instanceDomain) as ChannelRow[];
    return rows;
  }

  /**
   * Handle get channel counts.
   */
  getChannelCounts(): ChannelCounts {
    const row = this.db
      .prepare(
        `SELECT
           COUNT(*) AS total,
           COALESCE(SUM(videos_count IS NOT NULL), 0) AS with_videos,
           COALESCE(SUM(videos_count IS NULL AND last_error_source = 'videos_count'), 0) AS with_error
         FROM channels`
      )
      .get() as { total: number; with_videos: number; with_error: number } | undefined;
    return {
      total: row?.total ?? 0,
      withVideos: row?.with_videos ?? 0,
      withError: row?.with_error ?? 0
    };
  }

  /**
   * Handle update channel videos count.
   */
  updateChannelVideosCount(channelId: string, instanceDomain: string, videosCount: number) {
    this.db
      .prepare(
        `UPDATE channels
         SET videos_count = ?, last_error = NULL, last_error_at = NULL, last_error_source = NULL
         WHERE channel_id = ? AND instance_domain = ? AND videos_count IS NULL`
      )
      .run(videosCount, channelId, instanceDomain);
  }

  /**
   * Handle update channel videos count error.
   */
  updateChannelVideosCountError(channelId: string, instanceDomain: string, message: string) {
    this.db
      .prepare(
        `UPDATE channels
         SET last_error = ?, last_error_at = ?, last_error_source = ?
         WHERE channel_id = ? AND instance_domain = ? AND videos_count IS NULL`
      )
      .run(message, Date.now(), "videos_count", channelId, instanceDomain);
  }

  /**
   * Handle update channel health ok.
   */
  updateChannelHealthOk(channelId: string, instanceDomain: string) {
    this.db
      .prepare(
        `UPDATE channels
         SET health_status = ?, health_checked_at = ?, health_error = NULL
         WHERE channel_id = ? AND instance_domain = ?`
      )
      .run("ok", Date.now(), channelId, instanceDomain);
  }

  /**
   * Handle update channel health error.
   */
  updateChannelHealthError(channelId: string, instanceDomain: string, message: string) {
    this.db
      .prepare(
        `UPDATE channels
         SET health_status = ?, health_checked_at = ?, health_error = ?
         WHERE channel_id = ? AND instance_domain = ?`
      )
      .run("error", Date.now(), message, channelId, instanceDomain);
  }
}
