/**
 * Test helpers for crawler database characterization tests.
 *
 * Helpers create isolated SQLite files and expose direct read utilities so tests
 * assert persisted state instead of method calls.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";

export interface TempDb {
  dir: string;
  dbPath: string;
  cleanup: () => void;
}

/**
 * Create a temporary database path for one crawler DB test.
 */
export function createTempDb(prefix: string): TempDb {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `${prefix}-`));
  return {
    dir,
    dbPath: path.join(dir, "crawl.db"),
    cleanup: () => fs.rmSync(dir, { recursive: true, force: true })
  };
}

/**
 * Read a single row and fail with a helpful assertion if it is missing.
 */
export function getRow<T extends object>(dbPath: string, sql: string, ...params: unknown[]): T {
  const db = new Database(dbPath, { readonly: true });
  try {
    const row = db.prepare(sql).get(...params) as T | undefined;
    assert.ok(row, `expected row for query: ${sql}`);
    return row as T;
  } finally {
    db.close();
  }
}

/**
 * Read all rows from a temporary crawler DB.
 */
export function allRows<T extends object>(dbPath: string, sql: string, ...params: unknown[]): T[] {
  const db = new Database(dbPath, { readonly: true });
  try {
    return db.prepare(sql).all(...params) as T[];
  } finally {
    db.close();
  }
}

/**
 * Execute setup SQL against a temporary crawler DB.
 */
export function execSql(dbPath: string, sql: string, ...params: unknown[]) {
  const db = new Database(dbPath);
  try {
    db.prepare(sql).run(...params);
  } finally {
    db.close();
  }
}
