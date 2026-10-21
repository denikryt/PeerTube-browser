/** CLI for opt-in host-level channels -> counts -> videos scheduling. */

import { Command } from "commander";

import { crawlHostPipeline } from "./host-pipeline-worker.js";
import { isNoNetworkError } from "./http.js";

const program = new Command();

program
  .option("--db <path>", "SQLite DB path", "data/crawl.db")
  .option("--existing-db <path>", "Reference production DB used to skip known videos", "")
  .option("--hosts-file <path>", "Optional included hosts file", "")
  .option("--exclude-hosts-file <path>", "Optional excluded hosts file", "")
  .option("--concurrency <number>", "Concurrent host pipelines", "4")
  .option("--host-concurrency <number>", "Concurrent requests within one host", "2")
  .option("--host-delay <ms>", "Minimum delay between requests to one host", "200")
  .option("--timeout <ms>", "HTTP timeout per request", "5000")
  .option("--max-retries <number>", "HTTP retry attempts", "3")
  .option("--max-instances <number>", "Limit selected hosts (0 = unlimited)", "0")
  .option("--max-channels <number>", "Limit inserted channels per host (0 = unlimited)", "0")
  .option("--max-videos-pages <number>", "Limit video pages per channel (0 = unlimited)", "0")
  .option("--stop-after-full-pages <number>", "Stop after N all-known video pages", "0")
  .option("--sort <value>", "Video-list sort", "-publishedAt")
  .option("--resume", "Resume every host stage from persisted progress", false);

program.parse(process.argv);
const options = program.opts();

const shared = {
  dbPath: String(options.db),
  hostsFile: options.hostsFile || null,
  excludeHostsFile: options.excludeHostsFile || null,
  concurrency: Number(options.concurrency),
  hostConcurrency: Number(options.hostConcurrency),
  hostDelayMs: Number(options.hostDelay),
  timeoutMs: Number(options.timeout),
  maxRetries: Number(options.maxRetries),
  resume: Boolean(options.resume),
  errorsOnly: false
};

try {
  await crawlHostPipeline({
    channels: {
      ...shared,
      newOnly: true,
      maxInstances: Number(options.maxInstances),
      maxChannels: Number(options.maxChannels)
    },
    counts: shared,
    videos: {
      ...shared,
      existingDbPath: options.existingDb || null,
      newOnly: true,
      stopAfterFullPages: Number(options.stopAfterFullPages),
      sort: String(options.sort),
      maxInstances: Number(options.maxInstances),
      maxChannels: Number(options.maxChannels),
      maxVideosPages: Number(options.maxVideosPages),
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false
    }
  });
} catch (error) {
  if (isNoNetworkError(error)) {
    console.error("[host-pipeline] no network detected; stopping without unsafe progress updates");
    process.exit(1);
  }
  throw error;
}
