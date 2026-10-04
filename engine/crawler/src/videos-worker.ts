/**
 * Module `engine/crawler/src/videos-worker.ts`: provide runtime functionality.
 */

import Database from "better-sqlite3";
import { VideoStore } from "./db/videos.js";
import { assertMetadataMaintenanceSchema, assertThumbnailMaintenanceSchema } from "./db/schema.js";
import type {
  ExistingVideoRefresh,
  VideoActivityPubMetadataPatch,
  VideoChannelRow,
  VideoDetailMetadataPatch,
  VideoProgressRow,
  VideoThumbnailRow,
  VideoTagRow,
  VideoUpsertRow
} from "./db/types.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { formatCrawlError, shouldTryAlternateProtocol } from "./error-classification.js";
import { createRequestLimiter, type RequestLimiter } from "./request-limiter.js";
import { loadHostsFromFile, scopeHosts } from "./host-filters.js";
import { createProgressOrdinal, formatMetricLog } from "./log-format.js";
import {
  resolveLegacyThumbnailCompatibility,
  resolvePreferredPreviewPath,
  resolveThumbnailCandidates
} from "./video-media.js";
import { normalizeVideoMetadata } from "./video-metadata.js";
import {
  fetchActivityPubLiveMetadata,
  type ActivityPubLiveMetadata
} from "./video-activitypub.js";

const PAGE_SIZE = 50;
const CHANNEL_CONCURRENCY = 2;
const TAGS_CONCURRENCY = 4;
const VIDEO_DETAIL_CONCURRENCY = 4;

export interface VideoCrawlOptions {
  dbPath: string;
  hostsFile: string | null;
  excludeHostsFile: string | null;
  existingDbPath: string | null;
  concurrency: number;
  hostConcurrency: number;
  timeoutMs: number;
  maxRetries: number;
  resume: boolean;
  errorsOnly: boolean;
  newOnly: boolean;
  stopAfterFullPages: number;
  sort: string;
  maxInstances: number;
  maxChannels: number;
  maxVideosPages: number;
  tagsOnly: boolean;
  updateTags: boolean;
  commentsOnly: boolean;
  refreshThumbnails: boolean;
  metadataOnly?: boolean;
  updateMetadata?: boolean;
  /** DB-backed host scope that excludes error/unknown instances in supported maintenance modes. */
  onlyHealthyHosts?: boolean;
  hostDelayMs: number;
  /** In-process host scope used by the optional host-level scheduler. */
  hosts?: readonly string[];
}

interface Page<T> {
  total?: number;
  data?: T[];
}

interface PeerTubeAccountRef {
  avatar?: unknown;
  avatars?: unknown;
  id?: number | string;
  name?: string;
  displayName?: string;
  display_name?: string;
  url?: string;
  host?: string;
}

interface PeerTubeVideoChannel {
  id?: number | string;
  name?: string;
  displayName?: string;
  display_name?: string;
  url?: string;
  host?: string;
  account?: PeerTubeAccountRef;
  ownerAccount?: PeerTubeAccountRef;
}

interface PeerTubeCategory {
  id?: number | string;
  label?: string;
  name?: string;
}

interface PeerTubeVideo {
  [key: string]: unknown;
  id?: number | string;
  uuid?: string;
  name?: string;
  title?: string;
  description?: string;
  tags?: string[];
  category?: PeerTubeCategory | string | number;
  channel?: PeerTubeVideoChannel;
  account?: PeerTubeAccountRef;
  publishedAt?: string;
  published_at?: string;
  createdAt?: string;
  created_at?: string;
  url?: string;
  duration?: number;
  thumbnailUrl?: string;
  thumbnailPath?: string;
  thumbnail_path?: string;
  thumbnail?: unknown;
  embedPath?: string;
  embed_path?: string;
  views?: number;
  views_count?: number;
  likes?: number;
  likes_count?: number;
  dislikes?: number;
  dislikes_count?: number;
  commentsCount?: number;
  comments_count?: number;
  comments?: number;
  nsfw?: boolean;
  previewPath?: string;
  preview_path?: string;
}

interface BuiltVideoPersistence {
  row: VideoUpsertRow;
  refresh: ExistingVideoRefresh;
}

interface PeerTubeVideoDetail extends PeerTubeVideo {
  [key: string]: unknown;
  thumbnails?: unknown;
  thumbnailUrl?: string;
  thumbnailPath?: string;
  thumbnail_path?: string;
  thumbnail?: unknown;
  previewPath?: string;
  preview_path?: string;
  previewUrl?: string;
  preview_url?: string;
  tags?: string[];
  comments?: number;
  commentsCount?: number;
  comments_count?: number;
  licence?: unknown;
  license?: unknown;
  language?: unknown;
  nsfwSummary?: string;
  originallyPublishedAt?: string;
  updatedAt?: string;
  isLive?: boolean;
  permanentLive?: boolean | null;
  liveSaveReplay?: boolean | null;
  aspectRatio?: number;
  support?: string;
}

interface VideoDetailFetchResult {
  detail: PeerTubeVideoDetail;
  protocol: string;
}

interface ChannelMeta {
  channelSlug: string | null;
  displayName: string | null;
  channelUrl: string | null;
}

interface NewVideoCounter {
  total: number;
}

/**
 * Handle crawl videos.
 */
export async function crawlVideos(options: VideoCrawlOptions) {
  if (options.metadataOnly || options.updateMetadata) {
    await crawlVideoMetadata(options);
    return;
  }
  if (options.updateTags) {
    await crawlVideoTags(options, "present");
    return;
  }
  if (options.tagsOnly) {
    await crawlVideoTags(options, "missing");
    return;
  }
  if (options.commentsOnly) {
    await crawlVideoComments(options);
    return;
  }
  if (options.refreshThumbnails) {
    await refreshVideoThumbnails(options);
    return;
  }
  const store = new VideoStore({ dbPath: options.dbPath });
  const includedHosts = options.hosts
    ? new Set(options.hosts.map((host) => host.toLowerCase()))
    : loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const existingDb = openExistingDb(options);
  const hostsAll = store.listInstances();
  const filteredHosts = scopeHosts(hostsAll, includedHosts, excludedHosts);
  const hosts =
    options.maxInstances > 0
      ? filteredHosts.slice(0, options.maxInstances)
      : filteredHosts;
  // Counts are resolved by the preceding count stage. Selecting only positive
  // rows avoids one request per known-empty or still-unknown channel.
  const channelsAll = store.listChannelsWithVideos(1, hosts);
  const channels =
    options.maxChannels > 0
      ? channelsAll.slice(0, options.maxChannels)
      : channelsAll;
  const channelMeta = new Map<string, ChannelMeta>(
    channels.map((channel) => [
      channel.channel_id,
      {
        channelSlug: channel.channel_name,
        displayName: channel.display_name,
        channelUrl: channel.channel_url
      }
    ])
  );
  // Keep run-local statistics out of SQLite so concurrent host pipelines
  // cannot reset or increment one another's counters.
  const newVideos: NewVideoCounter = { total: 0 };

  const progressScope = options.hosts ? [...hosts] : undefined;
  store.prepareVideoProgress(channels, options.resume, progressScope);
  const statuses = (options.errorsOnly
    ? ["error"]
    : ["pending", "in_progress"]) satisfies VideoProgressRow["status"][];
  const workItems = store.listVideoWorkItems(statuses, progressScope);
  const grouped = groupByInstance(workItems);
  const instances = Array.from(grouped.keys());
  const workerCount = Math.min(options.concurrency, Math.max(1, instances.length));
  const nextChannelOrdinal = createProgressOrdinal(workItems.length);

  console.log(
    `[videos] instances=${instances.length} channels=${workItems.length} concurrency=${workerCount} hostConcurrency=${options.hostConcurrency} resume=${options.resume} errorsOnly=${options.errorsOnly}`
  );

  try {
    const queue = instances.slice();
    const workers = Array.from({ length: workerCount }, () =>
      workerLoop(
        queue,
        grouped,
        channelMeta,
        store,
        existingDb,
        options,
        nextChannelOrdinal,
        newVideos
      )
    );
    await Promise.all(workers);

    console.log(formatMetricLog("videos", [["new_total", newVideos.total]], "finished"));
  } finally {
    existingDb?.close();
    store.close();
  }
}

/**
 * Handle crawl video comments.
 */
async function crawlVideoComments(options: VideoCrawlOptions) {
  const store = new VideoStore({ dbPath: options.dbPath });
  const includedHosts = loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const items = store.listVideosForComments(options.resume);
  const grouped = groupByInstance(items);
  const instances = scopeHosts(Array.from(grouped.keys()), includedHosts, excludedHosts);
  const workerCount = Math.min(options.concurrency, Math.max(1, instances.length));

  console.log(
    `[comments] instances=${instances.length} videos=${items.length} concurrency=${workerCount} resume=${options.resume}`
  );

  const queue = instances.slice();
  const workers = Array.from({ length: workerCount }, () =>
    commentsWorkerLoop(queue, grouped, store, options)
  );
  await Promise.all(workers);

  console.log("[comments] finished");
  store.close();
}

/**
 * Handle crawl video tags.
 */
async function crawlVideoTags(options: VideoCrawlOptions, mode: "missing" | "present") {
  const store = new VideoStore({ dbPath: options.dbPath });
  const includedHosts = loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const items = store.listVideosForTags(mode);
  const grouped = groupByInstance(items);
  const instances = scopeHosts(Array.from(grouped.keys()), includedHosts, excludedHosts);
  const workerCount = Math.min(options.concurrency, Math.max(1, instances.length));

  console.log(
    `[tags] instances=${instances.length} videos=${items.length} concurrency=${workerCount}`
  );

  const queue = instances.slice();
  const workers = Array.from({ length: workerCount }, () =>
    tagWorkerLoop(queue, grouped, store, options)
  );
  await Promise.all(workers);

  console.log("[tags] finished");
  store.close();
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  queue: string[],
  grouped: Map<string, VideoProgressRow[]>,
  channelMeta: Map<string, ChannelMeta>,
  store: VideoStore,
  existingDb: Database.Database | null,
  options: VideoCrawlOptions,
  nextChannelOrdinal: () => string,
  newVideos: NewVideoCounter
) {
  while (true) {
    const host = queue.pop();
    if (!host) return;
    const items = grouped.get(host);
    if (!items) continue;
    await processInstance(
      host,
      items,
      channelMeta,
      store,
      existingDb,
      options,
      nextChannelOrdinal,
      newVideos
    );
  }
}

/**
 * Handle process instance.
 */
async function processInstance(
  host: string,
  items: VideoProgressRow[],
  channelMeta: Map<string, ChannelMeta>,
  store: VideoStore,
  existingDb: Database.Database | null,
  options: VideoCrawlOptions,
  nextChannelOrdinal: () => string,
  newVideos: NewVideoCounter
) {
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
  console.log(formatMetricLog("videos", [["channels", items.length]], "start", normalizedHost));

  await mapWithConcurrency(items, CHANNEL_CONCURRENCY, async (item) => {
    const meta = channelMeta.get(item.channelId);
    // Allocate before network work begins so every line for this channel keeps
    // the same crawl-wide position even when completions arrive out of order.
    const channelOrdinal = nextChannelOrdinal();
    await processChannel(
      normalizedHost,
      item,
      meta,
      store,
      existingDb,
      options,
      requestLimiter,
      channelOrdinal,
      newVideos
    );
  });

  console.log(`[videos] done ${normalizedHost}`);
}

/**
 * Handle comments worker loop.
 */
async function commentsWorkerLoop(
  queue: string[],
  grouped: Map<string, VideoTagRow[]>,
  store: VideoStore,
  options: VideoCrawlOptions
) {
  while (true) {
    const host = queue.pop();
    if (!host) return;
    const items = grouped.get(host);
    if (!items) continue;
    await processCommentsInstance(host, items, store, options);
  }
}

/**
 * Handle tag worker loop.
 */
async function tagWorkerLoop(
  queue: string[],
  grouped: Map<string, VideoTagRow[]>,
  store: VideoStore,
  options: VideoCrawlOptions
) {
  while (true) {
    const host = queue.pop();
    if (!host) return;
    const items = grouped.get(host);
    if (!items) continue;
    await processTagInstance(host, items, store, options);
  }
}

/**
 * Handle process tag instance.
 */
async function processTagInstance(
  host: string,
  items: VideoTagRow[],
  store: VideoStore,
  options: VideoCrawlOptions
) {
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
  console.log(formatMetricLog("tags", [["videos", items.length]], "start", normalizedHost));
  for (const item of items) {
    try {
      const tagsJson = await fetchVideoTags(normalizedHost, item.videoUuid, options, requestLimiter);
      if (tagsJson !== null) {
        store.updateVideoTags(item.videoId, normalizedHost, tagsJson);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const status = extractHttpStatus(message);
      // Only direct-detail absence is canonical; retain the process outage abort.
      if (status === 404 || status === 410) {
        store.updateVideoInvalid(item.videoId, normalizedHost, status === 404 ? "not_found" : "gone");
      } else if (isNoNetworkError(error)) {
        throw error;

      } else {
        store.updateVideoError(item.videoId, normalizedHost, message);
        console.warn(`[tags] error ${normalizedHost}/${item.videoUuid}: ${message}`);
      }
    }
  }

  console.log(`[tags] done ${normalizedHost}`);
}

/**
 * Handle process comments instance.
 */
async function processCommentsInstance(
  host: string,
  items: VideoTagRow[],
  store: VideoStore,
  options: VideoCrawlOptions
) {
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
  console.log(formatMetricLog("comments", [["videos", items.length]], "start", normalizedHost));
  for (const item of items) {
    try {
      const commentsCount = await fetchVideoComments(normalizedHost, item.videoUuid, options, requestLimiter);
      if (commentsCount !== null) {
        store.updateVideoComments(item.videoId, normalizedHost, commentsCount);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const status = extractHttpStatus(message);
      // Only direct-detail absence is canonical; retain the process outage abort.
      if (status === 404 || status === 410) {
        store.updateVideoInvalid(item.videoId, normalizedHost, status === 404 ? "not_found" : "gone");
      } else if (isNoNetworkError(error)) {
        throw error;

      } else {
        store.updateVideoError(item.videoId, normalizedHost, message);
        console.warn(`[comments] error ${normalizedHost}/${item.videoUuid}: ${message}`);
      }
    }
  }

  console.log(`[comments] done ${normalizedHost}`);
}

/**
 * Handle process channel.
 */
async function processChannel(
  host: string,
  item: VideoProgressRow,
  meta: ChannelMeta | undefined,
  store: VideoStore,
  existingDb: Database.Database | null,
  options: VideoCrawlOptions,
  requestLimiter: RequestLimiter,
  channelOrdinal: string,
  newVideos: NewVideoCounter
) {
  const channelSlug = item.channelName ?? meta?.channelSlug ?? null;
  if (!channelSlug) {
    store.updateVideoProgress(host, item.channelId, "error", item.lastStart, "missing channel slug");
    console.warn(
      formatMetricLog(
        "videos",
        [["channel", channelOrdinal]],
        "skip",
        `${host}/${item.channelId} missing channel slug`
      )
    );
    return;
  }

  const startAt = item.status === "in_progress" ? item.lastStart : 0;
  store.updateVideoProgress(host, item.channelId, "in_progress", startAt, null);
  console.log(
    formatMetricLog(
      "videos",
      [["channel", channelOrdinal], ["start", startAt], ["resume", item.status]],
      "",
      `${host}/${channelSlug}`
    )
  );

  try {
    const { localCount, totalCount } = await crawlChannelVideos(
      host,
      {
        channelId: item.channelId,
        channelSlug,
        displayName: meta?.displayName ?? null,
        channelUrl: meta?.channelUrl ?? null
      },
      startAt,
      store,
      existingDb,
      options,
      requestLimiter
    );
    store.updateVideoProgress(host, item.channelId, "done", 0, null);
    newVideos.total += localCount;
    console.log(
      formatMetricLog(
        "videos",
        [["new", localCount], ["total", totalCount], ["channel", channelOrdinal]],
        "",
        `${host}/${channelSlug}`
      )
    );
  } catch (error) {
    const message = formatCrawlError(error);
    store.updateVideoProgress(host, item.channelId, "error", startAt, message);
    console.warn(
      formatMetricLog(
        "videos",
        [["channel", channelOrdinal]],
        "error",
        `${host}/${channelSlug}: ${message}`
      )
    );
  }
}

/**
 * Handle crawl channel videos.
 */
async function crawlChannelVideos(
  host: string,
  channel: {
    channelId: string;
    channelSlug: string;
    displayName: string | null;
    channelUrl: string | null;
  },
  startAt: number,
  store: VideoStore,
  existingDb: Database.Database | null,
  options: VideoCrawlOptions,
  requestLimiter: RequestLimiter
) {
  let start = startAt;
  let protocol = "https:";
  let totalCount = 0;
  let localCount = 0;
  let fullPagesSeen = 0;
  let pagesFetched = 0;

  while (true) {
    const { page, protocol: usedProtocol } = await fetchPage(
      host,
      channel.channelSlug,
      start,
      options,
      protocol,
      requestLimiter
    );
    protocol = usedProtocol;
    pagesFetched += 1;

    if (typeof page.total === "number" && Number.isFinite(page.total) && page.total >= 0) {
      // Refresh the stored count while paging metadata so deletions or uploads
      // observed after the count stage are reflected in staging.
      store.updateChannelVideosCount(channel.channelId, host, page.total);
    }

    const data = Array.isArray(page.data) ? page.data : [];
    // Novelty is a persistence invariant, not a --new-videos optimization.
    // Always know which local rows already exist so repeated full crawls cannot
    // route them through full semantic-field insertion/upsert behavior.
    const ids = Array.from(
      new Set(
        data
          .map((video) => toStringId(video.uuid ?? video.id))
          .filter((value): value is string => Boolean(value))
      )
    );
    const existingIds = store.listExistingVideoIds(host, ids);
    const externalExistingIds = options.newOnly
      ? queryExternalExistingVideoIds(existingDb, host, ids)
      : new Set<string>();
    const nextStart = start + PAGE_SIZE;
    totalCount += data.length;

    if (data.length > 0) {
      const checkedAt = Date.now();
      const rows = await buildVideoRows(
        data,
        host,
        protocol,
        channel,
        checkedAt,
        existingIds,
        externalExistingIds,
        options,
        requestLimiter
      );
      localCount += rows.newRows.length;
      store.insertNewVideos(rows.newRows);
      store.refreshExistingVideoMetadata(rows.existingRows);
    }

    store.updateVideoProgress(host, channel.channelId, "in_progress", nextStart, null);

    const knownIds = options.newOnly
      ? new Set([...existingIds, ...externalExistingIds])
      : null;
    if (
      options.newOnly &&
      options.stopAfterFullPages > 0 &&
      ids.length > 0 &&
      knownIds &&
      knownIds.size >= ids.length
    ) {
      // The same video can exist in both staging and prod after a resumed or
      // partially merged run. Count the union so overlap cannot hide a new ID
      // and stop pagination before later pages are inspected.
      fullPagesSeen += 1;
      if (fullPagesSeen >= options.stopAfterFullPages) {
        console.log(
          formatMetricLog(
            "videos",
            [["full_pages", fullPagesSeen], ["page_start", start]],
            "stop",
            `${host}/${channel.channelSlug}`
          )
        );
        break;
      }
    } else {
      fullPagesSeen = 0;
    }

    if (page.total !== undefined) {
      if (nextStart >= page.total) break;
    } else if (data.length < PAGE_SIZE) {
      break;
    }
    if (options.maxVideosPages > 0 && pagesFetched >= options.maxVideosPages) {
      break;
    }

    start = nextStart;
  }

  return { localCount, totalCount };
}

/**
 * Build persisted rows for one page while enriching media from live detail
 * payloads. Detail failures fall back to list payload media so channel crawls
 * keep progressing even when a host's detail endpoint is flaky.
 */
async function buildVideoRows(
  videos: PeerTubeVideo[],
  host: string,
  protocol: string,
  channel: {
    channelId: string;
    channelSlug: string;
    displayName: string | null;
    channelUrl: string | null;
  },
  checkedAt: number,
  existingIds: Set<string>,
  externalExistingIds: Set<string>,
  options: VideoCrawlOptions,
  requestLimiter: RequestLimiter
): Promise<{ newRows: VideoUpsertRow[]; existingRows: ExistingVideoRefresh[] }> {
  const built = new Array<{ value: BuiltVideoPersistence; existing: boolean } | null>(videos.length).fill(null);

  await mapWithConcurrency(
    videos.map((video, index) => ({ video, index })),
    VIDEO_DETAIL_CONCURRENCY,
    async ({ video, index }) => {
      const videoId = toStringId(video.uuid ?? video.id);
      if (!videoId) return;
      const existsLocally = existingIds.has(videoId);
      if (options.newOnly && (existsLocally || externalExistingIds.has(videoId))) {
        return;
      }

      const detailResult = await fetchVideoDetailBestEffort(
        host,
        video,
        options,
        protocol,
        requestLimiter
      );
      const value = await toVideoRow(
        video,
        host,
        protocol,
        channel,
        checkedAt,
        detailResult,
        options,
        requestLimiter
      );
      if (value) built[index] = { value, existing: existsLocally };
    }
  );

  const newRows: VideoUpsertRow[] = [];
  const existingRows: ExistingVideoRefresh[] = [];
  for (const item of built) {
    if (!item) continue;
    if (item.existing) {
      existingRows.push(item.value.refresh);
    } else {
      newRows.push(item.value.row);
    }
  }
  return { newRows, existingRows };
}

/**
 * Handle fetch page.
 */
async function fetchPage(
  host: string,
  channelName: string,
  start: number,
  options: VideoCrawlOptions,
  protocol: string,
  requestLimiter: RequestLimiter
) {
  const primaryUrl = buildChannelVideosUrl(
    host,
    channelName,
    start,
    PAGE_SIZE,
    protocol,
    options.sort
  );

  try {
    const page = await requestLimiter.run(() => fetchJsonWithRetry<Page<PeerTubeVideo>>(primaryUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    }));
    return { page, protocol };
  } catch (error) {
    if (!shouldTryAlternateProtocol(error)) throw error;
    const fallbackProtocol = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildChannelVideosUrl(
      host,
      channelName,
      start,
      PAGE_SIZE,
      fallbackProtocol,
      options.sort
    );
    const page = await requestLimiter.run(() => fetchJsonWithRetry<Page<PeerTubeVideo>>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
    }));
    return { page, protocol: fallbackProtocol };
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
  protocol: string,
  sort: string
) {
  const safeSort = sort && sort.trim().length > 0 ? sort.trim() : "-publishedAt";
  return `${protocol}//${host}/api/v1/video-channels/${encodeURIComponent(
    channelName
  )}/videos?start=${start}&count=${count}&sort=${encodeURIComponent(safeSort)}`;
}

/**
 * Handle to video row.
 */
async function toVideoRow(
  video: PeerTubeVideo,
  host: string,
  protocol: string,
  channel: {
    channelId: string | null;
    channelSlug: string;
    displayName: string | null;
    channelUrl: string | null;
  },
  checkedAt: number,
  detailResult: VideoDetailFetchResult | null,
  options: VideoCrawlOptions,
  requestLimiter: RequestLimiter
): Promise<BuiltVideoPersistence | null> {
  const videoId = toStringId(video.uuid ?? video.id);
  if (!videoId) return null;

  const detail = detailResult?.detail ?? null;
  const mediaProtocol = detailResult?.protocol ?? protocol;
  const detailRecord = detail as Record<string, unknown> | null;
  const listRecord = video as Record<string, unknown>;

  let normalized = normalizeVideoMetadata({
    listVideo: listRecord,
    detail: detailRecord,
    host,
    protocol: mediaProtocol
  });

  const candidateVideoUrl = toNullableString(detail?.url ?? video.url);
  let activityPub: ActivityPubLiveMetadata | null = null;
  if (
    normalized.isLive === 1 &&
    (normalized.permanentLive === null || normalized.liveSaveReplay === null) &&
    candidateVideoUrl
  ) {
    try {
      const live = await requestLimiter.run(() =>
        fetchActivityPubLiveMetadata(
          candidateVideoUrl,
          host,
          toNullableString(detail?.uuid ?? video.uuid),
          { timeoutMs: options.timeoutMs, maxRetries: options.maxRetries }
        )
      );
      activityPub = live;
      normalized = normalizeVideoMetadata({
        listVideo: listRecord,
        detail: detailRecord,
        activityPub: live as unknown as Record<string, unknown>,
        host,
        protocol: mediaProtocol
      });
    } catch (error) {
      // Public AP parity is best-effort. REST metadata remains usable and a
      // version-0 live row can be retried later by metadata maintenance.
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`[videos] ActivityPub live metadata fallback ${host}/${videoId}: ${message}`);
    }
  }

  const sourceChannel =
    (detail?.channel as PeerTubeVideoChannel | undefined) ?? video.channel ?? null;
  const incomingChannelId =
    toStringId(sourceChannel?.id) ?? (channel.channelId || null);
  const incomingChannelName =
    toNullableString(sourceChannel?.displayName ?? sourceChannel?.display_name) ??
    channel.displayName;
  const incomingChannelUrl =
    toNullableString(sourceChannel?.url) ?? channel.channelUrl ?? null;
  const thumbnailCandidates = detailResult
    ? resolveThumbnailCandidates(detail?.thumbnails, host, mediaProtocol)
    : null;
  const thumbnailCompatibility = thumbnailCandidates === null
    ? resolveLegacyThumbnailCompatibility(detail, video, host, mediaProtocol)
    : thumbnailCandidates[0] ?? { url: null, width: null, height: null };
  const thumbnailCandidatesJson = thumbnailCandidates === null
    ? null
    : JSON.stringify(thumbnailCandidates);

  const row: VideoUpsertRow = {
    videoId,
    videoUuid: toNullableString(video.uuid ?? detail?.uuid),
    videoNumericId: toNullableNumber(detail?.id ?? video.id),
    instanceDomain: host,
    channelId: incomingChannelId,
    channelName: incomingChannelName,
    channelUrl: incomingChannelUrl,
    accountName: normalized.accountName,
    accountUrl: normalized.accountUrl,
    title: normalized.title,
    description: normalized.description,
    tagsJson: normalized.tagsJson,
    category: normalized.category,
    categoryId: normalized.categoryId,
    licenceId: normalized.licenceId,
    licence: normalized.licence,
    language: normalized.language,
    languageLabel: normalized.languageLabel,
    publishedAt: normalized.publishedAt,
    originallyPublishedAt: normalized.originallyPublishedAt,
    updatedAt: normalized.updatedAt,
    videoUrl: candidateVideoUrl,
    duration: toNullableNumber(detail?.duration ?? video.duration),
    thumbnailUrl: thumbnailCompatibility.url,
    thumbnailCandidatesJson,
    thumbnailWidth: thumbnailCompatibility.width,
    thumbnailHeight: thumbnailCompatibility.height,
    embedPath: toNullableString(detail?.embedPath ?? detail?.embed_path ?? video.embedPath ?? video.embed_path),
    views: toNullableNumber(detail?.views ?? detail?.views_count ?? video.views ?? video.views_count),
    likes: toNullableNumber(detail?.likes ?? detail?.likes_count ?? video.likes ?? video.likes_count),
    dislikes: toNullableNumber(detail?.dislikes ?? detail?.dislikes_count ?? video.dislikes ?? video.dislikes_count),
    commentsCount: toCommentsCount(
      detail?.comments ?? detail?.commentsCount ?? detail?.comments_count ??
      video.comments ?? video.commentsCount ?? video.comments_count
    ),
    nsfw: normalized.nsfw,
    sensitiveSummary: normalized.sensitiveSummary,
    isLive: normalized.isLive,
    permanentLive: normalized.permanentLive,
    liveSaveReplay: normalized.liveSaveReplay,
    aspectRatio: normalized.aspectRatio,
    support: normalized.support,
    accountUsername: normalized.accountUsername,
    accountAvatarUrl: normalized.accountAvatarUrl,
    metadataVersion: normalized.metadataVersion,
    previewPath: resolvePreferredPreviewPath(detail, video),
    lastCheckedAt: checkedAt
  };

  const detailPatch = detailRecord ? buildDetailMetadataPatch(normalized, detailRecord) : undefined;
  const activityPubPatch = activityPub ? buildActivityPubMetadataPatch(activityPub) : undefined;
  return {
    row,
    refresh: {
      base: row,
      ...(detailPatch ? { detail: detailPatch } : {}),
      ...(activityPubPatch ? { activityPub: activityPubPatch } : {}),
      ...(detailResult && thumbnailCandidates !== null
        ? { thumbnail: thumbnailCandidates }
        : {})
    }
  };
}

/** Build detail-owned values only after a successful detail response. */
function buildDetailMetadataPatch(
  normalized: ReturnType<typeof normalizeVideoMetadata>,
  detail: Record<string, unknown>
): VideoDetailMetadataPatch {
  return {
    categoryId: normalized.categoryId,
    category: normalized.category,
    licenceId: normalized.licenceId,
    licence: normalized.licence,
    language: normalized.language,
    languageLabel: normalized.languageLabel,
    sensitiveSummary: normalized.sensitiveSummary,
    originallyPublishedAt: normalized.originallyPublishedAt,
    updatedAt: normalized.updatedAt,
    aspectRatio: normalized.aspectRatio,
    support: normalized.support,
    accountUsername: normalized.accountUsername,
    accountAvatarUrl: normalized.accountAvatarUrl,
    ...(hasOwn(detail, "permanentLive") || hasOwn(detail, "permanent_live")
      ? { permanentLive: normalized.permanentLive }
      : {}),
    ...(hasOwn(detail, "liveSaveReplay") || hasOwn(detail, "live_save_replay")
      ? { liveSaveReplay: normalized.liveSaveReplay }
      : {})
  };
}

/** Build a sparse AP patch so absent/null fields never erase stored values. */
function buildActivityPubMetadataPatch(
  live: ActivityPubLiveMetadata
): VideoActivityPubMetadataPatch | undefined {
  const patch: VideoActivityPubMetadataPatch = {};
  if (live.permanentLive !== null) patch.permanentLive = live.permanentLive ? 1 : 0;
  if (live.liveSaveReplay !== null) patch.liveSaveReplay = live.liveSaveReplay ? 1 : 0;
  return Object.keys(patch).length > 0 ? patch : undefined;
}

/** Check whether a successful detail payload explicitly supplied one field. */
function hasOwn(value: Record<string, unknown> | null, key: string): boolean {
  return Boolean(value && Object.prototype.hasOwnProperty.call(value, key));
}

/** Group work rows by PeerTube instance while preserving their concrete row type. */
function groupByInstance<T extends { instanceDomain: string }>(items: T[]): Map<string, T[]> {
  const grouped = new Map<string, T[]>();
  for (const item of items) {
    const list = grouped.get(item.instanceDomain) ?? [];
    list.push(item);
    grouped.set(item.instanceDomain, list);
  }
  return grouped;
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
 * Handle to nullable timestamp.
 */
function toNullableTimestamp(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.length > 0) {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return null;
}

/**
 * Handle to nullable boolean.
 */
function toNullableBoolean(value: unknown): number | null {
  if (typeof value === "boolean") return value ? 1 : 0;
  return null;
}

/**
 * Handle to tags json.
 */
function toTagsJson(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  const tags = value.filter((tag) => typeof tag === "string");
  return JSON.stringify(tags);
}

/**
 * Handle to comments count.
 */
function toCommentsCount(value: unknown): number | null {
  return toNullableNumber(value);
}

/**
 * Handle to string id.
 */
function toStringId(value: unknown): string | null {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

/**
 * Handle fetch video detail.
 */
async function fetchVideoDetail(
  host: string,
  videoUuid: string,
  options: VideoCrawlOptions,
  protocol: string,
  requestLimiter: RequestLimiter
): Promise<VideoDetailFetchResult> {
  const primaryUrl = buildVideoDetailUrl(host, videoUuid, protocol);
  try {
    return {
      detail: await requestLimiter.run(() => fetchJsonWithRetry<PeerTubeVideoDetail>(primaryUrl, {
        timeoutMs: options.timeoutMs,
        maxRetries: options.maxRetries
      })),
      protocol
    };
  } catch (error) {
    if (!shouldTryAlternateProtocol(error)) throw error;
    const fallbackProtocol = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildVideoDetailUrl(host, videoUuid, fallbackProtocol);
    return {
      detail: await requestLimiter.run(() => fetchJsonWithRetry<PeerTubeVideoDetail>(alternateUrl, {
        timeoutMs: options.timeoutMs,
        maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
      })),
      protocol: fallbackProtocol
    };
  }
}

/**
 * Attempt per-video detail enrichment without turning a detail-endpoint
 * failure into a dropped list row. Existing-row persistence preserves
 * last-known-good enrichment fields when this request fails.
 */
async function fetchVideoDetailBestEffort(
  host: string,
  video: PeerTubeVideo,
  options: VideoCrawlOptions,
  protocol: string,
  requestLimiter: RequestLimiter
): Promise<VideoDetailFetchResult | null> {
  if (!video.uuid) return null;
  try {
    return await fetchVideoDetail(host, video.uuid, options, protocol, requestLimiter);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    // Detail enrichment is best-effort during the main crawl. Falling back to
    // the list payload keeps ingestion moving while the absence of a detail
    // patch prevents destructive refresh of last-known-good enrichment.
    console.warn(`[videos] detail fallback ${host}/${video.uuid}: ${message}`);
    return null;
  }
}

/**
 * Backfill metadata-v1 fields in an already-migrated crawler/whitelist DB.
 *
 * Schema validation is deliberately read-only and happens before any network
 * work so this maintenance command can never become an implicit production
 * schema migration path.
 */
async function crawlVideoMetadata(options: VideoCrawlOptions) {
  assertMetadataMaintenanceSchema(options.dbPath);
  const store = new VideoStore({ dbPath: options.dbPath, initializeSchema: false });
  const includedHosts = loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const items = store.listVideosForMetadata(Boolean(options.updateMetadata));
  const grouped = groupByInstance(items);
  const allHosts = scopeHosts(Array.from(grouped.keys()), includedHosts, excludedHosts);
  // Health is a persisted host-level observation, so apply it after explicit
  // include/exclude filters without probing every failed video again.
  const healthyHosts = options.onlyHealthyHosts ? store.listHealthyInstanceHosts() : null;
  const healthyScopedHosts = healthyHosts
    ? allHosts.filter((host) => healthyHosts.has(host.toLowerCase()))
    : allHosts;
  const hosts = options.maxInstances > 0
    ? healthyScopedHosts.slice(0, options.maxInstances)
    : healthyScopedHosts;
  // Count only work that survived host scoping so the initial total remains a
  // truthful denominator when operators run a targeted/resumed maintenance pass.
  const scopedVideoCount = hosts.reduce((total, host) => total + (grouped.get(host)?.length ?? 0), 0);
  const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));
  const nextVideoOrdinal = createProgressOrdinal(scopedVideoCount);
  let updated = 0;
  let errors = 0;

  console.log(
    `[metadata] instances=${hosts.length} videos=${scopedVideoCount} concurrency=${workerCount} update=${Boolean(options.updateMetadata)} healthy_only=${Boolean(options.onlyHealthyHosts)}`
  );

  try {
    const queue = hosts.slice();
    const workers = Array.from({ length: workerCount }, async () => {
      while (true) {
        const host = queue.shift();
        if (!host) return;
        const limiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
        for (const item of grouped.get(host) ?? []) {
          // Allocate before awaiting I/O so concurrent host workers expose one
          // stable crawl-wide ordinal instead of ambiguous host-local counters.
          const videoOrdinal = nextVideoOrdinal();
          const subject = `${item.instanceDomain}/${item.videoId}`;
          try {
            const detailResult = await fetchVideoDetail(
              host,
              item.videoUuid,
              options,
              "https:",
              limiter
            );
            const detail = detailResult.detail;
            const channelRef = detail.channel;
            const built = await toVideoRow(
              detail,
              host,
              detailResult.protocol,
              {
                channelId: toStringId(channelRef?.id),
                channelSlug: toNullableString(channelRef?.name) ?? "",
                displayName: toNullableString(
                  channelRef?.displayName ?? channelRef?.display_name
                ),
                channelUrl: toNullableString(channelRef?.url)
              },
              Date.now(),
              detailResult,
              options,
              limiter
            );
            if (!built) {
              store.updateVideoError(item.videoId, item.instanceDomain, "metadata detail missing video identity");
              errors += 1;
              console.warn(
                formatMetricLog(
                  "metadata",
                  [["video", videoOrdinal], ["updated", updated], ["errors", errors]],
                  "error",
                  subject
                )
              );
              continue;
            }
            // Persist against the stable local identity selected before the
            // request; remote numeric/UUID variants must not retarget a row.
            const localBase = {
              ...built.refresh.base,
              videoId: item.videoId,
              videoUuid: item.videoUuid,
              instanceDomain: item.instanceDomain
            };
            store.applyMetadataBackfill({
              ...built.refresh,
              base: localBase
            });
            updated += 1;
            console.log(
              formatMetricLog(
                "metadata",
                [["video", videoOrdinal], ["updated", updated], ["errors", errors]],
                "done",
                subject
              )
            );
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            const status = extractHttpStatus(message);
            // A successful PeerTube detail response that says the resource is
            // gone is definitive for this stored UUID. Transient transport,
            // rate-limit, and server failures deliberately remain resumable.
            if (status === 404 || status === 410) {
              store.updateVideoInvalid(
                item.videoId,
                item.instanceDomain,
                status === 404 ? "not_found" : "gone"
              );
            } else {
              store.updateVideoError(item.videoId, item.instanceDomain, message);
            }
            errors += 1;
            console.warn(
              formatMetricLog(
                "metadata",
                [["video", videoOrdinal], ["updated", updated], ["errors", errors]],
                status === 404 || status === 410 ? "invalid" : "error",
                subject
              )
            );
          }
        }
      }
    });
    await Promise.all(workers);
    console.log("[metadata] finished");
  } finally {
    store.close();
  }
}


/**
 * Handle refresh video thumbnails.
 *
 * This maintenance mode revisits live PeerTube video detail pages so stale
 * feed thumbnails can be rewritten without replaying the full channel crawl.
 */
async function refreshVideoThumbnails(options: VideoCrawlOptions) {
  // Thumbnail maintenance must never become an implicit schema-migration path.
  assertThumbnailMaintenanceSchema(options.dbPath);
  const store = new VideoStore({ dbPath: options.dbPath, initializeSchema: false });
  const includedHosts = loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const items = store.listVideosForThumbnailRefresh(options.resume);
  const grouped = groupByInstance(items);
  const scopedHosts = scopeHosts(Array.from(grouped.keys()), includedHosts, excludedHosts);
  // Apply the same persisted `health_status = ok` contract as metadata after
  // explicit include/exclude scope. This avoids retrying known failed hosts
  // while preserving the unfiltered full-refresh behavior unless requested.
  const healthyHosts = options.onlyHealthyHosts ? store.listHealthyInstanceHosts() : null;
  const healthyScopedHosts = healthyHosts
    ? scopedHosts.filter((host) => healthyHosts.has(host.toLowerCase()))
    : scopedHosts;
  const hosts = options.maxInstances > 0
    ? healthyScopedHosts.slice(0, options.maxInstances)
    : healthyScopedHosts;
  const scopedVideoCount = hosts.reduce((total, host) => total + (grouped.get(host)?.length ?? 0), 0);
  const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));
  const nextVideoOrdinal = createProgressOrdinal(scopedVideoCount);
  // These counters are run-local. JavaScript updates them between awaits, so
  // concurrent host workers expose one monotonic operator-visible summary.
  const progress = { updated: 0, errors: 0 };

  console.log(
    `[thumbnails] instances=${hosts.length} videos=${scopedVideoCount} concurrency=${workerCount} resume=${options.resume} healthy_only=${Boolean(options.onlyHealthyHosts)}`
  );

  try {
    const queue = hosts.slice();
    const workers = Array.from({ length: workerCount }, () =>
      thumbnailWorkerLoop(queue, grouped, store, options, nextVideoOrdinal, progress)
    );
    await Promise.all(workers);
    console.log("[thumbnails] finished");
  } finally {
    store.close();
  }
}

/**
 * Handle thumbnail refresh worker loop.
 *
 * One worker processes one host at a time so the crawler does not spray many
 * detail requests across the same PeerTube instance concurrently.
 */
async function thumbnailWorkerLoop(
  queue: string[],
  grouped: Map<string, VideoThumbnailRow[]>,
  store: VideoStore,
  options: VideoCrawlOptions,
  nextVideoOrdinal: () => string,
  progress: { updated: number; errors: number }
) {
  while (true) {
    const host = queue.shift();
    if (!host) return;
    const rows = grouped.get(host) ?? [];
    const requestLimiter = createRequestLimiter(options.hostConcurrency, options.hostDelayMs);
    for (const row of rows) {
      // Allocate before I/O to retain a stable crawl-wide position even when
      // multiple hosts finish details in a different order.
      const videoOrdinal = nextVideoOrdinal();
      const subject = `${host}/${row.videoUuid}`;
      try {
        const { detail, protocol } = await fetchVideoDetail(
          host,
          row.videoUuid,
          options,
          "https:",
          requestLimiter
        );
        const candidates = resolveThumbnailCandidates(detail.thumbnails, host, protocol);
        const checkedAt = Date.now();
        if (candidates === null) {
          // A successful legacy-shaped detail response is not authoritative for
          // candidate state. Preserve every persisted thumbnail field so SQL NULL
          // remains resumable and prior authoritative arrays cannot be downgraded.
          console.warn(
            formatMetricLog(
              "thumbnails",
              [["video", videoOrdinal], ["updated", progress.updated], ["errors", progress.errors]],
              "legacy",
              subject
            )
          );
        } else {
          store.updateVideoThumbnailCandidates(
            row.videoId,
            row.instanceDomain,
            candidates,
            checkedAt
          );
          progress.updated += 1;
          // Successful modern detail is visible in the operator log as well as
          // SQLite so a long maintenance run has an auditable success signal.
          if (candidates.length === 0) {
            console.log(
              formatMetricLog(
                "thumbnails",
                [["video", videoOrdinal], ["updated", progress.updated], ["errors", progress.errors], ["candidates", 0]],
                "empty",
                subject
              )
            );
          } else {
            console.log(
              formatMetricLog(
                "thumbnails",
                [["video", videoOrdinal], ["updated", progress.updated], ["errors", progress.errors], ["candidates", candidates.length]],
                "",
                subject
              )
            );
          }
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const status = extractHttpStatus(message);
        // A gone detail UUID is definitive and becomes excluded from future
        // maintenance. Other errors remain retryable but are recorded so
        // operators can distinguish unstable remotes from completed work.
        if (status === 404 || status === 410) {
          store.updateVideoInvalid(
            row.videoId,
            row.instanceDomain,
            status === 404 ? "not_found" : "gone"
          );
        } else {
          store.updateVideoError(row.videoId, row.instanceDomain, message);
        }
        progress.errors += 1;
        console.warn(
          `${formatMetricLog(
            "thumbnails",
            [["video", videoOrdinal], ["updated", progress.updated], ["errors", progress.errors]],
            status === 404 || status === 410 ? "invalid" : "error",
            subject
          )}: ${message}`
        );
      }
    }
  }
}

/**
 * Handle fetch video tags.
 */
async function fetchVideoTags(
  host: string,
  videoUuid: string,
  options: VideoCrawlOptions,
  requestLimiter: RequestLimiter
): Promise<string | null> {
  const { detail } = await fetchVideoDetail(
    host,
    videoUuid,
    options,
    "https:",
    requestLimiter
  );
  return toTagsJson(detail.tags);
}

/**
 * Handle fetch video comments.
 */
async function fetchVideoComments(
  host: string,
  videoUuid: string,
  options: VideoCrawlOptions,
  requestLimiter: RequestLimiter
): Promise<number | null> {
  const { detail } = await fetchVideoDetail(
    host,
    videoUuid,
    options,
    "https:",
    requestLimiter
  );
  return toCommentsCount(detail.comments ?? detail.commentsCount ?? detail.comments_count);
}

/**
 * Handle build video detail url.
 */
function buildVideoDetailUrl(host: string, videoUuid: string, protocol: string) {
  return `${protocol}//${host}/api/v1/videos/${encodeURIComponent(videoUuid)}`;
}

/**
 * Handle open existing db.
 */
function openExistingDb(options: VideoCrawlOptions): Database.Database | null {
  if (!options.existingDbPath || options.existingDbPath.trim().length === 0) {
    return null;
  }
  return new Database(options.existingDbPath, {
    readonly: true,
    fileMustExist: true
  });
}

/**
 * Handle query external existing video ids.
 */
function queryExternalExistingVideoIds(
  db: Database.Database | null,
  instanceDomain: string,
  ids: string[]
): Set<string> {
  if (!db || ids.length === 0) return new Set();
  const placeholders = ids.map(() => "?").join(", ");
  const rows = db
    .prepare(
      `SELECT video_id
       FROM videos
       WHERE instance_domain = ?
         AND video_id IN (${placeholders})`
    )
    .all(instanceDomain, ...ids) as { video_id: string }[];
  return new Set(rows.map((row) => row.video_id));
}

/**
 * Handle extract http status.
 */
function extractHttpStatus(message: string): number | null {
  const match = message.match(/HTTP (\d{3})/);
  if (!match) return null;
  return Number(match[1]);
}
