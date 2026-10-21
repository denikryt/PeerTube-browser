/** Host-level orchestration for channel, count, and video crawler stages. */

import { crawlChannels, type ChannelCrawlOptions } from "./channels-worker.js";
import {
  crawlChannelVideosCount,
  type ChannelVideosCountOptions
} from "./channels-videos-count-worker.js";
import { ChannelStore } from "./db/channels.js";
import {
  HostPipelineStore,
  type HostPipelineCandidate,
  type HostPipelineStage
} from "./db/host-pipeline.js";
import { loadHostsFromFile, scopeHosts } from "./host-filters.js";
import { crawlVideos, type VideoCrawlOptions } from "./videos-worker.js";

export interface HostPipelineStages {
  channels: (host: string) => Promise<void>;
  counts: (host: string) => Promise<void>;
  videos: (host: string) => Promise<void>;
}

export interface HostPipelineOptions {
  channels: ChannelCrawlOptions;
  counts: ChannelVideosCountOptions;
  videos: VideoCrawlOptions;
}

/**
 * Run pending host stages with a global channels -> counts -> videos priority.
 *
 * A completed stage returns its host to the next-stage queue. Every free slot
 * then selects the earliest available stage again. This lets ready hosts reach
 * videos while a slow count is still in flight, but queued channel discovery
 * always wins over queued count or video work.
 */
export async function runHostPipelineHosts(
  candidates: HostPipelineCandidate[],
  concurrency: number,
  stages: HostPipelineStages
) {
  if (candidates.length === 0) return;

  const queues: Record<HostPipelineStage, string[]> = {
    channels: [],
    counts: [],
    videos: []
  };
  for (const candidate of candidates) queues[candidate.stage].push(candidate.host);
  const workerCount = Math.min(Math.max(1, concurrency), candidates.length);

  /** Select the globally earliest queued stage without disturbing in-flight work. */
  const takeNext = (): HostPipelineCandidate | null => {
    for (const stage of ["channels", "counts", "videos"] as const) {
      const host = queues[stage].shift();
      if (host) return { host, stage };
    }
    return null;
  };

  /** Report queued work without consuming the next host during completion checks. */
  const hasQueuedWork = () => Object.values(queues).some((queue) => queue.length > 0);

  /** Advance only after persistence for the current stage has completed. */
  const nextStage = (stage: HostPipelineStage): HostPipelineStage | null => {
    if (stage === "channels") return "counts";
    if (stage === "counts") return "videos";
    return null;
  };

  await new Promise<void>((resolve, reject) => {
    let active = 0;
    let failed = false;
    let firstError: unknown;

    const schedule = () => {
      while (!failed && active < workerCount) {
        const work = takeNext();
        if (!work) break;
        active += 1;
        console.log(`[host-pipeline] stage=${work.stage} start host=${work.host}`);
        Promise.resolve(stages[work.stage](work.host))
          .then(() => {
            const following = nextStage(work.stage);
            if (following && !failed) queues[following].push(work.host);
            if (!following) console.log(`[host-pipeline] done host=${work.host}`);
          })
          .catch((error: unknown) => {
            // Stop assigning fresh work after a failure, but let already active
            // requests settle before rejecting so no DB writes outlive the caller.
            if (!failed) {
              failed = true;
              firstError = error;
            }
          })
          .finally(() => {
            active -= 1;
            schedule();
          });
      }

      if (active === 0) {
        if (failed) reject(firstError);
        else if (!hasQueuedWork()) resolve();
      }
    };

    schedule();
  });
}

/**
 * Resolve the selected instances and run existing crawler workers per host.
 *
 * The workers receive an in-process host scope, so they reuse their production
 * persistence and retry paths while preserving progress rows owned by other
 * concurrently scheduled hosts.
 */
export async function crawlHostPipeline(options: HostPipelineOptions) {
  const store = new ChannelStore({ dbPath: options.channels.dbPath });
  const includedHosts = loadHostsFromFile(options.channels.hostsFile);
  const excludedHosts = loadHostsFromFile(options.channels.excludeHostsFile);
  const selected = scopeHosts(store.listInstances(), includedHosts, excludedHosts);
  store.close();

  const priorityStore = new HostPipelineStore(options.channels.dbPath);
  const candidates = priorityStore.listPendingHosts(selected);
  priorityStore.close();
  const limited = options.channels.maxInstances > 0
    ? candidates.slice(0, options.channels.maxInstances)
    : candidates;
  const stageCounts = {
    channels: limited.filter((candidate) => candidate.stage === "channels").length,
    counts: limited.filter((candidate) => candidate.stage === "counts").length,
    videos: limited.filter((candidate) => candidate.stage === "videos").length
  };
  console.log(
    `[host-pipeline] hosts=${limited.length} channels=${stageCounts.channels} counts=${stageCounts.counts} videos=${stageCounts.videos} concurrency=${Math.min(options.channels.concurrency, Math.max(1, limited.length))}`
  );

  await runHostPipelineHosts(limited, options.channels.concurrency, {
    channels: (host) => crawlChannels({
      ...options.channels,
      hosts: [host],
      concurrency: 1,
      maxInstances: 0
    }),
    counts: (host) => crawlChannelVideosCount({
      ...options.counts,
      hosts: [host],
      concurrency: 1
    }),
    videos: (host) => crawlVideos({
      ...options.videos,
      hosts: [host],
      concurrency: 1,
      maxInstances: 0
    })
  });

  console.log("[host-pipeline] finished");
}
