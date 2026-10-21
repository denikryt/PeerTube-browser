/** Host-level orchestration for channel, count, and video crawler stages. */

import { crawlChannels, checkChannelHealth, type ChannelCrawlOptions } from "./channels-worker.js";
import {
  crawlChannelVideosCount,
  type ChannelVideosCountOptions
} from "./channels-videos-count-worker.js";
import { ChannelStore } from "./db/channels.js";
import { checkInstancesHealth } from "./instances-health-cli.js";

import { loadHostsFromFile, loadIncludedHostsFromFile, scopeHosts } from "./host-filters.js";
import { crawlVideos, type VideoCrawlOptions } from "./videos-worker.js";
import { assertWorkActive, stopWork, type WorkCancellation } from "./work-cancellation.js";

type HostPipelineStage = "channels" | "counts" | "videos";
interface HostPipelineCandidate { host: string; stage: HostPipelineStage }

/** A false channel result stops only that host without authorizing child work. */
export interface HostPipelineStages {
  channels: (host: string) => Promise<void | boolean>;
  counts: (host: string) => Promise<void | boolean>;
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
  hosts: string[],
  concurrency: number,
  stages: HostPipelineStages,
  cancellation: WorkCancellation = { stopped: false }
) {
  if (hosts.length === 0) return;
  assertWorkActive(cancellation);

  const queues: Record<HostPipelineStage, string[]> = {
    channels: [],
    counts: [],
    videos: []
  };
  // Only this invocation's fresh, probed host selection can enqueue work.
  // Persisted historic `done` never determines a starting stage.
  queues.channels.push(...hosts);
  const workerCount = Math.min(Math.max(1, concurrency), hosts.length);

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

    const schedule = () => {
      while (!cancellation.stopped && active < workerCount) {
        const work = takeNext();
        if (!work) break;
        active += 1;
        console.log(`[host-pipeline] stage=${work.stage} start host=${work.host}`);
        Promise.resolve().then(() => {
          assertWorkActive(cancellation);
          return stages[work.stage](work.host);
        })
          .then((advance) => {
            // An incomplete persisted stage must not authorize child requests.
            if (advance === false) return;
            const following = nextStage(work.stage);
            if (following && !cancellation.stopped) queues[following].push(work.host);
            if (!following) console.log(`[host-pipeline] done host=${work.host}`);
          })
          .catch((error: unknown) => {
            // Stop assigning fresh work after a failure, but let already active
            // requests settle before rejecting so no DB writes outlive the caller.
            // WorkCancellation owns the first fatal reason, including errors
            // already published by a nested worker before this catch runs.
            stopWork(cancellation, error);
          })
          .finally(() => {
            active -= 1;
            schedule();
          });
      }

      if (active === 0) {
        if (cancellation.stopped) reject(cancellation.reason);
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
  let selected: string[];
  try {
    const includedHosts = loadIncludedHostsFromFile(options.channels.hostsFile);
    const excludedHosts = loadHostsFromFile(options.channels.excludeHostsFile);
    const filtered = scopeHosts(store.listInstances(), includedHosts, excludedHosts, options.channels.hosts);
    selected = options.channels.maxInstances > 0
      ? filtered.slice(0, options.channels.maxInstances)
      : filtered;
    if (selected.length) store.initializeParentEnumeration(selected);
  } finally {
    store.close();
  }
  if (!selected.length) return;
  // This scheduler owns a single reset -> fresh probe -> enumeration sequence.
  // Worker callbacks use alreadyInitialized and must never reset again.
  const cancellation: WorkCancellation = { stopped: false };
  await checkInstancesHealth({
    cancellation, dbPath: options.channels.dbPath, concurrency: options.channels.concurrency,
    hostDelayMs: options.channels.hostDelayMs, timeoutMs: options.channels.timeoutMs,
    maxRetries: options.channels.maxRetries, minAgeDays: null, minAgeMin: null,
    minAgeSec: null, hostsFile: options.channels.hostsFile, host: null,
    errorsOnly: false, hosts: selected
  });
  const state = new ChannelStore({ dbPath: options.channels.dbPath });
  let eligible: string[];
  try {
    eligible = state.listFreshHealthyHosts(selected);
  } finally {
    state.close();
  }
  console.log(`[host-pipeline] selected=${selected.length} eligible=${eligible.length}`);

  // The same probe-owned signal is retained through every child stage.
  await runHostPipelineHosts(eligible, options.channels.concurrency, {
    channels: async (host) => {
      assertWorkActive(cancellation);
      await crawlChannels({ ...options.channels, cancellation, hosts: [host], concurrency: 1,
        maxInstances: 0, alreadyInitialized: true });
      const state = new ChannelStore({ dbPath: options.channels.dbPath });
      let finished: boolean;
      try {
        finished = state.listFreshHealthyHosts([host], true).length === 1;
      } finally {
        state.close();
      }
      if (!finished) return false;
      // Direct health is restricted to unresolved channels of this host.
      // No database handle is held while requests are in flight.
      assertWorkActive(cancellation);
      await checkChannelHealth({ ...options.channels, cancellation, hosts: [host], maxInstances: 0 });
      return true;
    },
    counts: async (host) => {
      assertWorkActive(cancellation);
      const check = new ChannelStore({ dbPath: options.channels.dbPath });
      try {
        if (!check.listFreshHealthyHosts([host], true).length) return false;
      } finally {
        check.close();
      }
      await crawlChannelVideosCount({ ...options.counts, cancellation, hosts: [host], concurrency: 1 });
      return true;
    },
    videos: (host) => crawlVideos({
      ...options.videos,
      cancellation,
      hosts: [host],
      concurrency: 1,
      maxInstances: 0
    })
  }, cancellation);

  console.log("[host-pipeline] finished");
}
