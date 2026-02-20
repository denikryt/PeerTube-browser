/**
 * Module `engine/crawler/src/channels-videos-count-cli.ts`: provide runtime functionality.
 */
import { Command } from "commander";
import { crawlChannelVideosCount } from "./channels-videos-count-worker.js";
import { isNoNetworkError } from "./http.js";
const program = new Command();
program
    .option("--db <path>", "SQLite DB path", "data/crawl.db")
    .option("--exclude-hosts-file <path>", "Optional local file with excluded hosts (one per line)", "")
    .option("--concurrency <number>", "Concurrent instances", "4")
    .option("--timeout <ms>", "HTTP timeout in ms", "5000")
    .option("--max-retries <number>", "HTTP retry attempts", "3")
    .option("--resume", "Skip channels with existing counts or errors", false)
    .option("--errors", "Process only channels with recorded errors", false);
program.parse(process.argv);
const options = program.opts();
try {
    await crawlChannelVideosCount({
        dbPath: options.db,
        excludeHostsFile: options.excludeHostsFile || null,
        concurrency: Number(options.concurrency),
        timeoutMs: Number(options.timeout),
        maxRetries: Number(options.maxRetries),
        resume: Boolean(options.resume),
        errorsOnly: Boolean(options.errors)
    });
}
catch (error) {
    if (isNoNetworkError(error)) {
        console.error("[channels-videos] no network detected; stopping without progress updates");
        process.exit(1);
    }
    throw error;
}
