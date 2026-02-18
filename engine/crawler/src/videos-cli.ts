/**
 * Module `engine/crawler/src/videos-cli.ts`: provide runtime functionality.
 */

import { Command } from "commander";
import { crawlVideos } from "./videos-worker.js";
import { isNoNetworkError } from "./http.js";

const program = new Command();

program
  .option("--db <path>", "SQLite DB path", "data/crawl.db")
  .option(
    "--exclude-hosts-file <path>",
    "Optional local file with excluded hosts (one per line)",
    ""
  )
  .option(
    "--existing-db <path>",
    "Optional reference DB path used by --new-videos to skip already known videos",
    ""
  )
  .option(
    "--concurrency <number>",
    "Number of concurrent instance workers",
    "4"
  )
  .option("--timeout <ms>", "HTTP timeout per request in ms", "5000")
  .option("--max-retries <number>", "HTTP retry attempts per request", "3")
  .option(
    "--new-videos",
    "Skip videos that already exist in the database (by video_id + instance_domain)",
    false
  )
  .option(
    "--stop-after-full-pages <number>",
    "Stop after N consecutive pages where all videos already exist (requires --new-videos; default: 0)",
    "0"
  )
  .option(
    "--sort <value>",
    "Sort value passed to /video-channels/:name/videos (example: -publishedAt)",
    "-publishedAt"
  )
  .option(
    "--max-instances <number>",
    "Limit number of instances to process (0 = no limit)",
    "0"
  )
  .option(
    "--max-channels <number>",
    "Limit number of channels to process (0 = no limit)",
    "0"
  )
  .option(
    "--max-videos-pages <number>",
    "Limit number of pages fetched per channel (0 = no limit)",
    "0"
  )
  .option(
    "--tags",
    "Tags-only mode: fetch per-video tags via /api/v1/videos/:uuid for videos with tags_json NULL or []",
    false
  )
  .option(
    "--update-tags",
    "Tags-only mode: refresh tags via /api/v1/videos/:uuid for videos with existing tags_json",
    false
  )
  .option(
    "--comments",
    "Comments-only mode: fetch per-video comments via /api/v1/videos/:uuid",
    false
  )
  .option(
    "--host-delay <ms>",
    "Delay between requests per host in tags/comments mode",
    "200"
  )
  .option("--resume", "Resume from existing progress tables", false)
  .option("--errors", "Process only channels with recorded errors", false);

program.parse(process.argv);

const options = program.opts();

try {
  await crawlVideos({
    dbPath: options.db,
    excludeHostsFile: options.excludeHostsFile || null,
    existingDbPath: options.existingDb || null,
    concurrency: Number(options.concurrency),
    timeoutMs: Number(options.timeout),
    maxRetries: Number(options.maxRetries),
    newOnly: Boolean(options.newVideos),
    stopAfterFullPages: Number(options.stopAfterFullPages),
    sort: String(options.sort),
    maxInstances: Number(options.maxInstances),
    maxChannels: Number(options.maxChannels),
    maxVideosPages: Number(options.maxVideosPages),
    tagsOnly: Boolean(options.tags),
    updateTags: Boolean(options.updateTags),
    commentsOnly: Boolean(options.comments),
    hostDelayMs: Number(options.hostDelay),
    resume: Boolean(options.resume),
    errorsOnly: Boolean(options.errors)
  });
} catch (error) {
  if (isNoNetworkError(error)) {
    console.error("[videos] no network detected; stopping without progress updates");
    process.exit(1);
  }
  throw error;
}
