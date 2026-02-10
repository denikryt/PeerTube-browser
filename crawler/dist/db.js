import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
const schemaSql = fs.readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
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
function getColumns(db, table) {
    return db
        .prepare(`PRAGMA table_info(${table})`)
        .all()
        .map((row) => row.name);
}
function tableExists(db, table) {
    const row = db
        .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?")
        .get(table);
    return Boolean(row?.name);
}
function applyBaseSchema(db) {
    db.exec(schemaSql);
    migrateInstances(db);
    migrateChannels(db);
    migrateVideos(db);
    db.exec(schemaSql);
}
function migrateInstances(db) {
    if (!tableExists(db, "instances"))
        return;
    const columns = getColumns(db, "instances");
    const needsRebuild = columns.some((column) => DEPRECATED_INSTANCE_COLUMNS.has(column)) ||
        !columns.includes("health_status") ||
        !columns.includes("health_checked_at") ||
        !columns.includes("health_error") ||
        !columns.includes("last_error") ||
        !columns.includes("last_error_at") ||
        !columns.includes("last_error_source");
    if (!needsRebuild)
        return;
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
function migrateChannels(db) {
    if (!tableExists(db, "channels"))
        return;
    const columns = getColumns(db, "channels");
    const needsRebuild = columns.some((column) => DEPRECATED_CHANNEL_COLUMNS.has(column)) ||
        !columns.includes("health_status") ||
        !columns.includes("health_checked_at") ||
        !columns.includes("health_error") ||
        !columns.includes("last_error") ||
        !columns.includes("last_error_at") ||
        !columns.includes("last_error_source");
    if (!needsRebuild)
        return;
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
function migrateVideos(db) {
    if (!tableExists(db, "videos"))
        return;
    const columns = getColumns(db, "videos");
    const needsRebuild = !columns.includes("last_error") ||
        !columns.includes("last_error_at") ||
        !columns.includes("error_count");
    if (!needsRebuild)
        return;
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
export class CrawlerStore {
    db;
    hasStateTable = false;
    constructor(options) {
        const dir = path.dirname(options.dbPath);
        fs.mkdirSync(dir, { recursive: true });
        if (!options.resume && fs.existsSync(options.dbPath)) {
            fs.unlinkSync(options.dbPath);
        }
        this.db = new Database(options.dbPath);
        this.db.pragma("journal_mode = WAL");
        this.initSchema(options);
    }
    initSchema(options) {
        applyBaseSchema(this.db);
        if (options.collectGraph) {
            this.ensureEdges();
        }
        if (options.collectGraph || options.expandBeyondWhitelist) {
            this.ensureQueue();
            this.ensureCrawlState();
        }
    }
    ensureEdges() {
        this.db.exec(`
      CREATE TABLE IF NOT EXISTS edges (
        source_host TEXT NOT NULL,
        target_host TEXT NOT NULL,
        PRIMARY KEY (source_host, target_host)
      );
    `);
    }
    ensureQueue() {
        this.db.exec(`
      CREATE TABLE IF NOT EXISTS queue (
        host TEXT PRIMARY KEY,
        enqueued_at INTEGER NOT NULL
      );
    `);
    }
    ensureCrawlState() {
        this.hasStateTable = true;
        this.db.exec(`
      CREATE TABLE IF NOT EXISTS crawl_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `);
    }
    close() {
        this.db.close();
    }
    setState(key, value) {
        if (!this.hasStateTable)
            return;
        const stmt = this.db.prepare("INSERT INTO crawl_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value");
        stmt.run(key, value);
    }
    getState(key) {
        if (!this.hasStateTable)
            return undefined;
        const row = this.db.prepare("SELECT value FROM crawl_state WHERE key = ?").get(key);
        return row?.value;
    }
    incrementState(key, delta) {
        if (!Number.isFinite(delta) || delta === 0)
            return;
        const current = this.getState(key);
        const currentValue = current ? Number(current) : 0;
        const nextValue = Number.isFinite(currentValue) ? currentValue + delta : delta;
        this.setState(key, String(nextValue));
    }
    ensureInstance(host) {
        const transaction = this.db.transaction((value) => {
            this.db.prepare("INSERT OR IGNORE INTO instances (host) VALUES (?)").run(value);
            this.db
                .prepare("INSERT OR IGNORE INTO instance_crawl_progress (host, status, updated_at) VALUES (?, 'pending', ?)")
                .run(value, Date.now());
        });
        transaction(host);
    }
    enqueueHost(host, delayMs = 0) {
        const status = this.getCrawlStatus(host);
        if (status === "done" || status === "processing")
            return;
        const stmt = this.db.prepare("INSERT OR REPLACE INTO queue (host, enqueued_at) VALUES (?, ?)");
        stmt.run(host, Date.now() + delayMs);
    }
    claimNextHost() {
        const now = Date.now();
        const transaction = this.db.transaction(() => {
            const row = this.db
                .prepare("SELECT host FROM queue WHERE enqueued_at <= ? ORDER BY enqueued_at ASC LIMIT 1")
                .get(now);
            if (!row)
                return null;
            this.db.prepare("DELETE FROM queue WHERE host = ?").run(row.host);
            this.db
                .prepare("UPDATE instance_crawl_progress SET status = 'processing', last_start = ?, updated_at = ? WHERE host = ?")
                .run(Date.now(), Date.now(), row.host);
            return row.host;
        });
        return transaction();
    }
    nextQueueTime() {
        const row = this.db
            .prepare("SELECT enqueued_at FROM queue ORDER BY enqueued_at ASC LIMIT 1")
            .get();
        return row ? row.enqueued_at : null;
    }
    markDone(host) {
        this.db
            .prepare("UPDATE instances SET last_error = NULL, last_error_at = NULL, last_error_source = NULL WHERE host = ?")
            .run(host);
        this.db
            .prepare("UPDATE instance_crawl_progress SET status = 'done', updated_at = ? WHERE host = ?")
            .run(Date.now(), host);
    }
    markError(host, error) {
        this.db
            .prepare("UPDATE instances SET last_error = ?, last_error_at = ?, last_error_source = ? WHERE host = ?")
            .run(error, Date.now(), "instances", host);
        this.db
            .prepare("UPDATE instance_crawl_progress SET status = 'error', error_count = error_count + 1, updated_at = ? WHERE host = ?")
            .run(Date.now(), host);
    }
    getErrorCount(host) {
        const row = this.db
            .prepare("SELECT error_count FROM instance_crawl_progress WHERE host = ?")
            .get(host);
        return row?.error_count ?? 0;
    }
    getCrawlStatus(host) {
        const row = this.db
            .prepare("SELECT status FROM instance_crawl_progress WHERE host = ?")
            .get(host);
        return row?.status;
    }
    insertEdge(source, target) {
        if (source === target)
            return;
        this.db
            .prepare("INSERT OR IGNORE INTO edges (source_host, target_host) VALUES (?, ?)")
            .run(source, target);
    }
    recoverQueue(allowedHosts) {
        this.db
            .prepare("UPDATE instance_crawl_progress SET status = 'pending' WHERE status = 'processing'")
            .run();
        const rows = this.db
            .prepare("SELECT host FROM instance_crawl_progress WHERE status = 'pending'")
            .all();
        for (const row of rows) {
            if (allowedHosts && !allowedHosts.has(row.host)) {
                continue;
            }
            this.enqueueHost(row.host);
        }
    }
}
export class ChannelStore {
    db;
    upsertStmt;
    constructor(options) {
        const dir = path.dirname(options.dbPath);
        fs.mkdirSync(dir, { recursive: true });
        this.db = new Database(options.dbPath);
        this.db.pragma("journal_mode = WAL");
        this.initSchema();
        this.upsertStmt = this.db.prepare(`INSERT INTO channels (
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
        avatar_url = excluded.avatar_url`);
    }
    initSchema() {
        applyBaseSchema(this.db);
    }
    close() {
        this.db.close();
    }
    ensureInstance(host) {
        this.db
            .prepare("INSERT OR IGNORE INTO instances (host) VALUES (?)")
            .run(host);
    }
    markInstanceDone(host) {
        this.ensureInstance(host);
        this.db
            .prepare("UPDATE instances SET last_error = NULL, last_error_at = NULL, last_error_source = NULL WHERE host = ?")
            .run(host);
    }
    markInstanceError(host, error) {
        this.ensureInstance(host);
        const now = Date.now();
        this.db
            .prepare("UPDATE instances SET last_error = ?, last_error_at = ?, last_error_source = ? WHERE host = ?")
            .run(error, now, "channels", host);
    }
    markInstanceHealthOk(host) {
        this.ensureInstance(host);
        const now = Date.now();
        this.db
            .prepare("UPDATE instances SET health_status = ?, health_checked_at = ?, health_error = NULL WHERE host = ?")
            .run("ok", now, host);
    }
    markInstanceHealthError(host, error) {
        this.ensureInstance(host);
        const now = Date.now();
        this.db
            .prepare("UPDATE instances SET health_status = ?, health_checked_at = ?, health_error = ? WHERE host = ?")
            .run("error", now, error, host);
    }
    listInstances() {
        const rows = this.db
            .prepare("SELECT host FROM instances ORDER BY host ASC")
            .all();
        return rows.map((row) => row.host);
    }
    listExistingChannelIds(instanceDomain, ids) {
        if (ids.length === 0)
            return new Set();
        const placeholders = ids.map(() => "?").join(", ");
        const rows = this.db
            .prepare(`SELECT channel_id
         FROM channels
         WHERE instance_domain = ?
           AND channel_id IN (${placeholders})`)
            .all(instanceDomain, ...ids);
        return new Set(rows.map((row) => row.channel_id));
    }
    listInstancesNeedingHealth(minAgeMs) {
        const cutoff = Date.now() - Math.max(0, minAgeMs);
        const rows = this.db
            .prepare(`SELECT host
         FROM instances
         WHERE health_checked_at IS NULL OR health_checked_at <= ?
         ORDER BY host ASC`)
            .all(cutoff);
        return rows.map((row) => row.host);
    }
    listErrorInstancesNeedingHealth(minAgeMs) {
        const cutoff = Date.now() - Math.max(0, minAgeMs);
        const rows = this.db
            .prepare(`SELECT host
         FROM instances
         WHERE health_status = 'error'
           AND (health_checked_at IS NULL OR health_checked_at <= ?)
         ORDER BY host ASC`)
            .all(cutoff);
        return rows.map((row) => row.host);
    }
    listChannelInstances() {
        const rows = this.db
            .prepare(`SELECT DISTINCT c.instance_domain
         FROM channels c
         JOIN instances i ON i.host = c.instance_domain
         ORDER BY c.instance_domain ASC`)
            .all();
        return rows.map((row) => row.instance_domain);
    }
    prepareChannelProgress(hosts, resume) {
        if (!resume) {
            this.db.prepare("DELETE FROM channel_crawl_progress").run();
        }
        this.pruneChannelProgress(hosts);
        const now = Date.now();
        const insertStmt = this.db.prepare(`INSERT OR IGNORE INTO channel_crawl_progress
        (instance_domain, status, last_start, updated_at)
        VALUES (?, 'pending', 0, ?)`);
        const transaction = this.db.transaction((items) => {
            for (const host of items) {
                insertStmt.run(host, now);
            }
        });
        transaction(hosts);
    }
    pruneChannelProgress(hosts) {
        if (hosts.length === 0) {
            this.db.prepare("DELETE FROM channel_crawl_progress").run();
            return;
        }
        const placeholders = hosts.map(() => "?").join(", ");
        this.db
            .prepare(`DELETE FROM channel_crawl_progress WHERE instance_domain NOT IN (${placeholders})`)
            .run(...hosts);
    }
    listChannelWorkItems() {
        const rows = this.db
            .prepare(`SELECT instance_domain, status, last_start
         FROM channel_crawl_progress
         WHERE status IN ('pending', 'in_progress')
         ORDER BY instance_domain ASC`)
            .all();
        return rows.map((row) => ({
            instanceDomain: row.instance_domain,
            status: row.status,
            lastStart: row.last_start
        }));
    }
    updateChannelProgress(host, status, lastStart) {
        this.db
            .prepare(`UPDATE channel_crawl_progress
         SET status = ?, last_start = ?, updated_at = ?
         WHERE instance_domain = ?`)
            .run(status, lastStart, Date.now(), host);
    }
    upsertChannels(rows) {
        if (rows.length === 0)
            return;
        const transaction = this.db.transaction((items) => {
            for (const row of items) {
                this.upsertStmt.run(row.channelId, row.channelName, row.channelUrl, row.displayName, row.instanceDomain, row.videosCount, row.followersCount, row.avatarUrl);
            }
        });
        transaction(rows);
    }
    listChannelsForInstance(instanceDomain) {
        const rows = this.db
            .prepare(`SELECT channel_id, channel_name, instance_domain, videos_count,
                health_status, health_checked_at, health_error,
                last_error, last_error_at, last_error_source
         FROM channels
         WHERE instance_domain = ?`)
            .all(instanceDomain);
        return rows;
    }
    getChannelCounts() {
        const row = this.db
            .prepare(`SELECT
           COUNT(*) AS total,
           COALESCE(SUM(videos_count IS NOT NULL), 0) AS with_videos,
           COALESCE(SUM(videos_count IS NULL AND last_error_source = 'videos_count'), 0) AS with_error
         FROM channels`)
            .get();
        return {
            total: row?.total ?? 0,
            withVideos: row?.with_videos ?? 0,
            withError: row?.with_error ?? 0
        };
    }
    updateChannelVideosCount(channelId, instanceDomain, videosCount) {
        this.db
            .prepare(`UPDATE channels
         SET videos_count = ?, last_error = NULL, last_error_at = NULL, last_error_source = NULL
         WHERE channel_id = ? AND instance_domain = ? AND videos_count IS NULL`)
            .run(videosCount, channelId, instanceDomain);
    }
    updateChannelVideosCountError(channelId, instanceDomain, message) {
        this.db
            .prepare(`UPDATE channels
         SET last_error = ?, last_error_at = ?, last_error_source = ?
         WHERE channel_id = ? AND instance_domain = ? AND videos_count IS NULL`)
            .run(message, Date.now(), "videos_count", channelId, instanceDomain);
    }
    updateChannelHealthOk(channelId, instanceDomain) {
        this.db
            .prepare(`UPDATE channels
         SET health_status = ?, health_checked_at = ?, health_error = NULL
         WHERE channel_id = ? AND instance_domain = ?`)
            .run("ok", Date.now(), channelId, instanceDomain);
    }
    updateChannelHealthError(channelId, instanceDomain, message) {
        this.db
            .prepare(`UPDATE channels
         SET health_status = ?, health_checked_at = ?, health_error = ?
         WHERE channel_id = ? AND instance_domain = ?`)
            .run("error", Date.now(), message, channelId, instanceDomain);
    }
}
export class VideoStore {
    db;
    upsertStmt;
    state = new Map();
    constructor(options) {
        const dir = path.dirname(options.dbPath);
        fs.mkdirSync(dir, { recursive: true });
        this.db = new Database(options.dbPath);
        this.db.pragma("journal_mode = WAL");
        this.initSchema();
        this.upsertStmt = this.db.prepare(`INSERT INTO videos (
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
        error_count = 0`);
    }
    initSchema() {
        applyBaseSchema(this.db);
    }
    close() {
        this.db.close();
    }
    setState(key, value) {
        this.state.set(key, value);
    }
    getState(key) {
        return this.state.get(key);
    }
    incrementState(key, delta) {
        if (!Number.isFinite(delta) || delta === 0)
            return;
        const current = this.getState(key);
        const currentValue = current ? Number(current) : 0;
        const nextValue = Number.isFinite(currentValue) ? currentValue + delta : delta;
        this.setState(key, String(nextValue));
    }
    listInstances() {
        const rows = this.db.prepare("SELECT host FROM instances ORDER BY host ASC").all();
        return rows.map((row) => row.host);
    }
    listExistingVideoIds(instanceDomain, ids) {
        if (ids.length === 0)
            return new Set();
        const placeholders = ids.map(() => "?").join(", ");
        const rows = this.db
            .prepare(`SELECT video_id FROM videos WHERE instance_domain = ? AND video_id IN (${placeholders})`)
            .all(instanceDomain, ...ids);
        return new Set(rows.map((row) => row.video_id));
    }
    listChannelsWithVideos(minVideos, instances) {
        if (instances.length === 0)
            return [];
        const placeholders = instances.map(() => "?").join(", ");
        const rows = this.db
            .prepare(`SELECT channel_id, channel_name, display_name, channel_url, instance_domain, videos_count
         FROM channels
         WHERE videos_count >= ?
           AND channel_name IS NOT NULL
           AND instance_domain IN (${placeholders})`)
            .all(minVideos, ...instances);
        return rows;
    }
    listVideosForTags(mode = "missing") {
        const whereClause = mode === "present"
            ? "AND invalid_reason IS NULL AND tags_json IS NOT NULL AND tags_json != '[]'"
            : "AND invalid_reason IS NULL AND (tags_json IS NULL OR tags_json = '[]')";
        const rows = this.db
            .prepare(`SELECT video_id, video_uuid, instance_domain
         FROM videos
         WHERE video_uuid IS NOT NULL
         ${whereClause}`)
            .all();
        return rows.map((row) => ({
            videoId: row.video_id,
            videoUuid: row.video_uuid,
            instanceDomain: row.instance_domain
        }));
    }
    listVideosForComments(resume) {
        const whereClause = resume
            ? "AND comments_count IS NULL AND invalid_reason IS NULL"
            : "AND invalid_reason IS NULL";
        const rows = this.db
            .prepare(`SELECT video_id, video_uuid, instance_domain
         FROM videos
         WHERE video_uuid IS NOT NULL
         ${whereClause}`)
            .all();
        return rows.map((row) => ({
            videoId: row.video_id,
            videoUuid: row.video_uuid,
            instanceDomain: row.instance_domain
        }));
    }
    prepareVideoProgress(channels, resume) {
        if (!resume) {
            this.db.prepare("DELETE FROM video_crawl_progress").run();
        }
        this.pruneVideoProgress(channels);
        const now = Date.now();
        const insertStmt = this.db.prepare(`INSERT OR IGNORE INTO video_crawl_progress
        (instance_domain, channel_id, channel_name, status, last_start, updated_at)
        VALUES (?, ?, ?, 'pending', 0, ?)`);
        const transaction = this.db.transaction((items) => {
            for (const channel of items) {
                insertStmt.run(channel.instance_domain, channel.channel_id, channel.channel_name, now);
            }
        });
        transaction(channels);
    }
    pruneVideoProgress(channels) {
        if (channels.length === 0) {
            this.db.prepare("DELETE FROM video_crawl_progress").run();
            return;
        }
        const instanceSet = new Set(channels.map((channel) => channel.instance_domain));
        const existingInstances = this.db
            .prepare("SELECT DISTINCT instance_domain FROM video_crawl_progress")
            .all();
        const instancesToRemove = existingInstances
            .map((row) => row.instance_domain)
            .filter((instance) => !instanceSet.has(instance));
        deleteInstancesInChunks(this.db, instancesToRemove);
        const tempTable = "temp_video_channels";
        this.db.exec(`CREATE TEMP TABLE IF NOT EXISTS ${tempTable} (channel_id TEXT PRIMARY KEY)`);
        const clearTemp = this.db.prepare(`DELETE FROM ${tempTable}`);
        const insertTemp = this.db.prepare(`INSERT OR IGNORE INTO ${tempTable} (channel_id) VALUES (?)`);
        const deleteMissing = this.db.prepare(`DELETE FROM video_crawl_progress
       WHERE instance_domain = ?
       AND channel_id NOT IN (SELECT channel_id FROM ${tempTable})`);
        const channelsByInstance = new Map();
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
    listVideoWorkItems(statuses) {
        const placeholders = statuses.map(() => "?").join(", ");
        const rows = this.db
            .prepare(`SELECT instance_domain, channel_id, channel_name, status, last_start, last_error
         FROM video_crawl_progress
         WHERE status IN (${placeholders})
         ORDER BY instance_domain ASC, channel_id ASC`)
            .all(...statuses);
        return rows.map((row) => ({
            instanceDomain: row.instance_domain,
            channelId: row.channel_id,
            channelName: row.channel_name,
            status: row.status,
            lastStart: row.last_start,
            lastError: row.last_error
        }));
    }
    updateVideoProgress(instanceDomain, channelId, status, lastStart, error) {
        this.db
            .prepare(`UPDATE video_crawl_progress
         SET status = ?, last_start = ?, last_error = ?, last_error_at = ?, updated_at = ?
         WHERE instance_domain = ? AND channel_id = ?`)
            .run(status, lastStart, error, error ? Date.now() : null, Date.now(), instanceDomain, channelId);
    }
    upsertVideos(rows) {
        if (rows.length === 0)
            return;
        const transaction = this.db.transaction((items) => {
            for (const row of items) {
                this.upsertStmt.run(row.videoId, row.videoUuid, row.videoNumericId, row.instanceDomain, row.channelId, row.channelName, row.channelUrl, row.accountName, row.accountUrl, row.title, row.description, row.tagsJson, row.category, row.publishedAt, row.videoUrl, row.duration, row.thumbnailUrl, row.embedPath, row.views, row.likes, row.dislikes, row.commentsCount, row.nsfw, row.previewPath, row.lastCheckedAt);
            }
        });
        transaction(rows);
    }
    updateVideoTags(videoId, instanceDomain, tagsJson) {
        this.db
            .prepare(`UPDATE videos
         SET tags_json = ?, last_error = NULL, last_error_at = NULL, error_count = 0
         WHERE video_id = ? AND instance_domain = ?`)
            .run(tagsJson, videoId, instanceDomain);
    }
    updateVideoComments(videoId, instanceDomain, commentsCount) {
        this.db
            .prepare(`UPDATE videos
         SET comments_count = ?, last_error = NULL, last_error_at = NULL, error_count = 0
         WHERE video_id = ? AND instance_domain = ?`)
            .run(commentsCount, videoId, instanceDomain);
    }
    updateVideoInvalid(videoId, instanceDomain, reason) {
        this.db
            .prepare(`UPDATE videos
         SET invalid_reason = ?, invalid_at = ?, last_error = ?, last_error_at = ?, error_count = error_count + 1
         WHERE video_id = ? AND instance_domain = ?`)
            .run(reason, Date.now(), reason, Date.now(), videoId, instanceDomain);
    }
    updateVideoError(videoId, instanceDomain, message) {
        this.db
            .prepare(`UPDATE videos
         SET last_error = ?, last_error_at = ?, error_count = error_count + 1
         WHERE video_id = ? AND instance_domain = ?`)
            .run(message, Date.now(), videoId, instanceDomain);
    }
}
function deleteInstancesInChunks(db, instances) {
    if (instances.length === 0)
        return;
    const chunkSize = 500;
    for (let i = 0; i < instances.length; i += chunkSize) {
        const chunk = instances.slice(i, i + chunkSize);
        const placeholders = chunk.map(() => "?").join(", ");
        db.prepare(`DELETE FROM video_crawl_progress WHERE instance_domain IN (${placeholders})`).run(...chunk);
    }
}
