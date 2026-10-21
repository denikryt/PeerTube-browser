/**
 * Module `engine/crawler/src/channels-worker.ts`: provide runtime functionality.
 */

import { ChannelStore } from "./db/channels.js";
import { checkInstancesHealth } from "./instances-health-cli.js";
import type { ChannelProgressRow, ChannelUpsertRow } from "./db/types.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { classifyCrawlError, formatCrawlError, shouldTryAlternateProtocol } from "./error-classification.js";
import { createRequestLimiter, type RequestLimiter } from "./request-limiter.js";
import { loadHostsFromFile, loadIncludedHostsFromFile, scopeHosts } from "./host-filters.js";
import { formatMetricLog } from "./log-format.js";
import { extractAccountIdentity } from "./video-metadata.js";
import { assertWorkActive, stopWork, type WorkCancellation } from "./work-cancellation.js";

const PAGE_SIZE = 50;

export interface ChannelCrawlOptions {
  dbPath: string;
  hostsFile: string | null;
  excludeHostsFile: string | null;
  concurrency: number;
  hostConcurrency: number;
  hostDelayMs: number;
  timeoutMs: number;
  maxRetries: number;
  newOnly: boolean;
  maxInstances: number;
  maxChannels: number;
  resume: boolean;
  errorsOnly: boolean;
  /** Initialize parent state only; owned by the sequential updater before probe. */
  initializeOnly?: boolean;
  /** Parent reset/probe already happened in the owning orchestration mode. */
  alreadyInitialized?: boolean;
  /** In-process host scope used by the optional host-level scheduler. */
  hosts?: readonly string[];
  /** Optional shared host-pipeline fatal signal. */
  cancellation?: WorkCancellation;
}

interface ChannelInsertLimitState {
  remaining: number | null;
}

interface Page<T> {
  total?: number;
  data?: T[];
}

interface PeerTubeAvatar {
  url?: string;
  path?: string;
  staticPath?: string;
  width?: number;
}

interface PeerTubeAccountRef {
  host?: string;
  url?: string;
  name?: string;
  displayName?: string;
  display_name?: string;
  avatar?: PeerTubeAvatar;
  avatars?: PeerTubeAvatar[];
}

interface PeerTubeVideoChannel {
  id?: number | string;
  url?: string;
  name?: string;
  displayName?: string;
  display_name?: string;
  host?: string;
  account?: PeerTubeAccountRef;
  ownerAccount?: PeerTubeAccountRef;
  followersCount?: number;
  followers_count?: number;
  videosCount?: number;
  videos_count?: number;
  avatar?: PeerTubeAvatar;
  avatars?: PeerTubeAvatar[];
}


/**
 * Handle crawl channels.
 */
export async function crawlChannels(options: ChannelCrawlOptions) {
  const cancellation = options.cancellation ?? { stopped: false };
  assertWorkActive(cancellation);
  const store = new ChannelStore({ dbPath: options.dbPath });
  try {
    const includedHosts = loadIncludedHostsFromFile(options.hostsFile);
    const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
    const hostsAll = store.listInstances();
    const filteredHosts = scopeHosts(hostsAll, includedHosts, excludedHosts, options.hosts);
    const effectiveHosts =
      options.maxInstances > 0
        ? filteredHosts.slice(0, options.maxInstances)
        : filteredHosts;
    if (effectiveHosts.length === 0) {
      return;
    }
    if (options.initializeOnly && options.alreadyInitialized) {
      throw new Error("Parent scope cannot be both initialized and already initialized");
    }
    if (options.initializeOnly) {
      store.initializeParentEnumeration(effectiveHosts);
      return;
    }
    if (options.alreadyInitialized) {
      store.assertParentEnumerationPrepared(effectiveHosts);
    } else {
      store.initializeParentEnumeration(effectiveHosts);
      // Standalone enumeration owns the probe. The updater and host pipeline
      // prepare/probe independently and explicitly request alreadyInitialized.
      await checkInstancesHealth({
        dbPath: options.dbPath, concurrency: options.concurrency,
        hostDelayMs: options.hostDelayMs, timeoutMs: options.timeoutMs,
        maxRetries: options.maxRetries, minAgeDays: null, minAgeMin: null,
        minAgeSec: null, hostsFile: options.hostsFile,
        host: null, errorsOnly: false, hosts: effectiveHosts
      });
    }
    const eligibleHosts = store.listFreshHealthyHosts(effectiveHosts);
    if (!eligibleHosts.length) return;
    const workerCount = Math.min(options.concurrency, Math.max(1, eligibleHosts.length));
    const limitState: ChannelInsertLimitState = {
      remaining: options.maxChannels > 0 ? options.maxChannels : null
    };

    const progressScope = [...eligibleHosts];
    const workItems = store.listChannelWorkItems(
      ["pending", "in_progress"],
      progressScope
    );

    console.log(
      `[channels] instances=${effectiveHosts.length} work=${workItems.length} concurrency=${workerCount} hostConcurrency=${options.hostConcurrency} resume=${options.resume} errorsOnly=${options.errorsOnly}`
    );

    const queue = workItems.slice();
    const workers = Array.from({ length: workerCount }, () =>
      workerLoop(queue, store, options, limitState, cancellation).catch(error => {
        stopWork(cancellation, error);
        queue.length = 0;
        throw error;
      })
    );
    // Settle in-flight operations before releasing the shared SQLite handle.
    const results = await Promise.allSettled(workers);
    const rejected = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
    if (rejected) throw rejected.reason;

    console.log("[channels] finished");
  } finally {
    store.close();
  }
}

/**
 * Handle check channel health.
 */
export async function checkChannelHealth(options: ChannelCrawlOptions) {
  const cancellation = options.cancellation ?? { stopped: false };
  assertWorkActive(cancellation);
  const store = new ChannelStore({ dbPath: options.dbPath });
  try {
    const includedHosts = loadIncludedHostsFromFile(options.hostsFile);
    const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
    const selected = scopeHosts(store.listChannelInstances(), includedHosts, excludedHosts, options.hosts);
    const hosts = store.listFreshHealthyHosts(selected, true);
    const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));

    console.log(
      `[channels-health] instances=${hosts.length} concurrency=${workerCount}`
    );

    const queue = hosts.slice();
    const workers = Array.from({ length: workerCount }, () =>
      healthWorkerLoop(queue, store, options, cancellation).catch(error => {
        stopWork(cancellation, error);
        queue.length = 0;
        throw error;
      })
    );
    // Settle in-flight operations before releasing the shared SQLite handle.
    const results = await Promise.allSettled(workers);
    const rejected = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
    if (rejected) throw rejected.reason;

    console.log("[channels-health] finished");
  } finally {
    store.close();
  }
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  queue: ChannelProgressRow[],
  store: ChannelStore,
  options: ChannelCrawlOptions,
  limitState: ChannelInsertLimitState,
  cancellation: WorkCancellation
) {
  while (!cancellation.stopped) {
    const item = queue.pop();
    if (!item) return;
    if (limitState.remaining !== null && limitState.remaining <= 0) {
      return;
    }
    await processInstance(item, store, options, limitState, cancellation);
  }
}

/**
 * Handle health worker loop.
 */
async function healthWorkerLoop(
  queue: string[],
  store: ChannelStore,
  options: ChannelCrawlOptions,
  cancellation: WorkCancellation
) {
  while (!cancellation.stopped) {
    const host = queue.pop();
    if (!host) return;
    await processHealthInstance(host, store, options, cancellation);
  }
}

/**
 * Handle process instance.
 */
async function processInstance(
  item: ChannelProgressRow,
  store: ChannelStore,
  options: ChannelCrawlOptions,
  limitState: ChannelInsertLimitState,
  cancellation: WorkCancellation
) {
  assertWorkActive(cancellation);
  const normalizedHost = item.instanceDomain.toLowerCase();
  const requestLimiter = createRequestLimiter(
    options.hostConcurrency, options.hostDelayMs,
    () => assertWorkActive(cancellation),
    (error) => { if (isNoNetworkError(error)) stopWork(cancellation, error); }
  );
  // Old offsets may have advanced past locally discarded rows. An incomplete
  // listing must establish completeness again from the first remote page.
  const startAt = 0;
  store.updateChannelProgress(normalizedHost, "in_progress", startAt);
  console.log(
    formatMetricLog(
      "channels",
      [["start", startAt], ["resume", item.status]],
      "host",
      normalizedHost
    )
  );

  try {
    const { localCount, totalCount, completed } = await crawlInstanceChannels(
      normalizedHost,
      startAt,
      store,
      options,
      limitState,
      requestLimiter,
      cancellation
    );

    // Resolving a bounded crawl is not proof that every remote channel was saved.
    assertWorkActive(cancellation);
    store.updateChannelProgress(normalizedHost, completed ? "done" : "in_progress", 0);
    if (completed) store.markInstanceDone(normalizedHost);
    console.log(
      formatMetricLog(
        "channels",
        [["local", localCount], ["total", totalCount]],
        "host",
        normalizedHost
      )
    );
  } catch (error) {
    if (isNoNetworkError(error)) {
      stopWork(cancellation, error);
      throw error;
    }
    const message = error instanceof Error ? error.message : String(error);
    const storedError = formatCrawlError(error);
    const status = extractHttpStatus(message);

    if (status && status >= 400 && status < 500) {
      store.updateChannelProgress(normalizedHost, "error", startAt);
      store.markInstanceError(normalizedHost, storedError);
      console.warn(`[channels] skip ${normalizedHost} status=${status}`);
      return;
    }

    if (status && status >= 500) {
      store.updateChannelProgress(normalizedHost, "error", startAt);
      store.markInstanceError(normalizedHost, storedError);
      console.warn(`[channels] error ${normalizedHost} status=${status}`);
      return;
    }

    if (error instanceof SyntaxError) {
      store.updateChannelProgress(normalizedHost, "error", startAt);
      store.markInstanceError(normalizedHost, storedError);
      console.warn(`[channels] invalid JSON ${normalizedHost}`);
      return;
    }

    store.updateChannelProgress(normalizedHost, "error", startAt);
    store.markInstanceError(normalizedHost, storedError);
    console.warn(`[channels] error ${normalizedHost}: ${message}`);
  }
}

/**
 * Handle process health instance.
 */
async function processHealthInstance(
  host: string,
  store: ChannelStore,
  options: ChannelCrawlOptions,
  cancellation: WorkCancellation
) {
  assertWorkActive(cancellation);
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(
    options.hostConcurrency, options.hostDelayMs,
    () => assertWorkActive(cancellation),
    (error) => { if (isNoNetworkError(error)) stopWork(cancellation, error); }
  );
  const channels = store.listUnresolvedChannelsForHealth(normalizedHost);
  if (channels.length === 0) {
    console.log(formatMetricLog("channels-health", [["channels", 0]], "skip", normalizedHost));
    return;
  }

  console.log(
    formatMetricLog("channels-health", [["channels", channels.length]], "start", normalizedHost)
  );

  let hadError = false;
  let transportFailures = 0;
  let hostUnavailable = false;
  let probe: Promise<void> | null = null;
  const totalChannels = channels.length;
  let processedChannels = 0;
  /**
   * Handle next processed.
   */
  const nextProcessed = () => {
    processedChannels += 1;
    return processedChannels;
  };
  await mapWithConcurrency(channels, options.hostConcurrency, async (channel) => {
    assertWorkActive(cancellation);
    // A failed parent probe stops this host only; sibling hosts still run.
    if (hostUnavailable) return;
    if (probe) {
      await probe;
      if (!hostUnavailable) probe = null;
    }
    if (hostUnavailable) return;
    if (!channel.channel_name) return;
    const current = nextProcessed();
    console.log(
      `[channels-health] start ${current}/${totalChannels} ${normalizedHost}/${channel.channel_name}`
    );
    try {
      const count = await fetchChannelHealth(normalizedHost, channel.channel_name, options, requestLimiter);
      store.updateChannelHealthOk(channel.channel_id, normalizedHost);
      transportFailures = 0;
      if (count !== null) store.updateChannelVideosCount(channel.channel_id, normalizedHost, count);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      // A proven local outage is a run failure, not a fresh remote error.
      if (isNoNetworkError(error)) {
        // Stop the outer host queue immediately, not only after this host's
        // other in-flight channel requests have finished draining.
        stopWork(cancellation, error);
        throw error;
      }
      hadError = true;
      store.updateChannelHealthError(channel.channel_id, normalizedHost, message);
      const kind = classifyCrawlError(error).kind;
      if (kind === "network" || kind === "timeout") {
        transportFailures += 1;
        if (transportFailures >= 3 && !probe) {
          // Three consecutive transport failures may mean the instance died
          // after its initial probe. Confirm once before skipping its backlog.
          probe = (async () => {
            try {
              const result = await fetchPage(normalizedHost, 0, options, "https:", requestLimiter);
              if (!result.page || !Array.isArray(result.page.data) ||
                  result.page.data.length > PAGE_SIZE ||
                  (result.page.total !== undefined &&
                    (!Number.isSafeInteger(result.page.total) || result.page.total < 0 ||
                      result.page.data.length !== Math.min(PAGE_SIZE, result.page.total)))) {
                throw new Error("Invalid instance-health page");
              }
              transportFailures = 0;
            } catch (probeError) {
              if (isNoNetworkError(probeError)) throw probeError;
              hostUnavailable = true;
              store.markInstanceHealthError(normalizedHost, formatCrawlError(probeError));
              console.warn(`[channels-health] parent unavailable ${normalizedHost}`);
            }
          })();
        }
        if (probe) {
          await probe;
          if (!hostUnavailable) probe = null;
        }
      } else {
        transportFailures = 0;
      }
      console.warn(
        `[channels-health] error ${normalizedHost}/${channel.channel_name}: ${message}`
      );
    }
  }, cancellation);

  console.log(formatMetricLog("channels-health", [["error", hadError]], "done", normalizedHost));
}

/**
 * Handle crawl instance channels.
 */
async function crawlInstanceChannels(
  host: string,
  startAt: number,
  store: ChannelStore,
  options: ChannelCrawlOptions,
  limitState: ChannelInsertLimitState,
  requestLimiter: RequestLimiter,
  cancellation: WorkCancellation
) {
  let start = startAt;
  let protocol = "https:";
  let totalCount = 0;
  let localCount = 0;
  let completed = false;

  while (!cancellation.stopped) {
    if (limitState.remaining !== null && limitState.remaining <= 0) {
      break;
    }
    const { page, protocol: usedProtocol } = await fetchPage(
      host,
      start,
      options,
      protocol,
      requestLimiter
    );
    protocol = usedProtocol;

    // Validate the envelope before any writes from this page. A corrupt 2xx
    // response must not authorize completion or import a partial page.
    if (!page || !Array.isArray(page.data) || page.data.length > PAGE_SIZE ||
        (page.total !== undefined && (!Number.isSafeInteger(page.total) || page.total < 0 ||
          start > page.total || page.data.length !== Math.min(PAGE_SIZE, page.total - start)))) {
      throw new Error("Invalid or incomplete channel-list page");
    }
    const data = page.data;
    const nextStart = start + PAGE_SIZE;
    let droppedEligibleRows = false;
    totalCount += data.length;

    if (data.length > 0) {
      const ids = options.newOnly
        ? Array.from(
            new Set(
              data
                .map((channel) =>
                  channel.id !== undefined ? String(channel.id) : null
                )
                .filter((value): value is string => Boolean(value))
            )
          )
        : [];
      const existingIds = options.newOnly
        ? store.listExistingChannelIds(host, ids)
        : null;
      const rows: ChannelUpsertRow[] = [];
      const existingRows: ChannelUpsertRow[] = [];
      for (const channel of data) {
        const channelHost = extractChannelHost(channel);
        if (channelHost !== host) continue;
        const channelId = channel.id !== undefined ? String(channel.id) : null;
        if (!channelId) continue;
        const owner = extractAccountIdentity(
          channel.ownerAccount ?? channel.account ?? null,
          host,
          protocol
        );
        const row: ChannelUpsertRow = {
          channelId,
          channelName: toNullableString(channel.name),
          channelUrl: toNullableString(channel.url),
          displayName: toNullableString(channel.displayName ?? channel.display_name),
          instanceDomain: host,
          videosCount: toNullableNumber(channel.videosCount ?? channel.videos_count),
          followersCount: toNullableNumber(channel.followersCount ?? channel.followers_count),
          avatarUrl: getChannelAvatarUrl(channel, host, protocol),
          ownerAccountUsername: owner.username,
          ownerAccountDisplayName: owner.displayName,
          ownerAccountUrl: owner.url,
          ownerAccountAvatarUrl: owner.avatarUrl
        };
        if (existingIds && existingIds.has(channelId)) {
          // Existing metadata remains untouched in --new-channels mode, while
          // the fresh count still controls the following count/video stages.
          existingRows.push(row);
          continue;
        }
        rows.push(row);
      }
      store.refreshChannelVideoCountsFromListing(existingRows);
      const acceptedRows = takeRowsWithinLimit(rows, limitState);
      droppedEligibleRows = acceptedRows.length < rows.length;
      localCount += acceptedRows.length;
      store.upsertChannels(acceptedRows);
      // Only channels actually observed and persisted in this invocation may
      // acquire fresh positive health. Budget-dropped rows remain unresolved.
      for (const row of [...existingRows, ...acceptedRows]) {
        store.updateChannelHealthOk(row.channelId, host);
      }
    }

    // A resumed incomplete listing starts at page zero so rows dropped by a
    // local budget cannot disappear behind a persisted remote page offset.
    store.updateChannelProgress(host, "in_progress", 0);
    const remoteEnd = page.total !== undefined ? nextStart >= page.total : data.length < PAGE_SIZE;
    if (remoteEnd || droppedEligibleRows) {
      completed = remoteEnd && !droppedEligibleRows;
      break;
    }
    start = nextStart;
  }

  return { localCount, totalCount, completed };
}

/**
 * Handle take rows within limit.
 */
function takeRowsWithinLimit(
  rows: ChannelUpsertRow[],
  limitState: ChannelInsertLimitState
): ChannelUpsertRow[] {
  if (rows.length === 0) return rows;
  if (limitState.remaining === null) return rows;
  if (limitState.remaining <= 0) return [];
  if (rows.length <= limitState.remaining) {
    limitState.remaining -= rows.length;
    return rows;
  }
  const accepted = rows.slice(0, limitState.remaining);
  limitState.remaining = 0;
  return accepted;
}

/**
 * Handle fetch page.
 */
async function fetchPage(
  host: string,
  start: number,
  options: ChannelCrawlOptions,
  protocol: string,
  requestLimiter: RequestLimiter
) {
  const primaryUrl = buildUrl(host, start, PAGE_SIZE, protocol);

  try {
    const page = await requestLimiter.run(() => fetchJsonWithRetry<Page<PeerTubeVideoChannel>>(primaryUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    }));
    return { page, protocol };
  } catch (error) {
    // An explicit local outage has priority over message-based protocol fallback.
    if (isNoNetworkError(error) || !shouldTryAlternateProtocol(error)) throw error;
    const fallbackProtocol = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildUrl(host, start, PAGE_SIZE, fallbackProtocol);
    const page = await requestLimiter.run(() => fetchJsonWithRetry<Page<PeerTubeVideoChannel>>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
    }));
    return { page, protocol: fallbackProtocol };
  }
}

/**
 * Handle build url.
 */
function buildUrl(host: string, start: number, count: number, protocol: string) {
  return `${protocol}//${host}/api/v1/video-channels?start=${start}&count=${count}`;
}

/**
 * Handle fetch channel health.
 */
async function fetchChannelHealth(
  host: string,
  channelName: string,
  options: ChannelCrawlOptions,
  requestLimiter: RequestLimiter
) {
  const page = await fetchWithFallback(host, channelName, options, "https:", requestLimiter);
  // A successful JSON parse alone does not prove that the PeerTube endpoint
  // returned a usable channel page. Never publish ok for a malformed envelope.
  if (!page || !Array.isArray(page.data) || page.data.length > 1 ||
      (page.total !== undefined && (!Number.isSafeInteger(page.total) ||
        page.total < page.data.length || page.total < 0))) {
    throw new Error("Invalid channel-health page");
  }
  return page.total ?? null;
}

/**
 * Handle fetch with fallback.
 */
async function fetchWithFallback(
  host: string,
  channelName: string,
  options: ChannelCrawlOptions,
  protocol: string,
  requestLimiter: RequestLimiter
) {
  const url = buildChannelVideosUrl(host, channelName, 0, 1, protocol);
  try {
    return await requestLimiter.run(() => fetchJsonWithRetry<Page<unknown>>(url, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    }));
  } catch (error) {
    // An explicit local outage has priority over message-based protocol fallback.
    if (isNoNetworkError(error) || !shouldTryAlternateProtocol(error)) throw error;
    const alternate = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildChannelVideosUrl(host, channelName, 0, 1, alternate);
    return await requestLimiter.run(() => fetchJsonWithRetry<Page<unknown>>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
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

/** Drain started channel operations before propagating a fatal mapper failure. */
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
        // Stop assigning further identities while already-started requests drain.
        stopWork(cancellation, error);
        index = items.length;
        throw error;
      }
    }
  });

  const results = await Promise.allSettled(workers);
  const rejected = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
  if (rejected) throw rejected.reason;
}


/**
 * Handle extract channel host.
 */
function extractChannelHost(channel: PeerTubeVideoChannel): string | null {
  const host =
    channel.host ?? channel.account?.host ?? channel.ownerAccount?.host ?? extractHostFromUrl(channel.account?.url);
  if (!host) return null;
  return normalizeHost(host);
}

/**
 * Handle extract host from url.
 */
function extractHostFromUrl(value?: string) {
  if (!value) return null;
  try {
    if (value.startsWith("http://") || value.startsWith("https://")) {
      return new URL(value).host;
    }
    if (value.includes("/")) {
      return new URL(`https://${value}`).host;
    }
    return value;
  } catch {
    return null;
  }
}

/**
 * Handle normalize host.
 */
function normalizeHost(host: string) {
  return host.trim().toLowerCase();
}

/**
 * Handle to nullable string.
 */
function toNullableString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Handle to nullable number.
 */
function toNullableNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/**
 * Handle get channel avatar url.
 */
function getChannelAvatarUrl(channel: PeerTubeVideoChannel, host: string, protocol: string) {
  const avatar = pickBestAvatar(channel.avatars) ?? channel.avatar;
  return resolveAvatarUrl(avatar, host, protocol);
}

/**
 * Handle pick best avatar.
 */
function pickBestAvatar(avatars: PeerTubeAvatar[] | undefined) {
  if (!avatars || avatars.length === 0) return undefined;
  let best = avatars[0];
  for (const avatar of avatars) {
    if ((avatar.width ?? 0) > (best.width ?? 0)) {
      best = avatar;
    }
  }
  return best;
}

/**
 * Handle resolve avatar url.
 */
function resolveAvatarUrl(avatar: PeerTubeAvatar | undefined, host: string, protocol: string) {
  if (!avatar) return null;
  const candidate = avatar.url ?? avatar.path ?? avatar.staticPath;
  if (!candidate || typeof candidate !== "string") return null;
  if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
    return candidate;
  }
  if (candidate.startsWith("/")) {
    return `${protocol}//${host}${candidate}`;
  }
  return `${protocol}//${host}/${candidate}`;
}

/**
 * Handle extract http status.
 */
function extractHttpStatus(message: string): number | null {
  const match = message.match(/HTTP (\d{3})/);
  if (!match) return null;
  return Number(match[1]);
}
