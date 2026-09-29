/**
 * Orchestrate opt-in live thumbnail candidate verification through production crawler stages.
 *
 * The smoke validates persisted REST metadata only. It may fetch PeerTube video detail JSON
 * to compare persisted candidates with the production normalizer, but it never probes image
 * asset URLs. Broken remote images are intentionally a browser fallback concern.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { crawl } from "./crawler.js";
import { crawlChannels } from "./channels-worker.js";
import { crawlChannelVideosCount } from "./channels-videos-count-worker.js";
import { crawlVideos } from "./videos-worker.js";
import {
  DEFAULT_JOINPEERTUBE_WHITELIST_URL,
  fetchInstanceRegistryHosts
} from "./instance-registry.js";
import { resolveThumbnailCandidates, type PeerTubeVideoMediaLike } from "./video-media.js";

export interface LiveThumbnailSmokeOptions {
  registryUrl: string;
  requiredHosts: number;
  candidateLimit: number;
  maxChannelsPerHost: number;
  maxVideoPages: number;
  timeoutMs: number;
  maxRetries: number;
  concurrency: number;
  fullInstance: boolean;
  keepArtifacts: boolean;
  reportPath: string | null;
}

export interface VideoThumbnailResult {
  host: string;
  videoUuid: string | null;
  videoId: string;
  thumbnailUrl: string | null;
  persistedState: string | null;
  expectedUrls: string[] | null;
  persistedUrls: string[] | null;
  valid: boolean;
  error: string | null;
}

export interface HostSmokeResult {
  host: string;
  accepted: boolean;
  videos: number;
  validCandidateRows: number;
  invalidCandidateRows: number;
  reason: string | null;
  artifactDir: string | null;
  videoResults: VideoThumbnailResult[];
}

export interface LiveThumbnailSmokeReport {
  started_at: string;
  finished_at: string;
  registry_url: string;
  options: Record<string, number | boolean | string | null>;
  attempted_hosts: string[];
  accepted_hosts: HostSmokeResult[];
  rejected_hosts: HostSmokeResult[];
  failures: VideoThumbnailResult[];
  selected_hosts: number;
  crawled_hosts: number;
  crawled_videos: number;
  valid_candidate_rows: number;
  invalid_candidate_rows: number;
  artifact_root: string | null;
}

interface PersistedVideoRow {
  video_id: string;
  video_uuid: string | null;
  instance_domain: string;
  thumbnail_url: string | null;
  thumbnail_candidates_json: string | null;
}

export interface LiveThumbnailSmokeDependencies {
  fetchRegistryHosts: typeof fetchInstanceRegistryHosts;
  crawlInstances: typeof crawl;
  crawlChannelsStage: typeof crawlChannels;
  crawlCountsStage: typeof crawlChannelVideosCount;
  crawlVideosStage: typeof crawlVideos;
  /** Used only for PeerTube detail JSON. Candidate asset URLs must never reach it. */
  fetchImpl: typeof fetch;
  makeTempDir: (prefix: string) => string;
  removeDir: (dir: string) => void;
}

const defaultDependencies: LiveThumbnailSmokeDependencies = {
  fetchRegistryHosts: fetchInstanceRegistryHosts,
  crawlInstances: crawl,
  crawlChannelsStage: crawlChannels,
  crawlCountsStage: crawlChannelVideosCount,
  crawlVideosStage: crawlVideos,
  fetchImpl: fetch,
  makeTempDir: (prefix) => fs.mkdtempSync(path.join(os.tmpdir(), prefix)),
  removeDir: (dir) => fs.rmSync(dir, { recursive: true, force: true })
};

/** Return bounded defaults for the opt-in third-party live smoke. */
export function defaultLiveThumbnailSmokeOptions(): LiveThumbnailSmokeOptions {
  return {
    registryUrl: DEFAULT_JOINPEERTUBE_WHITELIST_URL,
    requiredHosts: 5,
    candidateLimit: 50,
    maxChannelsPerHost: 3,
    maxVideoPages: 1,
    timeoutMs: 8000,
    maxRetries: 1,
    concurrency: 2,
    fullInstance: false,
    keepArtifacts: false,
    reportPath: null
  };
}

/** Run bounded production crawler stages and validate persisted candidate metadata. */
export async function runLiveThumbnailSmoke(
  options: LiveThumbnailSmokeOptions,
  dependencies: Partial<LiveThumbnailSmokeDependencies> = {}
): Promise<LiveThumbnailSmokeReport> {
  const deps = { ...defaultDependencies, ...dependencies };
  const startedAt = new Date().toISOString();
  const artifactRoot = deps.makeTempDir("peertube-thumbnail-smoke-");
  const accepted: HostSmokeResult[] = [];
  const rejected: HostSmokeResult[] = [];
  const attempted: string[] = [];

  try {
    const hosts = await deps.fetchRegistryHosts(options.registryUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    });
    const candidates = hosts.slice(0, options.candidateLimit);

    for (const host of candidates) {
      if (accepted.length >= options.requiredHosts) break;
      attempted.push(host);
      const hostDir = path.join(artifactRoot, sanitizeHost(host));
      fs.mkdirSync(hostDir, { recursive: true });
      const dbPath = path.join(hostDir, "crawl.db");
      const whitelistPath = path.join(hostDir, "whitelist.txt");
      fs.writeFileSync(whitelistPath, `${host}\n`, "utf8");

      let result: HostSmokeResult;
      try {
        await runCandidateCrawler(host, dbPath, whitelistPath, options, deps);
        const rows = readPersistedVideos(dbPath, host);
        if (rows.length === 0) {
          result = rejectedHost(host, "crawler persisted no videos", options.keepArtifacts ? hostDir : null);
        } else {
          const videoResults = await validateRows(rows, options, deps.fetchImpl);
          const invalid = videoResults.filter((item) => !item.valid).length;
          result = {
            host,
            accepted: true,
            videos: rows.length,
            validCandidateRows: rows.length - invalid,
            invalidCandidateRows: invalid,
            reason: null,
            artifactDir: options.keepArtifacts ? hostDir : null,
            videoResults
          };
          accepted.push(result);
        }
      } catch (error) {
        result = rejectedHost(
          host,
          error instanceof Error ? error.message : String(error),
          options.keepArtifacts ? hostDir : null
        );
      }
      if (!result.accepted) rejected.push(result);
      if (!options.keepArtifacts) deps.removeDir(hostDir);
    }

    const report = buildReport(
      startedAt,
      options,
      attempted,
      accepted,
      rejected,
      options.keepArtifacts ? artifactRoot : null
    );
    if (options.reportPath) {
      fs.mkdirSync(path.dirname(options.reportPath), { recursive: true });
      fs.writeFileSync(options.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    }
    return report;
  } finally {
    if (!options.keepArtifacts) deps.removeDir(artifactRoot);
  }
}

/** Render one candidate-oriented summary without implying remote image health. */
export function summarizeLiveThumbnailSmoke(report: LiveThumbnailSmokeReport): string {
  const lines = [
    `started_at=${report.started_at}`,
    `finished_at=${report.finished_at}`,
    `selected_hosts=${report.selected_hosts}`,
    `crawled_hosts=${report.crawled_hosts}`,
    `crawled_videos=${report.crawled_videos}`,
    `valid_candidate_rows=${report.valid_candidate_rows}`,
    `invalid_candidate_rows=${report.invalid_candidate_rows}`
  ];
  for (const host of report.accepted_hosts) {
    lines.push(
      `accepted host=${host.host} videos=${host.videos} valid_candidates=${host.validCandidateRows} invalid_candidates=${host.invalidCandidateRows}`
    );
    for (const video of host.videoResults.filter((item) => !item.valid)) {
      lines.push(
        `invalid host=${video.host} video_uuid=${video.videoUuid ?? "null"} video_id=${video.videoId} error=${video.error ?? "unknown"}`
      );
    }
  }
  for (const host of report.rejected_hosts) {
    lines.push(`rejected host=${host.host} reason=${host.reason ?? "unknown"}`);
  }
  return lines.join("\n");
}

/** Enforce live-smoke candidate-persistence acceptance criteria. */
export function assertLiveThumbnailSmoke(report: LiveThumbnailSmokeReport): void {
  const requiredHosts = Number(report.options.required_hosts ?? 0);
  if (report.selected_hosts < requiredHosts) {
    throw new Error(`insufficient usable hosts: selected=${report.selected_hosts} required=${requiredHosts}`);
  }
  if (report.crawled_videos <= 0) throw new Error("live thumbnail smoke crawled zero videos");
  if (report.invalid_candidate_rows > 0) {
    throw new Error(
      `live thumbnail smoke found ${report.invalid_candidate_rows} candidate persistence mismatches`
    );
  }
}

/** Execute the existing production crawler stages against one isolated candidate DB. */
async function runCandidateCrawler(
  host: string,
  dbPath: string,
  whitelistPath: string,
  options: LiveThumbnailSmokeOptions,
  deps: LiveThumbnailSmokeDependencies
): Promise<void> {
  await deps.crawlInstances({
    whitelistUrl: options.registryUrl,
    whitelistFile: whitelistPath,
    hostsFile: null,
    excludeHostsFile: null,
    dbPath,
    concurrency: 1,
    hostDelayMs: 0,
    timeoutMs: options.timeoutMs,
    resume: false,
    maxRetries: options.maxRetries,
    maxErrors: 1,
    maxInstances: 1,
    expandBeyondWhitelist: false,
    collectGraph: false
  });
  await deps.crawlChannelsStage({
    dbPath,
    hostsFile: null,
    excludeHostsFile: null,
    concurrency: 1,
    hostConcurrency: 1,
    hostDelayMs: 0,
    timeoutMs: options.timeoutMs,
    maxRetries: options.maxRetries,
    newOnly: false,
    maxInstances: 1,
    maxChannels: options.fullInstance ? 0 : options.maxChannelsPerHost,
    resume: false,
    errorsOnly: false
  });
  await deps.crawlCountsStage({
    dbPath,
    hostsFile: null,
    excludeHostsFile: null,
    concurrency: 1,
    hostConcurrency: 1,
    hostDelayMs: 0,
    timeoutMs: options.timeoutMs,
    maxRetries: options.maxRetries,
    resume: false,
    errorsOnly: false
  });
  await deps.crawlVideosStage({
    dbPath,
    hostsFile: null,
    excludeHostsFile: null,
    existingDbPath: null,
    concurrency: Math.max(1, options.concurrency),
    hostConcurrency: 1,
    timeoutMs: options.timeoutMs,
    maxRetries: options.maxRetries,
    resume: false,
    errorsOnly: false,
    newOnly: false,
    stopAfterFullPages: 0,
    sort: "-publishedAt",
    maxInstances: 1,
    maxChannels: options.fullInstance ? 0 : options.maxChannelsPerHost,
    maxVideosPages: options.fullInstance ? 0 : options.maxVideoPages,
    tagsOnly: false,
    updateTags: false,
    commentsOnly: false,
    refreshThumbnails: false,
    metadataOnly: false,
    updateMetadata: false,
    onlyHealthyHosts: false,
    hostDelayMs: 0
  });
  void host;
}

/** Compare persisted candidate state with a fresh REST detail normalization only. */
async function validateRows(
  rows: PersistedVideoRow[],
  options: LiveThumbnailSmokeOptions,
  fetchImpl: typeof fetch
): Promise<VideoThumbnailResult[]> {
  return mapWithConcurrency(rows, Math.max(1, options.concurrency), async (row) => {
    if (!row.video_uuid) {
      return invalidResult(row, null, null, "missing video_uuid");
    }
    const detailUrl = `https://${row.instance_domain}/api/v1/videos/${encodeURIComponent(row.video_uuid)}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs);
    let detail: PeerTubeVideoMediaLike;
    try {
      const response = await fetchImpl(detailUrl, {
        redirect: "follow",
        signal: controller.signal,
        headers: { accept: "application/json" }
      });
      if (!response.ok) {
        return invalidResult(row, null, null, `HTTP ${response.status} for ${detailUrl}`);
      }
      detail = (await response.json()) as PeerTubeVideoMediaLike;
    } catch (error) {
      return invalidResult(row, null, null, error instanceof Error ? error.message : String(error));
    } finally {
      clearTimeout(timeout);
    }

    const expectedCandidates = resolveThumbnailCandidates(detail.thumbnails, row.instance_domain, "https:");
    if (expectedCandidates === null) {
      const valid = row.thumbnail_candidates_json === null;
      return {
        ...baseResult(row),
        expectedUrls: null,
        persistedUrls: null,
        valid,
        error: valid ? null : "legacy detail must preserve SQL NULL candidate state"
      };
    }

    const expectedUrls = expectedCandidates.map((candidate) => candidate.url);
    const persisted = parseStoredCandidateArray(row.thumbnail_candidates_json);
    if (!persisted.ok) {
      return invalidResult(row, expectedUrls, null, persisted.error);
    }
    const mirror = expectedCandidates[0]?.url ?? null;
    const valid = arraysEqual(persisted.urls, expectedUrls) && row.thumbnail_url === mirror;
    return {
      ...baseResult(row),
      expectedUrls,
      persistedUrls: persisted.urls,
      valid,
      error: valid ? null : "persisted candidate order or primary mirror differs from REST normalization"
    };
  });
}

/** Decode the authoritative candidate-object storage shape into ordered URLs. */
function parseStoredCandidateArray(value: string | null):
  | { ok: true; urls: string[] }
  | { ok: false; error: string } {
  if (value === null) return { ok: false, error: "candidate state is SQL NULL after successful modern detail" };
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) {
      return { ok: false, error: "candidate storage is not a JSON array" };
    }
    const urls: string[] = [];
    for (const item of parsed) {
      if (!item || typeof item !== "object" || typeof (item as { url?: unknown }).url !== "string") {
        return { ok: false, error: "candidate storage contains a non-candidate member" };
      }
      urls.push((item as { url: string }).url);
    }
    return { ok: true, urls };
  } catch {
    return { ok: false, error: "candidate storage is malformed JSON" };
  }
}

/** Build common per-row reporting fields without exposing raw crawler internals. */
function baseResult(row: PersistedVideoRow) {
  return {
    host: row.instance_domain,
    videoUuid: row.video_uuid,
    videoId: row.video_id,
    thumbnailUrl: row.thumbnail_url,
    persistedState: row.thumbnail_candidates_json
  };
}

/** Build a controlled invalid-row result for detail/storage failures. */
function invalidResult(
  row: PersistedVideoRow,
  expectedUrls: string[] | null,
  persistedUrls: string[] | null,
  error: string
): VideoThumbnailResult {
  return {
    ...baseResult(row),
    expectedUrls,
    persistedUrls,
    valid: false,
    error
  };
}

/** Apply bounded concurrency without changing source ordering in the report. */
async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workers = Array.from(
    { length: Math.min(concurrency, Math.max(1, items.length)) },
    async () => {
      while (true) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= items.length) return;
        results[index] = await mapper(items[index]);
      }
    }
  );
  await Promise.all(workers);
  return results;
}

/** Read only candidate-state fields needed by the smoke. */
function readPersistedVideos(dbPath: string, host: string): PersistedVideoRow[] {
  const db = new Database(dbPath, { readonly: true });
  try {
    return db.prepare(
      `SELECT video_id, video_uuid, instance_domain, thumbnail_url, thumbnail_candidates_json
       FROM videos
       WHERE instance_domain = ?
       ORDER BY video_id ASC`
    ).all(host) as PersistedVideoRow[];
  } finally {
    db.close();
  }
}

/** Compare two ordered candidate lists exactly. */
function arraysEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

/** Build one rejected-host result without partial candidate state. */
function rejectedHost(host: string, reason: string, artifactDir: string | null): HostSmokeResult {
  return {
    host,
    accepted: false,
    videos: 0,
    validCandidateRows: 0,
    invalidCandidateRows: 0,
    reason,
    artifactDir,
    videoResults: []
  };
}

/** Aggregate candidate-oriented counts and failure rows. */
function buildReport(
  startedAt: string,
  options: LiveThumbnailSmokeOptions,
  attempted: string[],
  accepted: HostSmokeResult[],
  rejected: HostSmokeResult[],
  artifactRoot: string | null
): LiveThumbnailSmokeReport {
  const crawledVideos = accepted.reduce((sum, host) => sum + host.videos, 0);
  const valid = accepted.reduce((sum, host) => sum + host.validCandidateRows, 0);
  const invalid = accepted.reduce((sum, host) => sum + host.invalidCandidateRows, 0);
  return {
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    registry_url: options.registryUrl,
    options: {
      required_hosts: options.requiredHosts,
      candidate_limit: options.candidateLimit,
      max_channels_per_host: options.maxChannelsPerHost,
      max_video_pages: options.maxVideoPages,
      timeout_ms: options.timeoutMs,
      max_retries: options.maxRetries,
      concurrency: options.concurrency,
      full_instance: options.fullInstance,
      keep_artifacts: options.keepArtifacts,
      report_path: options.reportPath
    },
    attempted_hosts: attempted,
    accepted_hosts: accepted,
    rejected_hosts: rejected,
    failures: accepted.flatMap((host) => host.videoResults.filter((item) => !item.valid)),
    selected_hosts: accepted.length,
    crawled_hosts: accepted.length,
    crawled_videos: crawledVideos,
    valid_candidate_rows: valid,
    invalid_candidate_rows: invalid,
    artifact_root: artifactRoot
  };
}

/** Convert a registry host into a filesystem-safe artifact directory name. */
function sanitizeHost(host: string): string {
  return host.replace(/[^a-z0-9.-]+/gi, "_");
}
