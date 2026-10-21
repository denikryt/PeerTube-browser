/**
 * SQLite connection helpers for crawler stores.
 *
 * This module centralizes filesystem setup, optional reset behavior, database
 * opening, and WAL configuration while preserving the constructor semantics of
 * the old monolithic db.ts stores.
 */

import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";

export interface OpenCrawlerDatabaseOptions {
  reset?: boolean;
}

/**
 * Open a crawler SQLite database and apply the current WAL setting.
 *
 * The reset option exists for CrawlerStore only; ChannelStore and VideoStore
 * intentionally pass reset=false to preserve their non-deleting constructors.
 */
export function openCrawlerDatabase(
  dbPath: string,
  options: OpenCrawlerDatabaseOptions = {}
): Database.Database {
  const dir = path.dirname(dbPath);
  fs.mkdirSync(dir, { recursive: true });

  if (options.reset && fs.existsSync(dbPath)) {
    fs.unlinkSync(dbPath);
  }

  const db = new Database(dbPath);
  db.pragma("journal_mode = WAL");
  return db;
}
