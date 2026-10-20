/**
 * Module `engine/crawler/src/channels-videos-count-worker.ts`: provide runtime functionality.
 */

import { ChannelStore } from "./db/channels.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { formatCrawlError, shouldTryAlternateProtocol } from "./error-classification.js";
import { createRequestLimiter, type RequestLimiter } from "./request-limiter.js";
import { loadHostsFromFile, loadIncludedHostsFromFile, scopeHosts } from "./host-filters.js";
import { formatMetricLog } from "./log-format.js";
import { assertWorkActive, stopWork, type WorkCancellation } from "./work-cancellation.js";

const CHANNEL_CONCURRENCY = 2;

export interface ChannelVideosCountOptions {
  dbPath: string;
  hostsFile: string | null;
  excludeHostsFile: string | null;
  concurrency: number;
  hostConcurrency: number;
  hostDelayMs: number;
  timeoutMs: number;
  maxRetries: number;
  resume: boolean;
  errorsOnly: boolean;
  /** In-process host scope used by the optional host-level scheduler. */
  hosts?: readonly string[];
  /** Run-wide cancellation shared by all host-pipeline stages when provided. */
  cancellation?: WorkCancellation;
}

interface ChannelVideoPage {
  total?: number;
}

interface ChannelVideoCountResult {
  total: number | null;
  error: string | null;
}

interface ChannelProgressState {
  totalChannels: number;
  channelsWithVideosCount: number;
  channelsWithError: number;
  updatedThisRun: number;
}

type StatusReporter = (message: string) => void;

/**
 * Handle crawl channel videos count.
 */
export async function crawlChannelVideosCount(options: ChannelVideosCountOptions) {
  const cancellation = options.cancellation ?? { stopped: false };
  assertWorkActive(cancellation);
  const store = new ChannelStore({ dbPath: options.dbPath });
  const includedHosts = loadIncludedHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const selected = scopeHosts(store.listInstances(), includedHosts, excludedHosts, options.hosts);
  // Retry provenance belongs to hosts with count errors, not to unrelated
  // historical parents in the same unscoped staging database.
  const repairScope = options.errorsOnly ? store.listHostsWithCountRepair(selected) : selected;
  if (options.errorsOnly) store.assertParentEnumerationPrepared(repairScope);
  const hosts = store.listFreshHealthyHosts(repairScope, true);
  const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));

  const counts = store.getChannelCounts();
  const progress: ChannelProgressState = {
    totalChannels: counts.total,
    channelsWithVideosCount: counts.withVideos,
    channelsWithError: counts.withError,
    updatedThisRun: 0
  };
  updateStatus(
    `[channels-videos] instances=${hosts.length} concurrency=${workerCount} hostConcurrency=${options.hostConcurrency} resume=${options.resume} errorsOnly=${options.errorsOnly}`
  );
  updateProgress(progress);
  updateStatus("[channels-videos] idle");

  const queue = hosts.slice();
  const workers = Array.from({ length: workerCount }, () =>
    workerLoop(queue, store, options, progress, cancellation)
  );
  try {
    const results = await Promise.allSettled(workers.map(worker => worker.catch(error => {
      stopWork(cancellation, error);
      queue.length = 0;
      throw error;
    })));
    const rejected = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
    if (rejected) throw rejected.reason;
    updateStatus("[channels-videos] finished");
  } finally {
    store.close();
  }
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  queue: string[],
  store: ChannelStore,
  options: ChannelVideosCountOptions,
  progress: ChannelProgressState,
  cancellation: WorkCancellation
) {
  while (!cancellation.stopped) {
    const host = queue.pop();
    if (!host) return;
    await processInstance(host, store, options, progress, cancellation);
  }
}

/**
 * Handle process instance.
 */
async function processInstance(
  host: string,
  store: ChannelStore,
  options: ChannelVideosCountOptions,
  progress: ChannelProgressState,
  cancellation: WorkCancellation
) {
  assertWorkActive(cancellation);
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(
    options.hostConcurrency, options.hostDelayMs,
    () => assertWorkActive(cancellation),
    (error) => { if (isNoNetworkError(error)) stopWork(cancellation, error); }
  );
  updateStatus(`[channels-videos] start ${normalizedHost}`);

  try {
    const { total, updated } = await updateVideosCountForInstance(
      normalizedHost,
      store,
      options,
      progress,
      requestLimiter,
      cancellation
    );
    updateStatus(
      formatMetricLog(
        "channels-videos",
        [["updated", updated], ["total", total]],
        "host",
        normalizedHost
      )
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    updateStatus(`[channels-videos] error ${normalizedHost}: ${message}`);
    if (isNoNetworkError(error)) {
      stopWork(cancellation, error);
      throw error;
    }
  }
}

/**
 * Handle update videos count for instance.
 */
async function updateVideosCountForInstance(
  host: string,
  store: ChannelStore,
  options: ChannelVideosCountOptions,
  progress: ChannelProgressState,
  requestLimiter: RequestLimiter,
  cancellation: WorkCancellation
) {
  assertWorkActive(cancellation);
  const channels = store.listChannelsForVideoCount(host, options.resume, options.errorsOnly);
  let updated = 0;

  await mapWithConcurrency(channels, CHANNEL_CONCURRENCY, async (channel) => {
    // The repository query already excludes completed rows and, during normal
    // resume, recorded errors. This worker therefore performs network work only.
    assertWorkActive(cancellation);
    if (!channel.channel_name) return;
    const hadError = channel.last_error_source === "videos_count";
    const videosCount = await fetchChannelVideosCount(
      host,
      channel.channel_name,
      options,
      (message) => updateStatus(message),
      requestLimiter
    );
    if (videosCount.error) {
      store.updateChannelVideosCountError(channel.channel_id, host, videosCount.error);
      if (!hadError) {
        progress.channelsWithError += 1;
      }
      updateStatus(`[channels-videos] error ${host}/${channel.channel_name}`);
      updateProgress(progress);
      return;
    }
    if (videosCount.total === null) return;
    store.updateChannelVideosCount(channel.channel_id, host, videosCount.total);
    updated += 1;
    progress.updatedThisRun += 1;
    // ``with_videos`` is a content metric, not a count-completeness metric:
    // resolved empty channels must not inflate it.
    if (videosCount.total > 0) {
      progress.channelsWithVideosCount += 1;
    }
    if (hadError) {
      progress.channelsWithError = Math.max(0, progress.channelsWithError - 1);
    }
    updateStatus(
      formatMetricLog(
        "channels-videos",
        [["videos_count", videosCount.total]],
        "channel",
        `${host}/${channel.channel_name}`
      )
    );
    updateProgress(progress);
  }, cancellation);

  return { total: channels.length, updated };
}

/**
 * Handle fetch channel videos count.
 */
async function fetchChannelVideosCount(
  host: string,
  channelName: string,
  options: ChannelVideosCountOptions,
  reportStatus: StatusReporter,
  requestLimiter: RequestLimiter
): Promise<ChannelVideoCountResult> {
  try {
    const page = await fetchWithFallback(
      host,
      channelName,
      options,
      "https:",
      reportStatus,
      requestLimiter
    );
    const total = page.total;
    if (typeof total === "number" && Number.isSafeInteger(total) && total >= 0) {
      return { total, error: null };
    }
    return { total: null, error: "[invalid_response] invalid total in response" };
  } catch (error) {
    if (isNoNetworkError(error)) {
      throw error;
    }
    const message = formatCrawlError(error);
    reportStatus(`[channels-videos] count error ${host}/${channelName}: ${message}`);
    return { total: null, error: message };
  }
}

/**
 * Handle fetch with fallback.
 */
async function fetchWithFallback(
  host: string,
  channelName: string,
  options: ChannelVideosCountOptions,
  protocol: string,
  reportStatus: StatusReporter,
  requestLimiter: RequestLimiter
) {
  const url = buildChannelVideosUrl(host, channelName, 0, 1, protocol);
  try {
    return await requestLimiter.run(() => fetchJsonWithRetry<ChannelVideoPage>(url, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries,
      log: reportStatus
    }));
  } catch (error) {
    // An explicit local outage has priority over message-based protocol fallback.
    if (isNoNetworkError(error) || !shouldTryAlternateProtocol(error)) throw error;
    const alternate = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildChannelVideosUrl(host, channelName, 0, 1, alternate);
    return await requestLimiter.run(() => fetchJsonWithRetry<ChannelVideoPage>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2)),
      log: reportStatus
    }));
  }
}

/**
 * Handle build channel videos url.
 */
function buildChannelVideosUrl(
  host: string,
  channelName: string,
  start: number,
  count: number,
  protocol: string
) {
  return `${protocol}//${host}/api/v1/video-channels/${encodeURIComponent(
    channelName
  )}/videos?start=${start}&count=${count}`;
}

async function mapWithConcurrency<T>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<void>,
  cancellation: WorkCancellation
) {
  if (items.length === 0) return;
  const limit = Math.max(1, concurrency);
  let index = 0;

  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (!cancellation.stopped) {
      const current = index;
      index += 1;
      if (current >= items.length) return;
      try {
        await mapper(items[current]);
      } catch (error) {
        // A proven local outage prevents newly scheduled channel requests,
        // while all already-started mappers must finish before SQLite closes.
        stopWork(cancellation, error);
        index = items.length;
        throw error;
      }
    }
  });

  const settled = await Promise.allSettled(workers);
  const rejected = settled.find((result): result is PromiseRejectedResult => result.status === "rejected");
  if (rejected) throw rejected.reason;
}

/**
 * Handle format progress.
 */
function formatProgress(progress: ChannelProgressState) {
  const total = Math.max(0, progress.totalChannels);
  const withVideos = Math.max(0, progress.channelsWithVideosCount);
  return formatMetricLog(
    "channels-videos",
    [
      ["updated", progress.updatedThisRun],
      ["errors", progress.channelsWithError],
      ["with_videos", withVideos],
      ["total", total]
    ],
    "progress"
  );
}

/**
 * Handle update progress.
 */
function updateProgress(progress: ChannelProgressState) {
  const line = formatProgress(progress);
  console.log(line);
}

/**
 * Handle update status.
 */
function updateStatus(message: string) {
  console.log(message);
}
