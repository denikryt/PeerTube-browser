/**
 * Module `engine/crawler/src/instances-cli.ts`: provide runtime functionality.
 */

import { Command } from "commander";
import { loadHostsFromFile } from "./host-filters.js";
import { crawl } from "./crawler.js";
import { isNoNetworkError } from "./http.js";
import { DEFAULT_JOINPEERTUBE_WHITELIST_URL } from "./instance-registry.js";

const program = new Command();

program
  .option(
    "--whitelist-url <url>",
    "Whitelist JSON URL",
    DEFAULT_JOINPEERTUBE_WHITELIST_URL
  )
  .option("--db <path>", "SQLite DB path", "data/crawl.db")
  .option(
    "--whitelist-file <path>",
    "Optional local file with whitelist hosts (one per line)",
    ""
  )
  .option(
    "--hosts-file <path>",
    "Optional local file with included hosts (one per line)",
    ""
  )
  .option(
    "--exclude-hosts-file <path>",
    "Optional local file with excluded hosts (one per line)",
    ""
  )
  .option("--concurrency <number>", "Concurrent workers", "4")
  .option("--host-delay <ms>", "Minimum delay between request starts to one host", "200")
  .option("--timeout <ms>", "HTTP timeout in ms", "5000")
  .option("--max-retries <number>", "HTTP retry attempts", "3")
  .option("--max-errors <number>", "Retries per host", "3")
  .option(
    "--max-instances <number>",
    "Limit number of whitelist instances to process (0 = no limit)",
    "0"
  )
  .option("--expand-beyond-whitelist", "Discover instances beyond the whitelist", false)
  .option("--graph", "Collect instance relationships (followers/following)", false)
  .option("--allow-empty-scoped-whitelist", "Allow empty registry overlap for a resumed explicit scope", false)
  .option("--resume", "Resume from existing DB", false);

program.parse(process.argv);

const options = program.opts();

try {
  if (options.allowEmptyScopedWhitelist &&
      (!options.resume || options.graph || options.expandBeyondWhitelist ||
       loadHostsFromFile(options.hostsFile).size === 0)) {
    throw new Error("--allow-empty-scoped-whitelist requires nonempty hosts scope, resume and no graph/expand");
  }
  await crawl({
    allowEmptyScopedWhitelist: Boolean(options.allowEmptyScopedWhitelist),
    whitelistUrl: options.whitelistUrl,
    whitelistFile: options.whitelistFile || null,
    hostsFile: options.hostsFile || null,
    excludeHostsFile: options.excludeHostsFile || null,
    dbPath: options.db,
    concurrency: Number(options.concurrency),
    hostDelayMs: Number(options.hostDelay),
    timeoutMs: Number(options.timeout),
    resume: Boolean(options.resume),
    maxRetries: Number(options.maxRetries),
    maxErrors: Number(options.maxErrors),
    maxInstances: Number(options.maxInstances),
    expandBeyondWhitelist: Boolean(options.expandBeyondWhitelist),
    collectGraph: Boolean(options.graph)
  });
} catch (error) {
  if (isNoNetworkError(error)) {
    console.error("[crawl] no network detected; stopping without progress updates");
    process.exit(1);
  }
  throw error;
}
