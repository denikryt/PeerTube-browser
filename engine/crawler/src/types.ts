/**
 * Module `engine/crawler/src/types.ts`: provide runtime functionality.
 */

export type CrawlStatus = "pending" | "processing" | "done" | "error";

export interface CrawlOptions {
  whitelistUrl: string;
  whitelistFile: string | null;
  excludeHostsFile: string | null;
  dbPath: string;
  concurrency: number;
  timeoutMs: number;
  resume: boolean;
  maxRetries: number;
  maxErrors: number;
  maxInstances: number;
  expandBeyondWhitelist: boolean;
  collectGraph: boolean;
}

export interface Page<T> {
  total?: number;
  data?: T[];
}

export interface ServerFollowItem {
  id?: number | string;
  follower?: PeerTubeServerRef | string;
  following?: PeerTubeServerRef | string;
}

export interface PeerTubeServerRef {
  host?: string;
  hostname?: string;
  url?: string;
  id?: string;
  name?: string;
}
