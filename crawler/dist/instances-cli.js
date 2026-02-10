import { Command } from "commander";
import { crawl } from "./crawler.js";
import { isNoNetworkError } from "./http.js";
const program = new Command();
program
    .option("--whitelist-url <url>", "Whitelist JSON URL", "https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true")
    .option("--db <path>", "SQLite DB path", "data/crawl.db")
    .option("--concurrency <number>", "Concurrent workers", "4")
    .option("--timeout <ms>", "HTTP timeout in ms", "5000")
    .option("--max-retries <number>", "HTTP retry attempts", "3")
    .option("--max-errors <number>", "Retries per host", "3")
    .option("--max-instances <number>", "Limit number of whitelist instances to process (0 = no limit)", "0")
    .option("--expand-beyond-whitelist", "Discover instances beyond the whitelist", false)
    .option("--graph", "Collect instance relationships (followers/following)", false)
    .option("--resume", "Resume from existing DB", false);
program.parse(process.argv);
const options = program.opts();
try {
    await crawl({
        whitelistUrl: options.whitelistUrl,
        dbPath: options.db,
        concurrency: Number(options.concurrency),
        timeoutMs: Number(options.timeout),
        resume: Boolean(options.resume),
        maxRetries: Number(options.maxRetries),
        maxErrors: Number(options.maxErrors),
        maxInstances: Number(options.maxInstances),
        expandBeyondWhitelist: Boolean(options.expandBeyondWhitelist),
        collectGraph: Boolean(options.graph)
    });
}
catch (error) {
    if (isNoNetworkError(error)) {
        console.error("[crawl] no network detected; stopping without progress updates");
        process.exit(1);
    }
    throw error;
}
