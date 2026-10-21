/** Report-only host-isolated observations using the shared detail/retry boundary. */
import {
  VideoAvailabilityWorkStore,
  type AvailabilityWorkRow,
} from "./db/video-availability.js";
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

/** A single invocation-wide stop signal shared by host and detail queues.
 * It is never global: a failed sweep cannot cancel an independent invocation.
 */
interface WorkCancellation {
  stopped: boolean;
  reason?: unknown;
}

/** Stop ALL sibling queues on the first fatal rejection, then drain every
 * operation already started before allowing the owner to close SQLite.
 */
async function bounded<T>(
  items: T[],
  limit: number,
  operation: (item: T) => Promise<void>,
  cancellation: WorkCancellation,
): Promise<void> {
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (!cancellation.stopped && next < items.length) {
        const item = items[next++];
        try {
          await operation(item);
        } catch (error) {
          if (!cancellation.stopped) {
            cancellation.stopped = true;
            cancellation.reason = error;
          }
        }
      }
    }),
  );
  if (cancellation.stopped) throw cancellation.reason;
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

/** Consume a parent-admitted immutable worklist directly at the video boundary.
 * The upstream materializer has already proved parent eligibility. Rechecking
 * a channel list here could discard valid video observations on a new failure.
 */
async function processAvailabilityHost(
  host: string,
  workStore: VideoAvailabilityWorkStore,
  options: AvailabilitySweepOptions,
  cancellation: WorkCancellation,
): Promise<void> {
  // Worklist corruption is fatal; never silently mark an entire host unknown.
  if (!safeHost(host)) throw new Error("Unsafe availability work host");
  const limiter = createRequestLimiter(
    options.hostConcurrency, options.hostDelayMs,
    () => { if (cancellation.stopped) throw cancellation.reason; },
  );
  let cursor: AvailabilityWorkRow | undefined;
  for (;;) {
    // The other host may have failed while this host was awaiting its batch.
    if (cancellation.stopped) return;
    const batch = workStore.pendingBatch(host, cursor);
    if (!batch.length) return;
    cursor = batch.at(-1)!;
    await bounded(batch, options.hostConcurrency, async (row) => {
      const result = await fetchVideoDetailResult(
        host, row.video_uuid, options, "https:", limiter,
      );
      workStore.recordResult(row, result);
    }, cancellation);
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
  const cancellation: WorkCancellation = { stopped: false };
  try {
    await bounded(store.hosts(), options.concurrency, (host) =>
      processAvailabilityHost(host, store, options, cancellation),
      cancellation,
    );
    store.assertComplete();
  } finally {
    store.close();
  }
}
