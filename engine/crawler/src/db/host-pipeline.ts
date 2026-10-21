/** Read-only scheduling state for the optional host-level crawler pipeline. */

import Database from "better-sqlite3";

import { openCrawlerDatabase } from "./connection.js";

export type HostPipelineStage = "channels" | "counts" | "videos";

export interface HostPipelineCandidate {
  host: string;
  stage: HostPipelineStage;
}

/**
 * Classify hosts by their earliest unfinished normal-crawl stage.
 *
 * This repository does not mutate progress. It only gives the scheduler a
 * deterministic channels -> NULL counts -> videos queue and omits hosts whose
 * normal work is already complete or retained for explicit error retry.
 */
export class HostPipelineStore {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = openCrawlerDatabase(dbPath);
  }

  /** Close the scheduling read connection. */
  close() {
    this.db.close();
  }

  /** Return pending hosts ordered by their earliest unfinished stage. */
  listPendingHosts(hosts: string[]): HostPipelineCandidate[] {
    if (hosts.length === 0) return [];
    const placeholders = hosts.map(() => "?").join(", ");
    return this.db.prepare(
      `WITH candidates AS (
         SELECT i.host,
                CASE
                  WHEN cp.instance_domain IS NULL
                    OR cp.status IN ('pending', 'in_progress')
                    THEN 'channels'
                  WHEN EXISTS (
                    SELECT 1 FROM channels c
                    WHERE c.instance_domain = i.host
                      AND c.channel_name IS NOT NULL
                      AND c.videos_count IS NULL
                      AND COALESCE(c.last_error_source, '') != 'videos_count'
                  ) THEN 'counts'
                  WHEN EXISTS (
                    SELECT 1
                    FROM channels c
                    LEFT JOIN video_crawl_progress vp
                      ON vp.instance_domain = c.instance_domain
                     AND vp.channel_id = c.channel_id
                    WHERE c.instance_domain = i.host
                      AND c.channel_name IS NOT NULL
                      AND c.videos_count > 0
                      AND (vp.channel_id IS NULL OR vp.status IN ('pending', 'in_progress'))
                  ) THEN 'videos'
                  ELSE 'complete'
                END AS stage
         FROM instances i
         LEFT JOIN channel_crawl_progress cp ON cp.instance_domain = i.host
         WHERE i.host IN (${placeholders})
       )
       SELECT host, stage
       FROM candidates
       WHERE stage != 'complete'
       ORDER BY CASE stage
                  WHEN 'channels' THEN 0
                  WHEN 'counts' THEN 1
                  WHEN 'videos' THEN 2
                  ELSE 3
                END,
                host ASC`
    ).all(...hosts) as HostPipelineCandidate[];
  }
}
