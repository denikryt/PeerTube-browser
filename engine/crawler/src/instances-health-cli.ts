/**
 * Module `engine/crawler/src/instances-health-cli.ts`: provide runtime functionality.
 */

import { Command } from "commander";
import { ChannelStore } from "./db.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";

interface InstanceHealthOptions {
  dbPath: string;
  concurrency: number;
  timeoutMs: number;
  maxRetries: number;
  minAgeDays: number | null;
  minAgeMin: number | null;
  minAgeSec: number | null;
  host: string | null;
  errorsOnly: boolean;
}

interface HealthPage {
  total?: number;
}

const program = new Command();

program
  .option("--db <path>", "SQLite DB path", "data/crawl.db")
  .option("--concurrency <number>", "Concurrent instances", "4")
  .option("--timeout <ms>", "HTTP timeout in ms", "5000")
  .option("--max-retries <number>", "HTTP retry attempts", "3")
  .option("--host <host>", "Check only a single instance host")
  .option("--errors-only", "Check only instances with health_status=error", false)
  .option(
    "--min-age-days <number>",
    "Only check instances last health checked at least this many days ago"
  )
  .option(
    "--min-age-min <number>",
    "Only check instances last health checked at least this many minutes ago"
  )
  .option(
    "--min-age-sec <number>",
    "Only check instances last health checked at least this many seconds ago"
  );

program.parse(process.argv);

const options = program.opts();

try {
  await checkInstancesHealth({
    dbPath: options.db,
    concurrency: Number(options.concurrency),
    timeoutMs: Number(options.timeout),
    maxRetries: Number(options.maxRetries),
    minAgeDays: parseOptionalNumber(options.minAgeDays),
    minAgeMin: parseOptionalNumber(options.minAgeMin),
    minAgeSec: parseOptionalNumber(options.minAgeSec),
    host: parseOptionalHost(options.host),
    errorsOnly: Boolean(options.errorsOnly)
  });
} catch (error) {
  if (isNoNetworkError(error)) {
    console.error("[instances-health] no network detected; stopping without progress updates");
    process.exit(1);
  }
  throw error;
}

/**
 * Handle check instances health.
 */
async function checkInstancesHealth(options: InstanceHealthOptions) {
  const store = new ChannelStore({ dbPath: options.dbPath });
  const minAgeMs = computeMinAgeMs(options);
  const hosts = options.host
    ? [options.host]
    : options.errorsOnly
      ? store.listErrorInstancesNeedingHealth(minAgeMs)
      : store.listInstancesNeedingHealth(minAgeMs);
  const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));
  const total = hosts.length;
  let processed = 0;

  const ageLabel = formatMinAgeLabel(options);
  const errorsLabel = options.errorsOnly ? " errors_only=true" : "";
  console.log(
    `[instances-health] instances=${total} concurrency=${workerCount}${ageLabel}${errorsLabel}`
  );

  const queue = hosts.slice();
  const workers = Array.from({ length: workerCount }, () =>
    workerLoop(queue, store, options, total, () => {
      processed += 1;
      return processed;
    })
  );
  await Promise.all(workers);

  console.log("[instances-health] finished");
  store.close();
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  queue: string[],
  store: ChannelStore,
  options: InstanceHealthOptions,
  total: number,
  nextProcessed: () => number
) {
  while (true) {
    const host = queue.pop();
    if (!host) return;
    await processInstance(host, store, options, total, nextProcessed);
  }
}

/**
 * Handle process instance.
 */
async function processInstance(
  host: string,
  store: ChannelStore,
  options: InstanceHealthOptions,
  total: number,
  nextProcessed: () => number
) {
  const normalizedHost = host.toLowerCase();
  const current = nextProcessed();
  console.log(`[instances-health] start ${current}/${total} ${normalizedHost}`);

  try {
    await fetchInstanceHealth(normalizedHost, options, "https:");
    store.markInstanceHealthOk(normalizedHost);
    console.log(`[instances-health] done ${normalizedHost}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (isNoNetworkError(error)) {
      console.warn(`[instances-health] network issue ${normalizedHost}: ${message}`);
      return;
    }
    store.markInstanceHealthError(normalizedHost, message);
    console.warn(`[instances-health] error ${normalizedHost}: ${message}`);
  }
}

/**
 * Handle fetch instance health.
 */
async function fetchInstanceHealth(
  host: string,
  options: InstanceHealthOptions,
  protocol: string
) {
  const url = buildHealthUrl(host, protocol);
  try {
    return await fetchJsonWithRetry<HealthPage>(url, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    });
  } catch {
    const alternate = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildHealthUrl(host, alternate);
    return await fetchJsonWithRetry<HealthPage>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
    });
  }
}

/**
 * Handle build health url.
 */
function buildHealthUrl(host: string, protocol: string) {
  return `${protocol}//${host}/api/v1/video-channels?start=0&count=1`;
}

/**
 * Handle parse optional number.
 */
function parseOptionalNumber(value: unknown): number | null {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Handle parse optional host.
 */
function parseOptionalHost(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Handle compute min age ms.
 */
function computeMinAgeMs(options: InstanceHealthOptions): number {
  const days = Math.max(0, options.minAgeDays ?? 0);
  const mins = Math.max(0, options.minAgeMin ?? 0);
  const secs = Math.max(0, options.minAgeSec ?? 0);
  return (
    days * 24 * 60 * 60 * 1000 +
    mins * 60 * 1000 +
    secs * 1000
  );
}

/**
 * Handle format min age label.
 */
function formatMinAgeLabel(options: InstanceHealthOptions): string {
  const parts: string[] = [];
  if (options.minAgeDays !== null) parts.push(`days=${options.minAgeDays}`);
  if (options.minAgeMin !== null) parts.push(`min=${options.minAgeMin}`);
  if (options.minAgeSec !== null) parts.push(`sec=${options.minAgeSec}`);
  return parts.length > 0 ? ` min_age(${parts.join(",")})` : "";
}
