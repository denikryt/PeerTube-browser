/** Bound concurrent network operations that target one remote host. */

export interface RequestLimiter {
  /** Run one operation after a per-host concurrency slot becomes available. */
  run<T>(operation: () => Promise<T>): Promise<T>;
}

/**
 * Create a FIFO semaphore for requests sent to one PeerTube instance.
 *
 * Holding the slot across retries and backoff prevents nested channel/detail
 * pools from multiplying the operator's requested per-host pressure. Reserving
 * request start times centrally makes the host delay apply to every crawl mode,
 * including concurrent channel pages and per-video detail enrichment.
 */
export function createRequestLimiter(concurrency: number, delayMs = 0): RequestLimiter {
  const limit = Math.max(1, Math.floor(concurrency));
  const minimumDelayMs = Math.max(0, Math.floor(delayMs));
  let active = 0;
  let nextStartAt = 0;
  const waiting: Array<() => void> = [];

  const acquire = async () => {
    if (active < limit) {
      active += 1;
      return;
    }
    await new Promise<void>((resolve) => waiting.push(resolve));
  };

  const release = () => {
    const next = waiting.shift();
    if (next) {
      // Transfer the occupied slot directly to the oldest waiter. Keeping the
      // active count unchanged avoids a microtask gap where a newcomer could
      // bypass the queued operation and temporarily exceed the limit.
      next();
      return;
    }
    active -= 1;
  };

  return {
    async run<T>(operation: () => Promise<T>): Promise<T> {
      await acquire();
      try {
        // JavaScript runs this reservation synchronously until the first await,
        // so concurrent holders cannot reserve the same per-host start slot.
        const now = Date.now();
        const startAt = Math.max(now, nextStartAt);
        nextStartAt = startAt + minimumDelayMs;
        if (startAt > now) {
          await new Promise<void>((resolve) => setTimeout(resolve, startAt - now));
        }
        return await operation();
      } finally {
        release();
      }
    }
  };
}
