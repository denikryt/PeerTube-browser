/** Report-only host-isolated observations using the shared detail/retry boundary. */
import {
  VideoAvailabilityWorkStore,
  type AvailabilityWorkRow,
} from "./db/video-availability.js";
import { fetchJsonWithRetry } from "./http.js";
import {
  classifyCrawlError,
  shouldTryAlternateProtocol,
} from "./error-classification.js";
import {
  createRequestLimiter,
  type RequestLimiter,
} from "./request-limiter.js";
import { fetchVideoDetailResult } from "./video-detail.js";
import { normalizeHostToken } from "./host-filters.js";

/** Network tuning only; production and selection belong exclusively to Python. */
export interface AvailabilitySweepOptions {
  dbPath: string;
  concurrency: number;
  hostConcurrency: number;
  hostDelayMs: number;
  timeoutMs: number;
  maxRetries: number;
}

/** Stop scheduling on fatal exceptions, then drain already active operations. */
async function bounded<T>(
  items: T[],
  limit: number,
  operation: (item: T) => Promise<void>,
): Promise<void> {
  let next = 0,
    failed = false;
  let failure: unknown;
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (!failed && next < items.length) {
        const item = items[next++];
        try {
          await operation(item);
        } catch (error) {
          if (!failed) {
            failed = true;
            failure = error;
          }
        }
      }
    }),
  );
  if (failed) throw failure;
}

/** Accept only an exact URL authority, rejecting credentials, paths and queries. */
function safeHost(host: string): boolean {
  try {
    const url = new URL(`https://${host}`);
    return (
      !!host &&
      normalizeHostToken(host) === host &&
      (url.host === host || host === `${url.host}:443`) &&
      !url.username &&
      !url.password &&
      url.pathname === "/" &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

/** One logical coarse probe with the existing transport-only protocol fallback. */
async function preflight(
  host: string,
  options: AvailabilitySweepOptions,
  limiter: RequestLimiter,
): Promise<string> {
  const request = (protocol: string, retries: number) =>
    limiter.run(() =>
      fetchJsonWithRetry<unknown>(
        `${protocol}//${host}/api/v1/video-channels?start=0&count=1`,
        { timeoutMs: options.timeoutMs, maxRetries: retries },
      ),
    );
  let protocol = "https:",
    payload: unknown;
  try {
    payload = await request(protocol, options.maxRetries);
  } catch (error) {
    if (!shouldTryAlternateProtocol(error)) throw error;
    protocol = "http:";
    payload = await request(
      protocol,
      Math.max(1, Math.floor(options.maxRetries / 2)),
    );
  }
  // A semantic-invalid successful response never gains HTTP fallback authority.
  if (!payload || typeof payload !== "object" || Array.isArray(payload))
    throw new Error("invalid preflight payload");
  const p = payload as { total?: unknown; data?: unknown };
  if (
    typeof p.total !== "number" ||
    !Number.isFinite(p.total) ||
    !Number.isInteger(p.total) ||
    p.total < 0 ||
    !Array.isArray(p.data)
  )
    throw new Error("invalid preflight payload");
  return protocol;
}

/** Probe one normalized host once, then consume immutable bounded identity batches. */
async function processAvailabilityHost(
  host: string,
  workStore: VideoAvailabilityWorkStore,
  options: AvailabilitySweepOptions,
): Promise<void> {
  const limiter = createRequestLimiter(
    options.hostConcurrency,
    options.hostDelayMs,
  );
  if (!safeHost(host)) {
    workStore.markHostPreflightUnknown(host, "unsafe_host");
    return;
  }
  let protocol: string;
  // Catch only preflight failures; result persistence errors remain fatal.
  try {
    protocol = await preflight(host, options, limiter);
  } catch (error) {
    // TODO(nodeforge-availability-network-outage): Replace this temporary host-UNKNOWN treatment when parent orchestration can positively distinguish a process-wide network outage from remote-host failure.
    workStore.markHostPreflightUnknown(host, classifyCrawlError(error).kind);
    return;
  }
  let cursor: AvailabilityWorkRow | undefined;
  for (;;) {
    const batch = workStore.pendingBatch(host, cursor);
    if (!batch.length) return;
    // Advance by selected original PK regardless of which rows finish first.
    cursor = batch.at(-1)!;
    await bounded(batch, options.hostConcurrency, async (row) => {
      const result = await fetchVideoDetailResult(
        host,
        row.video_uuid,
        options,
        protocol,
        limiter,
      );
      workStore.recordResult(row, result);
    });
  }
}

/** Run only an accepted fresh staging worklist; Python owns the final report. */
export async function runAvailabilitySweep(
  options: AvailabilitySweepOptions,
): Promise<void> {
  for (const name of [
    "concurrency",
    "hostConcurrency",
    "hostDelayMs",
    "timeoutMs",
    "maxRetries",
  ] as const) {
    const value = options[name];
    const minimum = ["hostDelayMs", "maxRetries"].includes(name) ? 0 : 1;
    if (
      typeof value !== "number" ||
      !Number.isSafeInteger(value) ||
      value < minimum
    )
      throw new Error(`Invalid availability ${name}`);
  }
  const store = new VideoAvailabilityWorkStore(options.dbPath);
  try {
    await bounded(store.hosts(), options.concurrency, (host) =>
      processAvailabilityHost(host, store, options),
    );
    store.assertComplete();
  } finally {
    store.close();
  }
}
