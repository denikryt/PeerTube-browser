/**
 * Orchestrate opt-in live thumbnail verification through the production crawler pipeline.
 *
 * This module is intentionally separate from deterministic tests. It owns bounded live
 * orchestration, image probing, failure diagnostics, artifact cleanup, and structured
 * reporting while delegating all PeerTube persistence work to production crawler stages.
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
import { resolvePeerTubeMediaUrl, type PeerTubeVideoMediaLike } from "./video-media.js";

const DEFAULT_BODY_CAP_BYTES = 64 * 1024;

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
  bodyCapBytes?: number;
}

export interface ThumbnailProbeResult {
  url: string;
  valid: boolean;
  status: number | null;
  contentType: string | null;
  finalUrl: string | null;
  bytesRead: number;
  error: string | null;
}

export type ThumbnailFailureClassification =
  | "stored_thumbnail_stale_but_live_candidate_works"
  | "all_live_candidates_invalid"
  | "video_detail_unavailable"
  | "media_fields_missing";

export interface VideoThumbnailResult {
  host: string;
  videoUuid: string | null;
  videoId: string;
  thumbnailUrl: string | null;
  previewPath: string | null;
  probe: ThumbnailProbeResult;
  classification: ThumbnailFailureClassification | null;
  candidateProbes: ThumbnailProbeResult[];
  detailError: string | null;
}

export interface HostSmokeResult {
  host: string;
  accepted: boolean;
  videos: number;
  validThumbnails: number;
  invalidThumbnails: number;
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
  valid_thumbnails: number;
  invalid_thumbnails: number;
  artifact_root: string | null;
}

interface PersistedVideoRow {
  video_id: string;
  video_uuid: string | null;
  instance_domain: string;
  thumbnail_url: string | null;
  preview_path: string | null;
}

export interface LiveThumbnailSmokeDependencies {
  fetchRegistryHosts: typeof fetchInstanceRegistryHosts;
  crawlInstances: typeof crawl;
  crawlChannelsStage: typeof crawlChannels;
  crawlCountsStage: typeof crawlChannelVideosCount;
  crawlVideosStage: typeof crawlVideos;
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

/** Return the live runner defaults used by the CLI and documentation. */
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
    reportPath: null,
    bodyCapBytes: DEFAULT_BODY_CAP_BYTES
  };
}

/** Probe an image URL with bounded GET semantics used by both stored and detail candidates. */
export async function probeThumbnailUrl(
  url: string,
  options: { timeoutMs: number; bodyCapBytes?: number; fetchImpl?: typeof fetch }
): Promise<ThumbnailProbeResult> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const bodyCapBytes = options.bodyCapBytes ?? DEFAULT_BODY_CAP_BYTES;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs);

  try {
    const response = await fetchImpl(url, {
      redirect: "follow",
      signal: controller.signal,
      headers: { accept: "image/*,*/*;q=0.8" }
    });
    const contentType = response.headers.get("content-type");
    const bytesRead = await readBoundedBody(response, bodyCapBytes);
    const valid =
      response.status >= 200 &&
      response.status <= 299 &&
      Boolean(contentType?.toLowerCase().startsWith("image/")) &&
      bytesRead > 0;
    return {
      url,
      valid,
      status: response.status,
      contentType,
      finalUrl: response.url || url,
      bytesRead,
      error: valid ? null : describeInvalidResponse(response.status, contentType, bytesRead)
    };
  } catch (error) {
    return {
      url,
      valid: false,
      status: null,
      contentType: null,
      finalUrl: null,
      bytesRead: 0,
      error: error instanceof Error ? error.message : String(error)
    };
  } finally {
    clearTimeout(timeout);
  }
}

/** Diagnose one failed stored URL against current PeerTube detail media fields. */
export async function diagnoseFailedThumbnail(
  row: PersistedVideoRow,
  options: { timeoutMs: number; bodyCapBytes?: number; fetchImpl?: typeof fetch }
): Promise<{
  classification: ThumbnailFailureClassification;
  candidateProbes: ThumbnailProbeResult[];
  detailError: string | null;
}> {
  const fetchImpl = options.fetchImpl ?? fetch;
  if (!row.video_uuid) {
    return { classification: "video_detail_unavailable", candidateProbes: [], detailError: "missing video_uuid" };
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
      return {
        classification: "video_detail_unavailable",
        candidateProbes: [],
        detailError: `HTTP ${response.status} for ${detailUrl}`
      };
    }
    detail = (await response.json()) as PeerTubeVideoMediaLike;
  } catch (error) {
    return {
      classification: "video_detail_unavailable",
      candidateProbes: [],
      detailError: error instanceof Error ? error.message : String(error)
    };
  } finally {
    clearTimeout(timeout);
  }

  const rawCandidates = [
    detail.thumbnailPath,
    detail.thumbnailUrl,
    detail.previewPath,
    detail.previewUrl,
    detail.thumbnail,
    detail.thumbnail_path,
    detail.preview_path
  ];
  const candidates: string[] = [];
  const seen = new Set<string>();
  for (const raw of rawCandidates) {
    const resolved = resolvePeerTubeMediaUrl(raw, row.instance_domain, "https:");
    if (!resolved || seen.has(resolved)) continue;
    seen.add(resolved);
    candidates.push(resolved);
  }
  if (candidates.length === 0) {
    return { classification: "media_fields_missing", candidateProbes: [], detailError: null };
  }

  const candidateProbes: ThumbnailProbeResult[] = [];
  for (const candidate of candidates) {
    candidateProbes.push(await probeThumbnailUrl(candidate, options));
  }
  return {
    classification: candidateProbes.some((probe) => probe.valid)
      ? "stored_thumbnail_stale_but_live_candidate_works"
      : "all_live_candidates_invalid",
    candidateProbes,
    detailError: null
  };
}

/** Run the bounded live crawl and validate every video persisted by accepted hosts. */
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
          const invalid = videoResults.filter((item) => !item.probe.valid).length;
          result = {
            host,
            accepted: true,
            videos: rows.length,
            validThumbnails: rows.length - invalid,
            invalidThumbnails: invalid,
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

    const report = buildReport(startedAt, options, attempted, accepted, rejected, options.keepArtifacts ? artifactRoot : null);
    if (options.reportPath) {
      fs.mkdirSync(path.dirname(options.reportPath), { recursive: true });
      fs.writeFileSync(options.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    }
    return report;
  } finally {
    if (!options.keepArtifacts) deps.removeDir(artifactRoot);
  }
}

/** Render a concise human-readable report with host and failure details. */
export function summarizeLiveThumbnailSmoke(report: LiveThumbnailSmokeReport): string {
  const lines = [
    `started_at=${report.started_at}`,
    `finished_at=${report.finished_at}`,
    `selected_hosts=${report.selected_hosts}`,
    `crawled_hosts=${report.crawled_hosts}`,
    `crawled_videos=${report.crawled_videos}`,
    `valid_thumbnails=${report.valid_thumbnails}`,
    `invalid_thumbnails=${report.invalid_thumbnails}`
  ];
  for (const host of report.accepted_hosts) {
    lines.push(`accepted host=${host.host} videos=${host.videos} valid=${host.validThumbnails} invalid=${host.invalidThumbnails}`);
    for (const video of host.videoResults.filter((item) => !item.probe.valid)) {
      lines.push(
        `invalid host=${video.host} video_uuid=${video.videoUuid ?? "null"} video_id=${video.videoId} status=${video.probe.status ?? "null"} content_type=${video.probe.contentType ?? "null"} final_url=${video.probe.finalUrl ?? "null"} classification=${video.classification ?? "null"} error=${video.probe.error ?? "unknown"}`
      );
    }
  }
  for (const host of report.rejected_hosts) {
    lines.push(`rejected host=${host.host} reason=${host.reason ?? "unknown"}`);
  }
  return lines.join("\n");
}

/** Enforce all live-smoke acceptance criteria with one controlled error. */
export function assertLiveThumbnailSmoke(report: LiveThumbnailSmokeReport): void {
  const requiredHosts = Number(report.options.required_hosts ?? 0);
  if (report.selected_hosts < requiredHosts) {
    throw new Error(`insufficient usable hosts: selected=${report.selected_hosts} required=${requiredHosts}`);
  }
  if (report.crawled_videos <= 0) throw new Error("live thumbnail smoke crawled zero videos");
  if (report.invalid_thumbnails > 0) {
    throw new Error(`live thumbnail smoke found ${report.invalid_thumbnails} invalid thumbnails`);
  }
}

/** Execute the exact production crawler stages against one isolated candidate DB. */
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
    timeoutMs: options.timeoutMs,
    maxRetries: options.maxRetries,
    newOnly: false,
    maxInstances: 1,
    maxChannels: options.fullInstance ? 0 : options.maxChannelsPerHost,
    resume: false
  });
  await deps.crawlCountsStage({
    dbPath,
    hostsFile: null,
    excludeHostsFile: null,
    concurrency: 1,
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
    hostDelayMs: 0
  });
  void host;
}

/** Validate all persisted rows and attach live-detail diagnostics to each failure. */
async function validateRows(
  rows: PersistedVideoRow[],
  options: LiveThumbnailSmokeOptions,
  fetchImpl: typeof fetch
): Promise<VideoThumbnailResult[]> {
  return mapWithConcurrency(rows, Math.max(1, options.concurrency), async (row) => {
    const url = normalizeAbsoluteHttpUrl(row.thumbnail_url);
    const probe = url
      ? await probeThumbnailUrl(url, { timeoutMs: options.timeoutMs, bodyCapBytes: options.bodyCapBytes, fetchImpl })
      : missingUrlProbe(row.thumbnail_url);
    let classification: ThumbnailFailureClassification | null = null;
    let candidateProbes: ThumbnailProbeResult[] = [];
    let detailError: string | null = null;
    if (!probe.valid) {
      const diagnostic = await diagnoseFailedThumbnail(row, {
        timeoutMs: options.timeoutMs,
        bodyCapBytes: options.bodyCapBytes,
        fetchImpl
      });
      classification = diagnostic.classification;
      candidateProbes = diagnostic.candidateProbes;
      detailError = diagnostic.detailError;
    }
    return {
      host: row.instance_domain,
      videoUuid: row.video_uuid,
      videoId: row.video_id,
      thumbnailUrl: row.thumbnail_url,
      previewPath: row.preview_path,
      probe,
      classification,
      candidateProbes,
      detailError
    };
  });
}

/** Apply bounded concurrency without changing source ordering in the returned report. */
async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(concurrency, Math.max(1, items.length)) }, async () => {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= items.length) return;
      results[index] = await mapper(items[index]);
    }
  });
  await Promise.all(workers);
  return results;
}

/** Read only the persisted media fields required by the smoke contract. */
function readPersistedVideos(dbPath: string, host: string): PersistedVideoRow[] {
  const db = new Database(dbPath, { readonly: true });
  try {
    return db.prepare(
      `SELECT video_id, video_uuid, instance_domain, thumbnail_url, preview_path
       FROM videos
       WHERE instance_domain = ?
       ORDER BY video_id ASC`
    ).all(host) as PersistedVideoRow[];
  } finally {
    db.close();
  }
}

/** Read at most the configured byte cap and cancel the remaining response body. */
async function readBoundedBody(response: Response, cap: number): Promise<number> {
  if (!response.body) return 0;
  const reader = response.body.getReader();
  let total = 0;
  try {
    while (total < cap) {
      const { done, value } = await reader.read();
      if (done) break;
      total += Math.min(value.byteLength, cap - total);
      if (total >= cap) {
        await reader.cancel("thumbnail probe byte cap reached");
        break;
      }
    }
    return total;
  } finally {
    reader.releaseLock();
  }
}

/** Reject blank, relative, and non-HTTP stored thumbnail values before network I/O. */
function normalizeAbsoluteHttpUrl(value: string | null): string | null {
  if (!value?.trim()) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/** Represent a missing or malformed stored URL in the same structured probe model. */
function missingUrlProbe(value: string | null): ThumbnailProbeResult {
  return {
    url: value ?? "",
    valid: false,
    status: null,
    contentType: null,
    finalUrl: null,
    bytesRead: 0,
    error: value?.trim() ? "thumbnail_url is not an absolute HTTP URL" : "thumbnail_url is empty"
  };
}

/** Produce a stable reason for status, media type, or empty-body contract failures. */
function describeInvalidResponse(status: number, contentType: string | null, bytesRead: number): string {
  if (status < 200 || status > 299) return `HTTP ${status}`;
  if (!contentType?.toLowerCase().startsWith("image/")) return `unexpected content-type ${contentType ?? "missing"}`;
  if (bytesRead <= 0) return "empty response body";
  return "invalid image response";
}

/** Build one rejected-host result without leaking partial candidate state. */
function rejectedHost(host: string, reason: string, artifactDir: string | null): HostSmokeResult {
  return {
    host,
    accepted: false,
    videos: 0,
    validThumbnails: 0,
    invalidThumbnails: 0,
    reason,
    artifactDir,
    videoResults: []
  };
}

/** Aggregate stable summary counts and a flat failure list from per-host results. */
function buildReport(
  startedAt: string,
  options: LiveThumbnailSmokeOptions,
  attempted: string[],
  accepted: HostSmokeResult[],
  rejected: HostSmokeResult[],
  artifactRoot: string | null
): LiveThumbnailSmokeReport {
  const crawledVideos = accepted.reduce((sum, host) => sum + host.videos, 0);
  const valid = accepted.reduce((sum, host) => sum + host.validThumbnails, 0);
  const invalid = accepted.reduce((sum, host) => sum + host.invalidThumbnails, 0);
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
    failures: accepted.flatMap((host) => host.videoResults.filter((item) => !item.probe.valid)),
    selected_hosts: accepted.length,
    crawled_hosts: accepted.length,
    crawled_videos: crawledVideos,
    valid_thumbnails: valid,
    invalid_thumbnails: invalid,
    artifact_root: artifactRoot
  };
}

/** Convert a registry host into a filesystem-safe isolated artifact directory name. */
function sanitizeHost(host: string): string {
  return host.replace(/[^a-z0-9.-]+/gi, "_");
}
