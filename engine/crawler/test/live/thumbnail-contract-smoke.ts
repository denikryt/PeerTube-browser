/** CLI entrypoint for the opt-in live PeerTube thumbnail contract smoke. */

import path from "node:path";
import { Command } from "commander";
import {
  assertLiveThumbnailSmoke,
  defaultLiveThumbnailSmokeOptions,
  runLiveThumbnailSmoke,
  summarizeLiveThumbnailSmoke
} from "../../src/live-thumbnail-smoke.js";

const defaults = defaultLiveThumbnailSmokeOptions();
const program = new Command();
program
  .description("Run live third-party PeerTube crawl and thumbnail requests")
  .option("--registry-url <url>", "JoinPeerTube registry URL", defaults.registryUrl)
  .option("--required-hosts <n>", "Usable hosts required", String(defaults.requiredHosts))
  .option("--candidate-limit <n>", "Registry candidates to attempt", String(defaults.candidateLimit))
  .option("--max-channels-per-host <n>", "Bounded channels per host", String(defaults.maxChannelsPerHost))
  .option("--max-video-pages <n>", "Bounded video pages per channel", String(defaults.maxVideoPages))
  .option("--timeout <ms>", "Network timeout", String(defaults.timeoutMs))
  .option("--max-retries <n>", "HTTP retry attempts", String(defaults.maxRetries))
  .option("--concurrency <n>", "Crawler concurrency", String(defaults.concurrency))
  .option("--full-instance", "Remove channel and video page caps", false)
  .option("--keep-artifacts", "Preserve temporary candidate databases", false)
  .option("--report <path>", "Write structured JSON report", "");
program.parse(process.argv);
const cli = program.opts();

console.warn("[live-thumbnail-smoke] performs live third-party network requests and is not a deterministic test");

try {
  const reportPath = cli.report ? path.resolve(String(cli.report)) : null;
  const report = await runLiveThumbnailSmoke({
    registryUrl: String(cli.registryUrl),
    requiredHosts: positiveInt(cli.requiredHosts, "required-hosts"),
    candidateLimit: positiveInt(cli.candidateLimit, "candidate-limit"),
    maxChannelsPerHost: positiveInt(cli.maxChannelsPerHost, "max-channels-per-host"),
    maxVideoPages: positiveInt(cli.maxVideoPages, "max-video-pages"),
    timeoutMs: positiveInt(cli.timeout, "timeout"),
    maxRetries: nonNegativeInt(cli.maxRetries, "max-retries"),
    concurrency: positiveInt(cli.concurrency, "concurrency"),
    fullInstance: Boolean(cli.fullInstance),
    keepArtifacts: Boolean(cli.keepArtifacts),
    reportPath
  });
  console.log(summarizeLiveThumbnailSmoke(report));
  if (reportPath) console.log(`report=${reportPath}`);
  assertLiveThumbnailSmoke(report);
} catch (error) {
  console.error(`[live-thumbnail-smoke] failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}

/** Parse one required positive integer CLI option. */
function positiveInt(value: unknown, name: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) throw new Error(`--${name} must be a positive integer`);
  return parsed;
}

/** Parse one required non-negative integer CLI option. */
function nonNegativeInt(value: unknown, name: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) throw new Error(`--${name} must be a non-negative integer`);
  return parsed;
}

