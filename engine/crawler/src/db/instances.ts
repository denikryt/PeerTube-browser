/**
 * Instance crawl persistence for the TypeScript crawler.
 *
 * CrawlerStore owns instance queue, graph, state, and crawl-progress writes.
 * Network traversal remains in crawler.ts; this module preserves only the DB
 * behavior that previously lived in db.ts.
 */

import Database from "better-sqlite3";

import { openCrawlerDatabase } from "./connection.js";
import { applyBaseSchema } from "./schema.js";
import type { StoreOptions } from "./types.js";

export class CrawlerStore {
  private db: Database.Database;
  private hasStateTable = false;

  /**
   * Initialize the instance.
   */
  constructor(options: StoreOptions) {
    this.db = openCrawlerDatabase(options.dbPath, { reset: !options.resume });
    this.initSchema(options);
  }

  /**
   * Handle init schema.
   */
  private initSchema(options: StoreOptions) {
    applyBaseSchema(this.db);
    if (options.collectGraph) {
      this.ensureEdges();
    }
    if (options.collectGraph || options.expandBeyondWhitelist) {
      this.ensureQueue();
      this.ensureCrawlState();
    }
  }

  /**
   * Handle ensure edges.
   */
  private ensureEdges() {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS edges (
        source_host TEXT NOT NULL,
        target_host TEXT NOT NULL,
        PRIMARY KEY (source_host, target_host)
      );
    `);
  }

  /**
   * Handle ensure queue.
   */
  private ensureQueue() {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS queue (
        host TEXT PRIMARY KEY,
        enqueued_at INTEGER NOT NULL
      );
    `);
  }

  /**
   * Handle ensure crawl state.
   */
  private ensureCrawlState() {
    this.hasStateTable = true;
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS crawl_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `);
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
    if (!this.hasStateTable) return;
    const stmt = this.db.prepare(
      "INSERT INTO crawl_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    );
    stmt.run(key, value);
  }

  /**
   * Handle get state.
   */
  getState(key: string): string | undefined {
    if (!this.hasStateTable) return undefined;
    const row = this.db.prepare("SELECT value FROM crawl_state WHERE key = ?").get(key) as
      | { value: string }
      | undefined;
    return row?.value;
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
   * Handle ensure instance.
   */
  ensureInstance(host: string) {
    const transaction = this.db.transaction((value: string) => {
      this.db.prepare("INSERT OR IGNORE INTO instances (host) VALUES (?)").run(value);
      this.db
        .prepare(
          "INSERT OR IGNORE INTO instance_crawl_progress (host, status, updated_at) VALUES (?, 'pending', ?)"
        )
        .run(value, Date.now());
    });
    transaction(host);
  }

  /**
   * Handle enqueue host.
   */
  enqueueHost(host: string, delayMs = 0) {
    const status = this.getCrawlStatus(host);
    if (status === "done" || status === "processing") return;
    const stmt = this.db.prepare(
      "INSERT OR REPLACE INTO queue (host, enqueued_at) VALUES (?, ?)"
    );
    stmt.run(host, Date.now() + delayMs);
  }

  /**
   * Handle claim next host.
   */
  claimNextHost(): string | null {
    const now = Date.now();
    const transaction = this.db.transaction(() => {
      const row = this.db
        .prepare("SELECT host FROM queue WHERE enqueued_at <= ? ORDER BY enqueued_at ASC LIMIT 1")
        .get(now) as { host: string } | undefined;

      if (!row) return null;

      this.db.prepare("DELETE FROM queue WHERE host = ?").run(row.host);
      this.db
        .prepare(
          "UPDATE instance_crawl_progress SET status = 'processing', last_start = ?, updated_at = ? WHERE host = ?"
        )
        .run(Date.now(), Date.now(), row.host);
      return row.host;
    });

    return transaction();
  }

  /**
   * Handle next queue time.
   */
  nextQueueTime(): number | null {
    const row = this.db
      .prepare("SELECT enqueued_at FROM queue ORDER BY enqueued_at ASC LIMIT 1")
      .get() as { enqueued_at: number } | undefined;
    return row ? row.enqueued_at : null;
  }

  /**
   * Handle mark done.
   */
  markDone(host: string) {
    this.db
      .prepare(
        "UPDATE instances SET last_error = NULL, last_error_at = NULL, last_error_source = NULL WHERE host = ?"
      )
      .run(host);
    this.db
      .prepare(
        "UPDATE instance_crawl_progress SET status = 'done', updated_at = ? WHERE host = ?"
      )
      .run(Date.now(), host);
  }

  /**
   * Handle mark error.
   */
  markError(host: string, error: string) {
    this.db
      .prepare(
        "UPDATE instances SET last_error = ?, last_error_at = ?, last_error_source = ? WHERE host = ?"
      )
      .run(error, Date.now(), "instances", host);
    this.db
      .prepare(
        "UPDATE instance_crawl_progress SET status = 'error', error_count = error_count + 1, updated_at = ? WHERE host = ?"
      )
      .run(Date.now(), host);
  }

  /**
   * Handle get error count.
   */
  getErrorCount(host: string): number {
    const row = this.db
      .prepare("SELECT error_count FROM instance_crawl_progress WHERE host = ?")
      .get(host) as { error_count: number } | undefined;
    return row?.error_count ?? 0;
  }

  /**
   * Handle get crawl status.
   */
  private getCrawlStatus(host: string): string | undefined {
    const row = this.db
      .prepare("SELECT status FROM instance_crawl_progress WHERE host = ?")
      .get(host) as { status: string } | undefined;
    return row?.status;
  }

  /**
   * Handle insert edge.
   */
  insertEdge(source: string, target: string) {
    if (source === target) return;
    this.db
      .prepare("INSERT OR IGNORE INTO edges (source_host, target_host) VALUES (?, ?)")
      .run(source, target);
  }

  /**
   * Handle recover queue.
   */
  recoverQueue(allowedHosts?: Set<string>) {
    this.db
      .prepare("UPDATE instance_crawl_progress SET status = 'pending' WHERE status = 'processing'")
      .run();
    const rows = this.db
      .prepare("SELECT host FROM instance_crawl_progress WHERE status = 'pending'")
      .all() as { host: string }[];
    for (const row of rows) {
      if (allowedHosts && !allowedHosts.has(row.host)) {
        continue;
      }
      this.enqueueHost(row.host);
    }
  }
}
