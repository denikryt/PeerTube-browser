/**
 * Module `engine/crawler/src/instances-health-cli.ts`: provide runtime functionality.
 */

import { Command } from "commander";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { ChannelStore } from "./db/channels.js";
import { formatCrawlError, shouldTryAlternateProtocol } from "./error-classification.js";
import { loadIncludedHostsFromFile, scopeHosts } from "./host-filters.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { createRequestLimiter, type RequestLimiter } from "./request-limiter.js";
import { assertWorkActive, stopWork, type WorkCancellation } from "./work-cancellation.js";

export interface InstanceHealthOptions {
  /** Restrict a shared in-process probe to the owner's frozen host selection. */
  hosts?: readonly string[];
  /** Host pipeline may share the same fatal signal with subsequent stages. */
  cancellation?: WorkCancellation;
  dbPath: string;
  concurrency: number;
  hostDelayMs: number;
  timeoutMs: number;
  maxRetries: number;
  minAgeDays: number | null;
  minAgeMin: number | null;
  minAgeSec: number | null;
  hostsFile: string | null;
  host: string | null;
  errorsOnly: boolean;
  /** Retain completed probes from the same initialized crawler run. */
  skipObserved?: boolean;
}

interface HealthPage {
  total?: number;
  data?: unknown[];
}

/** CLI entry is intentionally excluded when a parent scheduler imports the probe. */
async function runCommandLine() {
const program = new Command();

program
  .option("--db <path>", "SQLite DB path", "data/crawl.db")
  .option(
    "--hosts-file <path>",
    "Optional local file with included hosts (one per line)",
    ""
  )
  .option("--concurrency <number>", "Concurrent instances", "4")
  .option("--host-delay <ms>", "Minimum delay between request starts to one host", "200")
  .option("--timeout <ms>", "HTTP timeout in ms", "5000")
  .option("--max-retries <number>", "HTTP retry attempts", "3")
  .option("--host <host>", "Check only a single instance host")
  .option("--errors-only", "Check only instances with health_status=error", false)
  .option("--skip-observed", "Continue an initialized probe without rechecking saved results", false)
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
    hostDelayMs: Number(options.hostDelay),
    timeoutMs: Number(options.timeout),
    maxRetries: Number(options.maxRetries),
    minAgeDays: parseOptionalNumber(options.minAgeDays),
    minAgeMin: parseOptionalNumber(options.minAgeMin),
    minAgeSec: parseOptionalNumber(options.minAgeSec),
    hostsFile: typeof options.hostsFile === "string" && options.hostsFile.trim() ? options.hostsFile : null,
    host: parseOptionalHost(options.host),
    errorsOnly: Boolean(options.errorsOnly),
    skipObserved: Boolean(options.skipObserved)
  });
} catch (error) {
  if (isNoNetworkError(error)) {
    console.error("[instances-health] no network detected; stopping without progress updates");
    process.exit(1);
  }
  throw error;
}

 }

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  await runCommandLine();
}

/**
 * Handle check instances health.
 */
export async function checkInstancesHealth(options: InstanceHealthOptions) {
  const cancellation = options.cancellation ?? { stopped: false };
  assertWorkActive(cancellation);
  const store = new ChannelStore({ dbPath: options.dbPath });
  const minAgeMs = computeMinAgeMs(options);
  const allHosts = options.host
    ? [options.host]
    : options.skipObserved
      ? store.listUnobservedInstancesForHealth()
    : options.errorsOnly
      ? store.listErrorInstancesNeedingHealth(minAgeMs)
      : store.listInstancesNeedingHealth(minAgeMs);
  const hosts = scopeHosts(allHosts, loadIncludedHostsFromFile(options.hostsFile), new Set<string>(), options.hosts);
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
    }, cancellation)
  );
  // One fatal worker must stop issuing new requests, but already active
  // workers must drain before the shared SQLite connection is released.
  try {
    const settled = await Promise.allSettled(workers.map(work => work.catch(error => {
      stopWork(cancellation, error);
      queue.length = 0;
      throw error;
    })));
    const rejected = settled.find((result): result is PromiseRejectedResult => result.status === "rejected");
    if (rejected) throw rejected.reason;
    console.log("[instances-health] finished");
  } finally {
    store.close();
  }
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  queue: string[],
  store: ChannelStore,
  options: InstanceHealthOptions,
  total: number,
  nextProcessed: () => number,
  cancellation: WorkCancellation
) {
  while (!cancellation.stopped) {
    const host = queue.pop();
    if (!host) return;
    await processInstance(host, store, options, total, nextProcessed, cancellation);
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
  nextProcessed: () => number,
  cancellation: WorkCancellation
) {
  assertWorkActive(cancellation);
  const normalizedHost = host.toLowerCase();
  const requestLimiter = createRequestLimiter(1, options.hostDelayMs,
    () => assertWorkActive(cancellation),
    (error) => { if (isNoNetworkError(error)) stopWork(cancellation, error); }
  );
  const current = nextProcessed();
  console.log(`[instances-health] start ${current}/${total} ${normalizedHost}`);

  try {
    await fetchInstanceHealth(normalizedHost, options, "https:", requestLimiter);
    store.markInstanceHealthOk(normalizedHost);
    console.log(`[instances-health] ok ${normalizedHost}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (isNoNetworkError(error)) {
      stopWork(cancellation, error);
      console.warn(
        `[instances-health] unchanged ${normalizedHost} local_network=${message}`
      );
      throw error;
    }
    const storedError = formatCrawlError(error);
    store.markInstanceHealthError(normalizedHost, storedError);
    console.warn(
      `[instances-health] error ${normalizedHost} error=${storedError}`
    );
  }
}

/**
 * Handle fetch instance health.
 */
async function fetchInstanceHealth(
  host: string,
  options: InstanceHealthOptions,
  protocol: string,
  requestLimiter: RequestLimiter
) {
  const url = buildHealthUrl(host, protocol);
  try {
    const page = await requestLimiter.run(() => fetchJsonWithRetry<HealthPage>(url, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    }));
    validateHealthPage(page);
    return page;
  } catch (error) {
    // An explicit local outage has priority over message-based protocol fallback.
    if (isNoNetworkError(error) || !shouldTryAlternateProtocol(error)) throw error;
    const alternate = protocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildHealthUrl(host, alternate);
    const page = await requestLimiter.run(() => fetchJsonWithRetry<HealthPage>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
    }));
    validateHealthPage(page);
    return page;
  }
}

/** A valid 2xx response must prove that the PeerTube instance spoke the API. */
function validateHealthPage(value: HealthPage) {
  if (!value || !Array.isArray(value.data) || !Number.isSafeInteger(value.total) ||
      (value.total as number) < value.data.length || (value.total as number) < 0 ||
      value.data.length > 1) {
    throw new Error("Invalid instance-health page");
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
