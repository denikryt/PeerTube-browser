/**
 * Module `engine/crawler/src/channels-worker.ts`: provide runtime functionality.
 */

import { ChannelStore } from "./db/channels.js";
import type { ChannelProgressRow, ChannelUpsertRow } from "./db/types.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { formatCrawlError, shouldTryAlternateProtocol } from "./error-classification.js";
import { createRequestLimiter, type RequestLimiter } from "./request-limiter.js";
import { loadHostsFromFile, scopeHosts } from "./host-filters.js";
import { formatMetricLog } from "./log-format.js";

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
  /** In-process host scope used by the optional host-level scheduler. */
  hosts?: readonly string[];
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
  const store = new ChannelStore({ dbPath: options.dbPath });
  const includedHosts = options.hosts
    ? new Set(options.hosts.map((host) => host.toLowerCase()))
    : loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const hostsAll = store.listInstances();
  const filteredHosts = scopeHosts(hostsAll, includedHosts, excludedHosts);
  const effectiveHosts =
    options.maxInstances > 0
      ? filteredHosts.slice(0, options.maxInstances)
      : filteredHosts;
  const workerCount = Math.min(options.concurrency, Math.max(1, effectiveHosts.length));
  const limitState: ChannelInsertLimitState = {
    remaining: options.maxChannels > 0 ? options.maxChannels : null
  };

  const progressScope = options.hosts ? [...effectiveHosts] : undefined;
  store.prepareChannelProgress(effectiveHosts, options.resume, progressScope);
  const workItems = store.listChannelWorkItems(
    options.errorsOnly ? ["error"] : ["pending", "in_progress"],
    progressScope
  );

  console.log(
    `[channels] instances=${effectiveHosts.length} work=${workItems.length} concurrency=${workerCount} hostConcurrency=${options.hostConcurrency} resume=${options.resume} errorsOnly=${options.errorsOnly}`
  );

  const queue = workItems.slice();
  const workers = Array.from({ length: workerCount }, () =>
    workerLoop(queue, store, options, limitState)
  );
  await Promise.all(workers);

  console.log("[channels] finished");
  store.close();
}

/**
 * Handle check channel health.
 */
export async function checkChannelHealth(options: ChannelCrawlOptions) {
  const store = new ChannelStore({ dbPath: options.dbPath });
  const includedHosts = loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const hosts = scopeHosts(store.listChannelInstances(), includedHosts, excludedHosts);
  const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));

  console.log(
    `[channels-health] instances=${hosts.length} concurrency=${workerCount}`
  );

  const queue = hosts.slice();
  const workers = Array.from({ length: workerCount }, () =>
    healthWorkerLoop(queue, store, options)
  );
  await Promise.all(workers);

  console.log("[channels-health] finished");
  store.close();
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  queue: ChannelProgressRow[],
  store: ChannelStore,
  options: ChannelCrawlOptions,
  limitState: ChannelInsertLimitState
) {
  while (true) {
    const item = queue.pop();
    if (!item) return;
    if (limitState.remaining !== null && limitState.remaining <= 0) {
      return;
    }
    await processInstance(item, store, options, limitState);
  }
}

/**
 * Handle health worker loop.
 */
async function healthWorkerLoop(
  queue: string[],
  store: ChannelStore,
  options: ChannelCrawlOptions
) {
  while (true) {
    const host = queue.pop();
    if (!host) return;
    await processHealthInstance(host, store, options);
  }
}

/**
 * Handle process instance.
 */
async function processInstance(
  item: ChannelProgressRow,
  store: ChannelStore,
  options: ChannelCrawlOptions,
  limitState: ChannelInsertLimitState
) {
  const normalizedHost = item.instanceDomain.toLowerCase();
  const requestLimiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
  const startAt = item.status === "in_progress" ? item.lastStart : 0;
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
    const { localCount, totalCount } = await crawlInstanceChannels(
      normalizedHost,
      startAt,
      store,
      options,
      limitState,
      requestLimiter
    );

    store.updateChannelProgress(normalizedHost, "done", 0);
    store.markInstanceDone(normalizedHost);
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
  options: ChannelCrawlOptions
) {
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
  const channels = store.listChannelsForInstance(normalizedHost);
  if (channels.length === 0) {
    console.log(formatMetricLog("channels-health", [["channels", 0]], "skip", normalizedHost));
    return;
  }

  console.log(
    formatMetricLog("channels-health", [["channels", channels.length]], "start", normalizedHost)
  );

  let hadError = false;
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
    if (!channel.channel_name) return;
    const current = nextProcessed();
    console.log(
      `[channels-health] start ${current}/${totalChannels} ${normalizedHost}/${channel.channel_name}`
    );
    try {
      await fetchChannelHealth(normalizedHost, channel.channel_name, options, requestLimiter);
      store.updateChannelHealthOk(channel.channel_id, normalizedHost);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (isNoNetworkError(error)) {
        console.warn(`[channels-health] network issue ${normalizedHost}: ${message}`);
        return;
      }
      hadError = true;
      store.updateChannelHealthError(channel.channel_id, normalizedHost, message);
      console.warn(
        `[channels-health] error ${normalizedHost}/${channel.channel_name}: ${message}`
      );
    }
  });

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
  requestLimiter: RequestLimiter
) {
  let start = startAt;
  let protocol = "https:";
  let totalCount = 0;
  let localCount = 0;

  while (true) {
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

    const data = Array.isArray(page.data) ? page.data : [];
    const nextStart = start + PAGE_SIZE;
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
        const row: ChannelUpsertRow = {
          channelId,
          channelName: toNullableString(channel.name),
          channelUrl: toNullableString(channel.url),
          displayName: toNullableString(channel.displayName ?? channel.display_name),
          instanceDomain: host,
          videosCount: toNullableNumber(channel.videosCount ?? channel.videos_count),
          followersCount: toNullableNumber(channel.followersCount ?? channel.followers_count),
          avatarUrl: getChannelAvatarUrl(channel, host, protocol)
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
      localCount += acceptedRows.length;
      store.upsertChannels(acceptedRows);
    }

    // Persist the next page offset after successfully storing this page.
    store.updateChannelProgress(host, "in_progress", nextStart);

    if (page.total !== undefined) {
      if (nextStart >= page.total) break;
    } else if (data.length < PAGE_SIZE) {
      break;
    }

    start = nextStart;
  }

  return { localCount, totalCount };
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
    if (!shouldTryAlternateProtocol(error)) throw error;
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
  await fetchWithFallback(host, channelName, options, "https:", requestLimiter);
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
    if (!shouldTryAlternateProtocol(error)) throw error;
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

async function mapWithConcurrency<T>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<void>
) {
  if (items.length === 0) return;
  const limit = Math.max(1, concurrency);
  let index = 0;

  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const current = index;
      index += 1;
      if (current >= items.length) return;
      await mapper(items[current]);
    }
  });

  await Promise.all(workers);
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
