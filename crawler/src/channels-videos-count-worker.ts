import { ChannelStore } from "./db.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { filterHosts, loadHostsFromFile } from "./host-filters.js";

const CHANNEL_CONCURRENCY = 2;

export interface ChannelVideosCountOptions {
  dbPath: string;
  excludeHostsFile: string | null;
  concurrency: number;
  timeoutMs: number;
  maxRetries: number;
  resume: boolean;
  errorsOnly: boolean;
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

export async function crawlChannelVideosCount(options: ChannelVideosCountOptions) {
  const store = new ChannelStore({ dbPath: options.dbPath });
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const hosts = filterHosts(store.listInstances(), excludedHosts);
  const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));

  const counts = store.getChannelCounts();
  const progress: ChannelProgressState = {
    totalChannels: counts.total,
    channelsWithVideosCount: counts.withVideos,
    channelsWithError: counts.withError,
    updatedThisRun: 0
  };
  updateStatus(
    `[channels-videos] instances=${hosts.length} concurrency=${workerCount} resume=${options.resume} errorsOnly=${options.errorsOnly}`
  );
  updateProgress(progress);
  updateStatus("[channels-videos] idle");

  const queue = hosts.slice();
  const workers = Array.from({ length: workerCount }, () =>
    workerLoop(queue, store, options, progress)
  );
  await Promise.all(workers);

  updateStatus("[channels-videos] finished");
  store.close();
}

async function workerLoop(
  queue: string[],
  store: ChannelStore,
  options: ChannelVideosCountOptions,
  progress: ChannelProgressState
) {
  while (true) {
    const host = queue.pop();
    if (!host) return;
    await processInstance(host, store, options, progress);
  }
}

async function processInstance(
  host: string,
  store: ChannelStore,
  options: ChannelVideosCountOptions,
  progress: ChannelProgressState
) {
  const normalizedHost = host.toLowerCase();
  updateStatus(`[channels-videos] start ${normalizedHost}`);

  try {
    const { total, updated } = await updateVideosCountForInstance(
      normalizedHost,
      store,
      options,
      progress
    );
    updateStatus(
      `[channels-videos] done ${normalizedHost} updated=${updated} total=${total}`
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    updateStatus(`[channels-videos] error ${normalizedHost}: ${message}`);
  }
}

async function updateVideosCountForInstance(
  host: string,
  store: ChannelStore,
  options: ChannelVideosCountOptions,
  progress: ChannelProgressState
) {
  const channels = store.listChannelsForInstance(host);
  let updated = 0;

  await mapWithConcurrency(channels, CHANNEL_CONCURRENCY, async (channel) => {
    if (!channel.channel_name) return;
    if (channel.videos_count !== null) {
      updateStatus(
        `[channels-videos] skip ${host}/${channel.channel_name} videos_count=${channel.videos_count}`
      );
      updateProgress(progress);
      return;
    }
    if (options.errorsOnly && channel.last_error_source !== "videos_count") {
      updateStatus(
        `[channels-videos] skip ${host}/${channel.channel_name} no_error`
      );
      updateProgress(progress);
      return;
    }
    if (options.resume && channel.last_error_source === "videos_count") {
      updateStatus(
        `[channels-videos] skip ${host}/${channel.channel_name} error=${channel.last_error ?? "unknown"}`
      );
      updateProgress(progress);
      return;
    }
    const hadError = channel.last_error_source === "videos_count";
    const videosCount = await fetchChannelVideosCount(
      host,
      channel.channel_name,
      options,
      (message) => updateStatus(message)
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
    progress.channelsWithVideosCount += 1;
    if (hadError) {
      progress.channelsWithError = Math.max(0, progress.channelsWithError - 1);
    }
    updateStatus(
      `[channels-videos] done ${host}/${channel.channel_name} videos_count=${videosCount.total}`
    );
    updateProgress(progress);
  });

  return { total: channels.length, updated };
}

async function fetchChannelVideosCount(
  host: string,
  channelName: string,
  options: ChannelVideosCountOptions,
  reportStatus: StatusReporter
): Promise<ChannelVideoCountResult> {
  try {
    const page = await fetchWithFallback(host, channelName, options, "https:", reportStatus);
    const total = page.total;
    if (typeof total === "number" && Number.isFinite(total)) {
      return { total, error: null };
    }
    return { total: null, error: "invalid total in response" };
  } catch (error) {
    if (isNoNetworkError(error)) {
      throw error;
    }
    const message = error instanceof Error ? error.message : String(error);
    reportStatus(`[channels-videos] count error ${host}/${channelName}: ${message}`);
    return { total: null, error: message };
  }
}

async function fetchWithFallback(
  host: string,
  channelName: string,
  options: ChannelVideosCountOptions,
  protocol: string,
  reportStatus: StatusReporter
) {
  const url = buildChannelVideosUrl(host, channelName, 0, 1, protocol);
  try {
    return await fetchJsonWithRetry<ChannelVideoPage>(url, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries,
      log: reportStatus
    });
  } catch {
    const alternate = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildChannelVideosUrl(host, channelName, 0, 1, alternate);
    return await fetchJsonWithRetry<ChannelVideoPage>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2)),
      log: reportStatus
    });
  }
}

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

function formatProgress(progress: ChannelProgressState) {
  const total = Math.max(0, progress.totalChannels);
  const withVideos = Math.max(0, progress.channelsWithVideosCount);
  return `[channels-videos] progress updated=${progress.updatedThisRun} errors=${progress.channelsWithError} with_videos=${withVideos} total=${total}`;
}

function updateProgress(progress: ChannelProgressState) {
  const line = formatProgress(progress);
  console.log(line);
}

function updateStatus(message: string) {
  console.log(message);
}
