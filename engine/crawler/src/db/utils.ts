/**
 * Shared crawler database helpers.
 *
 * Helpers live here only when they are reused by multiple store modules or are
 * easier to test as isolated DB utilities. They preserve the SQL behavior from
 * the previous monolithic db.ts module.
 */

import Database from "better-sqlite3";

/**
 * Delete video progress rows for instances in chunks to avoid huge SQL parameter lists.
 */
export function deleteInstancesInChunks(db: Database.Database, instances: string[]) {
  if (instances.length === 0) return;
  const chunkSize = 500;
  for (let i = 0; i < instances.length; i += chunkSize) {
    const chunk = instances.slice(i, i + chunkSize);
    const placeholders = chunk.map(() => "?").join(", ");
    db.prepare(
      `DELETE FROM video_crawl_progress WHERE instance_domain IN (${placeholders})`
    ).run(...chunk);
  }
}
