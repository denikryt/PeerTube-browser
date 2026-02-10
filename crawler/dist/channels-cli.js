import { Command } from "commander";
import { checkChannelHealth, crawlChannels } from "./channels-worker.js";
import { isNoNetworkError } from "./http.js";
const program = new Command();
program
    .option("--db <path>", "SQLite DB path", "data/crawl.db")
    .option("--concurrency <number>", "Concurrent instances", "4")
    .option("--timeout <ms>", "HTTP timeout in ms", "5000")
    .option("--max-retries <number>", "HTTP retry attempts", "3")
    .option("--new-channels", "Insert only channels that do not exist yet (skip updates for existing rows)", false)
    .option("--max-instances <number>", "Limit number of instances to process (0 = no limit)", "0")
    .option("--max-channels <number>", "Limit number of channels inserted during this run (0 = no limit)", "0")
    .option("--check-health", "Check channel health for all channels in the DB and record channel errors", false)
    .option("--resume", "Resume from existing progress", false);
program.parse(process.argv);
const options = program.opts();
try {
    const run = options.checkHealth ? checkChannelHealth : crawlChannels;
    await run({
        dbPath: options.db,
        concurrency: Number(options.concurrency),
        timeoutMs: Number(options.timeout),
        maxRetries: Number(options.maxRetries),
        newOnly: Boolean(options.newChannels),
        maxInstances: Number(options.maxInstances),
        maxChannels: Number(options.maxChannels),
        resume: Boolean(options.resume)
    });
}
catch (error) {
    if (isNoNetworkError(error)) {
        console.error("[channels] no network detected; stopping without progress updates");
        process.exit(1);
    }
    throw error;
}
